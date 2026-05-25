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

from assets.Boss import Boss
from assets.Character import Character
from assets.Config import Config
from assets.Global_state import GLOBAL_STATE
from assets.Mob import Mob
from assets.PhysicsManager import PhysicsManager
from assets.World import World
from assets.Achille import Dungeon, Room

from direct.gui.DirectGui import DirectFrame, DirectWaitBar
from direct.gui import DirectGuiGlobals as DGG
from direct.gui.OnscreenImage import OnscreenImage
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    CardMaker,
    ConfigVariableString,
    DirectionalLight,
    Fog,
    Point2,
    Point3,
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
CAMERA_EDGE_PADDING = 1.0
BOSS_FREE_CAMERA_SPEED = 22.0
BOSS_FREE_CAMERA_Z_PADDING = 4.0
BOSS_FREE_CAMERA_MODULE_HEIGHT_MARGIN = 8.0
ATTACK_INPUT_BUFFER = 0.70
ATTACK_COMBO_CANCEL_RATIO = 0.72
HITSTOP_DURATION = 0.045
COMBO_WINDOW = 0.85
COMBO_DAMAGE = (1.0, 1.18, 1.35)
COMBO_RANGE_BONUS = (0.0, 0.18, 0.34)

HERO_ATTACK_COOLDOWN = 0.40
BOSS_ATTACK_COOLDOWN = 0.55
CONTROLLED_MOB_ATTACK_COOLDOWN = 0.65
AI_ATTACK_COOLDOWN = 1.05
SPAWN_COOLDOWN = 1.75
DUNGEON_SWAP_COOLDOWN = 1.25
MOB_DROP_COOLDOWN = 1.0
ATTACK_RANGE = 2.8
MAX_ACTIVE_MOBS = 6

HERO_MAX_HP = 130
BOSS_MAX_HP = 220
MOB_MAX_HP = 65
BOSS_MAX_MANA = 100.0
BOSS_MANA_REGEN = 12.0
DUNGEON_SWAP_MANA_COST = 35.0
MOB_SPAWN_MANA_COST = 25.0
MOB_DROP_MANA_COST = 25.0

