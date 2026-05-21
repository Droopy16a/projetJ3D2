from __future__ import annotations

import asyncio
import json
import hashlib
import os
import random
import time
import math
from collections import deque
from typing import Any

from assets.Character import Character
from assets.Config import Config
from assets.Global_state import GLOBAL_STATE
from assets.Mob import Mob
from assets.PhysicsManager import PhysicsManager
from assets.World import World
from assets.Achille import Dungeon, Room

from direct.gui.DirectGui import DirectFrame, DirectWaitBar
from direct.gui import DirectGuiGlobals as DGG
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    CardMaker,
    ConfigVariableString,
    DirectionalLight,
    Fog,
    TextNode,
    TransparencyAttrib,
    Vec3,
    Vec4,
    WindowProperties,
    loadPrcFileData,
)

import websockets
try:
    import simplepbr
except ImportError:
    simplepbr = None


loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #f")
ConfigVariableString("bullet-filter-algorithm").setValue("groups-mask")

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
NETWORK_UPDATE_INTERVAL = 0.033
NETWORK_SMOOTHING = 18.0
SNAP_DISTANCE = 6.0
NETWORK_PREDICTION_LIMIT = 0.18
NETWORK_MOVE_SPEED = 0.25
NETWORK_MOVE_DIST = 0.06
CAMERA_SMOOTHING = 10.0
ATTACK_INPUT_BUFFER = 0.14
HITSTOP_DURATION = 0.045
COMBO_WINDOW = 0.52
COMBO_DAMAGE = (1.0, 1.18, 1.35)
COMBO_RANGE_BONUS = (0.0, 0.18, 0.34)

HERO_ATTACK_COOLDOWN = 0.40
BOSS_ATTACK_COOLDOWN = 0.55
CONTROLLED_MOB_ATTACK_COOLDOWN = 0.65
AI_ATTACK_COOLDOWN = 1.05
SPAWN_COOLDOWN = 1.75
ATTACK_RANGE = 2.8
MAX_ACTIVE_MOBS = 6

HERO_MAX_HP = 130
BOSS_MAX_HP = 220
MOB_MAX_HP = 65

HERO_DAMAGE = 22
BOSS_DAMAGE = 18
MOB_DAMAGE = 12
HUD_UPDATE_INTERVAL = 0.05

DUNGEON_ROOM_IMAGE_DIR = os.path.join("assets", "images", "dungeon_rooms")
DUNGEON_ROOM_FALLBACK_IMAGE = os.path.join(DUNGEON_ROOM_IMAGE_DIR, "default.png")
DUNGEON_EDITOR_BACKGROUND_IMAGES = (
    os.path.join("assets", "images", "dungeon_system_background.jpg"),
    os.path.join("assets", "images", "dungeon_menu_background.jpg"),
    os.path.join("assets", "images", "dungeon_system_background.png"),
    os.path.join("assets", "images", "dungeon_menu_background.png"),
)
DUNGEON_EDITOR_TAB_CLOSED_IMAGE = os.path.join("assets", "images", "dungeon_arrow_closed.png")
DUNGEON_EDITOR_TAB_OPEN_IMAGE = os.path.join("assets", "images", "dungeon_arrow_open.png")




class Game(ShowBase):
    def __init__(self, config: Config = Config()):
        super().__init__()
        self.game_config = config
        self.disableMouse()

        if simplepbr is not None:
            pbr = simplepbr.init(
                enable_shadows=True,
                env_map="./assets/env/cubemap.env",
            )
            pbr.use_hardware_skinning = True
            pbr.msaa_samples = 8
            pbr.enable_shadows = True
            pbr.use_330 = True # export MESA_GL_VERSION_OVERRIDE="3.00 ES"
            pbr.use_normal_maps = True
            pbr.use_emission_maps = True
            pbr.use_occlusion_maps = True
            pbr.enable_fog = True
        else:
            self.render.setShaderAuto()

        props = WindowProperties()
        props.setTitle(self.game_config.window_title)
        self.win.requestProperties(props)

        GLOBAL_STATE.set_camera(self)
        self.camera.setPos(0, -40, 6)
        self.camera.setHpr(0, 0, 0)
        self._setup_lighting()
        # self._setup_parallax_background()

        self.PORT = int(os.getenv("DUNGEON_ARISE_PORT", str(DEFAULT_PORT)))
        self.ws_host = os.getenv("DUNGEON_ARISE_HOST", DEFAULT_HOST)
        self.ws_uri = f"ws://{self.ws_host}:{self.PORT}"

        if self.game_config.module_seed is None:
            env_seed = os.getenv("DUNGEON_WORLD_SEED")
            if env_seed is not None:
                try:
                    self.game_config.module_seed = int(env_seed)
                except ValueError:
                    self.game_config.module_seed = None
            if self.game_config.module_seed is None:
                seed_src = f"{self.ws_host}:{self.PORT}"
                self.game_config.module_seed = int(hashlib.sha256(seed_src.encode()).hexdigest()[:8], 16)

        self.physics = PhysicsManager(self.game_config.gravity, self.render)
        self.world = World(self.game_config, self.render, self.loader, self.physics, index=0)
        self.min_x, self.max_x = self.world.setLimit()
        self.goal_x = self.max_x - 2.0
        self._setup_boss_editor()

        self.player_id: int | None = None
        self.hero: Character | None = None
        self.boss: Mob | None = None

        self.local_mobs: dict[int, Mob] = {}
        self.local_mob_hp: dict[int, int] = {}
        self.remote_mobs: dict[int, Mob] = {}
        self.next_mob_id = 1
        self.controlled_entity: str | int = "boss"

        self.hero_hp = HERO_MAX_HP
        self.boss_hp = BOSS_MAX_HP
        self.boss_phase_unlocked = False
        self.winner: str | None = None

        self.last_attack_times = {"hero": 0.0, "boss": 0.0, "mob": 0.0}
        self.combo_state = {
            "hero": {"step": -1, "last_time": 0.0},
            "boss": {"step": -1, "last_time": 0.0},
            "mob": {"step": -1, "last_time": 0.0},
        }
        self.ai_attack_clock: dict[int, float] = {}
        self.last_spawn_time = 0.0
        self.attack_buffer_until = 0.0
        self.hitstop_remaining = 0.0
        self.camera_follow_x = self.camera.getX()

        self.websocket = None
        self._event_loop = None
        self._connection_established = False
        self._ws_task = None
        self._outbox: deque[dict[str, Any]] = deque()
        self._pending_state_payload: dict[str, Any] | None = None
        self.network_update_interval = NETWORK_UPDATE_INTERVAL
        self.time_since_last_send = 0.0
        self._hud_time_accumulator = HUD_UPDATE_INTERVAL
        self.remote_targets: dict[str, dict[str, Any]] = {}
        self.active_vfx: list[dict[str, Any]] = []
        self.active_flashes: list[dict[str, Any]] = []
        self.status_timer = 0.0
        self._last_world_layout_sig: tuple[tuple[int, float, float], ...] | None = None

        self._ui_cache: dict[str, Any] = {}
        self._ui_visible: dict[str, bool] = {}
        self._setup_hud()
        self._pulse_model_template = self.loader.loadModel("models/misc/sphere")

        self.accept("f", self.spawn_local_mob_request)
        self.accept("tab", self.cycle_control)
        for slot in range(1, MAX_ACTIVE_MOBS + 1):
            self.accept(str(slot), self.select_control_slot, [slot])
        self.accept("b", self.select_control_boss)
        self.accept("0", self.select_control_boss)
        self._ui_consumed_click = False
        self.accept("mouse1", self._on_mouse1)
        self.accept("mouse1-up", self._on_mouse1_up)

        self.taskMgr.add(self._task_physics, "physics_task")
        self.taskMgr.add(self._task_update, "update_task")
        self.taskMgr.add(self._task_websocket, "websocket_task")
        self.taskMgr.add(self._task_boss_editor_drag, "boss_editor_drag")

    def _setup_lighting(self):
        self.render.clearLight()
        self.setBackgroundColor(0,0,0, 1)

        key = DirectionalLight("key_light")
        key.setColor(Vec4(1.1, 1.02, 0.9, 1))
        key.setShadowCaster(True, 2048, 2048)
        key_np = self.render.attachNewNode(key)
        key_np.setHpr(35, -50, 0)

        fill = DirectionalLight("fill_light")
        fill.setColor(Vec4(0.7, 0.35, 0.24, 1))
        fill_np = self.render.attachNewNode(fill)
        fill_np.setHpr(-45, -25, 0)

        rim = DirectionalLight("rim_light")
        rim.setColor(Vec4(0.85, 0.45, 0.4, 1))
        rim_np = self.render.attachNewNode(rim)
        rim_np.setHpr(145, -35, 0)

        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.08, 0.12, 0.3, 1))
        ambient_np = self.render.attachNewNode(ambient)

        self.render.setLight(key_np)
        self.render.setLight(fill_np)
        self.render.setLight(rim_np)
        self.render.setLight(ambient_np)

        # fog = Fog("scene_fog")
        # fog.setColor(0.06, 0.08, 0.06)
        # fog.setExpDensity(0.016)
        # self.render.setFog(fog)

    def _setup_parallax_background(self):
        self.parallax_root = self.render.attachNewNode("parallax_root")
        self.parallax_root.setBin("background", 0)
        self.parallax_root.setDepthWrite(False)
        self.parallax_root.setLightOff(1)

        def _make_layer(
            name: str,
            texture_path: str,
            y: float,
            scale: float,
            color: tuple[float, float, float, float],
        ):
            cm = CardMaker(name)
            cm.setFrame(-220, 220, -120, 120)
            np = self.parallax_root.attachNewNode(cm.generate())
            np.setPos(0, y, 30)
            np.setScale(scale)
            np.setTransparency(TransparencyAttrib.MAlpha)
            np.setTexture(self.loader.loadTexture(texture_path), 1)
            np.setColorScale(*color)
            return np

        self.parallax_far = _make_layer(
            "parallax_far",
            "assets/images/background.jpg",
            y=260,
            scale=1.4,
            color=(0.62, 0.7, 0.58, 1.0),
        )
        self.parallax_mid = _make_layer(
            "parallax_mid",
            "assets/images/eau.png",
            y=200,
            scale=1.25,
            color=(0.3, 0.45, 0.32, 0.5),
        )
        self.parallax_near = _make_layer(
            "parallax_near",
            "assets/images/background.jpg",
            y=150,
            scale=1.15,
            color=(0.32, 0.4, 0.3, 0.25),
        )

        self.parallax_layers = [
            (self.parallax_far, Vec3(0, 260, 30), 0.012, 0.004, 0.02),
            (self.parallax_mid, Vec3(0, 200, 30), 0.02, 0.006, 0.03),
            (self.parallax_near, Vec3(0, 150, 30), 0.03, 0.009, 0.04),
        ]
        self.parallax_time = 0.0

    def _update_parallax(self, dt: float):
        if not hasattr(self, "parallax_layers"):
            return
        self.parallax_time += dt
        cam_x = self.camera.getX()
        cam_z = self.camera.getZ()
        drift = math.sin(self.parallax_time * 0.45) * 0.02
        for node, base_pos, factor_x, factor_z, drift_amp in self.parallax_layers:
            node.setPos(
                base_pos.x + cam_x * factor_x + drift * drift_amp,
                base_pos.y,
                base_pos.z + cam_z * factor_z,
            )

    def _editor_image_key(self, value: Any) -> str:
        key = str(value or "").strip().lower()
        chars = []
        last_was_separator = False
        for char in key:
            if char.isalnum():
                chars.append(char)
                last_was_separator = False
            elif not last_was_separator:
                chars.append("_")
                last_was_separator = True
        return "".join(chars).strip("_")

    def _find_editor_room_image(self, room_name: str, meta: dict, index: int) -> str | None:
        image_keys = [
            self._editor_image_key(room_name),
            self._editor_image_key(meta.get("name")),
            self._editor_image_key(os.path.splitext(os.path.basename(str(meta.get("path", ""))))[0]),
            f"module_{index + 1}",
            f"room_{index + 1}",
        ]

        for key in image_keys:
            if not key:
                continue
            for extension in (".png", ".jpg", ".jpeg"):
                path = os.path.join(DUNGEON_ROOM_IMAGE_DIR, f"{key}{extension}")
                if os.path.exists(path):
                    return path

        if os.path.exists(DUNGEON_ROOM_FALLBACK_IMAGE):
            return DUNGEON_ROOM_FALLBACK_IMAGE
        return None

    def _apply_editor_room_style(self, room: Room, meta: dict, index: int):
        room.model.setTransparency(TransparencyAttrib.MAlpha)
        image_path = self._find_editor_room_image(room.name, meta, index)

        if image_path:
            texture = self.loader.loadTexture(image_path)
            room.model.setTexture(texture, 1)
            room.model.setColor(1, 1, 1, 1)
        else:
            room.model.setColor(*room.color)
    
    def _find_editor_background_image(self) -> str | None:
        for image_path in DUNGEON_EDITOR_BACKGROUND_IMAGES:
            if os.path.exists(image_path):
                return image_path
        return None
    
    def _find_first_existing_image(self, image_paths: str | tuple[str, ...]) -> str | None:
        if isinstance(image_paths, str):
            image_paths = (image_paths,)
        for image_path in image_paths:
            if os.path.exists(image_path):
                return image_path
        return None

    def _setup_editor_background(self):
        image_path = self._find_editor_background_image()
        if not image_path:
            return

        left, right, bottom, top = self.editor_frame
        card_maker = CardMaker("dungeon_editor_background")
        card_maker.set_frame(left, right, bottom, top)
        self.editor_background = self.editor_root.attachNewNode(card_maker.generate())
        self.editor_background.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_background.setTexture(self.loader.loadTexture(image_path), 1)
        self.editor_background.setColor(1, 1, 1, 1)
        self.editor_background.setBin("fixed", -10)

    def _setup_editor_tab_image(self):
        image_path = self._find_first_existing_image(DUNGEON_EDITOR_TAB_CLOSED_IMAGE)
        if not image_path:
            self.editor_tab_image = None
            return

        left, right, bottom, top = self.editor_tab_frame
        card_maker = CardMaker("dungeon_editor_tab_image")
        card_maker.set_frame(left, right, bottom, top)
        self.editor_tab_image = self.editor_tab.attachNewNode(card_maker.generate())
        self.editor_tab_image.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_tab_image.setTexture(self.loader.loadTexture(image_path), 1)
        self.editor_tab_image.setColor(1, 1, 1, 1)

    def _update_editor_tab_image(self):
        if not getattr(self, "editor_tab_image", None):
            return

        image_paths = (
            DUNGEON_EDITOR_TAB_OPEN_IMAGE
            if self.editor_expanded
            else DUNGEON_EDITOR_TAB_CLOSED_IMAGE
        )
        image_path = self._find_first_existing_image(image_paths)
        if not image_path:
            self.editor_tab_image.hide()
            self.editor_tab_label.show()
            return

        self.editor_tab_image.show()
        self.editor_tab_image.setTexture(self.loader.loadTexture(image_path), 1)
        self.editor_tab_label.hide()

    def _setup_boss_editor(self):
        self.editor_enabled = bool(getattr(self.world, "module_nodes", []))
        self.editor_frame = (0, 0.68, -0.34, 0.34)
        self.editor_root = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0, 0, 0, 0),
            frameSize=self.editor_frame,
            pos=(0.64, 0, 0),
        )
        self.editor_root.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_root.hide()
        self.editor_expanded = False
        self.editor_root.bind(DGG.B1PRESS, self._on_editor_panel_press)
        self._setup_editor_background()

        self.editor_tab_frame = (-0.06, 0.06, -0.06, 0.06)
        self.editor_tab = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0.02, 0.03, 0.04, 0.7),
            frameSize=self.editor_tab_frame,
            pos=(1.23, 0, 0),
        )
        self.editor_tab.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_tab.hide()
        self.editor_tab.bind(DGG.B1PRESS, self._on_editor_tab_press)
        self._setup_editor_tab_image()
        self.editor_tab_label = OnscreenText(
            text="<",
            pos=(0, -0.04),
            align=TextNode.ACenter,
            scale=0.07,
            fg=(0.95, 0.95, 0.95, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.editor_tab,
        )

        editor_left, editor_right, editor_bottom, editor_top = self.editor_frame
        editor_center_x = (editor_left + editor_right) * 0.5
        editor_height = editor_top - editor_bottom
        title_scale = min(0.045, max(0.026, editor_height * 0.07))

        self.editor_title = OnscreenText(
            text="BOSS EDITOR",
            pos=(editor_center_x, editor_top - editor_height * 0.14),
            align=TextNode.ACenter,
            scale=title_scale,
            fg=(0.95, 0.95, 0.95, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=False,
            parent=self.editor_root,
        )

        self.editor_canvas = self.editor_root.attachNewNode("editor_canvas")
        self.editor_scale = 0.12
        self.editor_canvas.setScale(self.editor_scale, 1, self.editor_scale)
        self.editor_canvas.setPos(0.08, 0, 0.35)

        self.editor_dungeon = Dungeon()
        self.editor_room_to_module: dict[Room, dict] = {}
        self.editor_module_to_room: dict[int, Room] = {}
        self.editor_dragged_room: Room | None = None
        self.editor_drag_offset = Vec3(0, 0, 0)
        self.editor_room_half_w = 0.5
        self.editor_room_half_h = 0.25

        if not self.editor_enabled:
            self.editor_notice = OnscreenText(
                text="No modules found.",
                pos=(editor_center_x, 0),
                align=TextNode.ACenter,
                scale=min(0.04, max(0.024, editor_height * 0.06)),
                fg=(0.9, 0.7, 0.7, 0.9),
                shadow=(0, 0, 0, 0.8),
                mayChange=False,
                parent=self.editor_root,
            )
            return

        colors = [
            (0.75, 0.45, 0.35, 1),
            (0.35, 0.55, 0.8, 1),
            (0.4, 0.7, 0.4, 1),
            (0.65, 0.55, 0.85, 1),
        ]

        card_maker = CardMaker("module_card")
        card_maker.set_frame(-0.5, 0.5, -0.25, 0.25)

        modules = list(zip(self.world.module_nodes, self.world.module_meta))
        total_width = (len(modules) - 1) * 1.0
        start_x = -total_width / 2 if modules else 0.0

        for i, (module, meta) in enumerate(modules):
            room_name = meta.get("name", f"Module {i + 1}")
            room = Room(room_name, colors[i % len(colors)])
            room.model = self.editor_canvas.attachNewNode(card_maker.generate())
            room.model.setPos(start_x + i * 1.0, 0, 0.0)
            self._apply_editor_room_style(room, meta, i)
            self.editor_dungeon.add_room(room)
            self.editor_room_to_module[room] = {"node": module, "meta": meta}
            self.editor_module_to_room[id(module)] = room

        for room in self.editor_dungeon.rooms:
            self.editor_dungeon.link_rooms(room, self.editor_canvas)

        self._fit_editor_canvas()
        self._compute_editor_world_mapping()
        self._sync_world_from_editor()

    def _compute_editor_world_mapping(self):
        modules = list(self.editor_room_to_module.values())
        if not modules:
            self.editor_unit_to_world = 1.0
            self.editor_world_origin = 0.0
            return

        world_centers = []
        editor_centers = []
        for room in self.editor_dungeon.rooms:
            mapping = self.editor_room_to_module.get(room)
            if not mapping:
                continue
            meta = mapping["meta"]
            node = mapping["node"]
            world_centers.append(node.getX() + meta["center_offset"])
            editor_centers.append(room.model.getX())

        if len(world_centers) > 1:
            world_centers_sorted = sorted(world_centers)
            editor_centers_sorted = sorted(editor_centers)
            world_spacing = sum(
                world_centers_sorted[i + 1] - world_centers_sorted[i]
                for i in range(len(world_centers_sorted) - 1)
            ) / (len(world_centers_sorted) - 1)
            editor_spacing = sum(
                editor_centers_sorted[i + 1] - editor_centers_sorted[i]
                for i in range(len(editor_centers_sorted) - 1)
            ) / (len(editor_centers_sorted) - 1)
            self.editor_unit_to_world = world_spacing / editor_spacing if editor_spacing else 1.0
        else:
            self.editor_unit_to_world = 1.0

        self.editor_world_origin = world_centers[0] - editor_centers[0] * self.editor_unit_to_world

    def _fit_editor_canvas(self):
        if not self.editor_dungeon.rooms:
            return
        min_x = min(room.model.getX() - self.editor_room_half_w for room in self.editor_dungeon.rooms)
        max_x = max(room.model.getX() + self.editor_room_half_w for room in self.editor_dungeon.rooms)
        min_z = min(room.model.getZ() - self.editor_room_half_h for room in self.editor_dungeon.rooms)
        max_z = max(room.model.getZ() + self.editor_room_half_h for room in self.editor_dungeon.rooms)

        content_w = max(0.01, max_x - min_x)
        content_h = max(0.01, max_z - min_z)
        content_cx = (min_x + max_x) * 0.5
        content_cz = (min_z + max_z) * 0.5

        left, right, bottom, top = self.editor_frame
        margin_x = 0.12
        margin_y = min(0.3, max(0.04, (top - bottom) * 0.2))
        available_w = max(0.01, (right - left) - margin_x * 2)
        available_h = max(0.01, (top - bottom) - margin_y * 2)

        scale = min(available_w / content_w, available_h / content_h) * 0.92
        self.editor_scale = scale
        self.editor_canvas.setScale(scale, 1, scale)

        target_x = left + margin_x + available_w * 0.5 - content_cx * scale
        target_z = bottom + margin_y + available_h * 0.5 - content_cz * scale
        self.editor_canvas.setPos(target_x, 0, target_z)

    def _get_editor_mouse_pos(self) -> Vec3 | None:
        if not self.mouseWatcherNode.hasMouse():
            return None
        mx = self.mouseWatcherNode.getMouseX()
        my = self.mouseWatcherNode.getMouseY()
        aspect = self.getAspectRatio()
        ax = mx * aspect
        az = my

        root_pos = self.editor_root.getPos(self.aspect2d)
        canvas_pos = self.editor_canvas.getPos(self.editor_root)
        local_x = (ax - root_pos.x - canvas_pos.x) / self.editor_scale
        local_z = (az - root_pos.z - canvas_pos.z) / self.editor_scale
        return Vec3(local_x, 0, local_z)

    def _boss_editor_handle_click(self) -> bool:
        if (
            not self.editor_enabled
            or self.player_id != 1
            or self.editor_root.isHidden()
            or not self.editor_expanded
        ):
            return False
        pos = self._get_editor_mouse_pos()
        if pos is None:
            return False
        for room in self.editor_dungeon.rooms:
            rx = room.model.getX()
            rz = room.model.getZ()
            if abs(pos.x - rx) <= self.editor_room_half_w and abs(pos.z - rz) <= self.editor_room_half_h:
                self.editor_dragged_room = room
                self.editor_drag_offset = room.model.getPos() - pos
                return True
        return False

    def _on_editor_panel_press(self, _event=None):
        if self.player_id != 1 or not self.editor_enabled or not self.editor_expanded:
            return
        self._ui_consumed_click = True
        self._boss_editor_handle_click()

    def _on_editor_tab_press(self, _event=None):
        if self.player_id != 1 or not self.editor_enabled:
            return
        self._ui_consumed_click = True
        self.editor_expanded = not self.editor_expanded

    def _is_mouse_over_editor(self) -> bool:
        if not self.editor_enabled or self.editor_root.isHidden() or not self.editor_expanded:
            return False
        if not self.mouseWatcherNode.hasMouse():
            return False
        mx = self.mouseWatcherNode.getMouseX()
        my = self.mouseWatcherNode.getMouseY()
        aspect = self.getAspectRatio()
        ax = mx * aspect
        az = my
        root_pos = self.editor_root.getPos(self.aspect2d)
        local_x = ax - root_pos.x
        local_z = az - root_pos.z
        left, right, bottom, top = self.editor_frame
        return left <= local_x <= right and bottom <= local_z <= top

    def _is_mouse_over_tab(self) -> bool:
        if not self.editor_enabled or self.editor_tab.isHidden():
            return False
        if not self.mouseWatcherNode.hasMouse():
            return False
        mx = self.mouseWatcherNode.getMouseX()
        my = self.mouseWatcherNode.getMouseY()
        aspect = self.getAspectRatio()
        ax = mx * aspect
        az = my
        tab_pos = self.editor_tab.getPos(self.aspect2d)
        local_x = ax - tab_pos.x
        local_z = az - tab_pos.z
        left, right, bottom, top = self.editor_tab_frame
        return left <= local_x <= right and bottom <= local_z <= top

    def _boss_editor_release(self):
        if not self.editor_dragged_room:
            return
        self.editor_dungeon.link_rooms(self.editor_dragged_room, self.editor_canvas)
        if self._editor_has_links():
            self._sync_world_from_editor()
        else:
            self._set_status("Link rooms with corridors to apply changes.")
        self.editor_dragged_room = None

    def _editor_has_links(self) -> bool:
        if not self.editor_dungeon.rooms:
            return False
        return all(room.corridor_left or room.corridor_right for room in self.editor_dungeon.rooms)

    def _sync_world_from_editor(self):
        if not self.editor_enabled:
            return
        levels = self._compute_editor_levels()
        ordered_rooms = sorted(self.editor_dungeon.rooms, key=lambda r: r.model.getX())
        current_x = 0.0
        for room in ordered_rooms:
            mapping = self.editor_room_to_module.get(room)
            if not mapping:
                continue
            node = mapping["node"]
            meta = mapping["meta"]
            min_bound = meta.get("min_bound")
            width = float(meta.get("width", 1.0))
            if min_bound is None:
                min_bound = Vec3(0, 0, 0)

            node.setX(current_x - float(min_bound.x))
            level_offset = levels.get(room, 0.0)
            node.setZ(meta["base_z"] + level_offset)
            current_x += width
        self.world.recompute_bounds()
        self.min_x, self.max_x = self.world.setLimit()
        self.goal_x = self.max_x - 2.0

    def _compute_editor_levels(self) -> dict[Room, float]:
        rooms = list(self.editor_dungeon.rooms)
        if not rooms:
            return {}
        rooms.sort(key=lambda r: r.model.getX())

        levels: dict[Room, float] = {}
        current_level = 0.0
        levels[rooms[0]] = current_level

        for i in range(1, len(rooms)):
            room = rooms[i]
            prev = rooms[i - 1] if i > 0 else None
            meta = self.editor_room_to_module.get(room, {}).get("meta", {})
            prev = self.editor_room_to_module.get(prev, {}).get("meta", {})
            delta = self._module_level_delta(meta, prev)
            current_level += delta
            levels[room] = current_level

        return levels

    def _module_level_delta(self, meta: dict, prev = None) -> float:
        name = str(meta.get("name", "")).lower()
        path = str(meta.get("path", "")).lower()
        key = name or path
        prev = str(prev.get("name", "")).lower() or str(prev.get("name", "")).lower()
        if "stair" in key and prev and "stair" in prev and prev.replace("stair", "") != key.replace("stair", ""):
            return 0.0
        if "base" in key:
            return 0.0
        if "stair_u" in key:
            return 8.0
        if "stair_d" in key:
            return -8.0
        return 0.0

    def _on_mouse1(self):
        if self._ui_consumed_click:
            self._ui_consumed_click = False
            return
        if self.player_id == 1 and self.editor_enabled and self._is_mouse_over_tab():
            self.editor_expanded = not self.editor_expanded
            return
        if self.player_id == 1 and self._is_mouse_over_editor():
            if self._boss_editor_handle_click():
                return
            return
        self.on_attack_input()

    def _on_mouse1_up(self):
        if self.player_id == 1 and self.editor_enabled:
            self._boss_editor_release()

    def _task_boss_editor_drag(self, task):
        if self.editor_dragged_room and self.player_id == 1:
            pos = self._get_editor_mouse_pos()
            if pos is not None:
                self.editor_dragged_room.model.setPos(pos + self.editor_drag_offset)
        return task.cont

    def _setup_hud(self):
        panel_color = (0.05, 0.07, 0.1, 0.65)
        panel_dark = (0.02, 0.03, 0.05, 0.85)
        text_main = (0.92, 0.96, 1.0, 0.95)
        text_sub = (0.72, 0.78, 0.86, 0.9)
        accent = (0.45, 0.85, 1.0, 0.95)

        self.ui_root = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0, 0, 0, 0),
        )
        self.ui_root.setTransparency(TransparencyAttrib.MAlpha)

        self.left_panel = DirectFrame(
            parent=self.ui_root,
            frameColor=panel_color,
            frameSize=(0, 0.64, -0.24, 0),
            pos=(-1.32, 0, 0.93),
        )
        self.left_panel.setTransparency(TransparencyAttrib.MAlpha)
        self.role_label = OnscreenText(
            text="Connecting...",
            pos=(0.03, -0.06),
            align=TextNode.ALeft,
            scale=0.05,
            fg=text_main,
            shadow=(0, 0, 0, 0.85),
            mayChange=True,
            parent=self.left_panel,
        )
        self.objective_label = OnscreenText(
            text="Waiting for role assignment.",
            pos=(0.03, -0.13),
            align=TextNode.ALeft,
            scale=0.04,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.left_panel,
        )
        self.phase_label = OnscreenText(
            text="",
            pos=(0.03, -0.2),
            align=TextNode.ALeft,
            scale=0.036,
            fg=accent,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.left_panel,
        )

        self.right_panel = DirectFrame(
            parent=self.ui_root,
            frameColor=panel_color,
            frameSize=(-0.64, 0, -0.24, 0),
            pos=(1.32, 0, 0.93),
        )
        self.right_panel.setTransparency(TransparencyAttrib.MAlpha)
        self.hero_label = OnscreenText(
            text="HERO",
            pos=(-0.6, -0.05),
            align=TextNode.ALeft,
            scale=0.035,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.right_panel,
        )
        self.hero_bar = DirectWaitBar(
            text="",
            range=HERO_MAX_HP,
            value=HERO_MAX_HP,
            barColor=(0.25, 0.85, 0.45, 0.9),
            frameColor=panel_dark,
            frameSize=(0, 0.52, -0.02, 0.02),
            pos=(-0.6, 0, -0.095),
            parent=self.right_panel,
        )
        self.hero_hp_text = OnscreenText(
            text=f"{HERO_MAX_HP}/{HERO_MAX_HP}",
            pos=(0.26, -0.01),
            align=TextNode.ACenter,
            scale=0.032,
            fg=text_main,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.hero_bar,
        )
        self.boss_label = OnscreenText(
            text="BOSS",
            pos=(-0.6, -0.135),
            align=TextNode.ALeft,
            scale=0.035,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.right_panel,
        )
        self.boss_bar = DirectWaitBar(
            text="",
            range=BOSS_MAX_HP,
            value=BOSS_MAX_HP,
            barColor=(0.95, 0.45, 0.35, 0.9),
            frameColor=panel_dark,
            frameSize=(0, 0.52, -0.02, 0.02),
            pos=(-0.6, 0, -0.175),
            parent=self.right_panel,
        )
        self.boss_hp_text = OnscreenText(
            text=f"{BOSS_MAX_HP}/{BOSS_MAX_HP}",
            pos=(0.26, -0.01),
            align=TextNode.ACenter,
            scale=0.032,
            fg=text_main,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.boss_bar,
        )
        self.mob_count_text = OnscreenText(
            text=f"Mobs: 0/{MAX_ACTIVE_MOBS}",
            pos=(-0.6, -0.215),
            align=TextNode.ALeft,
            scale=0.034,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.right_panel,
        )

        self.action_panel = DirectFrame(
            parent=self.ui_root,
            frameColor=panel_color,
            frameSize=(-0.7, 0.7, -0.15, 0),
            pos=(0, 0, -0.88),
        )
        self.action_panel.setTransparency(TransparencyAttrib.MAlpha)
        self.control_text = OnscreenText(
            text="Control: --",
            pos=(-0.66, -0.04),
            align=TextNode.ALeft,
            scale=0.038,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.action_panel,
        )
        self.combo_text = OnscreenText(
            text="Combo 0",
            pos=(0.66, -0.04),
            align=TextNode.ARight,
            scale=0.038,
            fg=accent,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.action_panel,
        )
        self.attack_bar = DirectWaitBar(
            text="",
            range=HERO_ATTACK_COOLDOWN,
            value=HERO_ATTACK_COOLDOWN,
            barColor=(0.45, 0.85, 1.0, 0.9),
            frameColor=panel_dark,
            frameSize=(0, 1.25, -0.02, 0.02),
            pos=(-0.62, 0, -0.085),
            parent=self.action_panel,
        )
        self.attack_text = OnscreenText(
            text="Attack Ready",
            pos=(0.62, -0.01),
            align=TextNode.ACenter,
            scale=0.034,
            fg=text_main,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.attack_bar,
        )
        self.spawn_bar = DirectWaitBar(
            text="",
            range=SPAWN_COOLDOWN,
            value=SPAWN_COOLDOWN,
            barColor=(1.0, 0.7, 0.35, 0.9),
            frameColor=panel_dark,
            frameSize=(0, 1.25, -0.02, 0.02),
            pos=(-0.62, 0, -0.125),
            parent=self.action_panel,
        )
        self.spawn_text = OnscreenText(
            text="Spawn Ready",
            pos=(0.62, -0.01),
            align=TextNode.ACenter,
            scale=0.032,
            fg=text_main,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.spawn_bar,
        )
        self.spawn_bar.hide()
        self.spawn_text.hide()

        self.status_panel = DirectFrame(
            parent=self.ui_root,
            frameColor=panel_color,
            frameSize=(-0.6, 0.6, -0.06, 0),
            pos=(0, 0, 0.98),
        )
        self.status_panel.setTransparency(TransparencyAttrib.MAlpha)
        self.status_text = OnscreenText(
            text="",
            pos=(0, -0.04),
            align=TextNode.ACenter,
            scale=0.045,
            fg=text_main,
            shadow=(0, 0, 0, 0.9),
            mayChange=True,
            parent=self.status_panel,
        )
        self.status_panel.hide()
        self._setup_hero_ui()

    def _setup_hero_ui(self):
        self.hero_ui_root = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0, 0, 0, 0),
        )
        self.hero_ui_root.setTransparency(TransparencyAttrib.MAlpha)

        self.hero_bars_root = DirectFrame(
            parent=self.hero_ui_root,
            frameColor=(0, 0, 0, 0),
            pos=(-1.28, 0, 0.93),
        )

        bar_width = 0.58
        bar_height = 0.035
        bar_shadow = (0.0, 0.0, 0.0, 0.35)

        def make_bar(name: str, y: float, x: float, color: tuple[float, float, float, float], label: str):
            bg = DirectFrame(
                parent=self.hero_bars_root,
                frameColor=bar_shadow,
                frameSize=(0, bar_width, -bar_height, 0),
                pos=(x, 0, y),
            )
            bg.setTransparency(TransparencyAttrib.MAlpha)
            bar = DirectWaitBar(
                parent=bg,
                text="",
                range=1.0,
                value=1.0,
                frameColor=(0, 0, 0, 0),
                barColor=color,
                frameSize=(0, bar_width, -bar_height, 0),
                pos=(0, 0, 0),
            )
            label_text = OnscreenText(
                text=f"{label}",
                pos=(bar_width + 0.08, -bar_height * 0.7),
                align=TextNode.ALeft,
                scale=0.038,
                fg=(0.95, 0.95, 0.95, 0.92),
                shadow=(0, 0, 0, 0.85),
                mayChange=True,
                parent=bg,
            )
            return bar, label_text

        self.hero_pv_bar, self.hero_pv_label = make_bar(
            "pv",
            y=0.0,
            x=0.0,
            color=(0.86, 0.22, 0.2, 0.95),
            label="PV",
        )
        self.hero_pm_bar, self.hero_pm_label = make_bar(
            "pm",
            y=-0.055,
            x=0.02,
            color=(0.32, 0.62, 0.9, 0.95),
            label="PM",
        )
        self.hero_endurance_bar, self.hero_endurance_label = make_bar(
            "endurance",
            y=-0.11,
            x=0.04,
            color=(0.35, 0.75, 0.35, 0.95),
            label="ENDURANCE",
        )

        self.hero_objective_text = OnscreenText(
            text="",
            pos=(-1.26, 0.74),
            align=TextNode.ALeft,
            scale=0.038,
            fg=(0.9, 0.92, 0.95, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.hero_ui_root,
        )

        self.hero_bottom_root = DirectFrame(
            parent=self.hero_ui_root,
            frameColor=(0, 0, 0, 0),
            pos=(-1.26, 0, -0.76),
        )

        self.hero_capacity_label = OnscreenText(
            text="SYMBOLE DE CAPACITE",
            pos=(0.02, 0.14),
            align=TextNode.ALeft,
            scale=0.032,
            fg=(0.9, 0.9, 0.9, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.hero_bottom_root,
        )
        self.hero_capacity_outer = DirectFrame(
            parent=self.hero_bottom_root,
            frameColor=(0.9, 0.9, 0.9, 0.15),
            frameSize=(-0.085, 0.085, -0.085, 0.085),
            pos=(0.08, 0, 0.0),
        )
        self.hero_capacity_outer.setTransparency(TransparencyAttrib.MAlpha)
        self.hero_capacity_inner = DirectFrame(
            parent=self.hero_capacity_outer,
            frameColor=(0.05, 0.05, 0.05, 0.7),
            frameSize=(-0.075, 0.075, -0.075, 0.075),
            pos=(0, 0, 0),
        )
        self.hero_capacity_inner.setTransparency(TransparencyAttrib.MAlpha)
        self.hero_capacity_icon = OnscreenText(
            text="*",
            pos=(0, -0.03),
            align=TextNode.ACenter,
            scale=0.08,
            fg=(0.95, 0.95, 0.95, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.hero_capacity_inner,
        )

        self.hero_items_label = OnscreenText(
            text="OBJETS OBTENUS",
            pos=(0.32, 0.03),
            align=TextNode.ALeft,
            scale=0.032,
            fg=(0.9, 0.9, 0.9, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.hero_bottom_root,
        )
        self.hero_item_slots_root = DirectFrame(
            parent=self.hero_bottom_root,
            frameColor=(0, 0, 0, 0),
            pos=(0.32, 0, -0.06),
        )
        self.hero_item_slots: list[DirectFrame] = []
        for i in range(4):
            slot = DirectFrame(
                parent=self.hero_item_slots_root,
                frameColor=(0.08, 0.08, 0.08, 0.7),
                frameSize=(0, 0.08, -0.08, 0),
                pos=(i * 0.095, 0, 0),
            )
            slot.setTransparency(TransparencyAttrib.MAlpha)
            self.hero_item_slots.append(slot)

        self.hero_ui_root.hide()

    def _set_status(self, text: str):
        self.status_text.setText(text)
        self.status_timer = 2.8
        self.status_panel.show()
        self.status_panel.setAlphaScale(0.9)
        self.status_text.setAlphaScale(1.0)

    def _update_status(self, dt: float):
        if self.status_timer <= 0.0:
            return
        self.status_timer = max(0.0, self.status_timer - dt)
        if self.status_timer <= 0.0:
            self.status_panel.hide()
            return
        fade_window = 0.6
        if self.status_timer < fade_window:
            alpha = max(0.0, self.status_timer / fade_window)
            self.status_panel.setAlphaScale(0.9 * alpha)
            self.status_text.setAlphaScale(alpha)

    def _set_visible(self, key: str, widget, visible: bool):
        previous = self._ui_visible.get(key)
        if previous is visible:
            return
        if visible:
            widget.show()
        else:
            widget.hide()
        self._ui_visible[key] = visible

    def _set_text_if_changed(self, key: str, widget, text: str):
        if self._ui_cache.get(key) == text:
            return
        widget.setText(text)
        self._ui_cache[key] = text

    def _set_widget_number_if_changed(
        self,
        key: str,
        widget,
        prop: str,
        value: float,
        tolerance: float = 1e-4,
    ):
        prev = self._ui_cache.get(key)
        if prev is not None and abs(float(prev) - float(value)) <= tolerance:
            return
        widget[prop] = value
        self._ui_cache[key] = float(value)

    def _update_hud(self):
        now = time.monotonic()
        is_hero = self.player_id == 0
        is_boss = self.player_id == 1

        if is_hero:
            role = "Hero"
            control = "Hero"
        elif is_boss:
            role = "Boss"
            control = self._control_label(self.controlled_entity).title()
        else:
            role = "Connecting"
            control = "--"

        right_hidden_for_editor = is_boss and self.editor_enabled and self.editor_expanded
        show_editor_tab = is_boss and self.editor_enabled
        show_editor_root = show_editor_tab and self.editor_expanded

        self._set_visible("hero_ui_root", self.hero_ui_root, is_hero)
        self._set_visible("left_panel", self.left_panel, not is_hero)
        self._set_visible("right_panel", self.right_panel, (not is_hero) and (not right_hidden_for_editor))
        self._set_visible("action_panel", self.action_panel, not is_hero)
        self._set_visible("editor_root", self.editor_root, show_editor_root)
        self._set_visible("editor_tab", self.editor_tab, show_editor_tab)
        if show_editor_tab:
            self._update_editor_tab_image()
            if self.editor_tab_label.isHidden():
                self._ui_cache["editor_tab_label"] = None
            else:
                self._set_text_if_changed(
                    "editor_tab_label",
                    self.editor_tab_label,
                    ">" if self.editor_expanded else "<",
                )

        self._set_text_if_changed("role_label", self.role_label, f"Role: {role}")
        self._set_text_if_changed("control_text", self.control_text, f"Control: {control}")

        if self.winner:
            objective = "Game over."
        elif is_hero:
            if self.boss_phase_unlocked:
                objective = "Objective: defeat the boss."
            else:
                objective = f"Objective: reach X >= {self.goal_x:.1f}, then defeat the boss."
        elif is_boss:
            objective = "Objective: kill the hero before they kill you."
        else:
            objective = "Waiting for role assignment."
        self._set_text_if_changed("objective_label", self.objective_label, objective)

        if self.winner:
            phase_text = f"{self.winner.title()} wins!"
        elif self.boss_phase_unlocked:
            phase_text = "Phase 2: boss vulnerable"
        else:
            phase_text = ""
        self._set_text_if_changed("phase_label", self.phase_label, phase_text)

        if is_hero:
            self._set_text_if_changed("hero_objective_text", self.hero_objective_text, objective)

        hero_hp = max(0, min(self.hero_hp, HERO_MAX_HP))
        boss_hp = max(0, min(self.boss_hp, BOSS_MAX_HP))
        self._set_widget_number_if_changed("hero_bar_range", self.hero_bar, "range", HERO_MAX_HP)
        self._set_widget_number_if_changed("hero_bar_value", self.hero_bar, "value", hero_hp)
        self._set_text_if_changed("hero_hp_text", self.hero_hp_text, f"{hero_hp}/{HERO_MAX_HP}")
        self._set_widget_number_if_changed("boss_bar_range", self.boss_bar, "range", BOSS_MAX_HP)
        self._set_widget_number_if_changed("boss_bar_value", self.boss_bar, "value", boss_hp)
        self._set_text_if_changed("boss_hp_text", self.boss_hp_text, f"{boss_hp}/{BOSS_MAX_HP}")

        mob_count = len(self.local_mobs) if is_boss else len(self.remote_mobs)
        self._set_text_if_changed("mob_count_text", self.mob_count_text, f"Mobs: {mob_count}/{MAX_ACTIVE_MOBS}")

        attack_cd = self._get_current_attack_cooldown()
        cd_key = self._get_attack_cooldown_key()
        attack_left = max(0.0, attack_cd - (now - self.last_attack_times[cd_key]))
        combo_step = self.combo_state[cd_key]["step"] + 1 if self.combo_state[cd_key]["step"] >= 0 else 0
        self._set_text_if_changed("combo_text", self.combo_text, f"Combo {combo_step}")

        self._set_widget_number_if_changed("attack_bar_range", self.attack_bar, "range", max(0.001, attack_cd))
        self._set_widget_number_if_changed("attack_bar_value", self.attack_bar, "value", max(0.0, attack_cd - attack_left))
        if attack_left <= 0.001:
            self._set_text_if_changed("attack_text", self.attack_text, "Attack Ready")
        else:
            self._set_text_if_changed("attack_text", self.attack_text, f"Attack {attack_left:.2f}s")

        if is_boss:
            spawn_left = max(0.0, SPAWN_COOLDOWN - (now - self.last_spawn_time))
            self._set_visible("spawn_bar", self.spawn_bar, True)
            self._set_visible("spawn_text", self.spawn_text, True)
            self._set_widget_number_if_changed("spawn_bar_range", self.spawn_bar, "range", SPAWN_COOLDOWN)
            self._set_widget_number_if_changed(
                "spawn_bar_value",
                self.spawn_bar,
                "value",
                max(0.0, SPAWN_COOLDOWN - spawn_left),
            )
            if spawn_left <= 0.001:
                self._set_text_if_changed(
                    "spawn_text",
                    self.spawn_text,
                    f"Spawn Ready ({len(self.local_mobs)}/{MAX_ACTIVE_MOBS})",
                )
            else:
                self._set_text_if_changed(
                    "spawn_text",
                    self.spawn_text,
                    f"Spawn {spawn_left:.2f}s ({len(self.local_mobs)}/{MAX_ACTIVE_MOBS})",
                )
        else:
            self._set_visible("spawn_bar", self.spawn_bar, False)
            self._set_visible("spawn_text", self.spawn_text, False)

        if is_hero:
            pv_ratio = 0.0 if HERO_MAX_HP <= 0 else hero_hp / HERO_MAX_HP
            self._set_widget_number_if_changed("hero_pv_value", self.hero_pv_bar, "value", max(0.0, min(1.0, pv_ratio)))

            pm_ratio = 1.0
            if attack_cd > 0.0:
                pm_ratio = 1.0 - (attack_left / attack_cd)
            self._set_widget_number_if_changed("hero_pm_value", self.hero_pm_bar, "value", max(0.0, min(1.0, pm_ratio)))

            end_ratio = 1.0
            state = self.combo_state.get(self._get_attack_cooldown_key(), {"step": -1, "last_time": 0.0})
            if state.get("step", -1) >= 0:
                elapsed = max(0.0, now - float(state.get("last_time", now)))
                end_ratio = max(0.0, 1.0 - (elapsed / COMBO_WINDOW))
            self._set_widget_number_if_changed(
                "hero_endurance_value",
                self.hero_endurance_bar,
                "value",
                max(0.0, min(1.0, end_ratio)),
            )

    def _init_entities_for_role(self):
        if self.hero or self.boss:
            return

        hero_start = Vec3(self.min_x + 2.0, 0, 7)
        boss_start = Vec3(self.max_x - 5.0, 0, 7)

        self.hero = Character(self.game_config, self.render, self.loader, self.physics, start_pos=hero_start)
        if self.player_id == 0:
            self.boss = Mob(self.game_config, self.render, self.loader, self.physics, boss_start, mode="REMOTE")
            self.controlled_entity = "hero"
            self._set_status("Hero ready. Reach the end to unlock the boss.")
        else:
            self.boss = Mob(self.game_config, self.render, self.loader, self.physics, boss_start, mode="PLAYER")
            self.controlled_entity = "boss"
            self._set_status("Boss ready. F=spawn (limit/cd), TAB=cycle, 1-6=pick mob, B=boss.")

        self._update_hud()

    def _queue_message(self, payload: dict[str, Any]):
        if payload.get("type") == "state":
            # Keep only the freshest state update to avoid latency from stale snapshots.
            self._pending_state_payload = payload
            return
        if len(self._outbox) > 300:
            while len(self._outbox) > 150:
                self._outbox.popleft()
        self._outbox.append(payload)

    def _get_attack_cooldown_key(self) -> str:
        if self.player_id == 0:
            return "hero"
        if self.controlled_entity == "boss":
            return "boss"
        return "mob"

    def _get_current_attack_cooldown(self) -> float:
        key = self._get_attack_cooldown_key()
        if key == "hero":
            return HERO_ATTACK_COOLDOWN
        if key == "boss":
            return BOSS_ATTACK_COOLDOWN
        return CONTROLLED_MOB_ATTACK_COOLDOWN

    def _can_attack(self, now: float) -> tuple[bool, str, float]:
        cd_key = self._get_attack_cooldown_key()
        cooldown = self._get_current_attack_cooldown()
        elapsed = now - self.last_attack_times[cd_key]
        if elapsed >= cooldown:
            return True, cd_key, 0.0
        return False, cd_key, cooldown - elapsed

    def _next_combo_multiplier(self, cd_key: str, now: float) -> tuple[float, float]:
        state = self.combo_state[cd_key]
        if now - state["last_time"] <= COMBO_WINDOW:
            state["step"] = (state["step"] + 1) % len(COMBO_DAMAGE)
        else:
            state["step"] = 0
        state["last_time"] = now
        idx = state["step"]
        return COMBO_DAMAGE[idx], COMBO_RANGE_BONUS[idx]

    def _apply_attack_lunge(self, attacker_np, intensity: float):
        if attacker_np is None:
            return
        if not hasattr(attacker_np, "node"):
            return

        node = attacker_np.node()
        if not hasattr(node, "getLinearVelocity"):
            return

        forward = attacker_np.getQuat().getForward()
        vel = node.getLinearVelocity()
        vel.setX(vel.x + forward.x * intensity)
        vel.setY(0.0)
        node.setLinearVelocity(vel)

    def _trigger_hitstop(self, duration: float = HITSTOP_DURATION):
        self.hitstop_remaining = max(self.hitstop_remaining, duration)

    def _set_remote_target(
        self,
        key: str,
        x: float,
        z: float,
        h: float,
        moving: bool = False,
        attacking: bool = False,
        jumping: bool = False,
    ):
        now = time.monotonic()
        prev = self.remote_targets.get(key)
        vx = vz = 0.0
        if prev is not None:
            dt = max(0.001, now - float(prev.get("last_update", now)))
            vx = (x - float(prev.get("x", x))) / dt
            vz = (z - float(prev.get("z", z))) / dt

        self.remote_targets[key] = {
            "x": x,
            "z": z,
            "h": h,
            "moving": moving,
            "attacking": attacking,
            "jumping": jumping,
            "vx": vx,
            "vz": vz,
            "last_update": now,
        }

    def _angle_lerp(self, current: float, target: float, factor: float) -> float:
        delta = ((target - current + 180.0) % 360.0) - 180.0
        return current + delta * factor

    def _resolve_remote_entity(self, key: str):
        if key == "hero":
            return self.hero
        if key == "boss":
            return self.boss
        if key.startswith("mob:"):
            try:
                mob_id = int(key.split(":", 1)[1])
            except ValueError:
                return None
            return self.remote_mobs.get(mob_id)
        return None

    async def _flush_outbox(self):
        if not self.websocket or not self._connection_established:
            return
        while self._outbox:
            payload = self._outbox.popleft()
            await self.websocket.send(json.dumps(payload, separators=(",", ":")))
        if self._pending_state_payload is not None:
            payload = self._pending_state_payload
            self._pending_state_payload = None
            await self.websocket.send(json.dumps(payload, separators=(",", ":")))

    async def websocket_handler(self):
        while True:
            try:
                self._set_status("Connecting to server...")
                async with websockets.connect(self.ws_uri) as websocket:
                    self.websocket = websocket
                    self._connection_established = True
                    self._set_status("Connected.")

                    while True:
                        try:
                            response = await asyncio.wait_for(websocket.recv(), timeout=0.02)
                            self._handle_server_message(response)
                        except asyncio.TimeoutError:
                            pass

                        await self._flush_outbox()
                        await asyncio.sleep(0.01)

            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                self._connection_established = False
                self.websocket = None
                self._set_status("Disconnected. Reconnecting...")
                await asyncio.sleep(1.5)
            except Exception as exc:
                self._connection_established = False
                self.websocket = None
                self._set_status("Network error. Reconnecting...")
                await asyncio.sleep(1.5)

    def _handle_server_message(self, raw_message: str):
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            if self.player_id is None and raw_message.isdigit():
                self.player_id = int(raw_message)
                GLOBAL_STATE.set_player_id(self.player_id)
                self._init_entities_for_role()
            return

        msg_type = data.get("type")
        if msg_type == "welcome":
            self.player_id = int(data.get("player_id", 0))
            GLOBAL_STATE.set_player_id(self.player_id)
            self._init_entities_for_role()
            return

        if msg_type == "peer_status":
            role = data.get("role")
            status = data.get("status")
            self._set_status(f"Peer role {role} {status}.")
            if status == "left":
                if int(role) == 1:
                    self.remote_targets.pop("boss", None)
                    for mob_id, mob in list(self.remote_mobs.items()):
                        mob.destroy()
                        del self.remote_mobs[mob_id]
                        self.remote_targets.pop(f"mob:{mob_id}", None)
                elif int(role) == 0:
                    self.remote_targets.pop("hero", None)
            return

        if msg_type == "relay":
            sender = int(data.get("from", -1))
            payload = data.get("payload", {})
            if isinstance(payload, dict):
                self._handle_peer_payload(sender, payload)

    def _handle_peer_payload(self, sender: int, payload: dict[str, Any]):
        payload_type = payload.get("type")
        if payload_type == "state":
            if sender == 0:
                self._apply_remote_hero_state(payload)
            elif sender == 1:
                self._apply_remote_boss_state(payload)
        elif payload_type == "attack":
            self._apply_incoming_attack(payload)
        elif payload_type == "phase":
            if bool(payload.get("unlocked", False)):
                self._unlock_boss_phase(announce=False)
        elif payload_type == "game_over":
            winner = payload.get("winner")
            if winner in ("hero", "boss"):
                self._declare_winner(winner, announce=False)

    def _apply_remote_hero_state(self, payload: dict[str, Any]):
        if not self.hero:
            return
        hero = payload.get("hero", {})
        if isinstance(hero, dict):
            self._set_remote_target(
                "hero",
                float(hero.get("x", self.hero.np.getX())),
                float(hero.get("z", self.hero.np.getZ())),
                float(hero.get("h", self.hero.np.getH())),
                bool(hero.get("moving", False)),
                bool(hero.get("attacking", False)),
                bool(hero.get("jumping", False)),
            )

        self.hero_hp = int(payload.get("hero_hp", self.hero_hp))
        if bool(payload.get("boss_phase_unlocked", False)):
            self._unlock_boss_phase(announce=False)

    def _apply_remote_boss_state(self, payload: dict[str, Any]):
        if not self.boss:
            return
        boss = payload.get("boss", {})
        if isinstance(boss, dict):
            self._set_remote_target(
                "boss",
                float(boss.get("x", self.boss.np.getX())),
                float(boss.get("z", self.boss.np.getZ())),
                float(boss.get("h", self.boss.np.getH())),
                bool(boss.get("moving", False)),
                bool(boss.get("attacking", False)),
                False,
            )

        self.boss_hp = int(payload.get("boss_hp", self.boss_hp))
        if bool(payload.get("boss_phase_unlocked", False)):
            self._unlock_boss_phase(announce=False)

        mobs = payload.get("mobs", [])
        if isinstance(mobs, list):
            self._sync_remote_mobs(mobs)

        world_payload = payload.get("world")
        if isinstance(world_payload, dict):
            self._apply_remote_world_layout(world_payload)

    def _apply_remote_world_layout(self, world_payload: dict[str, Any]):
        modules = world_payload.get("modules")
        if not isinstance(modules, list):
            return
        sig_items: list[tuple[int, float, float]] = []
        for item in modules:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("id", -1))
                x = round(float(item.get("x", 0.0)), 3)
                z = round(float(item.get("z", 0.0)), 3)
            except (TypeError, ValueError):
                continue
            sig_items.append((idx, x, z))
        sig = tuple(sig_items)
        if sig == self._last_world_layout_sig:
            return
        self._last_world_layout_sig = sig

        for item in modules:
            if not isinstance(item, dict):
                continue
            idx = int(item.get("id", -1))
            if idx < 0 or idx >= len(getattr(self.world, "module_nodes", [])):
                continue
            node = self.world.module_nodes[idx]
            node.setX(float(item.get("x", node.getX())))
            node.setZ(float(item.get("z", node.getZ())))
        self.world.recompute_bounds()
        self.min_x, self.max_x = self.world.setLimit()
        self.goal_x = self.max_x - 2.0

    def _sync_remote_mobs(self, mobs_data: list[dict[str, Any]]):
        seen_ids: set[int] = set()
        for data in mobs_data:
            try:
                mob_id = int(data.get("id"))
            except (TypeError, ValueError):
                continue
            seen_ids.add(mob_id)

            x = float(data.get("x", 0.0))
            z = float(data.get("z", 0.0))
            h = float(data.get("h", 0.0))

            if mob_id not in self.remote_mobs:
                self.remote_mobs[mob_id] = Mob(
                    self.game_config,
                    self.render,
                    self.loader,
                    self.physics,
                    start_pos=Vec3(x, 0, z),
                    mode="REMOTE",
                )

            self._set_remote_target(
                f"mob:{mob_id}",
                x,
                z,
                h,
                bool(data.get("moving", False)),
                bool(data.get("attacking", False)),
                False,
            )

        stale_ids = [mob_id for mob_id in self.remote_mobs if mob_id not in seen_ids]
        for mob_id in stale_ids:
            self.remote_mobs[mob_id].destroy()
            del self.remote_mobs[mob_id]
            self.remote_targets.pop(f"mob:{mob_id}", None)

    def _build_local_state_payload(self) -> dict[str, Any] | None:
        if self.player_id is None or not self.hero or not self.boss:
            return None

        if self.player_id == 0:
            hero_anim = self.hero.get_network_anim_state()
            return {
                "type": "state",
                "hero": {
                    "x": float(self.hero.np.getX()),
                    "z": float(self.hero.np.getZ()),
                    "h": float(self.hero.np.getH()),
                    "moving": bool(hero_anim["moving"]),
                    "jumping": bool(hero_anim["jumping"]),
                    "attacking": bool(hero_anim["attacking"]),
                },
                "hero_hp": self.hero_hp,
                "boss_phase_unlocked": self.boss_phase_unlocked,
            }

        boss_anim = self.boss.get_network_anim_state()
        mobs_payload = []
        for mob_id, mob in self.local_mobs.items():
            anim = mob.get_network_anim_state()
            mobs_payload.append(
                {
                    "id": mob_id,
                    "x": float(mob.np.getX()),
                    "z": float(mob.np.getZ()),
                    "h": float(mob.np.getH()),
                    "moving": bool(anim["moving"]),
                    "attacking": bool(anim["attacking"]),
                    "hp": int(self.local_mob_hp.get(mob_id, MOB_MAX_HP)),
                }
            )

        payload = {
            "type": "state",
            "boss": {
                "x": float(self.boss.np.getX()),
                "z": float(self.boss.np.getZ()),
                "h": float(self.boss.np.getH()),
                "moving": bool(boss_anim["moving"]),
                "attacking": bool(boss_anim["attacking"]),
            },
            "boss_hp": self.boss_hp,
            "boss_phase_unlocked": self.boss_phase_unlocked,
            "controlled": self.controlled_entity,
            "mobs": mobs_payload,
        }
        if self.editor_enabled:
            payload["world"] = self._get_world_layout_payload()
        return payload

    def _get_world_layout_payload(self) -> dict[str, Any]:
        layout = []
        levels = self._compute_editor_levels() if self.editor_enabled else {}
        for idx, node in enumerate(getattr(self.world, "module_nodes", [])):
            meta = self.world.module_meta[idx] if idx < len(self.world.module_meta) else {}
            room = self.editor_module_to_room.get(id(node)) if self.editor_enabled else None
            level_offset = float(levels.get(room, 0.0)) if room else 0.0
            layout.append(
                {
                    "id": idx,
                    "x": float(node.getX()),
                    "z": float(node.getZ()),
                    "level": level_offset,
                    "name": meta.get("name", ""),
                }
            )
        return {"modules": layout}

    def _unlock_boss_phase(self, announce: bool):
        if self.boss_phase_unlocked:
            return
        self.boss_phase_unlocked = True
        self._set_status("Boss is now vulnerable.")
        if announce:
            self._queue_message({"type": "phase", "unlocked": True})

    def _declare_winner(self, winner: str, announce: bool):
        if self.winner is not None:
            return
        self.winner = winner
        if winner == "hero":
            self._set_status("Hero wins.")
        else:
            self._set_status("Boss wins.")
        if announce:
            self._queue_message({"type": "game_over", "winner": winner})

    def _entity_distance(self, source_np, target_np) -> float:
        dx = source_np.getX() - target_np.getX()
        dz = source_np.getZ() - target_np.getZ()
        return (dx * dx + dz * dz) ** 0.5

    def _spawn_pulse_vfx(self, pos: Vec3, color: tuple[float, float, float, float], base_scale: float, duration: float):
        pulse = self._pulse_model_template.copyTo(self.render)
        pulse.setPos(pos)
        pulse.setScale(base_scale)
        pulse.setColor(*color)
        pulse.setTransparency(TransparencyAttrib.MAlpha)
        self.active_vfx.append(
            {
                "kind": "pulse",
                "np": pulse,
                "age": 0.0,
                "duration": duration,
                "base_scale": base_scale,
            }
        )

    def _spawn_damage_text(self, pos: Vec3, damage: int, color: tuple[float, float, float, float]):
        tn = TextNode("damage_text")
        tn.setAlign(TextNode.ACenter)
        tn.setText(f"-{damage}")
        tn.setTextColor(*color)
        txt_np = self.render.attachNewNode(tn)
        txt_np.setPos(pos + Vec3(0, 0, 3.4))
        txt_np.setBillboardPointEye()
        txt_np.setScale(1.3)
        self.active_vfx.append(
            {
                "kind": "text",
                "np": txt_np,
                "age": 0.0,
                "duration": 0.45,
                "rise_speed": 1.5,
            }
        )

    def _flash_entity(self, node, duration: float = 0.12):
        if node is None or node.isEmpty():
            return
        node.setColorScale(1.9, 0.55, 0.55, 1)
        self.active_flashes.append({"np": node, "time_left": duration})

    def _play_attack_vfx(self, attacker_np):
        if attacker_np is None:
            return
        self._spawn_pulse_vfx(attacker_np.getPos(self.render) + Vec3(0, 0, 1.8), (1.0, 0.85, 0.35, 0.75), 0.18, 0.2)

    def _play_hit_vfx(self, target_np, damage: int):
        if target_np is None:
            return
        world_pos = target_np.getPos(self.render) + Vec3(0, 0, 2.1)
        self._spawn_pulse_vfx(world_pos, (1.0, 0.35, 0.25, 0.85), 0.25, 0.22)
        self._spawn_damage_text(world_pos, damage, (1.0, 0.75, 0.35, 1.0))
        self._flash_entity(target_np, 0.1)
        self._trigger_hitstop(HITSTOP_DURATION)
        self.shake_camera(0.2, 0.12)

    def _update_vfx(self, dt: float):
        next_vfx: list[dict[str, Any]] = []
        for fx in self.active_vfx:
            node = fx["np"]
            if node.isEmpty():
                continue

            fx["age"] += dt
            t = min(1.0, fx["age"] / fx["duration"])
            if fx["kind"] == "pulse":
                scale = fx["base_scale"] * (1.0 + 3.2 * t)
                node.setScale(scale)
                node.setAlphaScale(max(0.0, 1.0 - t))
            elif fx["kind"] == "text":
                node.setZ(node.getZ() + fx["rise_speed"] * dt)
                node.setColorScale(1, 1, 1, max(0.0, 1.0 - t))

            if t >= 1.0:
                node.removeNode()
                continue
            next_vfx.append(fx)
        self.active_vfx = next_vfx

        next_flashes: list[dict[str, Any]] = []
        for flash in self.active_flashes:
            node = flash["np"]
            flash["time_left"] -= dt
            if flash["time_left"] <= 0.0:
                if node is not None and not node.isEmpty():
                    node.clearColorScale()
                continue
            next_flashes.append(flash)
        self.active_flashes = next_flashes

    def _update_remote_motion(self, dt: float):
        now = time.monotonic()
        for key, target in list(self.remote_targets.items()):
            smoothing = NETWORK_SMOOTHING
            prediction_limit = NETWORK_PREDICTION_LIMIT
            # if key.startswith("mob:"):
            #     smoothing *= 1.6
            #     prediction_limit *= 1.4
            blend = 1.0 - math.exp(-smoothing * dt)
            entity = self._resolve_remote_entity(key)
            if entity is None:
                self.remote_targets.pop(key, None)
                continue

            np = entity.np
            age = max(0.0, now - float(target.get("last_update", now)))
            predict = min(age, prediction_limit)
            tx = float(target["x"]) + float(target.get("vx", 0.0)) * predict
            tz = float(target["z"]) + float(target.get("vz", 0.0)) * predict
            th = float(target["h"])
            dx = tx - np.getX()
            dz = tz - np.getZ()
            dist = (dx * dx + dz * dz) ** 0.5

            if dist > SNAP_DISTANCE:
                np.setX(tx)
                np.setZ(tz)
            else:
                np.setX(np.getX() + dx * blend)
                np.setZ(np.getZ() + dz * blend)
            np.setH(self._angle_lerp(np.getH(), th, blend))

            speed = math.hypot(float(target.get("vx", 0.0)), float(target.get("vz", 0.0)))
            moving = bool(target.get("moving", False)) or speed > NETWORK_MOVE_SPEED or dist > NETWORK_MOVE_DIST

            if key == "hero" and self.hero:
                self.hero.apply_remote_animation(
                    moving,
                    bool(target["attacking"]),
                    bool(target["jumping"]),
                )
            else:
                entity.apply_remote_animation(moving, bool(target["attacking"]))

    def on_attack_input(self):
        if self.player_id is None or self.winner or not self.hero or not self.boss:
            return

        now = time.monotonic()
        can_attack, _, left = self._can_attack(now)
        if not can_attack:
            self.attack_buffer_until = now + ATTACK_INPUT_BUFFER
            self._set_status(f"Attack buffered ({left:.2f}s)")
            return

        self._perform_attack(now)

    def _perform_attack(self, now: float):
        can_attack, cd_key, _ = self._can_attack(now)
        if not can_attack:
            return
        self.last_attack_times[cd_key] = now
        self.attack_buffer_until = 0.0

        combo_multiplier, combo_range_bonus = self._next_combo_multiplier(cd_key, now)
        if self.player_id == 0:
            self.hero.perform_attack()
            self._send_hero_attack(combo_multiplier, combo_range_bonus)
        else:
            if self.controlled_entity == "boss" and self.boss:
                self.boss.perform_attack()
            elif isinstance(self.controlled_entity, int):
                mob = self.local_mobs.get(self.controlled_entity)
                if mob:
                    mob.perform_attack()
            self._send_boss_attack(combo_multiplier, combo_range_bonus)

    def _process_attack_buffer(self):
        if self.player_id is None or self.winner or not self.hero or not self.boss:
            self.attack_buffer_until = 0.0
            return
        if self.attack_buffer_until <= 0.0:
            return
        now = time.monotonic()
        if now > self.attack_buffer_until:
            self.attack_buffer_until = 0.0
            return
        can_attack, _, _ = self._can_attack(now)
        if can_attack:
            self._perform_attack(now)

    def _send_hero_attack(self, combo_multiplier: float, combo_range_bonus: float):
        self._play_attack_vfx(self.hero.np)
        self._apply_attack_lunge(self.hero.np, 3.5 + combo_range_bonus * 4.0)
        sent = False
        damage = int(HERO_DAMAGE * combo_multiplier)
        hit_range = ATTACK_RANGE + combo_range_bonus

        if self.boss_phase_unlocked and self._entity_distance(self.hero.np, self.boss.np) <= hit_range:
            self._queue_message({"type": "attack", "target": "boss", "damage": damage})
            self._play_hit_vfx(self.boss.np, damage)
            sent = True

        for mob_id, mob in self.remote_mobs.items():
            if self._entity_distance(self.hero.np, mob.np) <= hit_range:
                self._queue_message(
                    {"type": "attack", "target": "mob", "mob_id": mob_id, "damage": damage}
                )
                self._play_hit_vfx(mob.np, damage)
                sent = True

        if not sent:
            self._set_status("Attack missed.")

    def _get_controlled_np(self):
        if self.player_id == 0:
            return self.hero.np if self.hero else None
        if not self.boss:
            return None

        if self.controlled_entity == "boss":
            return self.boss.np
        if isinstance(self.controlled_entity, int):
            mob = self.local_mobs.get(self.controlled_entity)
            if mob:
                return mob.np
        return self.boss.np

    def _send_boss_attack(self, combo_multiplier: float, combo_range_bonus: float):
        attacker_np = self._get_controlled_np()
        if attacker_np is None or not self.hero:
            return

        self._play_attack_vfx(attacker_np)
        self._apply_attack_lunge(attacker_np, 2.8 + combo_range_bonus * 3.5)
        hit_range = ATTACK_RANGE + combo_range_bonus
        if self._entity_distance(attacker_np, self.hero.np) <= hit_range:
            base_damage = BOSS_DAMAGE if self.controlled_entity == "boss" else MOB_DAMAGE
            damage = int(base_damage * combo_multiplier)
            self._queue_message({"type": "attack", "target": "hero", "damage": damage})
            self._play_hit_vfx(self.hero.np, damage)
        else:
            self._set_status("Attack missed.")

    def _apply_incoming_attack(self, payload: dict[str, Any]):
        if self.winner:
            return

        target = payload.get("target")
        damage = int(payload.get("damage", 0))
        damage = max(0, damage)

        if self.player_id == 0 and target == "hero":
            self.hero_hp = max(0, self.hero_hp - damage)
            if self.hero:
                self._play_hit_vfx(self.hero.np, damage)
            if self.hero_hp == 0:
                self._declare_winner("boss", announce=True)
            return

        if self.player_id == 1 and target == "boss":
            if not self.boss_phase_unlocked:
                return
            self.boss_hp = max(0, self.boss_hp - damage)
            if self.boss:
                self._play_hit_vfx(self.boss.np, damage)
            if self.boss_hp == 0:
                self._declare_winner("hero", announce=True)
            return

        if self.player_id == 1 and target == "mob":
            mob_id = payload.get("mob_id")
            if not isinstance(mob_id, int):
                return
            if mob_id not in self.local_mobs:
                return
            hp = max(0, self.local_mob_hp.get(mob_id, MOB_MAX_HP) - damage)
            self.local_mob_hp[mob_id] = hp
            self._play_hit_vfx(self.local_mobs[mob_id].np, damage)
            if hp == 0:
                self._destroy_local_mob(mob_id)

    def spawn_local_mob_request(self):
        if self.player_id != 1 or self.winner:
            return
        if not self.boss:
            return
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            self._set_status(f"Spawn limit reached ({MAX_ACTIVE_MOBS}).")
            return

        now = time.monotonic()
        spawn_left = SPAWN_COOLDOWN - (now - self.last_spawn_time)
        if spawn_left > 0.0:
            self._set_status(f"Spawn on cooldown ({spawn_left:.2f}s)")
            return
        self.last_spawn_time = now

        source_np = self._get_controlled_np() or self.boss.np
        x = source_np.getX() + random.uniform(-1.5, 1.5)
        z = source_np.getZ() + 0.5
        mob_id = self.next_mob_id
        self.next_mob_id += 1

        mob = Mob(
            self.game_config,
            self.render,
            self.loader,
            self.physics,
            start_pos=Vec3(x, 0, z),
            mode="AI",
        )
        self.local_mobs[mob_id] = mob
        self.local_mob_hp[mob_id] = MOB_MAX_HP
        self.ai_attack_clock[mob_id] = 0.0
        self._spawn_pulse_vfx(mob.np.getPos(self.render) + Vec3(0, 0, 1.3), (0.4, 0.95, 1.0, 0.9), 0.22, 0.28)
        slot = self._get_mob_slot(mob_id)
        slot_text = f" (slot {slot})" if slot is not None else ""
        self._set_status(f"Spawned mob #{mob_id}{slot_text}.")

    def _destroy_local_mob(self, mob_id: int):
        mob = self.local_mobs.get(mob_id)
        if not mob:
            return

        self._spawn_pulse_vfx(mob.np.getPos(self.render) + Vec3(0, 0, 1.5), (1.0, 0.45, 0.25, 0.9), 0.28, 0.3)
        mob.destroy()
        del self.local_mobs[mob_id]
        self.local_mob_hp.pop(mob_id, None)
        self.ai_attack_clock.pop(mob_id, None)

        if self.controlled_entity == mob_id:
            self._set_controlled_entity("boss")

    def _set_controlled_entity(self, entity: str | int):
        if self.player_id != 1 or not self.boss:
            return

        if entity != "boss" and entity not in self.local_mobs:
            entity = "boss"
        self.controlled_entity = entity

        self.boss.set_mode("PLAYER" if self.controlled_entity == "boss" else "IDLE")
        for mob_id, mob in self.local_mobs.items():
            mob.set_mode("PLAYER" if mob_id == self.controlled_entity else "AI")

    def _get_mob_slot(self, mob_id: int) -> int | None:
        mob_ids = sorted(self.local_mobs.keys())
        try:
            return mob_ids.index(mob_id) + 1
        except ValueError:
            return None

    def _control_label(self, entity: str | int) -> str:
        if entity == "boss":
            return "boss"
        if isinstance(entity, int):
            slot = self._get_mob_slot(entity)
            slot_text = f" (slot {slot})" if slot is not None else ""
            return f"mob {entity}{slot_text}"
        return "boss"

    def cycle_control(self):
        if self.player_id != 1 or self.winner:
            return

        options: list[str | int] = ["boss"] + sorted(self.local_mobs.keys())
        if not options:
            return

        try:
            current_index = options.index(self.controlled_entity)
        except ValueError:
            current_index = 0

        next_index = (current_index + 1) % len(options)
        self._set_controlled_entity(options[next_index])
        self._set_status(f"Control: {self._control_label(self.controlled_entity)}")

    def select_control_boss(self):
        if self.player_id != 1 or self.winner:
            return
        self._set_controlled_entity("boss")
        self._set_status("Control: boss")

    def select_control_slot(self, slot: int):
        if self.player_id != 1 or self.winner:
            return
        mob_ids = sorted(self.local_mobs.keys())
        if not mob_ids:
            self._set_status("No mobs to control.")
            return
        if slot < 1 or slot > len(mob_ids):
            self._set_status(f"No mob in slot {slot}.")
            return
        mob_id = mob_ids[slot - 1]
        self._set_controlled_entity(mob_id)
        self._set_status(f"Control: {self._control_label(mob_id)}")

    def _update_ai_attacks(self):
        if self.player_id != 1 or not self.hero or self.winner:
            return

        now = time.monotonic()
        for mob_id, mob in self.local_mobs.items():
            if mob.mode != "AI":
                continue
            if not mob.is_attacking:
                continue
            if self._entity_distance(mob.np, self.hero.np) > ATTACK_RANGE:
                continue
            last_hit = self.ai_attack_clock.get(mob_id, 0.0)
            if now - last_hit >= AI_ATTACK_COOLDOWN:
                self.ai_attack_clock[mob_id] = now
                self._queue_message({"type": "attack", "target": "hero", "damage": MOB_DAMAGE})
                self._play_attack_vfx(mob.np)
                # Show impact feedback locally for AI hits as well.
                if self.hero:
                    self._play_hit_vfx(self.hero.np, MOB_DAMAGE)

    def shake_camera(self, intensity: float = 0.35, duration: float = 0.12):
        original_pos = self.camera.getPos(self.render)
        self.taskMgr.remove("camera_shake_task")

        def shake_task(task):
            elapsed = task.time
            if elapsed >= duration:
                self.camera.setPos(self.render, original_pos)
                return task.done

            fade = 1.0 - (elapsed / duration)
            offset = Vec3(
                random.uniform(-1, 1) * intensity * fade,
                random.uniform(-1, 1) * intensity * fade,
                random.uniform(-1, 1) * intensity * fade,
            )
            self.camera.setPos(self.render, original_pos + offset)
            return task.cont

        self.taskMgr.add(shake_task, "camera_shake_task")

    def _task_websocket(self, task):
        dt = globalClock.getDt()

        if self._event_loop is None:
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
            self._ws_task = self._event_loop.create_task(self.websocket_handler())

        self.time_since_last_send += dt
        if (
            self._connection_established
            and self.player_id is not None
            and self.time_since_last_send >= self.network_update_interval
        ):
            self.time_since_last_send = 0.0
            payload = self._build_local_state_payload()
            if payload:
                self._queue_message(payload)

        self._event_loop.run_until_complete(asyncio.sleep(0))
        return task.cont

    def _task_physics(self, task):
        if self.hitstop_remaining > 0.0:
            return task.cont
        dt = globalClock.getDt()
        self.physics.step(dt)
        return task.cont

    def _update_camera_follow(self, dt: float):
        target_np = self._get_controlled_np()
        if not target_np:
            return

        camy = self.camera.getY()
        camz = self.camera.getZ()
        target_x = max(self.min_x, min(target_np.getX(), self.max_x))

        target_z = target_np.getZ() + 4.0
        dead_zone = 1.6
        if abs(target_z - camz) > dead_zone:
            target_z = camz + (target_z - camz - math.copysign(dead_zone, target_z - camz))
        else:
            target_z = camz

        blend = min(1.0, dt * CAMERA_SMOOTHING)
        self.camera_follow_x += (target_x - self.camera_follow_x) * blend
        camz = camz + (target_z - camz) * min(1.0, dt * (CAMERA_SMOOTHING * 0.6))
        self.camera.setPos(self.camera_follow_x, camy, camz)

    def _tick_hud(self, dt: float, force: bool = False):
        if force:
            self._hud_time_accumulator = 0.0
            self._update_hud()
            return
        self._hud_time_accumulator += dt
        if self._hud_time_accumulator < HUD_UPDATE_INTERVAL:
            return
        self._hud_time_accumulator = 0.0
        self._update_hud()

    def _task_update(self, task):
        dt = globalClock.getDt()
        self._process_attack_buffer()

        if self.hitstop_remaining > 0.0:
            self.hitstop_remaining = max(0.0, self.hitstop_remaining - dt)
            self._update_vfx(dt)
            self._update_parallax(dt)
            self._update_status(dt)
            self._tick_hud(dt)
            return task.cont

        if self.hero:
            self.hero.update(dt)
        if self.boss:
            self.boss.update(dt)

        for mob in self.local_mobs.values():
            mob.update(dt)
        for mob in self.remote_mobs.values():
            mob.update(dt)

        self._update_remote_motion(dt)

        if self.player_id == 1:
            self._update_ai_attacks()

        if self.player_id == 0 and self.hero and not self.boss_phase_unlocked and self.hero.np.getX() >= self.goal_x:
            self._unlock_boss_phase(announce=True)

        self._update_vfx(dt)
        self._update_camera_follow(dt)
        self._update_parallax(dt)
        self._update_status(dt)
        self._tick_hud(dt)
        return task.cont


if __name__ == "__main__":
    game = Game()
    game.run()