HERO_DAMAGE = 22
BOSS_DAMAGE = 18
MOB_DAMAGE = 12
HUD_UPDATE_INTERVAL = 0.05
FALL_RECOVERY_DEPTH = 12.0
FALL_RECOVERY_SAFE_X_PADDING = 0.9
FALL_RECOVERY_RAY_UP = 36.0
FALL_RECOVERY_RAY_DOWN = 42.0
FALL_RECOVERY_LIFT = 1.0
SPAWN_FLOOR_LIFT = -7.0
MOB_ICON_PATH = os.path.join("assets", "images", "mob_icon.png")


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
        self.boss: Boss | None = None

        self.local_mobs: dict[int, Mob] = {}
        self.local_mob_hp: dict[int, int] = {}
        self.remote_mobs: dict[int, Mob] = {}
        self.next_mob_id = 1
        self.controlled_entity: str | int = "boss"

        self.hero_hp = HERO_MAX_HP
        self.boss_hp = BOSS_MAX_HP
        self.boss_mana = BOSS_MAX_MANA
        self.boss_phase_unlocked = False
        self.winner: str | None = None

        self.last_attack_times = {"hero": 0.0, "boss": 0.0, "mob": 0.0}
        self.last_boss_action_times = {"swap": -999.0, "spawn": -999.0, "drop": -999.0}
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
        self.boss_inventory_open = False
        self.boss_inventory_dragging: str | None = None
        self.boss_inventory_previous_control: str | int = "boss"
        self.free_camera_keys = {key: False for key in ("z", "q", "s", "d")}

        self._setup_hud()
        self._ui_cache: dict[str, Any] = {}
        self._ui_visible: dict[str, bool] = {}
        self._pulse_model_template = self.loader.loadModel("models/misc/sphere")

        self.accept("f", self.spawn_local_mob_request)
        self.accept("tab", self.cycle_control)
        for slot in range(1, MAX_ACTIVE_MOBS + 1):
            self.accept(str(slot), self.select_control_slot, [slot])
        self.accept("b", self.select_control_boss)
        self.accept("0", self.select_control_boss)
        self.accept("m", self._toggle_boss_editor_fullscreen)
        self.accept("e", self._toggle_boss_inventory)
        self.accept("z", self._set_free_camera_key, ["z", True])
        self.accept("z-up", self._set_free_camera_key, ["z", False])
        self.accept("s", self._set_free_camera_key, ["s", True])
        self.accept("s-up", self._set_free_camera_key, ["s", False])
        self.accept("q", self._set_free_camera_key, ["q", True])
        self.accept("q-up", self._set_free_camera_key, ["q", False])
        self.accept("d", self._set_free_camera_key, ["d", True])
        self.accept("d-up", self._set_free_camera_key, ["d", False])
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

    def _setup_boss_editor(self):
        self.editor_enabled = bool(getattr(self.world, "module_nodes", []))
        self.editor_texture_cache: dict[str, Any] = {}
        self.editor_frame = (-0.34, 0.34, -0.23, 0.23)
        self.editor_layout_sig: tuple[bool, float] | None = None
        self.editor_root = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0.015, 0.02, 0.025, 0.82),
            frameSize=self.editor_frame,
            pos=(1.38, 0, 0.7),
        )
        self.editor_root.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_root.hide()
        self.editor_expanded = False
        self.editor_root.bind(DGG.B1PRESS, self._on_editor_panel_press)

        self.editor_border = DirectFrame(
            parent=self.editor_root,
            frameColor=(0.96, 0.78, 0.35, 0.82),
            frameSize=self.editor_frame,
            pos=(0, 0, 0),
        )
        self.editor_border.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_backdrop = DirectFrame(
            parent=self.editor_root,
            frameColor=(0.035, 0.045, 0.05, 0.92),
            frameSize=(-0.325, 0.325, -0.215, 0.215),
            pos=(0, 0, 0),
        )
        self.editor_backdrop.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_grid = self.editor_root.attachNewNode("editor_grid")

        self.editor_title = OnscreenText(
            text="BOSS MAP",
            pos=(0, 0.162),
            align=TextNode.ACenter,
            scale=0.032,
            fg=(1.0, 0.88, 0.48, 0.95),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.editor_root,
        )
        self.editor_key_badge = DirectFrame(
            parent=self.editor_root,
            frameColor=(1.0, 0.82, 0.35, 0.9),
            frameSize=(-0.035, 0.035, -0.024, 0.024),
            pos=(0.29, 0, 0.164),
        )
        self.editor_key_badge.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_mode_label = OnscreenText(
            text="M",
            pos=(0, -0.008),
            align=TextNode.ACenter,
            scale=0.026,
            fg=(0.08, 0.1, 0.1, 0.95),
            mayChange=True,
            parent=self.editor_key_badge,
        )

        self.editor_canvas = self.editor_root.attachNewNode("editor_canvas")
        self.editor_scale = 0.12
        self.editor_canvas.setScale(self.editor_scale, 1, self.editor_scale)
        self.editor_canvas.setPos(0, 0, -0.02)
        self.editor_player_icon = None

        self.editor_dungeon = Dungeon()
        self.editor_room_to_module: dict[Room, dict] = {}
        self.editor_module_to_room: dict[int, Room] = {}
        self.editor_dragged_room: Room | None = None
        self.editor_drag_offset = Vec3(0, 0, 0)
        self.editor_drag_start_pos = Vec3(0, 0, 0)
        self.editor_room_half_w = 0.5
        self.editor_room_half_h = 0.25
        self._apply_boss_editor_layout(force=True)

        if not self.editor_enabled:
            self.editor_notice = OnscreenText(
                text="No modules found.",
                pos=(0, 0),
                align=TextNode.ACenter,
                scale=0.034,
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
            texture = self._get_boss_editor_texture(meta)
            if texture is not None:
                room.model.setTexture(texture, 1)
                room.model.setColor(1, 1, 1, 1)
                room.model.setTransparency(TransparencyAttrib.MAlpha)
            else:
                room.model.setColor(*room.color)
            room.model.setPos(start_x + i * 1.0, 0, 0.0)
            self.editor_dungeon.add_room(room)
            self.editor_room_to_module[room] = {"node": module, "meta": meta}
            self.editor_module_to_room[id(module)] = room
            if bool(meta.get("locked_endpoint", False)):
                lock_label = OnscreenText(
                    text="LOCK",
                    pos=(0, -0.035),
                    align=TextNode.ACenter,
                    scale=0.16,
                    fg=(1.0, 0.86, 0.32, 0.95),
                    shadow=(0, 0, 0, 0.9),
                    mayChange=False,
                    parent=room.model,
                )
                lock_label.setBin("fixed", 100)

        for room in self.editor_dungeon.rooms:
            self.editor_dungeon.link_rooms(room, self.editor_canvas)
        self._style_editor_corridors()
        self._setup_boss_map_player_icon()
        self._sync_locked_editor_room_heights()

        self._fit_editor_canvas()
        self._compute_editor_world_mapping()
        self._sync_world_from_editor()

    def _setup_boss_map_player_icon(self):
        icon_path = os.path.join("assets", "images", "player_icon.png")
        if not os.path.exists(icon_path):
            return
        self.editor_player_icon = OnscreenImage(
            image=icon_path,
            parent=self.editor_root,
            pos=(0, 0, 0),
            scale=(0.04, 1, 0.04),
        )
        self.editor_player_icon.setColor(1, 1, 1, 1)
        self.editor_player_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_player_icon.setBin("fixed", 120)
        self.editor_player_icon.setDepthTest(False)
        self.editor_player_icon.setDepthWrite(False)
        self.editor_player_icon.setLightOff(1)
        self.editor_player_icon.hide()

    def _apply_boss_editor_layout(self, force: bool = False):
        aspect = round(float(self.getAspectRatio()), 3)
        sig = (bool(self.editor_expanded), aspect)
        if not force and self.editor_layout_sig == sig:
            return
        self.editor_layout_sig = sig

        if self.editor_expanded:
            margin_x = 0.12
            self.editor_frame = (-aspect + margin_x, aspect - margin_x, -0.86, 0.86)
            self.editor_root["frameColor"] = (0.006, 0.009, 0.012, 0.92)
            self.editor_root["frameSize"] = self.editor_frame
            self.editor_root.setPos(0, 0, 0)
            self.editor_title.setScale(0.052)
            self.editor_title.setPos(0, 0.75)
            self.editor_key_badge["frameSize"] = (-0.046, 0.046, -0.032, 0.032)
            self.editor_key_badge.setPos(self.editor_frame[1] - 0.12, 0, 0.76)
            self.editor_mode_label.setScale(0.034)
            self.editor_mode_label.setPos(0, -0.012)
        else:
            self.editor_frame = (-0.34, 0.34, -0.23, 0.23)
            self.editor_root["frameColor"] = (0.015, 0.02, 0.025, 0.82)
            self.editor_root["frameSize"] = self.editor_frame
            self.editor_root.setPos(aspect - 0.40, 0, 0.71)
            self.editor_title.setScale(0.032)
            self.editor_title.setPos(0, 0.16)
            self.editor_key_badge["frameSize"] = (-0.035, 0.035, -0.024, 0.024)
            self.editor_key_badge.setPos(0.29, 0, 0.164)
            self.editor_mode_label.setScale(0.026)
            self.editor_mode_label.setPos(0, -0.008)

        left, right, bottom, top = self.editor_frame
        inset = 0.012 if self.editor_expanded else 0.014
        self.editor_border["frameSize"] = (left, right, bottom, top)
        self.editor_backdrop["frameSize"] = (left + inset, right - inset, bottom + inset, top - inset)
        self._rebuild_boss_editor_grid()
        self._fit_editor_canvas()

    def _rebuild_boss_editor_grid(self):
        self.editor_grid.node().removeAllChildren()
        left, right, bottom, top = self.editor_frame
        line_color = (0.45, 0.62, 0.65, 0.16) if self.editor_expanded else (0.45, 0.62, 0.65, 0.11)
        line_count = 8 if self.editor_expanded else 4
        thickness = 0.003 if self.editor_expanded else 0.0025

        for i in range(1, line_count):
            x = left + (right - left) * (i / line_count)
            cm = CardMaker("editor_grid_v")
            cm.set_frame(-thickness * 0.5, thickness * 0.5, bottom, top)
            line = self.editor_grid.attachNewNode(cm.generate())
            line.setPos(x, 0, 0)
            line.setColor(*line_color)
            line.setTransparency(TransparencyAttrib.MAlpha)

            z = bottom + (top - bottom) * (i / line_count)
            cm = CardMaker("editor_grid_h")
            cm.set_frame(left, right, -thickness * 0.5, thickness * 0.5)
            line = self.editor_grid.attachNewNode(cm.generate())
            line.setPos(0, 0, z)
            line.setColor(*line_color)
            line.setTransparency(TransparencyAttrib.MAlpha)

    def _toggle_boss_editor_fullscreen(self):
        if self.player_id != 1 or not self.editor_enabled:
            return
        if self.editor_expanded:
            self._boss_editor_release()
        self.editor_expanded = not self.editor_expanded
        self._apply_boss_editor_layout(force=True)

    def _get_boss_editor_texture(self, meta: dict):
        texture_path = self._get_boss_editor_texture_path(meta)
        if texture_path is None:
            return None
        if texture_path not in self.editor_texture_cache:
            self.editor_texture_cache[texture_path] = self.loader.loadTexture(texture_path)
        return self.editor_texture_cache[texture_path]

    def _get_boss_editor_texture_path(self, meta: dict) -> str | None:
        image_dir = os.path.join("assets", "images")
        module_key = f"{meta.get('name', '')} {meta.get('path', '')}".lower().replace("\\", "/")
        module_stem = os.path.splitext(os.path.basename(str(meta.get("path") or meta.get("name", ""))))[0]

        candidates: list[str] = []
        if "stair_u" in module_key or "stair-u" in module_key or "stair u" in module_key:
            candidates.append("stair_U.png")
        elif "stair_d" in module_key or "stair-d" in module_key or "stair d" in module_key:
            candidates.append("stair_D.png")
        elif "base" in module_key:
            candidates.append("base.png")
        elif "eau" in module_key or "water" in module_key:
            candidates.append("eau.png")

        if module_stem:
            candidates.extend([f"{module_stem}.png", f"{module_stem}.jpg", f"{module_stem}.jpeg"])

        for candidate in candidates:
            path = os.path.join(image_dir, candidate)
            if os.path.exists(path):
                return path
        return None

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
        margin_x = 0.24 if self.editor_expanded else 0.06
        margin_y = 0.28 if self.editor_expanded else 0.08
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

    def _world_pos_to_editor_pos(self, world_pos: Vec3) -> Vec3:
        best_room = None
        best_meta = None
        best_score = None
        for room in self.editor_dungeon.rooms:
            mapping = self.editor_room_to_module.get(room)
            if not mapping:
                continue
            node = mapping["node"]
            meta = mapping["meta"]
            left, right, _bottom, _top = self._module_world_bounds(node, meta)
            width = max(0.01, right - left)
            if left <= world_pos.x <= right:
                score = 0.0
            else:
                score = min(abs(world_pos.x - left), abs(world_pos.x - right))
            if best_score is None or score < best_score:
                best_room = room
                best_meta = (left, width)
                best_score = score

        if best_room is not None and best_meta is not None:
            left, width = best_meta
            local_t = max(0.0, min(1.0, (world_pos.x - left) / width))
            editor_x = best_room.model.getX() - self.editor_room_half_w + local_t * (self.editor_room_half_w * 2.0)
            return Vec3(editor_x, -0.02, best_room.model.getZ() + 0.02)

        unit_to_world = getattr(self, "editor_unit_to_world", 1.0) or 1.0
        origin = getattr(self, "editor_world_origin", 0.0)
        return Vec3((world_pos.x - origin) / unit_to_world, -0.02, 0.02)

    def _update_boss_map_player_icon(self):
        icon = getattr(self, "editor_player_icon", None)
        if icon is None:
            return
        hero = getattr(self, "hero", None)
        if not self.editor_enabled or self.player_id != 1 or hero is None:
            icon.hide()
            return
        editor_pos = self._world_pos_to_editor_pos(hero.np.getPos(self.render))
        canvas_pos = self.editor_canvas.getPos(self.editor_root)
        root_x = canvas_pos.x + editor_pos.x * self.editor_scale
        root_z = canvas_pos.z + editor_pos.z * self.editor_scale
        icon.setScale(0.06 if self.editor_expanded else 0.035)
        icon.setPos(root_x, 0, root_z)
        icon.show()

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
                if self._is_editor_room_locked(room):
                    self._set_status("Base rooms are locked.")
                    return True
                self.editor_dragged_room = room
                self.editor_drag_offset = room.model.getPos() - pos
                self.editor_drag_start_pos = room.model.getPos()
                return True
        return False

    def _on_editor_panel_press(self, _event=None):
        if self.player_id != 1 or not self.editor_enabled:
            return
        self._ui_consumed_click = True
        if not self.editor_expanded:
            return
        self._boss_editor_handle_click()

    def _on_editor_tab_press(self, _event=None):
        self._toggle_boss_editor_fullscreen()

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

    def _boss_editor_release(self):
        if not self.editor_dragged_room:
            return
        moved = (self.editor_dragged_room.model.getPos() - self.editor_drag_start_pos).length() > 0.01
        self.editor_dungeon.link_rooms(self.editor_dragged_room, self.editor_canvas)
        self._style_editor_corridors()
        self._sync_locked_editor_room_heights()
        if self._editor_has_links():
            if moved and not self._try_spend_boss_action(
                "swap",
                DUNGEON_SWAP_MANA_COST,
                DUNGEON_SWAP_COOLDOWN,
                "Dungeon swap",
            ):
                self.editor_dragged_room.model.setPos(self.editor_drag_start_pos)
                self.editor_dungeon.link_rooms(self.editor_dragged_room, self.editor_canvas)
                self._style_editor_corridors()
                self._sync_locked_editor_room_heights()
            else:
                self._sync_world_from_editor()
        else:
            self._set_status("Link rooms with corridors to apply changes.")
        self.editor_dragged_room = None

    def _style_editor_corridors(self):
        seen = set()
        for room in self.editor_dungeon.rooms:
            for corridor in (room.corridor_left, room.corridor_right):
                if not corridor or id(corridor) in seen:
                    continue
                seen.add(id(corridor))
                corridor.setColor(1.0, 0.82, 0.35, 0.75)
                corridor.setTransparency(TransparencyAttrib.MAlpha)

    def _editor_has_links(self) -> bool:
        if not self.editor_dungeon.rooms:
            return False
        return all(room.corridor_left or room.corridor_right for room in self.editor_dungeon.rooms)

    def _is_editor_room_locked(self, room: Room) -> bool:
        meta = self.editor_room_to_module.get(room, {}).get("meta", {})
        return bool(meta.get("locked_endpoint", False))

    def _ordered_editor_rooms(self) -> list[Room]:
        rooms = list(self.editor_dungeon.rooms)
        if len(rooms) <= 2:
            return rooms

        first_locked = None
        last_locked = None
        for room in rooms:
            meta = self.editor_room_to_module.get(room, {}).get("meta", {})
            if not bool(meta.get("locked_endpoint", False)):
                continue
            index = int(meta.get("index", 0))
            if index == 0:
                first_locked = room
            else:
                last_locked = room

        middle_rooms = [
            room
            for room in rooms
            if room is not first_locked and room is not last_locked
        ]
        middle_rooms.sort(key=lambda r: r.model.getX())

        ordered: list[Room] = []
        if first_locked is not None:
            ordered.append(first_locked)
        ordered.extend(middle_rooms)
        if last_locked is not None:
            ordered.append(last_locked)
        return ordered

    def _sync_locked_editor_room_heights(self):
        if not getattr(self, "editor_dungeon", None):
            return
        for room in self.editor_dungeon.rooms:
            if not self._is_editor_room_locked(room):
                continue
            room.model.setZ(0.0)

    def _sync_world_from_editor(self):
        if not self.editor_enabled:
            return
        levels = self._compute_editor_levels()
        ordered_rooms = self._ordered_editor_rooms()
        entity_module_ids = self._capture_entity_module_ids()
        move_deltas: list[dict[str, Any]] = []
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

            old_bounds = self._module_world_bounds(node, meta)
            old_x = float(node.getX())
            old_z = float(node.getZ())
            node.setX(current_x - float(min_bound.x))
            level_offset = levels.get(room, 0.0)
            node.setZ(meta["base_z"] + level_offset)
            self._sync_module_physics(node)
            dx = float(node.getX()) - old_x
            dz = float(node.getZ()) - old_z
            if abs(dx) > 1e-5 or abs(dz) > 1e-5:
                move_deltas.append({"module_id": id(node), "bounds": old_bounds, "delta": Vec3(dx, 0, dz), "width": width})
            current_x += width
        self._teleport_entities_with_modules(move_deltas, entity_module_ids)
        self.world.recompute_bounds()
        self.min_x, self.max_x = self.world.setLimit()
        self.goal_x = self.max_x - 2.0

    def _module_world_bounds(self, node, meta: dict) -> tuple[float, float, float, float]:
        min_bound = meta.get("min_bound")
        max_bound = meta.get("max_bound")
        if min_bound is None:
            min_bound = Vec3(0, 0, 0)
        if max_bound is None:
            max_bound = Vec3(float(meta.get("width", 1.0)), 0, 1.0)
        return (
            float(node.getX() + min_bound.x),
            float(node.getX() + max_bound.x),
            float(node.getZ() + min_bound.z),
            float(node.getZ() + max_bound.z),
        )

    def _get_endpoint_base_bounds(self, endpoint: str) -> tuple[float, float, float, float] | None:
        candidates: list[tuple[int, tuple[float, float, float, float]]] = []
        for idx, node in enumerate(getattr(self.world, "module_nodes", [])):
            meta = self.world.module_meta[idx] if idx < len(self.world.module_meta) else {}
            if not bool(meta.get("locked_endpoint", False)):
                continue
            bounds = self._module_world_bounds(node, meta)
            candidates.append((int(meta.get("index", idx)), bounds))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        if endpoint == "start":
            return candidates[0][1]
        return candidates[-1][1]

    def _get_spawn_z_on_base(self, x: float, endpoint: str, fallback_z: float) -> float:
        bounds = self._get_endpoint_base_bounds(endpoint)
        if bounds is None:
            return fallback_z

        left, right, bottom, top = bounds
        spawn_x = max(left + 0.5, min(float(x), right - 0.5))
        from_pos = Vec3(spawn_x, 0, top + FALL_RECOVERY_RAY_UP)
        to_pos = Vec3(spawn_x, 0, bottom - FALL_RECOVERY_RAY_DOWN)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        if result.hasHit():
            return float(result.getHitPos().z) + SPAWN_FLOOR_LIFT
        return float(top) + SPAWN_FLOOR_LIFT

    def _sync_module_physics(self, module_node):
        for body_np in module_node.find_all_matches("**/+BulletRigidBodyNode"):
            body = body_np.node()
            if hasattr(body, "setTransformDirty"):
                body.setTransformDirty()
            if hasattr(body, "setActive"):
                body.setActive(True)

    def _iter_world_entities(self):
        hero = getattr(self, "hero", None)
        boss = getattr(self, "boss", None)
        if hero:
            yield "hero", hero
        if boss:
            yield "boss", boss
        for mob in getattr(self, "local_mobs", {}).values():
            yield None, mob
        for mob_id, mob in getattr(self, "remote_mobs", {}).items():
            yield f"mob:{mob_id}", mob

    def _capture_entity_module_ids(self) -> dict[int, dict[str, Any]]:
        modules = []
        for idx, node in enumerate(getattr(self.world, "module_nodes", [])):
            meta = self.world.module_meta[idx] if idx < len(self.world.module_meta) else {}
            left, right, bottom, top = self._module_world_bounds(node, meta)
            modules.append(
                {
                    "id": id(node),
                    "left": left,
                    "right": right,
                    "center": (left + right) * 0.5,
                    "width": max(0.01, right - left),
                }
            )
        if not modules:
            return {}

        assignments: dict[int, dict[str, Any]] = {}
        padding_x = 1.5
        for _target_key, entity in self._iter_world_entities():
            np = getattr(entity, "np", None)
            if np is None or np.isEmpty():
                continue
            x = float(np.getX(self.render))
            best = None
            best_score = None
            for module in modules:
                left = module["left"] - padding_x
                right = module["right"] + padding_x
                if left <= x <= right:
                    score = abs(x - module["center"])
                else:
                    edge_dist = min(abs(x - left), abs(x - right))
                    if edge_dist > module["width"] * 0.35:
                        continue
                    score = edge_dist + module["width"]
                if best_score is None or score < best_score:
                    best = module
                    best_score = score
            if best is not None:
                assignments[id(entity)] = {
                    "module_id": best["id"],
                    "floor_offset": self._get_entity_floor_offset(np.getPos(self.render)),
                }
        return assignments

    def _teleport_entities_with_modules(
        self,
        move_deltas: list[dict[str, Any]],
        entity_module_ids: dict[int, dict[str, Any]] | None = None,
    ):
        if not move_deltas:
            return
        delta_by_module = {item.get("module_id"): item for item in move_deltas}
        padding_x = 1.0
        below_module_z = 3.0
        above_module_z = 18.0
        moved_entities: set[int] = set()
        for target_key, entity in self._iter_world_entities():
            np = getattr(entity, "np", None)
            if np is None or np.isEmpty() or id(entity) in moved_entities:
                continue
            pos = np.getPos(self.render)
            best_item = None
            assignment = (entity_module_ids or {}).get(id(entity), {})
            assigned_module_id = assignment.get("module_id")
            if assigned_module_id is not None:
                best_item = delta_by_module.get(assigned_module_id)
            if best_item is None:
                best_score = None
                for item in move_deltas:
                    left, right, bottom, top = item["bounds"]
                    if not (left - padding_x <= pos.x <= right + padding_x):
                        continue
                    if not (bottom - below_module_z <= pos.z <= top + above_module_z):
                        continue
                    center_x = (left + right) * 0.5
                    score = abs(pos.x - center_x)
                    if best_score is None or score < best_score:
                        best_item = item
                        best_score = score
            if best_item is None:
                continue

            delta = best_item["delta"]
            new_pos = self._snap_entity_to_floor(pos + delta, assignment.get("floor_offset"))
            np.setPos(self.render, new_pos)
            node = getattr(entity, "node", None)
            if node is not None:
                node.setLinearVelocity(Vec3(0, 0, 0))
                if hasattr(node, "setAngularVelocity"):
                    node.setAngularVelocity(Vec3(0, 0, 0))
            if getattr(entity, "is_climbing", False):
                if hasattr(entity, "climb_start_pos"):
                    entity.climb_start_pos += delta
                if hasattr(entity, "climb_target_pos"):
                    entity.climb_target_pos += delta
            if target_key in getattr(self, "remote_targets", {}):
                self.remote_targets[target_key]["x"] = float(new_pos.x)
                self.remote_targets[target_key]["z"] = float(new_pos.z)
                self.remote_targets[target_key]["vx"] = 0.0
                self.remote_targets[target_key]["vz"] = 0.0
            moved_entities.add(id(entity))

    def _get_entity_floor_offset(self, pos: Vec3) -> float | None:
        result = self.physics.world.rayTestClosest(pos + Vec3(0, 0, 2.0), pos - Vec3(0, 0, 8.0))
        if not result.hasHit():
            return None
        offset = float(pos.z - result.getHitPos().z)
        if -0.2 <= offset <= 4.0:
            return offset
        return None

    def _snap_entity_to_floor(self, pos: Vec3, floor_offset: float | None = None) -> Vec3:
        if floor_offset is None:
            return pos
        from_pos = pos + Vec3(0, 0, 8.0)
        to_pos = pos - Vec3(0, 0, 12.0)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        if not result.hasHit():
            return pos
        floor_z = result.getHitPos().z
        snapped_z = floor_z + floor_offset
        if abs(snapped_z - pos.z) > 6.0:
            return pos
        return Vec3(pos.x, pos.y, snapped_z)

    def _iter_fall_recovery_entities(self):
        if self.player_id == 0 and self.hero:
            yield "hero", self.hero
        elif self.player_id == 1:
            if self.boss:
                yield "boss", self.boss
            for mob_id, mob in self.local_mobs.items():
                yield f"mob:{mob_id}", mob

    def _nearest_module_bounds(self, x: float) -> tuple[float, float, float, float] | None:
        best_bounds = None
        best_score = None
        for idx, node in enumerate(getattr(self.world, "module_nodes", [])):
            meta = self.world.module_meta[idx] if idx < len(self.world.module_meta) else {}
            left, right, bottom, top = self._module_world_bounds(node, meta)
            if left <= x <= right:
                score = 0.0
            else:
                score = min(abs(x - left), abs(x - right))
            if best_score is None or score < best_score:
                best_bounds = (left, right, bottom, top)
                best_score = score
        return best_bounds

    def _get_fall_recovery_landing(self, pos: Vec3) -> Vec3 | None:
        bounds = self._nearest_module_bounds(float(pos.x))
        if bounds is None:
            min_bound = getattr(self.world, "_min_bound", None)
            max_bound = getattr(self.world, "_max_bound", None)
            if min_bound is None or max_bound is None:
                return None
            bounds = (float(min_bound.x), float(max_bound.x), float(min_bound.z), float(max_bound.z))

        left, right, bottom, top = bounds
        width = max(0.01, right - left)
        padding = min(FALL_RECOVERY_SAFE_X_PADDING, width * 0.35)
        safe_left = left + padding
        safe_right = right - padding
        if safe_left > safe_right:
            safe_left = safe_right = (left + right) * 0.5
        target_x = max(safe_left, min(float(pos.x), safe_right))

        from_pos = Vec3(target_x, 0, top + FALL_RECOVERY_RAY_UP)
        to_pos = Vec3(target_x, 0, bottom - FALL_RECOVERY_RAY_DOWN)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        floor_z = float(result.getHitPos().z) if result.hasHit() else float(top)
        return Vec3(target_x, 0, floor_z + FALL_RECOVERY_LIFT)

    def _should_recover_fall(self, pos: Vec3) -> bool:
        bounds = self._nearest_module_bounds(float(pos.x))
        if bounds is not None:
            return float(pos.z) < bounds[2] - FALL_RECOVERY_DEPTH

        min_bound = getattr(self.world, "_min_bound", None)
        if min_bound is not None:
            return float(pos.z) < float(min_bound.z) - FALL_RECOVERY_DEPTH
        return float(pos.z) < -FALL_RECOVERY_DEPTH

    def _recover_falling_entities(self):
        for target_key, entity in self._iter_fall_recovery_entities():
            np = getattr(entity, "np", None)
            if np is None or np.isEmpty():
                continue
            pos = np.getPos(self.render)
            if not self._should_recover_fall(pos):
                continue

            landing = self._get_fall_recovery_landing(pos)
            if landing is None:
                continue

            np.setPos(self.render, landing)
            node = getattr(entity, "node", None)
            if node is not None:
                node.setLinearVelocity(Vec3(0, 0, 0))
                if hasattr(node, "setAngularVelocity"):
                    node.setAngularVelocity(Vec3(0, 0, 0))
                if hasattr(node, "setActive"):
                    node.setActive(True)

            if getattr(entity, "is_climbing", False):
                entity.is_climbing = False
            if hasattr(entity, "is_jumping"):
                entity.is_jumping = False

            if target_key in getattr(self, "remote_targets", {}):
                self.remote_targets[target_key]["x"] = float(landing.x)
                self.remote_targets[target_key]["z"] = float(landing.z)
                self.remote_targets[target_key]["vx"] = 0.0
                self.remote_targets[target_key]["vz"] = 0.0

            self._set_status("Recovered from fall.")

    def _compute_editor_levels(self) -> dict[Room, float]:
        rooms = self._ordered_editor_rooms()
        if not rooms:
            return {}

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
        key = f"{meta.get('name', '')} {meta.get('path', '')}".lower().replace("-", "_")
        if "base" in key:
            return 0.0
        if "stair_u" in key:
            return 9.6
        if "stair_d" in key:
            return -9.6
        return 0.0

    def _on_mouse1(self):
        if self._ui_consumed_click:
            self._ui_consumed_click = False
            return
        if self.boss_inventory_open:
            if self._is_mouse_over_boss_inventory_mob_slot():
                self._start_boss_inventory_mob_drag()
            return
        if self.player_id == 1 and self._is_mouse_over_editor():
            if self._boss_editor_handle_click():
                return
            return
        self.on_attack_input()

    def _on_mouse1_up(self):
        if self.boss_inventory_open:
            self._drop_boss_inventory_drag()
            return
        if self.player_id == 1 and self.editor_enabled:
            self._boss_editor_release()

    def _task_boss_editor_drag(self, task):
        if self.editor_dragged_room and self.player_id == 1:
            pos = self._get_editor_mouse_pos()
            if pos is not None:
                self.editor_dragged_room.model.setPos(pos + self.editor_drag_offset)
                self._sync_locked_editor_room_heights()
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
        self._setup_boss_ui()
        self._setup_boss_inventory_ui()

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

    def _setup_boss_ui(self):
        self.boss_ui_root = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0, 0, 0, 0),
        )
        self.boss_ui_root.setTransparency(TransparencyAttrib.MAlpha)

        self.boss_control_root = DirectFrame(
            parent=self.boss_ui_root,
            frameColor=(0, 0, 0, 0),
            pos=(-1.18, 0, 0.9),
        )

        self.boss_control_icon_outer = DirectFrame(
            parent=self.boss_control_root,
            frameColor=(0.95, 0.88, 0.66, 0.86),
            frameSize=(-0.09, 0.09, -0.09, 0.09),
            pos=(0, 0, 0),
        )
        self.boss_control_icon_outer.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_control_icon_outer.bind(DGG.B1PRESS, self._on_boss_control_slot_press, ["boss"])

        self.boss_control_icon_inner = DirectFrame(
            parent=self.boss_control_icon_outer,
            frameColor=(0.045, 0.055, 0.065, 0.92),
            frameSize=(-0.074, 0.074, -0.074, 0.074),
            pos=(0, 0, 0),
        )
        self.boss_control_icon_inner.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_control_icon_inner.bind(DGG.B1PRESS, self._on_boss_control_slot_press, ["boss"])

        self.boss_control_icon_text = OnscreenText(
            text="B",
            pos=(0, -0.032),
            align=TextNode.ACenter,
            scale=0.072,
            fg=(1.0, 0.86, 0.38, 0.98),
            shadow=(0, 0, 0, 0.9),
            mayChange=True,
            parent=self.boss_control_icon_inner,
        )
        self.boss_control_mob_image = OnscreenImage(
            image=MOB_ICON_PATH,
            parent=self.boss_control_icon_inner,
            pos=(0, 0, 0),
            scale=(0.055, 1, 0.055),
        )
        self.boss_control_mob_image.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_control_mob_image.hide()

        bar_width = 0.68
        bar_height = 0.036
        bar_bg = (0.0, 0.0, 0.0, 0.42)

        def make_boss_bar(y: float, x: float, color: tuple[float, float, float, float], label: str):
            bg = DirectFrame(
                parent=self.boss_control_root,
                frameColor=bar_bg,
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
                text=label,
                pos=(bar_width + 0.06, -bar_height * 0.72),
                align=TextNode.ALeft,
                scale=0.04,
                fg=(0.94, 0.96, 1.0, 0.94),
                shadow=(0, 0, 0, 0.86),
                mayChange=True,
                parent=bg,
            )
            value_text = OnscreenText(
                text="",
                pos=(bar_width * 0.5, -bar_height * 0.72),
                align=TextNode.ACenter,
                scale=0.028,
                fg=(0.98, 0.98, 0.95, 0.92),
                shadow=(0, 0, 0, 0.86),
                mayChange=True,
                parent=bg,
            )
            return bar, label_text, value_text

        self.boss_pv_bar, self.boss_pv_label, self.boss_pv_text = make_boss_bar(
            y=0.04,
            x=0.105,
            color=(0.92, 0.16, 0.16, 0.96),
            label="PV",
        )
        self.boss_pm_bar, self.boss_pm_label, self.boss_pm_text = make_boss_bar(
            y=-0.014,
            x=0.13,
            color=(0.12, 0.62, 0.92, 0.94),
            label="PM",
        )

        self.boss_control_name = OnscreenText(
            text="BOSS",
            pos=(-0.08, -0.125),
            align=TextNode.ALeft,
            scale=0.034,
            fg=(0.9, 0.92, 0.95, 0.9),
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.boss_control_root,
        )

        self.boss_spawn_text = OnscreenText(
            text="",
            pos=(0.28, -0.125),
            align=TextNode.ALeft,
            scale=0.032,
            fg=(1.0, 0.8, 0.42, 0.94),
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.boss_control_root,
        )

        self.boss_mob_slots_root = DirectFrame(
            parent=self.boss_ui_root,
            frameColor=(0, 0, 0, 0),
            pos=(-0.48, 0, -0.76),
        )

        self.boss_mob_slots: list[dict[str, Any]] = []
        slot_size = 0.085
        slot_gap = 0.105
        for i in range(MAX_ACTIVE_MOBS):
            slot_root = DirectFrame(
                parent=self.boss_mob_slots_root,
                frameColor=(0, 0, 0, 0),
                frameSize=(-0.005, slot_size + 0.005, -0.12, 0.015),
                pos=(i * slot_gap, 0, 0),
            )
            slot_root.setTransparency(TransparencyAttrib.MAlpha)
            slot_root.bind(DGG.B1PRESS, self._on_boss_control_slot_press, [i + 1])

            slot_frame = DirectFrame(
                parent=slot_root,
                frameColor=(0.9, 0.86, 0.72, 0.72),
                frameSize=(0, slot_size, -slot_size, 0),
                pos=(0, 0, 0),
            )
            slot_frame.setTransparency(TransparencyAttrib.MAlpha)
            slot_frame.bind(DGG.B1PRESS, self._on_boss_control_slot_press, [i + 1])

            slot_inner = DirectFrame(
                parent=slot_frame,
                frameColor=(0.04, 0.05, 0.06, 0.9),
                frameSize=(0.008, slot_size - 0.008, -slot_size + 0.008, -0.008),
                pos=(0, 0, 0),
            )
            slot_inner.setTransparency(TransparencyAttrib.MAlpha)
            slot_inner.bind(DGG.B1PRESS, self._on_boss_control_slot_press, [i + 1])

            slot_label = OnscreenText(
                text=str(i + 1),
                pos=(slot_size * 0.5, -slot_size * 0.66),
                align=TextNode.ACenter,
                scale=0.04,
                fg=(0.78, 0.85, 0.9, 0.85),
                shadow=(0, 0, 0, 0.8),
                mayChange=True,
                parent=slot_inner,
            )
            slot_image = OnscreenImage(
                image=MOB_ICON_PATH,
                parent=slot_inner,
                pos=(slot_size * 0.5, 0, -slot_size * 0.5),
                scale=(0.033, 1, 0.033),
            )
            slot_image.setTransparency(TransparencyAttrib.MAlpha)
            slot_image.hide()

            hp_back = DirectFrame(
                parent=slot_root,
                frameColor=(0.0, 0.0, 0.0, 0.48),
                frameSize=(0, slot_size, -0.014, 0),
                pos=(0, 0, -slot_size - 0.016),
            )
            hp_back.setTransparency(TransparencyAttrib.MAlpha)
            hp_bar = DirectWaitBar(
                parent=hp_back,
                text="",
                range=MOB_MAX_HP,
                value=0,
                frameColor=(0, 0, 0, 0),
                barColor=(0.18, 0.86, 0.42, 0.94),
                frameSize=(0, slot_size, -0.014, 0),
                pos=(0, 0, 0),
            )

            self.boss_mob_slots.append(
                {
                    "root": slot_root,
                    "frame": slot_frame,
                    "inner": slot_inner,
                    "label": slot_label,
                    "image": slot_image,
                    "hp_bar": hp_bar,
                }
            )

        self.boss_ui_root.hide()

    def _setup_boss_inventory_ui(self):
        self.boss_inventory_root = DirectFrame(
            parent=self.aspect2d,
            frameColor=(0.018, 0.024, 0.032, 0.86),
            frameSize=(-0.42, 0.42, -0.15, 0.15),
            pos=(0, 0, -0.58),
        )
        self.boss_inventory_root.setTransparency(TransparencyAttrib.MAlpha)

        self.boss_inventory_title = OnscreenText(
            text="INVENTORY",
            pos=(-0.38, 0.095),
            align=TextNode.ALeft,
            scale=0.036,
            fg=(1.0, 0.84, 0.38, 0.95),
            shadow=(0, 0, 0, 0.85),
            mayChange=False,
            parent=self.boss_inventory_root,
        )
        self.boss_inventory_hint = OnscreenText(
            text="Drag mob into the dungeon",
            pos=(-0.38, 0.045),
            align=TextNode.ALeft,
            scale=0.028,
            fg=(0.78, 0.84, 0.9, 0.9),
            shadow=(0, 0, 0, 0.8),
            mayChange=False,
            parent=self.boss_inventory_root,
        )

        self.boss_inventory_mob_slot = DirectFrame(
            parent=self.boss_inventory_root,
            frameColor=(0.95, 0.78, 0.32, 0.88),
            frameSize=(-0.065, 0.065, -0.065, 0.065),
            pos=(0.24, 0, 0.01),
        )
        self.boss_inventory_mob_slot.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_inventory_mob_slot.bind(DGG.B1PRESS, self._on_boss_inventory_mob_press)

        self.boss_inventory_mob_inner = DirectFrame(
            parent=self.boss_inventory_mob_slot,
            frameColor=(0.04, 0.055, 0.065, 0.94),
            frameSize=(-0.053, 0.053, -0.053, 0.053),
            pos=(0, 0, 0),
        )
        self.boss_inventory_mob_inner.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_inventory_mob_inner.bind(DGG.B1PRESS, self._on_boss_inventory_mob_press)
        self.boss_inventory_mob_icon = OnscreenImage(
            image=MOB_ICON_PATH,
            parent=self.boss_inventory_mob_inner,
            pos=(0, 0, 0),
            scale=(0.052, 1, 0.052),
        )
        self.boss_inventory_mob_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_inventory_mob_count = OnscreenText(
            text="",
            pos=(0.24, -0.095),
            align=TextNode.ACenter,
            scale=0.028,
            fg=(0.9, 0.94, 0.98, 0.92),
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.boss_inventory_root,
        )

        self.boss_inventory_drag_icon = OnscreenImage(
            image=MOB_ICON_PATH,
            parent=self.aspect2d,
            pos=(0, 0, 0),
            scale=(0.06, 1, 0.06),
        )
        self.boss_inventory_drag_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_inventory_drag_icon.hide()
        self.boss_inventory_root.hide()

    def _set_free_camera_key(self, key: str, value: bool):
        if key in self.free_camera_keys:
            self.free_camera_keys[key] = value

    def _toggle_boss_inventory(self):
        if self.player_id != 1 or self.winner:
            return
        if self.boss_inventory_open:
            self._close_boss_inventory()
        else:
            self._open_boss_inventory()

    def _open_boss_inventory(self):
        if self.player_id != 1:
            return
        self.boss_inventory_open = True
        self.boss_inventory_previous_control = self.controlled_entity
        self.boss_inventory_dragging = None
        self.boss_inventory_drag_icon.hide()
        if self.boss:
            self.boss.set_mode("IDLE")
        for mob in self.local_mobs.values():
            mob.set_mode("AI")
        self.camera_follow_x = self.camera.getX()
        self._set_status("Inventory: drag mobs into the dungeon.")

    def _close_boss_inventory(self):
        self.boss_inventory_open = False
        self.boss_inventory_dragging = None
        self.boss_inventory_drag_icon.hide()
        for key in self.free_camera_keys:
            self.free_camera_keys[key] = False
        if self.player_id == 1:
            self._set_controlled_entity(self.boss_inventory_previous_control)
        self.camera_follow_x = self.camera.getX()

    def _on_boss_inventory_mob_press(self, _event=None):
        self._ui_consumed_click = True
        if not self.boss_inventory_open or self.player_id != 1:
            return
        self._start_boss_inventory_mob_drag()

    def _start_boss_inventory_mob_drag(self):
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            self._set_status(f"Spawn limit reached ({MAX_ACTIVE_MOBS}).")
            return
        drop_left = self._boss_action_left("drop", MOB_DROP_COOLDOWN)
        if drop_left > 0.0:
            self._set_status(f"Drop on cooldown ({drop_left:.1f}s).")
            return
        if self.boss_mana + 1e-5 < MOB_DROP_MANA_COST:
            self._set_status(f"Not enough mana for Drop mob ({int(MOB_DROP_MANA_COST)} PM).")
            return
        self.boss_inventory_dragging = "mob"
        self._update_boss_inventory_drag_icon()

    def _is_mouse_over_boss_inventory_mob_slot(self) -> bool:
        if not self.boss_inventory_open or self.boss_inventory_mob_slot.isHidden():
            return False
        if not self.mouseWatcherNode.hasMouse():
            return False
        aspect = self.getAspectRatio()
        mouse_x = self.mouseWatcherNode.getMouseX() * aspect
        mouse_z = self.mouseWatcherNode.getMouseY()
        slot_pos = self.boss_inventory_mob_slot.getPos(self.aspect2d)
        local_x = mouse_x - slot_pos.x
        local_z = mouse_z - slot_pos.z
        left, right, bottom, top = self.boss_inventory_mob_slot["frameSize"]
        return left <= local_x <= right and bottom <= local_z <= top

    def _update_boss_inventory_drag_icon(self):
        if self.boss_inventory_dragging is None or not self.mouseWatcherNode.hasMouse():
            self.boss_inventory_drag_icon.hide()
            return
        aspect = self.getAspectRatio()
        x = self.mouseWatcherNode.getMouseX() * aspect
        z = self.mouseWatcherNode.getMouseY()
        self.boss_inventory_drag_icon.setPos(x, 0, z)
        self.boss_inventory_drag_icon.show()

    def _is_mouse_over_boss_inventory(self) -> bool:
        if not self.boss_inventory_open or self.boss_inventory_root.isHidden():
            return False
        if not self.mouseWatcherNode.hasMouse():
            return False
        aspect = self.getAspectRatio()
        mouse_x = self.mouseWatcherNode.getMouseX() * aspect
        mouse_z = self.mouseWatcherNode.getMouseY()
        root_pos = self.boss_inventory_root.getPos(self.aspect2d)
        local_x = mouse_x - root_pos.x
        local_z = mouse_z - root_pos.z
        left, right, bottom, top = self.boss_inventory_root["frameSize"]
        return left <= local_x <= right and bottom <= local_z <= top

    def _mouse_to_world_y0(self) -> Vec3 | None:
        if not self.mouseWatcherNode.hasMouse():
            return None
        mx = self.mouseWatcherNode.getMouseX()
        my = self.mouseWatcherNode.getMouseY()
        near = Point3()
        far = Point3()
        self.camLens.extrude(Point2(mx, my), near, far)
        near_world = self.render.getRelativePoint(self.camera, near)
        far_world = self.render.getRelativePoint(self.camera, far)
        dy = far_world.y - near_world.y
        if abs(dy) < 1e-5:
            return None
        t = -near_world.y / dy
        return Vec3(
            near_world.x + (far_world.x - near_world.x) * t,
            0,
            near_world.z + (far_world.z - near_world.z) * t,
        )

    def _get_mob_drop_position_from_mouse(self) -> Vec3 | None:
        world_pos = self._mouse_to_world_y0()
        if world_pos is None:
            return None
        if world_pos.x < self.min_x or world_pos.x > self.max_x:
            return None

        bounds = self._nearest_module_bounds(float(world_pos.x))
        if bounds is None:
            return None
        left, right, bottom, top = bounds
        if not (left - 0.4 <= world_pos.x <= right + 0.4):
            return None

        from_pos = Vec3(world_pos.x, 0, top + FALL_RECOVERY_RAY_UP)
        to_pos = Vec3(world_pos.x, 0, bottom - FALL_RECOVERY_RAY_DOWN)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        if not result.hasHit():
            return None
        return Vec3(world_pos.x, 0, float(result.getHitPos().z) + SPAWN_FLOOR_LIFT)

    def _drop_boss_inventory_drag(self):
        if self.boss_inventory_dragging != "mob":
            return
        self.boss_inventory_dragging = None
        self.boss_inventory_drag_icon.hide()
        if self._is_mouse_over_boss_inventory():
            return
        pos = self._get_mob_drop_position_from_mouse()
        if pos is None:
            self._set_status("Drop mob on the dungeon floor.")
            return
        if not self._try_spend_boss_action("drop", MOB_DROP_MANA_COST, MOB_DROP_COOLDOWN, "Drop mob"):
            return
        self._spawn_local_mob_at(pos, status_label="Dropped mob")

    def _on_boss_control_slot_press(self, entity: str | int, _event=None):
        self._ui_consumed_click = True
        if self.player_id != 1 or self.winner:
            return
        if entity == "boss":
            self._set_controlled_entity("boss")
            self._set_status("Control: boss")
            return
        if not isinstance(entity, int):
            return

        mob_ids = sorted(self.local_mobs.keys())
        slot = entity
        if slot < 1 or slot > len(mob_ids):
            self._set_status(f"No mob in slot {slot}.")
            return
        mob_id = mob_ids[slot - 1]
        self._set_controlled_entity(mob_id)
        self._set_status(f"Control: {self._control_label(mob_id)}")

    def _get_controlled_boss_ui_state(self) -> tuple[str, str, int, int]:
        if self.controlled_entity == "boss":
            return "BOSS", "B", max(0, min(self.boss_hp, BOSS_MAX_HP)), BOSS_MAX_HP
        if isinstance(self.controlled_entity, int) and self.controlled_entity in self.local_mobs:
            slot = self._get_mob_slot(self.controlled_entity)
            icon = str(slot) if slot is not None else "M"
            hp = max(0, min(self.local_mob_hp.get(self.controlled_entity, MOB_MAX_HP), MOB_MAX_HP))
            return f"MOB {self.controlled_entity}", icon, hp, MOB_MAX_HP
        return "BOSS", "B", max(0, min(self.boss_hp, BOSS_MAX_HP)), BOSS_MAX_HP

    def _update_boss_ui(self, now: float, attack_cd: float, attack_left: float):
        name, icon, hp, max_hp = self._get_controlled_boss_ui_state()
        hp_ratio = 0.0 if max_hp <= 0 else hp / max_hp
        pm_ratio = 0.0 if BOSS_MAX_MANA <= 0 else self.boss_mana / BOSS_MAX_MANA

        is_controlled_mob = icon not in ("B", "boss")
        self._set_visible("boss_control_mob_image", self.boss_control_mob_image, is_controlled_mob)
        self._set_visible("boss_control_icon_text", self.boss_control_icon_text, not is_controlled_mob)
        if not is_controlled_mob:
            self._set_text_if_changed("boss_control_icon_text", self.boss_control_icon_text, icon)
        self._set_text_if_changed("boss_control_name", self.boss_control_name, f"Control: {name}")
        self._set_widget_number_if_changed("boss_ui_pv_value", self.boss_pv_bar, "value", max(0.0, min(1.0, hp_ratio)))
        self._set_widget_number_if_changed("boss_ui_pm_value", self.boss_pm_bar, "value", pm_ratio)
        self._set_text_if_changed("boss_ui_pv_text", self.boss_pv_text, f"{hp}/{max_hp}")
        self._set_text_if_changed("boss_ui_pm_text", self.boss_pm_text, f"{int(self.boss_mana)}/{int(BOSS_MAX_MANA)}")

        spawn_left = self._boss_action_left("spawn", SPAWN_COOLDOWN, now)
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            spawn_text = f"Spawn full {len(self.local_mobs)}/{MAX_ACTIVE_MOBS}"
        elif self.boss_mana + 1e-5 < MOB_SPAWN_MANA_COST:
            spawn_text = f"Spawn {int(MOB_SPAWN_MANA_COST)} PM"
        elif spawn_left <= 0.001:
            spawn_text = f"Spawn ready {int(MOB_SPAWN_MANA_COST)} PM"
        else:
            spawn_text = f"Spawn {spawn_left:.1f}s {int(MOB_SPAWN_MANA_COST)} PM"
        self._set_text_if_changed("boss_spawn_text", self.boss_spawn_text, spawn_text)

        mob_ids = sorted(self.local_mobs.keys())
        for index, slot in enumerate(self.boss_mob_slots):
            mob_id = mob_ids[index] if index < len(mob_ids) else None
            is_filled = mob_id is not None
            is_controlled = is_filled and self.controlled_entity == mob_id

            frame_color = (1.0, 0.82, 0.35, 0.92) if is_controlled else (0.9, 0.86, 0.72, 0.72)
            inner_color = (0.11, 0.14, 0.13, 0.96) if is_controlled else (0.04, 0.05, 0.06, 0.9)
            icon_color = (0.2, 1.0, 0.48, 0.98) if is_filled else (0.78, 0.85, 0.9, 0.34)

            slot["frame"]["frameColor"] = frame_color
            slot["inner"]["frameColor"] = inner_color
            slot["label"].setFg(icon_color)
            self._set_visible(f"boss_mob_slot_image_visible_{index}", slot["image"], is_filled)
            self._set_visible(f"boss_mob_slot_label_visible_{index}", slot["label"], not is_filled)
            slot["image"].setColor(1, 1, 1, 0.98 if is_filled else 0.0)

            if is_filled:
                hp_value = max(0, min(self.local_mob_hp.get(mob_id, MOB_MAX_HP), MOB_MAX_HP))
                self._set_widget_number_if_changed(f"boss_mob_slot_hp_{index}", slot["hp_bar"], "value", hp_value)
                self._set_widget_number_if_changed(f"boss_mob_slot_range_{index}", slot["hp_bar"], "range", MOB_MAX_HP)
            else:
                self._set_text_if_changed(f"boss_mob_slot_label_{index}", slot["label"], str(index + 1))
                self._set_widget_number_if_changed(f"boss_mob_slot_hp_{index}", slot["hp_bar"], "value", 0)
                self._set_widget_number_if_changed(f"boss_mob_slot_range_{index}", slot["hp_bar"], "range", MOB_MAX_HP)

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

        if self.editor_enabled:
            self._apply_boss_editor_layout()
        show_editor_root = is_boss and self.editor_enabled
        editor_fullscreen = show_editor_root and self.editor_expanded
        show_boss_ui = is_boss and not editor_fullscreen

        self._set_visible("hero_ui_root", self.hero_ui_root, is_hero)
        self._set_visible("boss_ui_root", self.boss_ui_root, show_boss_ui)
        self._set_visible("boss_inventory_root", self.boss_inventory_root, is_boss and self.boss_inventory_open)
        self._set_visible("left_panel", self.left_panel, (not is_hero) and (not is_boss) and (not editor_fullscreen))
        self._set_visible("right_panel", self.right_panel, (not is_hero) and (not is_boss) and (not editor_fullscreen))
        self._set_visible("action_panel", self.action_panel, (not is_hero) and (not is_boss) and (not editor_fullscreen))
        self._set_visible("editor_root", self.editor_root, show_editor_root)
        if is_boss and self.editor_enabled and not self.editor_expanded:
            self.right_panel.setZ(0.44)
        else:
            self.right_panel.setZ(0.93)
        if show_editor_root:
            self._set_text_if_changed("editor_title", self.editor_title, "BOSS EDITOR" if self.editor_expanded else "BOSS MAP")

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
            spawn_left = self._boss_action_left("spawn", SPAWN_COOLDOWN, now)
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
                    f"Spawn Ready {int(MOB_SPAWN_MANA_COST)} PM ({len(self.local_mobs)}/{MAX_ACTIVE_MOBS})",
                )
            else:
                self._set_text_if_changed(
                    "spawn_text",
                    self.spawn_text,
                    f"Spawn {spawn_left:.2f}s {int(MOB_SPAWN_MANA_COST)} PM ({len(self.local_mobs)}/{MAX_ACTIVE_MOBS})",
                )
        else:
            self._set_visible("spawn_bar", self.spawn_bar, False)
            self._set_visible("spawn_text", self.spawn_text, False)

        if is_boss:
            self._update_boss_ui(now, attack_cd, attack_left)
            self._set_text_if_changed(
                "boss_inventory_mob_count",
                self.boss_inventory_mob_count,
                f"{len(self.local_mobs)}/{MAX_ACTIVE_MOBS}",
            )

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
        if self.hero and self.boss:
            return

        hero_x = self.min_x + 2.0
        boss_x = self.max_x - 5.0
        hero_start = Vec3(hero_x, 0, self._get_spawn_z_on_base(hero_x, "start", 10.0))
        boss_start = Vec3(boss_x, 0, self._get_spawn_z_on_base(boss_x, "end", 10.0))

        if not self.hero:
            self.hero = Character(self.game_config, self.render, self.loader, self.physics, start_pos=hero_start)
        if self.player_id == 0:
            self._ensure_boss(boss_start, "REMOTE")
            self.controlled_entity = "hero"
            self._set_status("Hero ready. Reach the end to unlock the boss.")
        else:
            self._ensure_boss(boss_start, "PLAYER")
            self.controlled_entity = "boss"
            self._set_status("Boss ready. F=spawn, TAB=cycle, 1-6=pick mob, B=boss, M=map.")

        self._update_hud()

    def _ensure_boss(self, boss_start: Vec3, mode: str) -> Boss:
        if self.boss:
            self.boss.set_mode(mode)
            return self.boss
        self.boss = Boss(self.game_config, self.render, self.loader, self.physics, boss_start, mode=mode)
        return self.boss

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

    def _regen_boss_mana(self, dt: float):
        if self.player_id != 1 or self.winner:
            return
        self.boss_mana = min(BOSS_MAX_MANA, self.boss_mana + BOSS_MANA_REGEN * dt)

    def _boss_action_left(self, action_key: str, cooldown: float, now: float | None = None) -> float:
        if now is None:
            now = time.monotonic()
        return max(0.0, cooldown - (now - self.last_boss_action_times.get(action_key, -999.0)))

    def _try_spend_boss_action(self, action_key: str, mana_cost: float, cooldown: float, label: str) -> bool:
        if self.player_id != 1 or self.winner:
            return False
        now = time.monotonic()
        left = self._boss_action_left(action_key, cooldown, now)
        if left > 0.0:
            self._set_status(f"{label} on cooldown ({left:.1f}s).")
            return False
        if self.boss_mana + 1e-5 < mana_cost:
            self._set_status(f"Not enough mana for {label} ({int(mana_cost)} PM).")
            return False
        self.boss_mana = max(0.0, self.boss_mana - mana_cost)
        self.last_boss_action_times[action_key] = now
        return True

    def _can_attack(self, now: float, allow_combo_cancel: bool = False) -> tuple[bool, str, float]:
        cd_key = self._get_attack_cooldown_key()
        cooldown = self._get_current_attack_cooldown()
        elapsed = now - self.last_attack_times[cd_key]
        required_cooldown = cooldown
        state = self.combo_state.get(cd_key)
        if (
            allow_combo_cancel
            and state is not None
            and state["step"] >= 0
            and now - state["last_time"] <= COMBO_WINDOW
        ):
            required_cooldown *= ATTACK_COMBO_CANCEL_RATIO
        if elapsed >= required_cooldown:
            return True, cd_key, 0.0
        return False, cd_key, required_cooldown - elapsed

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
        attack_id: int = 0,
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
            "attack_id": attack_id,
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
                int(hero.get("attack_id", 0)),
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
                int(boss.get("attack_id", 0)),
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

        entity_module_ids = self._capture_entity_module_ids()
        move_deltas: list[dict[str, Any]] = []
        for item in modules:
            if not isinstance(item, dict):
                continue
            idx = int(item.get("id", -1))
            if idx < 0 or idx >= len(getattr(self.world, "module_nodes", [])):
                continue
            node = self.world.module_nodes[idx]
            meta = self.world.module_meta[idx] if idx < len(self.world.module_meta) else {}
            old_bounds = self._module_world_bounds(node, meta)
            old_x = float(node.getX())
            old_z = float(node.getZ())
            node.setX(float(item.get("x", old_x)))
            node.setZ(float(item.get("z", old_z)))
            self._sync_module_physics(node)
            dx = float(node.getX()) - old_x
            dz = float(node.getZ()) - old_z
            if abs(dx) > 1e-5 or abs(dz) > 1e-5:
                move_deltas.append({"module_id": id(node), "bounds": old_bounds, "delta": Vec3(dx, 0, dz), "width": meta.get("width", 1.0)})
        self._teleport_entities_with_modules(move_deltas, entity_module_ids)
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
                int(data.get("attack_id", 0)),
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
                    "attack_id": int(hero_anim["attack_id"]),
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
                    "attack_id": int(anim["attack_id"]),
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
                "attack_id": int(boss_anim["attack_id"]),
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

    def _entity_attack_distance(self, source_np, target_np) -> float:
        return abs(source_np.getX() - target_np.getX())

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
                    int(target.get("attack_id", 0)),
                )
            else:
                entity.apply_remote_animation(moving, bool(target["attacking"]), int(target.get("attack_id", 0)))

    def on_attack_input(self):
        if self.player_id is None or self.winner or not self.hero or not self.boss:
            return

        now = time.monotonic()
        can_attack, _, left = self._can_attack(now, allow_combo_cancel=True)
        if not can_attack:
            self.attack_buffer_until = now + ATTACK_INPUT_BUFFER
            self._set_status(f"Attack buffered ({left:.2f}s)")
            return

        self._perform_attack(now, allow_combo_cancel=True)

    def _perform_attack(self, now: float, allow_combo_cancel: bool = False):
        can_attack, cd_key, _ = self._can_attack(now, allow_combo_cancel=allow_combo_cancel)
        if not can_attack:
            return False

        animation_started = False
        if self.player_id == 0:
            animation_started = self.hero.perform_attack(restart=True, reverse_if_midpoint=True)
        else:
            if self.controlled_entity == "boss" and self.boss:
                animation_started = self.boss.perform_attack(restart=True, reverse_if_midpoint=True)
            elif isinstance(self.controlled_entity, int):
                mob = self.local_mobs.get(self.controlled_entity)
                if mob:
                    animation_started = mob.perform_attack(restart=True, reverse_if_midpoint=True)

        if not animation_started:
            self.attack_buffer_until = max(self.attack_buffer_until, now + ATTACK_INPUT_BUFFER)
            return False

        self.last_attack_times[cd_key] = now
        self.attack_buffer_until = 0.0

        combo_multiplier, combo_range_bonus = self._next_combo_multiplier(cd_key, now)
        if self.player_id == 0:
            self._send_hero_attack(combo_multiplier, combo_range_bonus)
        else:
            self._send_boss_attack(combo_multiplier, combo_range_bonus)
        return True

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
        can_attack, _, _ = self._can_attack(now, allow_combo_cancel=True)
        if can_attack:
            self._perform_attack(now, allow_combo_cancel=True)

    def _send_hero_attack(self, combo_multiplier: float, combo_range_bonus: float):
        self._play_attack_vfx(self.hero.np)
        self._apply_attack_lunge(self.hero.np, 3.5 + combo_range_bonus * 4.0)
        sent = False
        damage = int(HERO_DAMAGE * combo_multiplier)
        hit_range = ATTACK_RANGE + combo_range_bonus

        if self.boss_phase_unlocked and self._entity_attack_distance(self.hero.np, self.boss.np) <= hit_range:
            self._queue_message({"type": "attack", "target": "boss", "damage": damage})
            self._play_hit_vfx(self.boss.np, damage)
            sent = True

        for mob_id, mob in self.remote_mobs.items():
            if self._entity_attack_distance(self.hero.np, mob.np) <= hit_range:
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
        if self._entity_attack_distance(attacker_np, self.hero.np) <= hit_range:
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

        if not self._try_spend_boss_action("spawn", MOB_SPAWN_MANA_COST, SPAWN_COOLDOWN, "Spawn mob"):
            return
        self.last_spawn_time = self.last_boss_action_times["spawn"]

        source_np = self._get_controlled_np() or self.boss.np
        x = source_np.getX() + random.uniform(-1.5, 1.5)
        z = source_np.getZ() + 0.5
        self._spawn_local_mob_at(Vec3(x, 0, z))

    def _spawn_local_mob_at(self, pos: Vec3, status_label: str = "Spawned mob"):
        if self.player_id != 1 or self.winner:
            return
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            self._set_status(f"Spawn limit reached ({MAX_ACTIVE_MOBS}).")
            return
        mob_id = self.next_mob_id
        self.next_mob_id += 1

        mob = Mob(
            self.game_config,
            self.render,
            self.loader,
            self.physics,
            start_pos=pos,
            mode="AI",
        )
        self.local_mobs[mob_id] = mob
        self.local_mob_hp[mob_id] = MOB_MAX_HP
        self.ai_attack_clock[mob_id] = 0.0
        self._spawn_pulse_vfx(mob.np.getPos(self.render) + Vec3(0, 0, 1.3), (0.4, 0.95, 1.0, 0.9), 0.22, 0.28)
        slot = self._get_mob_slot(mob_id)
        slot_text = f" (slot {slot})" if slot is not None else ""
        self._set_status(f"{status_label} #{mob_id}{slot_text}.")

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
            if self._entity_attack_distance(mob.np, self.hero.np) > ATTACK_RANGE:
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
        min_cam_x, max_cam_x = self._get_camera_x_limits(camy)
        target_x = max(min_cam_x, min(target_np.getX(), max_cam_x))

        target_z = target_np.getZ() + 4.0
        dead_zone = 1.6
        if abs(target_z - camz) > dead_zone:
            target_z = camz + (target_z - camz - math.copysign(dead_zone, target_z - camz))
        else:
            target_z = camz

        blend = min(1.0, dt * CAMERA_SMOOTHING)
        self.camera_follow_x += (target_x - self.camera_follow_x) * blend
        self.camera_follow_x = max(min_cam_x, min(self.camera_follow_x, max_cam_x))
        camz = camz + (target_z - camz) * min(1.0, dt * (CAMERA_SMOOTHING * 0.6))
        self.camera.setPos(self.camera_follow_x, camy, camz)

    def _get_camera_x_limits(self, camy: float) -> tuple[float, float]:
        level_min = float(self.min_x)
        level_max = float(self.max_x)
        try:
            fov_x = float(self.camLens.getFov().x)
        except Exception:
            fov_x = 45.0
        half_visible = abs(camy) * math.tan(math.radians(fov_x * 0.5))
        half_visible = max(0.0, half_visible + CAMERA_EDGE_PADDING)
        min_cam_x = level_min + half_visible
        max_cam_x = level_max - half_visible
        if min_cam_x > max_cam_x:
            center = (level_min + level_max) * 0.5
            return center, center
        return min_cam_x, max_cam_x

    def _get_free_camera_z_limits(self) -> tuple[float, float]:
        min_bound = getattr(self.world, "_min_bound", None)
        max_bound = getattr(self.world, "_max_bound", None)
        if min_bound is None or max_bound is None:
            return -10.0, 30.0
        camy = self.camera.getY()
        try:
            fov_y = float(self.camLens.getFov().y)
        except Exception:
            fov_y = 35.0
        half_visible = abs(camy) * math.tan(math.radians(fov_y * 0.5))
        half_visible = max(0.0, half_visible + BOSS_FREE_CAMERA_Z_PADDING)
        min_z = float(min_bound.z) - BOSS_FREE_CAMERA_MODULE_HEIGHT_MARGIN + half_visible
        max_z = float(max_bound.z) + BOSS_FREE_CAMERA_MODULE_HEIGHT_MARGIN - half_visible
        if min_z > max_z:
            center = float(min_bound.z + max_bound.z) * 0.5
            return center, center
        return min_z, max_z

    def _update_boss_free_camera(self, dt: float):
        if not self.boss_inventory_open or self.player_id != 1:
            return
        camy = self.camera.getY()
        min_x, max_x = self._get_camera_x_limits(camy)
        min_z, max_z = self._get_free_camera_z_limits()

        move_x = float(self.free_camera_keys["d"]) - float(self.free_camera_keys["q"])
        move_z = float(self.free_camera_keys["z"]) - float(self.free_camera_keys["s"])
        if abs(move_x) > 1e-5 or abs(move_z) > 1e-5:
            length = math.hypot(move_x, move_z)
            if length > 1.0:
                move_x /= length
                move_z /= length
            next_x = self.camera.getX() + move_x * BOSS_FREE_CAMERA_SPEED * dt
            next_z = self.camera.getZ() + move_z * BOSS_FREE_CAMERA_SPEED * dt
        else:
            next_x = self.camera.getX()
            next_z = self.camera.getZ()

        next_x = max(min_x, min(next_x, max_x))
        next_z = max(min_z, min(next_z, max_z))
        self.camera.setPos(next_x, camy, next_z)
        self.camera_follow_x = next_x
        self._update_boss_inventory_drag_icon()

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
        self._regen_boss_mana(dt)
        self._process_attack_buffer()

        if self.hitstop_remaining > 0.0:
            self.hitstop_remaining = max(0.0, self.hitstop_remaining - dt)
            self._update_vfx(dt)
            self._update_boss_map_player_icon()
            if self.boss_inventory_open:
                self._update_boss_free_camera(dt)
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
        self._recover_falling_entities()

        if self.player_id == 1:
            self._update_ai_attacks()

        if self.player_id == 0 and self.hero and not self.boss_phase_unlocked and self.hero.np.getX() >= self.goal_x:
            self._unlock_boss_phase(announce=True)

        self._update_vfx(dt)
        if self.boss_inventory_open:
            self._update_boss_free_camera(dt)
        else:
            self._update_camera_follow(dt)
        self._update_boss_map_player_icon()
        self._update_status(dt)
        self._tick_hud(dt)
        return task.cont


if __name__ == "__main__":
    game = Game()
    game.run()
