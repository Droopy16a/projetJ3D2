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
from assets.Kayou import Kayou
from assets.PhysicsManager import PhysicsManager
from assets.World import World
from assets.Achille import Dungeon, Room

from direct.gui.DirectGui import DirectFrame, DirectWaitBar, DirectButton
from direct.gui import DirectGuiGlobals as DGG
from direct.gui.OnscreenImage import OnscreenImage
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    CardMaker,
    ConfigVariableString,
    DirectionalLight,
    Filename,
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
ATTACK_RANGE = 4.0
MAX_ACTIVE_MOBS = 6

HERO_MAX_HP = 130
BOSS_MAX_HP = 220
MOB_MAX_HP = 65
BOSS_MAX_MANA = 100.0
BOSS_MANA_REGEN = 6.0
DUNGEON_SWAP_MANA_COST = 65.0
MOB_SPAWN_MANA_COST = 25.0
MOB_DROP_MANA_COST = 25.0
KAYOU_DROP_MANA_COST = 45.0

BOSS_TELEPORT_MANA_COST = 40.0
BOSS_TELEPORT_COOLDOWN = 5.0
BOSS_TELEPORT_ANIM_DELAY = 0.75
HERO_DAMAGE = 8
BOSS_DAMAGE = 230
MOB_DAMAGE = HERO_MAX_HP
KAYOU_DAMAGE = 50
BOSS_READY_HERO_LEVEL = 9
HERO_DAMAGE_PER_LEVEL = 7
HERO_HEAL_PER_MOB_KILL = 10
HERO_MAX_MANA = 100.0
HERO_MANA_PER_MOB_KILL = 20.0
BIG_ATTACK_DAMAGE_MULTIPLIER = 2.5
HUD_UPDATE_INTERVAL = 0.05
FALL_RECOVERY_DEPTH = 12.0
FALL_RECOVERY_SAFE_X_PADDING = 0.9
FALL_RECOVERY_RAY_UP = 36.0
FALL_RECOVERY_RAY_DOWN = 42.0
FALL_RECOVERY_LIFT = 1.0
SPAWN_FLOOR_LIFT = -9.0
MOB_ICON_PATH = os.path.join("assets", "images", "mob_icon.png")
KAYOU_ICON_PATH = os.path.join("assets", "images", "kayou_icon.png")

MOB_DROP_COOLDOWN = 1.0
KAYOU_DROP_COOLDOWN = 3.0

MOB_ATTACK_STARTUP_DELAY = 0.5  # ~30 frames at 60fps
KAYOU_MAX_HP = 120


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
        self._setup_ui_theme()

        

        # Initialize and loop background music ambiance
        self.bg_music = self.loader.loadMusic(os.path.join("assets", "music","game_ambiance.mp3"))
        self.bg_music.setLoop(True)
        self.bg_music.setVolume(0.5)
        self.bg_music.play()

        # Load hero running sound
        self.sfx_hero_run = self.loader.loadSfx(os.path.join("assets", "music", "hero-run.mp3"))
        self.sfx_hero_run.setLoop(True)

        # Load hero attack sounds
        self.sfx_hero_attack_hit = self.loader.loadSfx(os.path.join("assets", "music", "hero-attack-hit.mp3"))
        self.sfx_hero_attack_miss = self.loader.loadSfx(os.path.join("assets", "music", "hero-attack-miss.mp3"))

        self.sfx_hero_jump = self.loader.loadSfx(os.path.join("assets", "music", "hero-jump.mp3"))
        self.sfx_hero_big_attack = self.loader.loadSfx(os.path.join("assets", "music", "hero-jump-attack.mp3"))
        self.sfx_hero_death = self.loader.loadSfx(os.path.join("assets", "music", "hero-death.mp3"))

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
                seed_src = f"DUNGEON_ARISE_WORLD:{self.PORT}"
                self.game_config.module_seed = int(hashlib.sha256(seed_src.encode()).hexdigest()[:8], 16)

        self.physics = PhysicsManager(self.game_config.gravity, self.render)
        if self.game_config.debug_physics:
            self.physics.enable_debug()
        self.world = World(self.game_config, self.render, self.loader, self.physics, index=0)
        self.min_x, self.max_x = self.world.setLimit()
        self._update_goal_x()
        self._setup_boss_editor()
        self._setup_hero_map()

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
        self.hero_mana = 0.0
        self.hero_was_jumping = False
        self.hero_level = 0
        self.hero_mob_kills = 0
        self.boss_phase_unlocked = False
        self.winner: str | None = None
        
        self.hero_start_pos: Vec3 | None = None
        self.hero_respawn_count = 0
        self.hero_death_count = 0
        self.max_respawns = 10  # 99 lives (configurable)
        self.hero_max_hp = HERO_MAX_HP  

        self.last_attack_times = {"hero": 0.0, "boss": 0.0, "mob": 0.0}
        self.last_boss_action_times = {"swap": -999.0, "spawn": -999.0, "drop": -999.0}
        self.combo_state = {
            "hero": {"step": -1, "last_time": 0.0},
            "boss": {"step": -1, "last_time": 0.0},
            "mob": {"step": -1, "last_time": 0.0},
        }
        self.ai_attack_clock: dict[int, float] = {}
        self.mob_attack_pending: dict[int, float] = {}
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
        self.last_boss_gate_status_time = 0.0
        self._last_world_layout_sig: tuple[tuple[int, float, float], ...] | None = None
        self.boss_inventory_open = False
        self.boss_inventory_dragging: str | None = None
        self.boss_inventory_previous_control: str | int = "boss"
        self.free_camera_keys = {key: False for key in ("z", "q", "s", "d")}
        self._ui_cache: dict[str, Any] = {}
        self._ui_visible: dict[str, bool] = {}
        self._ui_bar_state: dict[str, dict[str, Any]] = {}
        self._ui_fade_state: dict[str, dict[str, Any]] = {}
        self._ui_pulse_time = 0.0

        self._setup_hud()
        self._pulse_model_template = self.loader.loadModel("assets/models/sphere.egg.pz")

        self.accept("f", self.spawn_local_mob_request)
        self.accept("tab", self.cycle_control)
        for slot in range(1, MAX_ACTIVE_MOBS + 1):
            self.accept(str(slot), self.select_control_slot, [slot])
        self.accept("b", self.select_control_boss)
        self.accept("0", self.select_control_boss)
        self.accept("m", self._toggle_map_fullscreen)
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
        self.accept("t", self._boss_teleport_request)
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

    def _setup_ui_theme(self):
        self.ui_palette = {
            "void": (0.006, 0.008, 0.011, 0.92),
            "panel": (0.018, 0.021, 0.026, 0.78),
            "panel_deep": (0.009, 0.011, 0.016, 0.92),
            "panel_soft": (0.045, 0.041, 0.034, 0.34),
            "track": (0.012, 0.014, 0.018, 0.92),
            "track_light": (0.075, 0.070, 0.058, 0.28),
            "gold": (0.93, 0.72, 0.33, 0.96),
            "gold_dim": (0.48, 0.36, 0.19, 0.78),
            "gold_soft": (1.0, 0.78, 0.36, 0.18),
            "bronze": (0.54, 0.39, 0.22, 0.88),
            "text": (0.94, 0.91, 0.83, 0.98),
            "text_dim": (0.72, 0.68, 0.58, 0.88),
            "text_muted": (0.48, 0.51, 0.52, 0.72),
            "hp": (0.78, 0.065, 0.055, 0.96),
            "hp_dark": (0.30, 0.025, 0.022, 0.94),
            "mana": (0.13, 0.38, 0.82, 0.94),
            "mana_dark": (0.035, 0.11, 0.28, 0.9),
            "stamina": (0.28, 0.58, 0.28, 0.94),
            "cooldown": (0.0, 0.0, 0.0, 0.56),
            "shadow": (0.0, 0.0, 0.0, 0.54),
            "danger": (1.0, 0.19, 0.12, 0.0),
        }
        self.ui_rarity_colors = {
            "common": (0.56, 0.49, 0.39, 0.86),
            "uncommon": (0.34, 0.70, 0.46, 0.9),
            "rare": (0.33, 0.55, 0.95, 0.92),
            "epic": (0.62, 0.40, 0.92, 0.92),
            "legendary": (0.96, 0.66, 0.24, 0.98),
        }
        self.ui_font = None
        font_candidates = [
            os.path.join("assets", "fonts", "Cinzel-Regular.ttf"),
            os.path.join("assets", "fonts", "CormorantGaramond-Regular.ttf"),
            r"C:\Windows\Fonts\georgia.ttf",
            r"C:\Windows\Fonts\cambria.ttf",
            r"C:\Windows\Fonts\times.ttf",
        ]
        for font_path in font_candidates:
            if not os.path.exists(font_path):
                continue
            try:
                self.ui_font = self.loader.loadFont(Filename.fromOsSpecific(font_path))
                break
            except Exception:
                self.ui_font = None

    def _make_ui_text(self, **kwargs):
        font = getattr(self, "ui_font", None)
        if font is not None and "font" not in kwargs:
            kwargs["font"] = font
        return OnscreenText(**kwargs)

    @staticmethod
    def _inset_frame(frame: tuple[float, float, float, float], amount: float) -> tuple[float, float, float, float]:
        left, right, bottom, top = frame
        return (left + amount, right - amount, bottom + amount, top - amount)

    @staticmethod
    def _expand_frame(frame: tuple[float, float, float, float], amount: float) -> tuple[float, float, float, float]:
        left, right, bottom, top = frame
        return (left - amount, right + amount, bottom - amount, top + amount)

    def _make_ui_frame(
        self,
        parent,
        frame_color: tuple[float, float, float, float],
        frame_size: tuple[float, float, float, float],
        pos: tuple[float, float, float] = (0, 0, 0),
    ):
        frame = DirectFrame(
            parent=parent,
            frameColor=frame_color,
            frameSize=frame_size,
            pos=pos,
        )
        frame.setTransparency(TransparencyAttrib.MAlpha)
        return frame

    def _make_fantasy_panel(
        self,
        parent,
        frame_size: tuple[float, float, float, float],
        pos: tuple[float, float, float],
        *,
        name: str = "panel",
        frame_color: tuple[float, float, float, float] | None = None,
    ):
        palette = self.ui_palette
        root = self._make_ui_frame(
            parent,
            frame_color or palette["panel"],
            frame_size,
            pos,
        )
        root["frameSize"] = frame_size
        self._make_ui_frame(root, palette["shadow"], self._expand_frame(frame_size, 0.014), pos=(0.018, 0, -0.018))
        self._make_ui_frame(root, palette["gold_dim"], self._expand_frame(frame_size, 0.006))
        self._make_ui_frame(root, palette["panel_deep"], self._inset_frame(frame_size, 0.012))
        left, right, _bottom, top = frame_size
        self._make_ui_frame(root, palette["track_light"], (left + 0.018, right - 0.018, top - 0.026, top - 0.012))
        glow = self._make_ui_frame(root, palette["gold_soft"], self._inset_frame(frame_size, 0.022))
        glow.setAlphaScale(0.55)
        return root

    def _make_framed_bar(
        self,
        parent,
        *,
        pos: tuple[float, float, float],
        width: float,
        height: float,
        label: str,
        icon: str,
        bar_color: tuple[float, float, float, float],
        trail_color: tuple[float, float, float, float],
    ) -> dict[str, Any]:
        palette = self.ui_palette
        frame = (-0.066, width + 0.018, -height - 0.018, 0.028)
        root = self._make_ui_frame(parent, (0, 0, 0, 0), frame, pos)
        self._make_ui_frame(root, palette["shadow"], self._expand_frame(frame, 0.006), pos=(0.012, 0, -0.011))
        self._make_ui_frame(root, palette["bronze"], frame)
        self._make_ui_frame(root, palette["track"], (0, width, -height, 0))
        trail = DirectWaitBar(
            parent=root,
            text="",
            range=1.0,
            value=1.0,
            frameColor=(0, 0, 0, 0),
            barColor=trail_color,
            frameSize=(0, width, -height, 0),
            pos=(0, 0, 0),
        )
        trail.setTransparency(TransparencyAttrib.MAlpha)
        bar = DirectWaitBar(
            parent=root,
            text="",
            range=1.0,
            value=1.0,
            frameColor=(0, 0, 0, 0),
            barColor=bar_color,
            frameSize=(0, width, -height, 0),
            pos=(0, 0, 0),
        )
        bar.setTransparency(TransparencyAttrib.MAlpha)
        self._make_ui_frame(root, (1.0, 0.95, 0.72, 0.10), (0.006, width - 0.006, -height * 0.42, -0.005))
        flash = self._make_ui_frame(root, self.ui_palette["danger"], (0, width, -height, 0))
        icon_frame = self._make_ui_frame(
            root,
            palette["gold_dim"],
            (-0.052, 0.028, -height - 0.007, 0.018),
            pos=(-0.002, 0, 0),
        )
        self._make_ui_text(
            text=icon,
            pos=(-0.012, -height * 0.73),
            align=TextNode.ACenter,
            scale=max(0.022, height * 0.62),
            fg=palette["text"],
            shadow=(0, 0, 0, 0.88),
            mayChange=False,
            parent=icon_frame,
        )
        label_text = self._make_ui_text(
            text=label,
            pos=(0.044, height * 0.05),
            align=TextNode.ALeft,
            scale=max(0.024, height * 0.54),
            fg=palette["text_dim"],
            shadow=(0, 0, 0, 0.86),
            mayChange=True,
            parent=root,
        )
        value_text = self._make_ui_text(
            text="",
            pos=(width * 0.5, -height * 0.74),
            align=TextNode.ACenter,
            scale=max(0.022, height * 0.50),
            fg=palette["text"],
            shadow=(0, 0, 0, 0.88),
            mayChange=True,
            parent=root,
        )
        return {
            "root": root,
            "bar": bar,
            "trail": trail,
            "flash": flash,
            "label": label_text,
            "text": value_text,
            "width": width,
            "height": height,
        }

    def _set_animated_bar_value(
        self,
        key: str,
        widget,
        value: float,
        *,
        trail_widget=None,
        flash_widget=None,
        speed: float = 14.0,
        trail_speed: float = 4.2,
    ):
        value = float(value)
        state = self._ui_bar_state.get(key)
        if state is None:
            state = {
                "widget": widget,
                "target": value,
                "display": value,
                "trail": trail_widget,
                "trail_display": value,
                "flash": flash_widget,
                "flash_time": 0.0,
                "speed": speed,
                "trail_speed": trail_speed,
            }
            self._ui_bar_state[key] = state
            widget["value"] = value
            if trail_widget is not None:
                trail_widget["value"] = value
            return

        previous = float(state.get("target", value))
        state["widget"] = widget
        state["trail"] = trail_widget
        state["flash"] = flash_widget
        state["speed"] = speed
        state["trail_speed"] = trail_speed
        state["target"] = value
        if value < previous - 0.001:
            state["flash_time"] = 0.26
            state["trail_display"] = max(float(state.get("trail_display", previous)), previous)
        elif value > previous + 0.001:
            state["trail_display"] = value

    def _update_ui_animations(self, dt: float):
        self._ui_pulse_time += dt
        for key, state in list(self._ui_bar_state.items()):
            widget = state.get("widget")
            if widget is None:
                continue
            target = float(state.get("target", 0.0))
            display = float(state.get("display", target))
            blend = 1.0 - math.exp(-float(state.get("speed", 14.0)) * max(0.0, dt))
            display += (target - display) * blend
            if abs(display - target) < 0.001:
                display = target
            state["display"] = display
            widget["value"] = display

            trail_widget = state.get("trail")
            if trail_widget is not None:
                trail_display = float(state.get("trail_display", display))
                if trail_display > target:
                    trail_blend = 1.0 - math.exp(-float(state.get("trail_speed", 4.2)) * max(0.0, dt))
                else:
                    trail_blend = blend
                trail_display += (target - trail_display) * trail_blend
                if abs(trail_display - target) < 0.001:
                    trail_display = target
                state["trail_display"] = trail_display
                trail_widget["value"] = max(display, trail_display)

            flash_widget = state.get("flash")
            if flash_widget is not None:
                flash_time = max(0.0, float(state.get("flash_time", 0.0)) - dt)
                state["flash_time"] = flash_time
                alpha = min(0.38, flash_time / 0.26 * 0.38) if flash_time > 0 else 0.0
                flash_widget["frameColor"] = (1.0, 0.12, 0.07, alpha)

        for key, state in list(self._ui_fade_state.items()):
            widget = state.get("widget")
            if widget is None:
                self._ui_fade_state.pop(key, None)
                continue
            value = float(state.get("value", 1.0))
            target = float(state.get("target", 1.0))
            blend = 1.0 - math.exp(-10.0 * max(0.0, dt))
            value += (target - value) * blend
            if abs(value - target) < 0.01:
                value = target
                if target >= 1.0:
                    self._ui_fade_state.pop(key, None)
            state["value"] = value
            widget.setAlphaScale(value)

    def _is_mouse_over_widget(self, widget) -> bool:
        if widget is None or widget.isHidden() or not self.mouseWatcherNode.hasMouse():
            return False
        try:
            left, right, bottom, top = widget["frameSize"]
        except Exception:
            return False
        aspect = self.getAspectRatio()
        mouse_x = self.mouseWatcherNode.getMouseX() * aspect
        mouse_z = self.mouseWatcherNode.getMouseY()
        pos = widget.getPos(self.aspect2d)
        local_x = mouse_x - pos.x
        local_z = mouse_z - pos.z
        return left <= local_x <= right and bottom <= local_z <= top

    def _update_role_ui_layout(self):
        aspect = float(self.getAspectRatio())
        margin = 0.17
        if hasattr(self, "boss_control_root"):
            self.boss_control_root.setPos(-aspect + margin, 0, 0.84)
        if hasattr(self, "hero_bars_root"):
            self.hero_bars_root.setPos(-aspect + margin, 0, 0.88)
        if hasattr(self, "hero_map_root"):
            self._apply_hero_map_layout()
        if hasattr(self, "boss_mob_slots_root"):
            slot_size = getattr(self, "boss_slot_size", 0.108)
            slot_gap = getattr(self, "boss_slot_gap", 0.132)
            total_width = (MAX_ACTIVE_MOBS - 1) * slot_gap + slot_size
            self.boss_mob_slots_root.setPos(-total_width * 0.5, 0, -0.78)

    def _setup_boss_editor(self):
        palette = self.ui_palette
        self.editor_enabled = bool(getattr(self.world, "module_nodes", []))
        self.editor_texture_cache: dict[str, Any] = {}
        self.editor_frame = (-0.39, 0.39, -0.265, 0.265)
        self.editor_layout_sig: tuple[bool, float] | None = None
        self.editor_root = self._make_ui_frame(
            parent=self.aspect2d,
            frame_color=palette["panel"],
            frame_size=self.editor_frame,
            pos=(1.38, 0, 0.68),
        )
        self.editor_root.hide()
        self.editor_expanded = False
        self.editor_root.bind(DGG.B1PRESS, self._on_editor_panel_press)

        self.editor_shadow = self._make_ui_frame(
            self.editor_root,
            palette["shadow"],
            self._expand_frame(self.editor_frame, 0.018),
            pos=(0.018, 0, -0.018),
        )
        self.editor_border = self._make_ui_frame(
            self.editor_root,
            palette["gold_dim"],
            self._expand_frame(self.editor_frame, 0.006),
        )
        self.editor_backdrop = self._make_ui_frame(
            self.editor_root,
            palette["panel_deep"],
            self._inset_frame(self.editor_frame, 0.018),
        )
        self.editor_header = self._make_ui_frame(
            self.editor_root,
            (0.12, 0.095, 0.055, 0.45),
            (-0.36, 0.36, 0.145, 0.235),
        )
        self.editor_vignette_top = self._make_ui_frame(
            self.editor_root,
            (0.0, 0.0, 0.0, 0.26),
            (-0.36, 0.36, 0.105, 0.145),
        )
        self.editor_vignette_bottom = self._make_ui_frame(
            self.editor_root,
            (0.0, 0.0, 0.0, 0.22),
            (-0.36, 0.36, -0.235, -0.19),
        )
        self.editor_grid = self.editor_root.attachNewNode("editor_grid")

        self.editor_title = self._make_ui_text(
            text="DUNGEON",
            pos=(-0.335, 0.172),
            align=TextNode.ALeft,
            scale=0.034,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.86),
            mayChange=True,
            parent=self.editor_root,
        )
        self.editor_subtitle = self._make_ui_text(
            text="WAR TABLE",
            pos=(-0.335, 0.128),
            align=TextNode.ALeft,
            scale=0.018,
            fg=palette["text_dim"],
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.editor_root,
        )
        self.editor_key_badge = self._make_ui_frame(
            parent=self.editor_root,
            frame_color=palette["gold_dim"],
            frame_size=(-0.04, 0.04, -0.026, 0.026),
            pos=(0.315, 0, 0.175),
        )
        self.editor_mode_label = self._make_ui_text(
            text="M",
            pos=(0, -0.009),
            align=TextNode.ACenter,
            scale=0.026,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.75),
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
            self.editor_notice = self._make_ui_text(
                text="Dungeon map unavailable.",
                pos=(0, 0),
                align=TextNode.ACenter,
                scale=0.034,
                fg=palette["text_dim"],
                shadow=(0, 0, 0, 0.8),
                mayChange=False,
                parent=self.editor_root,
            )
            return

        colors = [
            (0.42, 0.30, 0.20, 0.95),
            (0.24, 0.34, 0.46, 0.95),
            (0.23, 0.38, 0.28, 0.95),
            (0.36, 0.28, 0.48, 0.95),
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
                lock_label = self._make_ui_text(
                    text="SEAL",
                    pos=(0, -0.035),
                    align=TextNode.ACenter,
                    scale=0.16,
                    fg=palette["gold"],
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
        self.editor_player_glow = self._make_ui_frame(
            self.editor_root,
            self.ui_palette["gold_soft"],
            (-0.028, 0.028, -0.028, 0.028),
        )
        self.editor_player_glow.setBin("fixed", 210)
        self.editor_player_glow.setDepthTest(False)
        self.editor_player_glow.setDepthWrite(False)
        self.editor_player_glow.hide()
        self.editor_player_marker = self._make_ui_frame(
            self.editor_root,
            (0.04, 0.025, 0.012, 0.92),
            (-0.018, 0.018, -0.018, 0.018),
        )
        self.editor_player_marker.setBin("fixed", 220)
        self.editor_player_marker.setDepthTest(False)
        self.editor_player_marker.setDepthWrite(False)
        self.editor_player_marker.hide()
        self.editor_player_icon = OnscreenImage(
            image=icon_path,
            parent=self.editor_root,
            pos=(0, 0, 0),
            scale=(0.044, 1, 0.044),
        )
        self.editor_player_icon.setColor(1.0, 1.0, 1.0, 1)
        self.editor_player_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.editor_player_icon.setBin("fixed", 230)
        self.editor_player_icon.setDepthTest(False)
        self.editor_player_icon.setDepthWrite(False)
        self.editor_player_icon.setLightOff(1)
        self.editor_player_icon.hide()

    def _setup_hero_map(self):
        palette = self.ui_palette
        self.hero_map_enabled = bool(getattr(self.world, "module_nodes", []))
        self.hero_map_frame = (-0.39, 0.39, -0.265, 0.265)
        self.hero_map_layout_sig: tuple[bool, float] | None = None
        self.hero_map_expanded = False
        self.hero_map_root = self._make_ui_frame(
            parent=self.aspect2d,
            frame_color=palette["panel"],
            frame_size=self.hero_map_frame,
            pos=(1.38, 0, 0.65),
        )
        self.hero_map_root.hide()

        self.hero_map_shadow = self._make_ui_frame(
            self.hero_map_root,
            palette["shadow"],
            self._expand_frame(self.hero_map_frame, 0.018),
            pos=(0.018, 0, -0.018),
        )
        self.hero_map_border = self._make_ui_frame(
            self.hero_map_root,
            palette["gold_dim"],
            self._expand_frame(self.hero_map_frame, 0.006),
        )
        self.hero_map_backdrop = self._make_ui_frame(
            self.hero_map_root,
            palette["panel_deep"],
            self._inset_frame(self.hero_map_frame, 0.018),
        )
        self.hero_map_header = self._make_ui_frame(
            self.hero_map_root,
            (0.12, 0.095, 0.055, 0.45),
            (-0.36, 0.36, 0.145, 0.235),
        )
        self.hero_map_vignette_top = self._make_ui_frame(
            self.hero_map_root,
            (0.0, 0.0, 0.0, 0.26),
            (-0.36, 0.36, 0.105, 0.145),
        )
        self.hero_map_vignette_bottom = self._make_ui_frame(
            self.hero_map_root,
            (0.0, 0.0, 0.0, 0.22),
            (-0.36, 0.36, -0.235, -0.19),
        )
        self.hero_map_grid = self.hero_map_root.attachNewNode("hero_map_grid")
        self.hero_map_title = self._make_ui_text(
            text="DUNGEON",
            pos=(-0.335, 0.172),
            align=TextNode.ALeft,
            scale=0.034,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.86),
            mayChange=True,
            parent=self.hero_map_root,
        )
        self.hero_map_subtitle = self._make_ui_text(
            text="PATH",
            pos=(-0.335, 0.128),
            align=TextNode.ALeft,
            scale=0.018,
            fg=palette["text_dim"],
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.hero_map_root,
        )
        self.hero_map_readonly_badge = self._make_ui_frame(
            parent=self.hero_map_root,
            frame_color=palette["gold_dim"],
            frame_size=(-0.04, 0.04, -0.026, 0.026),
            pos=(0.315, 0, 0.175),
        )
        self._make_ui_text(
            text="M",
            pos=(0, -0.009),
            align=TextNode.ACenter,
            scale=0.026,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.75),
            mayChange=False,
            parent=self.hero_map_readonly_badge,
        )

        self.hero_map_canvas = self.hero_map_root.attachNewNode("hero_map_canvas")
        self.hero_map_scale = 0.12
        self.hero_map_canvas.setScale(self.hero_map_scale, 1, self.hero_map_scale)
        self.hero_map_canvas.setPos(0, 0, -0.02)
        self.hero_map_room_half_w = 0.5
        self.hero_map_room_half_h = 0.25
        self.hero_map_dungeon = Dungeon()
        self.hero_map_room_to_module: dict[Room, dict] = {}
        self.hero_map_module_to_room: dict[int, Room] = {}
        self.hero_map_player_icon = None
        self.hero_map_player_glow = None
        self.hero_map_player_marker = None

        self._apply_hero_map_layout(force=True)
        if not self.hero_map_enabled:
            self.hero_map_notice = self._make_ui_text(
                text="Dungeon map unavailable.",
                pos=(0, 0),
                align=TextNode.ACenter,
                scale=0.034,
                fg=palette["text_dim"],
                shadow=(0, 0, 0, 0.8),
                mayChange=False,
                parent=self.hero_map_root,
            )
            return

        colors = [
            (0.42, 0.30, 0.20, 0.95),
            (0.24, 0.34, 0.46, 0.95),
            (0.23, 0.38, 0.28, 0.95),
            (0.36, 0.28, 0.48, 0.95),
        ]
        card_maker = CardMaker("hero_map_module_card")
        card_maker.set_frame(-0.5, 0.5, -0.25, 0.25)
        for i, (module, meta) in enumerate(zip(self.world.module_nodes, self.world.module_meta)):
            room = Room(meta.get("name", f"Module {i + 1}"), colors[i % len(colors)])
            room.model = self.hero_map_canvas.attachNewNode(card_maker.generate())
            texture = self._get_boss_editor_texture(meta)
            if texture is not None:
                room.model.setTexture(texture, 1)
                room.model.setColor(1, 1, 1, 1)
                room.model.setTransparency(TransparencyAttrib.MAlpha)
            else:
                room.model.setColor(*room.color)
            self.hero_map_dungeon.add_room(room)
            self.hero_map_room_to_module[room] = {"node": module, "meta": meta}
            self.hero_map_module_to_room[id(module)] = room
            if bool(meta.get("locked_endpoint", False)):
                seal = self._make_ui_text(
                    text="SEAL",
                    pos=(0, -0.035),
                    align=TextNode.ACenter,
                    scale=0.16,
                    fg=palette["gold"],
                    shadow=(0, 0, 0, 0.9),
                    mayChange=False,
                    parent=room.model,
                )
                seal.setBin("fixed", 100)

        self._sync_hero_map_from_world()
        self._setup_hero_map_player_icon()

    def _setup_hero_map_player_icon(self):
        icon_path = os.path.join("assets", "images", "player_icon.png")
        if not os.path.exists(icon_path):
            return
        self.hero_map_player_glow = self._make_ui_frame(
            self.hero_map_root,
            self.ui_palette["gold_soft"],
            (-0.028, 0.028, -0.028, 0.028),
        )
        self.hero_map_player_glow.setBin("fixed", 210)
        self.hero_map_player_glow.setDepthTest(False)
        self.hero_map_player_glow.setDepthWrite(False)
        self.hero_map_player_glow.hide()
        self.hero_map_player_marker = self._make_ui_frame(
            self.hero_map_root,
            (0.04, 0.025, 0.012, 0.92),
            (-0.018, 0.018, -0.018, 0.018),
        )
        self.hero_map_player_marker.setBin("fixed", 220)
        self.hero_map_player_marker.setDepthTest(False)
        self.hero_map_player_marker.setDepthWrite(False)
        self.hero_map_player_marker.hide()
        self.hero_map_player_icon = OnscreenImage(
            image=icon_path,
            parent=self.hero_map_root,
            pos=(0, 0, 0),
            scale=(0.044, 1, 0.044),
        )
        self.hero_map_player_icon.setColor(1.0, 1.0, 1.0, 1)
        self.hero_map_player_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.hero_map_player_icon.setBin("fixed", 230)
        self.hero_map_player_icon.setDepthTest(False)
        self.hero_map_player_icon.setDepthWrite(False)
        self.hero_map_player_icon.setLightOff(1)
        self.hero_map_player_icon.hide()

    def _apply_hero_map_layout(self, force: bool = False):
        aspect = round(float(self.getAspectRatio()), 3)
        sig = (bool(self.hero_map_expanded), aspect)
        if not force and self.hero_map_layout_sig == sig:
            return
        self.hero_map_layout_sig = sig
        if self.hero_map_expanded:
            margin_x = 0.12
            self.hero_map_frame = (-aspect + margin_x, aspect - margin_x, -0.86, 0.86)
            self.hero_map_root["frameColor"] = self.ui_palette["void"]
            self.hero_map_root.setPos(0, 0, 0)
            self.hero_map_title.setScale(0.052)
            self.hero_map_title.setPos(self.hero_map_frame[0] + 0.11, 0.755)
            self.hero_map_subtitle.setScale(0.026)
            self.hero_map_subtitle.setPos(self.hero_map_frame[0] + 0.112, 0.695)
            self.hero_map_readonly_badge["frameSize"] = (-0.046, 0.046, -0.032, 0.032)
            self.hero_map_readonly_badge.setPos(self.hero_map_frame[1] - 0.12, 0, 0.76)
        else:
            self.hero_map_frame = (-0.39, 0.39, -0.265, 0.265)
            self.hero_map_root["frameColor"] = self.ui_palette["panel"]
            self.hero_map_root.setPos(aspect - 0.47, 0, 0.65)
            self.hero_map_title.setScale(0.034)
            self.hero_map_title.setPos(-0.335, 0.172)
            self.hero_map_subtitle.setScale(0.018)
            self.hero_map_subtitle.setPos(-0.335, 0.128)
            self.hero_map_readonly_badge["frameSize"] = (-0.04, 0.04, -0.026, 0.026)
            self.hero_map_readonly_badge.setPos(0.315, 0, 0.175)
        self.hero_map_root["frameSize"] = self.hero_map_frame

        left, right, bottom, top = self.hero_map_frame
        inset = 0.026 if self.hero_map_expanded else 0.018
        self.hero_map_shadow["frameSize"] = self._expand_frame(self.hero_map_frame, 0.018)
        self.hero_map_border["frameSize"] = self._expand_frame(self.hero_map_frame, 0.006)
        self.hero_map_backdrop["frameSize"] = (left + inset, right - inset, bottom + inset, top - inset)
        header_h = 0.14 if self.hero_map_expanded else 0.09
        self.hero_map_header["frameSize"] = (left + inset, right - inset, top - header_h, top - inset)
        self.hero_map_vignette_top["frameSize"] = (left + inset, right - inset, top - header_h - 0.035, top - header_h)
        self.hero_map_vignette_bottom["frameSize"] = (left + inset, right - inset, bottom + inset, bottom + inset + 0.052)
        self._rebuild_hero_map_grid()
        self._fit_hero_map_canvas()

    def _rebuild_hero_map_grid(self):
        self.hero_map_grid.node().removeAllChildren()
        left, right, bottom, top = self.hero_map_frame
        line_color = (0.78, 0.61, 0.34, 0.13) if self.hero_map_expanded else (0.78, 0.61, 0.34, 0.09)
        line_count = 10 if self.hero_map_expanded else 5
        thickness = 0.003 if self.hero_map_expanded else 0.0025
        for i in range(1, line_count):
            x = left + (right - left) * (i / line_count)
            cm = CardMaker("hero_map_grid_v")
            cm.set_frame(-thickness * 0.5, thickness * 0.5, bottom, top)
            line = self.hero_map_grid.attachNewNode(cm.generate())
            line.setPos(x, 0, 0)
            line.setColor(*line_color)
            line.setTransparency(TransparencyAttrib.MAlpha)

            z = bottom + (top - bottom) * (i / line_count)
            cm = CardMaker("hero_map_grid_h")
            cm.set_frame(left, right, -thickness * 0.5, thickness * 0.5)
            line = self.hero_map_grid.attachNewNode(cm.generate())
            line.setPos(0, 0, z)
            line.setColor(*line_color)
            line.setTransparency(TransparencyAttrib.MAlpha)

    def _sync_hero_map_from_world(self):
        if not getattr(self, "hero_map_enabled", False):
            return
        entries = []
        for room, mapping in self.hero_map_room_to_module.items():
            node = mapping["node"]
            meta = mapping["meta"]
            center = float(node.getX() + meta.get("center_offset", 0.0))
            entries.append((center, room, node, meta))
        if not entries:
            return
        entries.sort(key=lambda item: item[0])
        start_x = -(len(entries) - 1) * 0.5
        for index, (_center, room, node, meta) in enumerate(entries):
            room.model.setPos(start_x + index, 0, 0.0)
        self._relink_hero_map_rooms(entries)
        self._fit_hero_map_canvas()

    def _relink_hero_map_rooms(self, entries: list[tuple[float, Room, Any, dict]]):
        for room in self.hero_map_dungeon.rooms:
            if room.corridor_left:
                room.corridor_left.removeNode()
            if room.corridor_right:
                room.corridor_right.removeNode()
            room.corridor_left = None
            room.corridor_right = None
            room.left = None
            room.right = None
        rooms = [entry[1] for entry in entries]
        for left_room, right_room in zip(rooms, rooms[1:]):
            corridor = self.hero_map_dungeon.create_corridor(self.hero_map_canvas, left_room, right_room)
            corridor.setColor(0.96, 0.70, 0.28, 0.72)
            corridor.setTransparency(TransparencyAttrib.MAlpha)
            left_room.right = right_room
            right_room.left = left_room
            left_room.corridor_right = corridor
            right_room.corridor_left = corridor

    def _fit_hero_map_canvas(self):
        if not getattr(self, "hero_map_dungeon", None) or not self.hero_map_dungeon.rooms:
            return
        min_x = min(room.model.getX() - self.hero_map_room_half_w for room in self.hero_map_dungeon.rooms)
        max_x = max(room.model.getX() + self.hero_map_room_half_w for room in self.hero_map_dungeon.rooms)
        min_z = min(room.model.getZ() - self.hero_map_room_half_h for room in self.hero_map_dungeon.rooms)
        max_z = max(room.model.getZ() + self.hero_map_room_half_h for room in self.hero_map_dungeon.rooms)
        content_w = max(0.01, max_x - min_x)
        content_h = max(0.01, max_z - min_z)
        content_cx = (min_x + max_x) * 0.5
        content_cz = (min_z + max_z) * 0.5
        left, right, bottom, top = self.hero_map_frame
        margin_x = 0.18 if self.hero_map_expanded else 0.055
        margin_y = 0.23 if self.hero_map_expanded else 0.075
        available_w = max(0.01, (right - left) - margin_x * 2)
        available_h = max(0.01, (top - bottom) - margin_y * 2)
        scale = min(available_w / content_w, available_h / content_h) * 0.97
        self.hero_map_scale = scale
        self.hero_map_canvas.setScale(scale, 1, scale)
        target_x = left + margin_x + available_w * 0.5 - content_cx * scale
        target_z = bottom + margin_y + available_h * 0.5 - content_cz * scale
        self.hero_map_canvas.setPos(target_x, 0, target_z)

    def _world_pos_to_hero_map_pos(self, world_pos: Vec3) -> Vec3:
        best_room = None
        best_meta = None
        best_score = None
        for room in self.hero_map_dungeon.rooms:
            mapping = self.hero_map_room_to_module.get(room)
            if not mapping:
                continue
            node = mapping["node"]
            meta = mapping["meta"]
            left, right, _bottom, _top = self._module_world_bounds(node, meta)
            width = max(0.01, right - left)
            score = 0.0 if left <= world_pos.x <= right else min(abs(world_pos.x - left), abs(world_pos.x - right))
            if best_score is None or score < best_score:
                best_room = room
                best_meta = (left, width)
                best_score = score
        if best_room is not None and best_meta is not None:
            left, width = best_meta
            local_t = max(0.0, min(1.0, (world_pos.x - left) / width))
            editor_x = best_room.model.getX() - self.hero_map_room_half_w + local_t * (self.hero_map_room_half_w * 2.0)
            return Vec3(editor_x, -0.02, best_room.model.getZ() + 0.02)
        return Vec3(0, -0.02, 0.02)

    def _update_hero_map_player_icon(self):
        icon = getattr(self, "hero_map_player_icon", None)
        if icon is None:
            return
        glow = getattr(self, "hero_map_player_glow", None)
        marker = getattr(self, "hero_map_player_marker", None)
        if not self.hero_map_enabled or self.player_id != 0 or self.hero is None:
            icon.hide()
            if glow is not None:
                glow.hide()
            if marker is not None:
                marker.hide()
            return
        hero_map_pos = self._world_pos_to_hero_map_pos(self.hero.np.getPos(self.render))
        canvas_pos = self.hero_map_canvas.getPos(self.hero_map_root)
        root_x = canvas_pos.x + hero_map_pos.x * self.hero_map_scale
        root_z = canvas_pos.z + hero_map_pos.z * self.hero_map_scale
        pulse = 0.5 + 0.5 * math.sin(self._ui_pulse_time * 5.4)
        base_scale = 0.062 if self.hero_map_expanded else 0.042
        left, right, bottom, top = self.hero_map_frame
        edge_pad = base_scale * 1.05
        root_x = max(left + edge_pad, min(right - edge_pad, root_x))
        root_z = max(bottom + edge_pad, min(top - edge_pad, root_z))
        icon.setScale(base_scale, 1, base_scale)
        icon.setPos(root_x, 0, root_z)
        icon.show()
        if marker is not None:
            marker_size = base_scale * 0.46
            marker["frameSize"] = (-marker_size, marker_size, -marker_size, marker_size)
            marker.setPos(root_x, 0, root_z)
            marker.show()
        if glow is not None:
            glow_size = base_scale * (0.78 + pulse * 0.32)
            glow["frameSize"] = (-glow_size, glow_size, -glow_size, glow_size)
            glow["frameColor"] = (1.0, 0.72, 0.24, 0.13 + pulse * 0.11)
            glow.setPos(root_x, 0, root_z)
            glow.show()

    def _apply_boss_editor_layout(self, force: bool = False):
        aspect = round(float(self.getAspectRatio()), 3)
        sig = (bool(self.editor_expanded), aspect)
        if not force and self.editor_layout_sig == sig:
            return
        self.editor_layout_sig = sig

        if self.editor_expanded:
            margin_x = 0.12
            self.editor_frame = (-aspect + margin_x, aspect - margin_x, -0.86, 0.86)
            self.editor_root["frameColor"] = self.ui_palette["void"]
            self.editor_root["frameSize"] = self.editor_frame
            self.editor_root.setPos(0, 0, 0)
            self.editor_title.setScale(0.052)
            self.editor_title.setPos(self.editor_frame[0] + 0.11, 0.755)
            self.editor_subtitle.setScale(0.026)
            self.editor_subtitle.setPos(self.editor_frame[0] + 0.112, 0.695)
            self.editor_key_badge["frameSize"] = (-0.046, 0.046, -0.032, 0.032)
            self.editor_key_badge.setPos(self.editor_frame[1] - 0.12, 0, 0.76)
            self.editor_mode_label.setScale(0.034)
            self.editor_mode_label.setPos(0, -0.012)
        else:
            self.editor_frame = (-0.39, 0.39, -0.265, 0.265)
            self.editor_root["frameColor"] = self.ui_palette["panel"]
            self.editor_root["frameSize"] = self.editor_frame
            self.editor_root.setPos(aspect - 0.47, 0, 0.65)
            self.editor_title.setScale(0.034)
            self.editor_title.setPos(-0.335, 0.172)
            self.editor_subtitle.setScale(0.018)
            self.editor_subtitle.setPos(-0.335, 0.128)
            self.editor_key_badge["frameSize"] = (-0.04, 0.04, -0.026, 0.026)
            self.editor_key_badge.setPos(0.315, 0, 0.175)
            self.editor_mode_label.setScale(0.026)
            self.editor_mode_label.setPos(0, -0.009)

        left, right, bottom, top = self.editor_frame
        inset = 0.026 if self.editor_expanded else 0.018
        self.editor_shadow["frameSize"] = self._expand_frame(self.editor_frame, 0.018)
        self.editor_border["frameSize"] = self._expand_frame(self.editor_frame, 0.006)
        self.editor_backdrop["frameSize"] = (left + inset, right - inset, bottom + inset, top - inset)
        header_h = 0.14 if self.editor_expanded else 0.09
        self.editor_header["frameSize"] = (left + inset, right - inset, top - header_h, top - inset)
        self.editor_vignette_top["frameSize"] = (left + inset, right - inset, top - header_h - 0.035, top - header_h)
        self.editor_vignette_bottom["frameSize"] = (left + inset, right - inset, bottom + inset, bottom + inset + 0.052)
        self._rebuild_boss_editor_grid()
        self._fit_editor_canvas()

    def _rebuild_boss_editor_grid(self):
        self.editor_grid.node().removeAllChildren()
        left, right, bottom, top = self.editor_frame
        line_color = (0.78, 0.61, 0.34, 0.13) if self.editor_expanded else (0.78, 0.61, 0.34, 0.09)
        line_count = 10 if self.editor_expanded else 5
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

    def _toggle_hero_map_fullscreen(self):
        if self.player_id != 0 or not self.hero_map_enabled:
            return
        self.hero_map_expanded = not self.hero_map_expanded
        self._apply_hero_map_layout(force=True)

    def _toggle_map_fullscreen(self):
        if self.player_id == 1:
            self._toggle_boss_editor_fullscreen()
        elif self.player_id == 0:
            self._toggle_hero_map_fullscreen()

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
        margin_x = 0.18 if self.editor_expanded else 0.055
        margin_y = 0.23 if self.editor_expanded else 0.075
        available_w = max(0.01, (right - left) - margin_x * 2)
        available_h = max(0.01, (top - bottom) - margin_y * 2)

        scale = min(available_w / content_w, available_h / content_h) * 0.97
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
        glow = getattr(self, "editor_player_glow", None)
        marker = getattr(self, "editor_player_marker", None)
        hero = getattr(self, "hero", None)
        if not self.editor_enabled or self.player_id != 1 or hero is None:
            icon.hide()
            if glow is not None:
                glow.hide()
            if marker is not None:
                marker.hide()
            return
        editor_pos = self._world_pos_to_editor_pos(hero.np.getPos(self.render))
        canvas_pos = self.editor_canvas.getPos(self.editor_root)
        root_x = canvas_pos.x + editor_pos.x * self.editor_scale
        root_z = canvas_pos.z + editor_pos.z * self.editor_scale
        base_scale = 0.062 if self.editor_expanded else 0.042
        pulse = 0.5 + 0.5 * math.sin(self._ui_pulse_time * 5.4)
        left, right, bottom, top = self.editor_frame
        edge_pad = base_scale * 1.05
        root_x = max(left + edge_pad, min(right - edge_pad, root_x))
        root_z = max(bottom + edge_pad, min(top - edge_pad, root_z))
        icon.setScale(base_scale, 1, base_scale)
        icon.setPos(root_x, 0, root_z)
        icon.show()
        if marker is not None:
            marker_size = base_scale * 0.46
            marker["frameSize"] = (-marker_size, marker_size, -marker_size, marker_size)
            marker.setPos(root_x, 0, root_z)
            marker.show()
        if glow is not None:
            glow_size = base_scale * (0.78 + pulse * 0.32)
            glow["frameSize"] = (-glow_size, glow_size, -glow_size, glow_size)
            glow["frameColor"] = (1.0, 0.72, 0.24, 0.13 + pulse * 0.11)
            glow.setPos(root_x, 0, root_z)
            glow.show()

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
        self._toggle_map_fullscreen()

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
                corridor.setColor(0.96, 0.70, 0.28, 0.72)
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
        self._update_goal_x()
        self._sync_hero_map_from_world()

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
                if self.local_mob_hp.get(mob_id, 0) > 0:
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

        # Position inside the module (e.g., center height)
        target_z = (bottom + top) * 0.5
        return Vec3(target_x, 0, target_z)

    def _should_recover_fall(self, pos: Vec3) -> bool:
        bounds = self._nearest_module_bounds(float(pos.x))
        if bounds is not None:
            left, right, bottom, top = bounds
            return float(pos.z) < bottom - FALL_RECOVERY_DEPTH or float(pos.z) > top + FALL_RECOVERY_DEPTH

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
        key_prev = f"{prev.get('name', '')} {prev.get('path', '')}".lower().replace("-", "_") if prev else ""
        if "base" in key:
            if "stair_u" in key_prev:
                return 9.6
            # if "stair_d" in key_prev:
            #     return -9.6
            return 0.0
        if "stair_u" in key and "stair_u" in key_prev:
            return 9.6
        if "stair_d" in key and "stair_u" not in key_prev:
            return -9.6
        return 0.0

    def _on_mouse1(self):
        if self._ui_consumed_click:
            self._ui_consumed_click = False
            return
        if self.boss_inventory_open:
            over_slot = self._is_mouse_over_boss_inventory_slot()
            if over_slot:
                self._start_boss_inventory_drag(over_slot)
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
        panel_color = self.ui_palette["panel"]
        panel_dark = self.ui_palette["track"]
        text_main = self.ui_palette["text"]
        text_sub = self.ui_palette["text_dim"]
        accent = self.ui_palette["gold"]

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
        self.role_label = self._make_ui_text(
            text="Connecting...",
            pos=(0.03, -0.06),
            align=TextNode.ALeft,
            scale=0.05,
            fg=text_main,
            shadow=(0, 0, 0, 0.85),
            mayChange=True,
            parent=self.left_panel,
        )
        self.objective_label = self._make_ui_text(
            text="Waiting for role assignment.",
            pos=(0.03, -0.13),
            align=TextNode.ALeft,
            scale=0.04,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.left_panel,
        )
        self.phase_label = self._make_ui_text(
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
        self.hero_label = self._make_ui_text(
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
            range=300,
            value=300,
            barColor=(0.25, 0.85, 0.45, 0.9),
            frameColor=panel_dark,
            frameSize=(0, 0.52, -0.02, 0.02),
            pos=(-0.6, 0, -0.095),
            parent=self.right_panel,
        )
        self.hero_hp_text = self._make_ui_text(
            text=f"{self.hero_max_hp}/{self.hero_max_hp}",
            pos=(0.26, -0.01),
            align=TextNode.ACenter,
            scale=0.032,
            fg=text_main,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.hero_bar,
        )
        self.boss_label = self._make_ui_text(
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
        self.boss_hp_text = self._make_ui_text(
            text=f"{BOSS_MAX_HP}/{BOSS_MAX_HP}",
            pos=(0.26, -0.01),
            align=TextNode.ACenter,
            scale=0.032,
            fg=text_main,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.boss_bar,
        )
        self.mob_count_text = self._make_ui_text(
            text=f"Summons 0/{MAX_ACTIVE_MOBS}",
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
        self.control_text = self._make_ui_text(
            text="Command --",
            pos=(-0.66, -0.04),
            align=TextNode.ALeft,
            scale=0.038,
            fg=text_sub,
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.action_panel,
        )
        self.combo_text = self._make_ui_text(
            text="Chain 0",
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
        self.attack_text = self._make_ui_text(
            text="Strike Ready",
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
        self.spawn_text = self._make_ui_text(
            text="Summon Ready",
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

        self.status_panel = self._make_fantasy_panel(
            self.ui_root,
            (-0.52, 0.52, -0.07, 0.012),
            (0, 0, 0.965),
            name="status",
            frame_color=(0.018, 0.018, 0.021, 0.72),
        )
        self.status_text = self._make_ui_text(
            text="",
            pos=(0, -0.046),
            align=TextNode.ACenter,
            scale=0.038,
            fg=self.ui_palette["text"],
            shadow=(0, 0, 0, 0.9),
            mayChange=True,
            parent=self.status_panel,
        )
        self.status_panel.hide()
        self._setup_hero_ui()
        self._setup_boss_ui()
        self._setup_boss_inventory_ui()
        self._setup_game_over_ui()

    def _setup_game_over_ui(self):
        palette = self.ui_palette
        self.game_over_root = self._make_fantasy_panel(
            self.ui_root,
            (-0.45, 0.45, -0.25, 0.25),
            (0, 0, 0),
            name="game_over"
        )
        self.game_over_root.hide()
        
        self.game_over_title = self._make_ui_text(
            text="",
            pos=(0, 0.08),
            align=TextNode.ACenter,
            scale=0.12,
            fg=palette["gold"],
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.game_over_root
        )
        
        self.restart_btn = DirectButton(
            parent=self.game_over_root,
            text="RESTART",
            scale=0.06,
            pos=(0, 0, -0.1),
            command=self._restart_game,
            relief=DGG.FLAT,
            frameColor=palette["gold_dim"],
            text_fg=palette["text"],
            text_font=self.ui_font,
            pad=(0.4, 0.2)
        )

    def _restart_game(self):
        self.winner = None
        self.game_over_root.hide()
        self.hero_hp = HERO_MAX_HP
        self.hero_max_hp = HERO_MAX_HP
        self.boss_hp = BOSS_MAX_HP
        self.boss_mana = BOSS_MAX_MANA
        self.hero_mana = 0.0
        self.hero_level = 0
        self.hero_mob_kills = 0
        self.hero_respawn_count = 0
        self.hero_death_count = 0
        self._reset_boss_phase(announce=True)
        if self.hero and self.hero_start_pos:
            self.hero.np.setPos(self.hero_start_pos)
            self.hero.node.setLinearVelocity(Vec3(0, 0, 0))
        if self.boss:
            bx = self.max_x - 5.0
            bz = self._get_spawn_z_on_base(bx, "end", 10.0)
            self.boss.np.setPos(Vec3(bx, 0, bz))
            self.boss.node.setLinearVelocity(Vec3(0, 0, 0))
        for mid in list(self.local_mobs.keys()):
            self._destroy_local_mob(mid)
        self._set_status("Game Restarted.")

    def _setup_hero_ui(self):
        palette = self.ui_palette
        self.hero_ui_root = DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, 0))
        self.hero_ui_root.setTransparency(TransparencyAttrib.MAlpha)

        self.hero_bars_root = DirectFrame(
            parent=self.hero_ui_root,
            frameColor=(0, 0, 0, 0),
            pos=(-1.55, 0, 0.88),
        )
        self.hero_bars_root.setTransparency(TransparencyAttrib.MAlpha)

        self.hero_vital_panel = self._make_fantasy_panel(
            self.hero_bars_root,
            (-0.11, 0.82, -0.230, 0.180),
            (0, 0, -0.095),
            name="hero_vital",
        )
        self.hero_title = self._make_ui_text(
            text="HERO",
            pos=(0.03, 0.112),
            align=TextNode.ALeft,
            scale=0.038,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.86),
            mayChange=True,
            parent=self.hero_vital_panel,
        )
        self.hero_power_text = self._make_ui_text(
            text="POWER 0",
            pos=(0.75, 0.11),
            align=TextNode.ARight,
            scale=0.026,
            fg=palette["gold"],
            shadow=(0, 0, 0, 0.86),
            mayChange=True,
            parent=self.hero_vital_panel,
        )

        self.hero_pv_parts = self._make_framed_bar(
            self.hero_vital_panel,
            pos=(0.08, 0, 0.052),
            width=0.64,
            height=0.046,
            label="HP",
            icon="HP",
            bar_color=palette["hp"],
            trail_color=(0.52, 0.10, 0.065, 0.78),
        )
        self.hero_pv_bar = self.hero_pv_parts["bar"]
        self.hero_pv_trail = self.hero_pv_parts["trail"]
        self.hero_pv_flash = self.hero_pv_parts["flash"]
        self.hero_pv_label = self.hero_pv_parts["label"]
        self.hero_pv_text = self.hero_pv_parts["text"]

        self.hero_pm_parts = self._make_framed_bar(
            self.hero_vital_panel,
            pos=(0.08, 0, -0.040),
            width=0.64,
            height=0.038,
            label="MANA",
            icon="MP",
            bar_color=palette["mana"],
            trail_color=palette["mana_dark"],
        )
        self.hero_pm_bar = self.hero_pm_parts["bar"]
        self.hero_pm_trail = self.hero_pm_parts["trail"]
        self.hero_pm_flash = self.hero_pm_parts["flash"]
        self.hero_pm_label = self.hero_pm_parts["label"]
        self.hero_pm_text = self.hero_pm_parts["text"]

        self.hero_endurance_parts = self._make_framed_bar(
            self.hero_vital_panel,
            pos=(0.08, 0, -0.125),
            width=0.64,
            height=0.034,
            label="POISE",
            icon="ST",
            bar_color=palette["stamina"],
            trail_color=(0.11, 0.24, 0.12, 0.84),
        )
        self.hero_endurance_bar = self.hero_endurance_parts["bar"]
        self.hero_endurance_trail = self.hero_endurance_parts["trail"]
        self.hero_endurance_flash = self.hero_endurance_parts["flash"]
        self.hero_endurance_label = self.hero_endurance_parts["label"]
        self.hero_endurance_text = self.hero_endurance_parts["text"]

        self.hero_ui_root.hide()

    def _setup_boss_ui(self):
        palette = self.ui_palette
        self.boss_ui_root = DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, 0))
        self.boss_ui_root.setTransparency(TransparencyAttrib.MAlpha)

        self.boss_control_root = DirectFrame(
            parent=self.boss_ui_root,
            frameColor=(0, 0, 0, 0),
            pos=(-1.55, 0, 0.84),
        )

        self.boss_command_panel = self._make_fantasy_panel(
            self.boss_control_root,
            (-0.13, 0.88, -0.19, 0.145),
            (0, 0, 0),
            name="boss_command",
        )
        self.boss_command_title = self._make_ui_text(
            text="COMMAND",
            pos=(0.155, 0.104),
            align=TextNode.ALeft,
            scale=0.025,
            fg=palette["text_dim"],
            shadow=(0, 0, 0, 0.86),
            mayChange=False,
            parent=self.boss_command_panel,
        )

        self.boss_control_icon_outer = self._make_ui_frame(
            self.boss_command_panel,
            palette["gold_dim"],
            (-0.096, 0.096, -0.096, 0.096),
            pos=(0, 0, -0.015),
        )
        self.boss_control_icon_outer.bind(DGG.B1PRESS, self._on_boss_control_slot_press, ["boss"])

        self.boss_control_icon_glow = self._make_ui_frame(
            parent=self.boss_control_icon_outer,
            frame_color=palette["gold_soft"],
            frame_size=(-0.088, 0.088, -0.088, 0.088),
        )
        self.boss_control_icon_inner = self._make_ui_frame(
            parent=self.boss_control_icon_outer,
            frame_color=palette["track"],
            frame_size=(-0.076, 0.076, -0.076, 0.076),
        )
        self.boss_control_icon_inner.bind(DGG.B1PRESS, self._on_boss_control_slot_press, ["boss"])
        self.boss_control_cooldown = self._make_ui_frame(
            parent=self.boss_control_icon_inner,
            frame_color=palette["cooldown"],
            frame_size=(-0.076, 0.076, -0.076, 0.076),
        )
        self.boss_control_cooldown.setBin("fixed", 80)
        self.boss_control_cooldown.hide()

        self.boss_control_icon_text = self._make_ui_text(
            text="B",
            pos=(0, -0.032),
            align=TextNode.ACenter,
            scale=0.074,
            fg=palette["gold"],
            shadow=(0, 0, 0, 0.9),
            mayChange=True,
            parent=self.boss_control_icon_inner,
        )
        self.boss_control_mob_image = OnscreenImage(
            image=MOB_ICON_PATH,
            parent=self.boss_control_icon_inner,
            pos=(0, 0, 0),
            scale=(0.059, 1, 0.059),
        )
        self.boss_control_mob_image.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_control_mob_image.hide()

        self.boss_pv_parts = self._make_framed_bar(
            self.boss_command_panel,
            pos=(0.17, 0, 0.053),
            width=0.62,
            height=0.044,
            label="VITALITY",
            icon="HP",
            bar_color=palette["hp"],
            trail_color=(0.52, 0.10, 0.065, 0.78),
        )
        self.boss_pv_bar = self.boss_pv_parts["bar"]
        self.boss_pv_trail = self.boss_pv_parts["trail"]
        self.boss_pv_flash = self.boss_pv_parts["flash"]
        self.boss_pv_label = self.boss_pv_parts["label"]
        self.boss_pv_text = self.boss_pv_parts["text"]

        self.boss_pm_parts = self._make_framed_bar(
            self.boss_command_panel,
            pos=(0.17, 0, -0.037),
            width=0.62,
            height=0.044,
            label="MANA",
            icon="MP",
            bar_color=palette["mana"],
            trail_color=palette["mana_dark"],
        )
        self.boss_pm_bar = self.boss_pm_parts["bar"]
        self.boss_pm_trail = self.boss_pm_parts["trail"]
        self.boss_pm_flash = self.boss_pm_parts["flash"]
        self.boss_pm_label = self.boss_pm_parts["label"]
        self.boss_pm_text = self.boss_pm_parts["text"]

        self.boss_control_name = self._make_ui_text(
            text="BOSS",
            pos=(0.155, -0.135),
            align=TextNode.ALeft,
            scale=0.029,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.boss_command_panel,
        )

        self.boss_spawn_text = self._make_ui_text(
            text="",
            pos=(0.79, -0.135),
            align=TextNode.ARight,
            scale=0.027,
            fg=palette["gold"],
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.boss_command_panel,
        )

        self.boss_mob_slots_root = DirectFrame(parent=self.boss_ui_root, frameColor=(0, 0, 0, 0), pos=(-0.48, 0, -0.78))
        self.boss_mob_slots_root.setTransparency(TransparencyAttrib.MAlpha)

        self.boss_mob_slots: list[dict[str, Any]] = []
        self.boss_slot_size = 0.108
        self.boss_slot_gap = 0.132
        slot_size = self.boss_slot_size
        slot_gap = self.boss_slot_gap
        rarity_cycle = ["common", "uncommon", "rare", "epic", "legendary", "rare"]
        for i in range(MAX_ACTIVE_MOBS):
            slot_root = self._make_ui_frame(
                parent=self.boss_mob_slots_root,
                frame_color=(0, 0, 0, 0),
                frame_size=(-0.012, slot_size + 0.012, -0.153, 0.027),
                pos=(i * slot_gap, 0, 0),
            )
            slot_root.bind(DGG.B1PRESS, self._on_boss_control_slot_press, [i + 1])

            slot_shadow = self._make_ui_frame(
                parent=slot_root,
                frame_color=palette["shadow"],
                frame_size=(-0.006, slot_size + 0.006, -slot_size - 0.006, 0.006),
                pos=(0.01, 0, -0.012),
            )
            slot_glow = self._make_ui_frame(
                parent=slot_root,
                frame_color=(1.0, 0.74, 0.28, 0.0),
                frame_size=(-0.01, slot_size + 0.01, -slot_size - 0.01, 0.01),
            )
            slot_frame = self._make_ui_frame(
                parent=slot_root,
                frame_color=palette["gold_dim"],
                frame_size=(0, slot_size, -slot_size, 0),
            )
            slot_frame.bind(DGG.B1PRESS, self._on_boss_control_slot_press, [i + 1])

            slot_inner = self._make_ui_frame(
                parent=slot_frame,
                frame_color=palette["track"],
                frame_size=(0.01, slot_size - 0.01, -slot_size + 0.01, -0.01),
            )
            slot_inner.bind(DGG.B1PRESS, self._on_boss_control_slot_press, [i + 1])
            slot_highlight = self._make_ui_frame(
                parent=slot_inner,
                frame_color=(1.0, 0.94, 0.70, 0.08),
                frame_size=(0.018, slot_size - 0.018, -slot_size * 0.38, -0.018),
            )
            slot_cooldown = self._make_ui_frame(
                parent=slot_inner,
                frame_color=palette["cooldown"],
                frame_size=(0.01, slot_size - 0.01, -slot_size + 0.01, -0.01),
            )
            slot_cooldown.setBin("fixed", 80)
            slot_cooldown.hide()

            slot_key_bg = self._make_ui_frame(
                parent=slot_root,
                frame_color=(0.07, 0.055, 0.036, 0.92),
                frame_size=(-0.003, 0.033, -0.032, 0.004),
                pos=(slot_size - 0.026, 0, -slot_size + 0.012),
            )
            slot_label = self._make_ui_text(
                text=str(i + 1),
                pos=(0.015, -0.022),
                align=TextNode.ACenter,
                scale=0.024,
                fg=palette["text"],
                shadow=(0, 0, 0, 0.8),
                mayChange=True,
                parent=slot_key_bg,
            )
            empty_label = self._make_ui_text(
                text="",
                pos=(slot_size * 0.5, -slot_size * 0.58),
                align=TextNode.ACenter,
                scale=0.022,
                fg=palette["text_muted"],
                shadow=(0, 0, 0, 0.78),
                mayChange=True,
                parent=slot_inner,
            )
            slot_image = OnscreenImage(
                image=MOB_ICON_PATH,
                parent=slot_inner,
                pos=(slot_size * 0.5, 0, -slot_size * 0.5),
                scale=(0.044, 1, 0.044),
            )
            slot_image.setTransparency(TransparencyAttrib.MAlpha)
            slot_image.hide()

            hp_back = self._make_ui_frame(
                parent=slot_root,
                frame_color=palette["track"],
                frame_size=(0, slot_size, -0.018, 0),
                pos=(0, 0, -slot_size - 0.024),
            )
            hp_trail = DirectWaitBar(
                parent=hp_back,
                text="",
                range=MOB_MAX_HP,
                value=0,
                frameColor=(0, 0, 0, 0),
                barColor=(0.38, 0.08, 0.055, 0.72),
                frameSize=(0, slot_size, -0.018, 0),
                pos=(0, 0, 0),
            )
            hp_trail.setTransparency(TransparencyAttrib.MAlpha)
            hp_bar = DirectWaitBar(
                parent=hp_back,
                text="",
                range=MOB_MAX_HP,
                value=0,
                frameColor=(0, 0, 0, 0),
                barColor=(0.24, 0.76, 0.38, 0.94),
                frameSize=(0, slot_size, -0.018, 0),
                pos=(0, 0, 0),
            )
            hp_bar.setTransparency(TransparencyAttrib.MAlpha)

            self.boss_mob_slots.append(
                {
                    "root": slot_root,
                    "shadow": slot_shadow,
                    "glow": slot_glow,
                    "frame": slot_frame,
                    "inner": slot_inner,
                    "highlight": slot_highlight,
                    "cooldown": slot_cooldown,
                    "key_bg": slot_key_bg,
                    "label": slot_label,
                    "empty_label": empty_label,
                    "image": slot_image,
                    "hp_trail": hp_trail,
                    "hp_bar": hp_bar,
                    "rarity": rarity_cycle[i % len(rarity_cycle)],
                    "slot_size": slot_size,
                }
            )

        self.boss_ui_root.hide()

    def _setup_boss_inventory_ui(self):
        palette = self.ui_palette
        self.boss_inventory_root = self._make_fantasy_panel(
            self.aspect2d,
            (-0.48, 0.48, -0.18, 0.18),
            (0, 0, -0.56),
            name="boss_inventory",
        )

        self.boss_inventory_title = self._make_ui_text(
            text="ARSENAL",
            pos=(-0.40, 0.105),
            align=TextNode.ALeft,
            scale=0.038,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.85),
            mayChange=False,
            parent=self.boss_inventory_root,
        )
        self.boss_inventory_hint = self._make_ui_text(
            text="SUMMON SHADE",
            pos=(-0.40, 0.055),
            align=TextNode.ALeft,
            scale=0.025,
            fg=palette["text_dim"],
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.boss_inventory_root,
        )

        self.boss_inventory_shade_slot = self._make_ui_frame(
            parent=self.boss_inventory_root,
            frame_color=self.ui_rarity_colors["legendary"],
            frame_size=(-0.078, 0.078, -0.078, 0.078),
            pos=(0.10, 0, 0.005),
        )
        self.boss_inventory_shade_slot.bind(DGG.B1PRESS, self._on_boss_inventory_slot_press, ["shade"])

        self.boss_inventory_shade_glow = self._make_ui_frame(
            parent=self.boss_inventory_shade_slot,
            frame_color=palette["gold_soft"],
            frame_size=(-0.09, 0.09, -0.09, 0.09),
        )
        self.boss_inventory_shade_inner = self._make_ui_frame(
            parent=self.boss_inventory_shade_slot,
            frame_color=palette["track"],
            frame_size=(-0.062, 0.062, -0.062, 0.062),
        )
        self.boss_inventory_shade_inner.bind(DGG.B1PRESS, self._on_boss_inventory_slot_press, ["shade"])
        self.boss_inventory_shade_icon = OnscreenImage(
            image=MOB_ICON_PATH,
            parent=self.boss_inventory_shade_inner,
            pos=(0, 0, 0),
            scale=(0.058, 1, 0.058),
        )
        self.boss_inventory_shade_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_inventory_shade_cooldown = self._make_ui_frame(
            parent=self.boss_inventory_shade_inner,
            frame_color=palette["cooldown"],
            frame_size=(-0.062, 0.062, -0.062, 0.062),
        )
        self.boss_inventory_shade_cooldown.setBin("fixed", 80)
        self.boss_inventory_shade_cooldown.hide()
        
        self.boss_inventory_kayou_slot = self._make_ui_frame(
            parent=self.boss_inventory_root,
            frame_color=self.ui_rarity_colors["epic"],
            frame_size=(-0.078, 0.078, -0.078, 0.078),
            pos=(0.30, 0, 0.005),
        )
        self.boss_inventory_kayou_slot.bind(DGG.B1PRESS, self._on_boss_inventory_slot_press, ["kayou"])

        self.boss_inventory_kayou_glow = self._make_ui_frame(
            parent=self.boss_inventory_kayou_slot,
            frame_color=palette["gold_soft"],
            frame_size=(-0.09, 0.09, -0.09, 0.09),
        )
        self.boss_inventory_kayou_inner = self._make_ui_frame(
            parent=self.boss_inventory_kayou_slot,
            frame_color=palette["track"],
            frame_size=(-0.062, 0.062, -0.062, 0.062),
        )
        self.boss_inventory_kayou_inner.bind(DGG.B1PRESS, self._on_boss_inventory_slot_press, ["kayou"])
        self.boss_inventory_kayou_icon = OnscreenImage(
            image=KAYOU_ICON_PATH,
            parent=self.boss_inventory_kayou_inner,
            pos=(0, 0, 0),
            scale=(0.058, 1, 0.058),
        )
        self.boss_inventory_kayou_icon.setTransparency(TransparencyAttrib.MAlpha)
        self.boss_inventory_kayou_cooldown = self._make_ui_frame(
            parent=self.boss_inventory_kayou_inner,
            frame_color=palette["cooldown"],
            frame_size=(-0.062, 0.062, -0.062, 0.062),
        )
        self.boss_inventory_kayou_cooldown.setBin("fixed", 80)
        self.boss_inventory_kayou_cooldown.hide()

        self.boss_inventory_mob_count = self._make_ui_text(
            text="",
            pos=(0.20, -0.11),
            align=TextNode.ACenter,
            scale=0.026,
            fg=palette["text"],
            shadow=(0, 0, 0, 0.8),
            mayChange=True,
            parent=self.boss_inventory_root,
        )
        self.boss_inventory_cost_text = self._make_ui_text(
            text="",
            pos=(0.20, 0.105),
            align=TextNode.ACenter,
            scale=0.023,
            fg=palette["gold"],
            shadow=(0, 0, 0, 0.82),
            mayChange=True,
            parent=self.boss_inventory_root,
        )

        self.boss_inventory_drag_icon = OnscreenImage(
            image=MOB_ICON_PATH,
            parent=self.aspect2d,
            pos=(0, 0, 0),
            scale=(0.072, 1, 0.072),
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
        self._set_status("Arsenal opened.")

    def _close_boss_inventory(self):
        self.boss_inventory_open = False
        self.boss_inventory_dragging = None
        self.boss_inventory_drag_icon.hide()
        for key in self.free_camera_keys:
            self.free_camera_keys[key] = False
        if self.player_id == 1:
            self._set_controlled_entity(self.boss_inventory_previous_control)
        self.camera_follow_x = self.camera.getX()

    def _on_boss_inventory_slot_press(self, mob_type: str, _event=None):
        self._ui_consumed_click = True
        if not self.boss_inventory_open or self.player_id != 1:
            return
        self._start_boss_inventory_drag(mob_type)

    def _start_boss_inventory_drag(self, mob_type: str):
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            self._set_status(f"Summon limit reached ({MAX_ACTIVE_MOBS}).")
            return
        
        mana_cost = KAYOU_DROP_MANA_COST if mob_type == "kayou" else MOB_DROP_MANA_COST
        cooldown = KAYOU_DROP_COOLDOWN if mob_type == "kayou" else MOB_DROP_COOLDOWN
        
        drop_left = self._boss_action_left(f"drop_{mob_type}", cooldown)
        if drop_left > 0.0:
            self._set_status(f"Summon recharging ({drop_left:.1f}s).")
            return
        if self.boss_mana + 1e-5 < mana_cost:
            self._set_status(f"Need {int(mana_cost)} MP to summon.")
            return
            
        self.boss_inventory_dragging = mob_type
        icon_path = KAYOU_ICON_PATH if mob_type == "kayou" else MOB_ICON_PATH
        self.boss_inventory_drag_icon.setImage(icon_path)
        self.boss_inventory_drag_icon.setTransparency(TransparencyAttrib.MAlpha)
        self._update_boss_inventory_drag_icon()

    def _is_mouse_over_boss_inventory_slot(self) -> str | None:
        if not self.boss_inventory_open:
            return None
        if self._is_mouse_over_widget(self.boss_inventory_shade_slot):
            return "shade"
        if self._is_mouse_over_widget(self.boss_inventory_kayou_slot):
            return "kayou"
        return None

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
        if self.boss_inventory_dragging is None:
            return
            
        mob_type = self.boss_inventory_dragging
        self.boss_inventory_dragging = None
        self.boss_inventory_drag_icon.hide()
        
        if self._is_mouse_over_boss_inventory():
            return
            
        pos = self._get_mob_drop_position_from_mouse()
        if pos is None:
            self._set_status("Summon on the dungeon floor.")
            return
            
        mana_cost = KAYOU_DROP_MANA_COST if mob_type == "kayou" else MOB_DROP_MANA_COST
        cooldown = KAYOU_DROP_COOLDOWN if mob_type == "kayou" else MOB_DROP_COOLDOWN
        label = "Summon Kayou" if mob_type == "kayou" else "Summon shade"
        
        if not self._try_spend_boss_action(f"drop_{mob_type}", mana_cost, cooldown, label):
            return
            
        self._spawn_local_mob_at(pos, mob_type=mob_type, status_label=label)

    def _on_boss_control_slot_press(self, entity: str | int, _event=None):
        self._ui_consumed_click = True
        if self.player_id != 1 or self.winner:
            return
        if entity == "boss":
            self._set_controlled_entity("boss")
            self._set_status("Commanding boss.")
            return
        if not isinstance(entity, int):
            return

        mob_ids = sorted(self.local_mobs.keys())
        slot = entity
        if slot < 1 or slot > len(mob_ids):
            self._set_status(f"Slot {slot} is empty.")
            return
        mob_id = mob_ids[slot - 1]
        self._set_controlled_entity(mob_id)
        self._set_status(f"Commanding {self._control_label(mob_id)}.")

    def _get_controlled_boss_ui_state(self) -> tuple[str, str, int, int]:
        if self.controlled_entity == "boss":
            return "BOSS", "B", max(0, min(self.boss_hp, BOSS_MAX_HP)), BOSS_MAX_HP
        if isinstance(self.controlled_entity, int) and self.controlled_entity in self.local_mobs:
            mob = self.local_mobs[self.controlled_entity]
            max_hp = KAYOU_MAX_HP if isinstance(mob, Kayou) else MOB_MAX_HP
            slot = self._get_mob_slot(self.controlled_entity)
            icon = str(slot) if slot is not None else "M"
            hp = max(0, min(self.local_mob_hp.get(self.controlled_entity, max_hp), max_hp))
            name = "KAYOU" if isinstance(mob, Kayou) else "SHADE"
            return f"{name} {slot}", icon, hp, max_hp
        return "BOSS", "B", max(0, min(self.boss_hp, BOSS_MAX_HP)), BOSS_MAX_HP

    def _update_boss_ui(self, now: float, attack_cd: float, attack_left: float):
        palette = self.ui_palette
        name, icon, hp, max_hp = self._get_controlled_boss_ui_state()
        hp_ratio = 0.0 if max_hp <= 0 else hp / max_hp
        pm_ratio = 0.0 if BOSS_MAX_MANA <= 0 else self.boss_mana / BOSS_MAX_MANA

        is_controlled_mob = icon not in ("B", "boss")
        self._set_visible("boss_control_mob_image", self.boss_control_mob_image, is_controlled_mob)
        self._set_visible("boss_control_icon_text", self.boss_control_icon_text, not is_controlled_mob)
        if not is_controlled_mob:
            self._set_text_if_changed("boss_control_icon_text", self.boss_control_icon_text, icon)
        self._set_text_if_changed("boss_control_name", self.boss_control_name, f"COMMAND {name}")
        self._set_animated_bar_value(
            "boss_ui_pv_value",
            self.boss_pv_bar,
            max(0.0, min(1.0, hp_ratio)),
            trail_widget=self.boss_pv_trail,
            flash_widget=self.boss_pv_flash,
        )
        self._set_animated_bar_value(
            "boss_ui_pm_value",
            self.boss_pm_bar,
            max(0.0, min(1.0, pm_ratio)),
            trail_widget=self.boss_pm_trail,
            flash_widget=self.boss_pm_flash,
            speed=10.0,
            trail_speed=7.0,
        )
        self._set_text_if_changed("boss_ui_pv_text", self.boss_pv_text, f"{hp}/{max_hp}")
        self._set_text_if_changed("boss_ui_pm_text", self.boss_pm_text, f"{int(self.boss_mana)}/{int(BOSS_MAX_MANA)}")

        pulse = 0.5 + 0.5 * math.sin(self._ui_pulse_time * 4.8)
        icon_hovered = self._is_mouse_over_widget(self.boss_control_icon_outer)
        icon_glow_alpha = 0.12 + pulse * 0.12 if self.controlled_entity == "boss" else 0.04
        if icon_hovered:
            icon_glow_alpha = max(icon_glow_alpha, 0.28)
        self.boss_control_icon_glow["frameColor"] = (1.0, 0.72, 0.28, icon_glow_alpha)
        if self.controlled_entity == "boss" and attack_cd > 0.0 and attack_left > 0.001:
            ratio = max(0.0, min(1.0, attack_left / attack_cd))
            self.boss_control_cooldown["frameSize"] = (-0.076, 0.076, -0.076, -0.076 + 0.152 * ratio)
            self.boss_control_cooldown.show()
        else:
            self.boss_control_cooldown.hide()

        spawn_left = self._boss_action_left("spawn", SPAWN_COOLDOWN, now)
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            spawn_text = f"SUMMONS FULL {len(self.local_mobs)}/{MAX_ACTIVE_MOBS}"
        elif self.boss_mana + 1e-5 < MOB_SPAWN_MANA_COST:
            spawn_text = f"SUMMON {int(MOB_SPAWN_MANA_COST)} MP"
        elif spawn_left <= 0.001:
            spawn_text = f"SUMMON READY {int(MOB_SPAWN_MANA_COST)} MP"
        else:
            spawn_text = f"SUMMON {spawn_left:.1f}S {int(MOB_SPAWN_MANA_COST)} MP"
        self._set_text_if_changed("boss_spawn_text", self.boss_spawn_text, spawn_text)

        mob_ids = sorted(self.local_mobs.keys())
        for index, slot in enumerate(self.boss_mob_slots):
            mob_id = mob_ids[index] if index < len(mob_ids) else None
            is_filled = mob_id is not None
            is_controlled = is_filled and self.controlled_entity == mob_id
            is_hovered = self._is_mouse_over_widget(slot["root"])
            rarity_color = self.ui_rarity_colors.get(slot.get("rarity", "common"), self.ui_rarity_colors["common"])

            if is_controlled:
                frame_color = palette["gold"]
                inner_color = (0.10, 0.095, 0.065, 0.96)
                glow_alpha = 0.22 + pulse * 0.18
            elif is_hovered:
                frame_color = (0.88, 0.66, 0.32, 0.95)
                inner_color = (0.055, 0.052, 0.044, 0.96)
                glow_alpha = 0.20
            elif is_filled:
                frame_color = rarity_color
                inner_color = (0.035, 0.038, 0.041, 0.94)
                glow_alpha = 0.06
            else:
                frame_color = (0.34, 0.29, 0.22, 0.62)
                inner_color = (0.018, 0.020, 0.024, 0.88)
                glow_alpha = 0.0
            key_color = palette["text"] if is_filled or is_hovered else palette["text_muted"]

            slot["frame"]["frameColor"] = frame_color
            slot["inner"]["frameColor"] = inner_color
            slot["glow"]["frameColor"] = (1.0, 0.72, 0.28, glow_alpha)
            slot["key_bg"]["frameColor"] = (0.12, 0.085, 0.045, 0.96 if is_filled or is_hovered else 0.72)
            slot["label"].setFg(key_color)
            self._set_visible(f"boss_mob_slot_image_visible_{index}", slot["image"], is_filled)
            self._set_visible(f"boss_mob_slot_empty_label_visible_{index}", slot["empty_label"], not is_filled)
            slot["image"].setColor(1, 1, 1, 0.98 if is_filled else 0.0)

            if is_filled:
                mob_instance = self.local_mobs[mob_id]
                max_hp_mob = KAYOU_MAX_HP if isinstance(mob_instance, Kayou) else MOB_MAX_HP
                hp_value = max(0, min(self.local_mob_hp.get(mob_id, max_hp_mob), max_hp_mob))
                if isinstance(mob_instance, Kayou):
                    slot["image"].setImage(KAYOU_ICON_PATH)
                else:
                    slot["image"].setImage(MOB_ICON_PATH)
                slot["image"].setTransparency(TransparencyAttrib.MAlpha)
            else:
                max_hp_mob = MOB_MAX_HP
                hp_value = 0
                self._set_text_if_changed(f"boss_mob_slot_label_{index}", slot["label"], str(index + 1))
            
            self._set_widget_number_if_changed(f"boss_mob_slot_trail_range_{index}", slot["hp_trail"], "range", max_hp_mob)
            self._set_widget_number_if_changed(f"boss_mob_slot_range_{index}", slot["hp_bar"], "range", max_hp_mob)
            self._set_animated_bar_value(
                f"boss_mob_slot_hp_value_{index}",
                slot["hp_bar"],
                hp_value,
                trail_widget=slot["hp_trail"],
                speed=16.0,
                trail_speed=5.0,
            )

            if is_controlled and attack_cd > 0.0 and attack_left > 0.001:
                ratio = max(0.0, min(1.0, attack_left / attack_cd))
                size = float(slot["slot_size"])
                inset = 0.01
                slot["cooldown"]["frameSize"] = (inset, size - inset, -size + inset, -size + inset + (size - inset * 2.0) * ratio)
                slot["cooldown"].show()
            else:
                slot["cooldown"].hide()

        # Update Arsenal (Inventory) Slots
        inventory_full = len(self.local_mobs) >= MAX_ACTIVE_MOBS
        inventory_pulse = 0.5 + 0.5 * math.sin(self._ui_pulse_time * 5.2)
        
        # Shade inventory slot
        shade_drop_left = self._boss_action_left("drop_shade", MOB_DROP_COOLDOWN, now)
        shade_hovered = self._is_mouse_over_widget(self.boss_inventory_shade_slot)
        shade_low_mana = self.boss_mana + 1e-5 < MOB_DROP_MANA_COST
        shade_ready = not inventory_full and not shade_low_mana and shade_drop_left <= 0.001
        
        if shade_ready:
            inv_border = self.ui_rarity_colors["legendary"]
            inv_glow = 0.18 + inventory_pulse * 0.16
        elif inventory_full:
            inv_border = (0.35, 0.30, 0.24, 0.68)
            inv_glow = 0.02
        elif shade_low_mana:
            inv_border = (0.34, 0.38, 0.56, 0.72)
            inv_glow = 0.04
        else:
            inv_border = (0.54, 0.39, 0.22, 0.82)
            inv_glow = 0.06
            
        if shade_hovered:
            inv_glow = max(inv_glow, 0.28)
            self._set_text_if_changed("boss_inventory_hint", self.boss_inventory_hint, "SUMMON SHADE")
            
        self.boss_inventory_shade_slot["frameColor"] = inv_border
        self.boss_inventory_shade_glow["frameColor"] = (1.0, 0.72, 0.28, inv_glow)
        
        if shade_drop_left > 0.001:
            ratio = max(0.0, min(1.0, shade_drop_left / MOB_DROP_COOLDOWN))
            self.boss_inventory_shade_cooldown["frameSize"] = (-0.062, 0.062, -0.062, -0.062 + 0.124 * ratio)
            self.boss_inventory_shade_cooldown.show()
        else:
            self.boss_inventory_shade_cooldown.hide()
            
        # Kayou inventory slot
        kayou_drop_left = self._boss_action_left("drop_kayou", KAYOU_DROP_COOLDOWN, now)
        kayou_hovered = self._is_mouse_over_widget(self.boss_inventory_kayou_slot)
        kayou_low_mana = self.boss_mana + 1e-5 < KAYOU_DROP_MANA_COST
        kayou_ready = not inventory_full and not kayou_low_mana and kayou_drop_left <= 0.001
        
        if kayou_ready:
            inv_border = self.ui_rarity_colors["epic"]
            inv_glow = 0.18 + inventory_pulse * 0.16
        elif inventory_full:
            inv_border = (0.35, 0.30, 0.24, 0.68)
            inv_glow = 0.02
        elif kayou_low_mana:
            inv_border = (0.34, 0.38, 0.56, 0.72)
            inv_glow = 0.04
        else:
            inv_border = (0.54, 0.39, 0.22, 0.82)
            inv_glow = 0.06
            
        if kayou_hovered:
            inv_glow = max(inv_glow, 0.28)
            self._set_text_if_changed("boss_inventory_hint", self.boss_inventory_hint, "SUMMON KAYOU")
            
        self.boss_inventory_kayou_slot["frameColor"] = inv_border
        self.boss_inventory_kayou_glow["frameColor"] = (1.0, 0.72, 0.28, inv_glow)
        
        if kayou_drop_left > 0.001:
            ratio = max(0.0, min(1.0, kayou_drop_left / KAYOU_DROP_COOLDOWN))
            self.boss_inventory_kayou_cooldown["frameSize"] = (-0.062, 0.062, -0.062, -0.062 + 0.124 * ratio)
            self.boss_inventory_kayou_cooldown.show()
        else:
            self.boss_inventory_kayou_cooldown.hide()

        if not shade_hovered and not kayou_hovered:
            inv_hint = "ARSENAL READY" if not inventory_full else "SUMMONS FULL"
            self._set_text_if_changed("boss_inventory_hint", self.boss_inventory_hint, inv_hint)

        self._set_text_if_changed("boss_inventory_mob_count", self.boss_inventory_mob_count, f"{len(self.local_mobs)}/{MAX_ACTIVE_MOBS}")
        
        current_cost = KAYOU_DROP_MANA_COST if kayou_hovered else MOB_DROP_MANA_COST
        self._set_text_if_changed("boss_inventory_cost_text", self.boss_inventory_cost_text, f"{int(current_cost)} MP")

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
            widget.setAlphaScale(0.0)
            self._ui_fade_state[key] = {"widget": widget, "value": 0.0, "target": 1.0}
        else:
            widget.hide()
            self._ui_fade_state.pop(key, None)
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
        self._update_role_ui_layout()

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
        if self.hero_map_enabled:
            self._apply_hero_map_layout()
        show_editor_root = is_boss and self.editor_enabled
        editor_fullscreen = show_editor_root and self.editor_expanded
        hero_map_fullscreen = is_hero and self.hero_map_enabled and self.hero_map_expanded
        show_boss_ui = is_boss and not editor_fullscreen

        self._set_visible("hero_ui_root", self.hero_ui_root, is_hero and not hero_map_fullscreen)
        self._set_visible("hero_map_root", self.hero_map_root, is_hero and self.hero_map_enabled)
        self._set_visible("boss_ui_root", self.boss_ui_root, show_boss_ui)
        self._set_visible("boss_inventory_root", self.boss_inventory_root, is_boss and self.boss_inventory_open)
        self._set_visible("left_panel", self.left_panel, (not is_hero) and (not is_boss) and (not editor_fullscreen) and (not hero_map_fullscreen))
        self._set_visible("right_panel", self.right_panel, (not is_hero) and (not is_boss) and (not editor_fullscreen) and (not hero_map_fullscreen))
        self._set_visible("action_panel", self.action_panel, (not is_hero) and (not is_boss) and (not editor_fullscreen) and (not hero_map_fullscreen))
        self._set_visible("editor_root", self.editor_root, show_editor_root)
        if is_boss and self.editor_enabled and not self.editor_expanded:
            self.right_panel.setZ(0.44)
        else:
            self.right_panel.setZ(0.93)
        if show_editor_root:
            self._set_text_if_changed("editor_title", self.editor_title, "WAR TABLE" if self.editor_expanded else "DUNGEON")
            self._set_text_if_changed("editor_subtitle", self.editor_subtitle, "TACTICAL MAP" if self.editor_expanded else "WAR TABLE")

        self._set_text_if_changed("role_label", self.role_label, f"ROLE {role}")
        self._set_text_if_changed("control_text", self.control_text, f"COMMAND {control}")

        if self.winner:
            objective = "Game over."
        elif is_hero:
            if self.boss_phase_unlocked:
                objective = "Defeat the boss."
            elif not self._hero_is_boss_ready():
                left = max(0, BOSS_READY_HERO_LEVEL - self.hero_level)
                objective = f"Hunt mobs, gain power ({left} kills to boss-ready)."
            else:
                objective = f"Reach the end, then defeat the boss."
        elif is_boss:
            objective = f"Break the hero before power {BOSS_READY_HERO_LEVEL}."
        else:
            objective = "Waiting for role assignment."
        self._set_text_if_changed("objective_label", self.objective_label, objective)

        if self.winner:
            phase_text = f"{self.winner.title()} wins!"
        elif self.boss_phase_unlocked:
            phase_text = "Phase 2: boss vulnerable"
        elif self._hero_is_boss_ready():
            phase_text = f"Hero power {self.hero_level}: boss gate open"
        elif self.player_id in (0, 1):
            phase_text = f"Hero power {self.hero_level}: damage {self._get_hero_damage()}"
        else:
            phase_text = ""
        self._set_text_if_changed("phase_label", self.phase_label, phase_text)

        hero_hp = max(0, min(self.hero_hp, self.hero_max_hp))
        boss_hp = max(0, min(self.boss_hp, BOSS_MAX_HP))
        self._set_widget_number_if_changed("hero_bar_range", self.hero_bar, "range", self.hero_max_hp)
        self._set_widget_number_if_changed("hero_bar_value", self.hero_bar, "value", hero_hp)
        self._set_text_if_changed("hero_hp_text", self.hero_hp_text, f"{hero_hp}/{self.hero_max_hp}")
        self._set_widget_number_if_changed("boss_bar_range", self.boss_bar, "range", BOSS_MAX_HP)
        self._set_widget_number_if_changed("boss_bar_value", self.boss_bar, "value", boss_hp)
        self._set_text_if_changed("boss_hp_text", self.boss_hp_text, f"{boss_hp}/{BOSS_MAX_HP}")

        mob_count = len(self.local_mobs) if is_boss else len(self.remote_mobs)
        self._set_text_if_changed("mob_count_text", self.mob_count_text, f"Summons {mob_count}/{MAX_ACTIVE_MOBS}")

        attack_cd = self._get_current_attack_cooldown()
        cd_key = self._get_attack_cooldown_key()
        attack_left = max(0.0, attack_cd - (now - self.last_attack_times[cd_key]))
        combo_step = self.combo_state[cd_key]["step"] + 1 if self.combo_state[cd_key]["step"] >= 0 else 0
        if is_hero:
            self._set_text_if_changed("combo_text", self.combo_text, f"Power {self.hero_level} DMG {self._get_hero_damage()}")
        else:
            self._set_text_if_changed("combo_text", self.combo_text, f"Chain {combo_step}")

        self._set_widget_number_if_changed("attack_bar_range", self.attack_bar, "range", max(0.001, attack_cd))
        self._set_widget_number_if_changed("attack_bar_value", self.attack_bar, "value", max(0.0, attack_cd - attack_left))
        if attack_left <= 0.001:
            self._set_text_if_changed("attack_text", self.attack_text, "Strike Ready")
        else:
            self._set_text_if_changed("attack_text", self.attack_text, f"Strike {attack_left:.2f}s")

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
                    f"Summon Ready {int(MOB_SPAWN_MANA_COST)} MP ({len(self.local_mobs)}/{MAX_ACTIVE_MOBS})",
                )
            else:
                self._set_text_if_changed(
                    "spawn_text",
                    self.spawn_text,
                    f"Summon {spawn_left:.2f}s {int(MOB_SPAWN_MANA_COST)} MP ({len(self.local_mobs)}/{MAX_ACTIVE_MOBS})",
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
            self._set_animated_bar_value(
                "hero_pv_value",
                self.hero_pv_bar,
                max(0.0, min(1.0, pv_ratio)),
                trail_widget=self.hero_pv_trail,
                flash_widget=self.hero_pv_flash,
            )
            self._set_text_if_changed("hero_pv_text", self.hero_pv_text, f"{hero_hp}/{HERO_MAX_HP}")

            pm_ratio = self.hero_mana / HERO_MAX_MANA
            self._set_animated_bar_value(
                "hero_pm_value",
                self.hero_pm_bar,
                max(0.0, min(1.0, pm_ratio)),
                trail_widget=self.hero_pm_trail,
                flash_widget=self.hero_pm_flash,
                speed=13.0,
                trail_speed=8.0,
            )
            pm_text = f"{int(self.hero_mana)}/{int(HERO_MAX_MANA)}"
            self._set_text_if_changed("hero_pm_text", self.hero_pm_text, pm_text)

            end_ratio = 1.0
            state = self.combo_state.get(self._get_attack_cooldown_key(), {"step": -1, "last_time": 0.0})
            if state.get("step", -1) >= 0:
                elapsed = max(0.0, now - float(state.get("last_time", now)))
                end_ratio = max(0.0, 1.0 - (elapsed / COMBO_WINDOW))
            self._set_animated_bar_value(
                "hero_endurance_value",
                self.hero_endurance_bar,
                max(0.0, min(1.0, end_ratio)),
                trail_widget=self.hero_endurance_trail,
                flash_widget=self.hero_endurance_flash,
                speed=12.0,
                trail_speed=6.0,
            )
            chain_text = f"Chain {combo_step}" if combo_step > 0 else "Calm"
            self._set_text_if_changed("hero_endurance_text", self.hero_endurance_text, chain_text)
            self._set_text_if_changed("hero_power_text", self.hero_power_text, f"POWER {self.hero_level}")

    def _init_entities_for_role(self):
        if self.hero and self.boss:
            return

        hero_x = self.min_x + 2.0
        boss_x = self.max_x - 5.0
        hero_start = Vec3(hero_x, 0, self._get_spawn_z_on_base(hero_x, "start", 10.0))
        boss_start = Vec3(boss_x, 0, self._get_spawn_z_on_base(boss_x, "end", 10.0))

        if not self.hero:
            self.hero = Character(self.game_config, self.render, self.loader, self.physics, start_pos=hero_start)
            self.hero_start_pos = hero_start
        if self.player_id == 0:
            self._ensure_boss(boss_start, "REMOTE")
            self.controlled_entity = "hero"
            self._set_status("Hero awakened.")
        else:
            self._ensure_boss(boss_start, "PLAYER")
            self.controlled_entity = "boss"
            self._set_status("Boss awakened.")

        self._update_hud()

    def _update_goal_x(self):
        if self.world and getattr(self.world, "module_meta", []):
            last_idx = len(self.world.module_meta) - 1
            meta = self.world.module_meta[last_idx]
            node = getattr(self.world, "module_nodes", [])[last_idx]
            center_offset = float(meta.get("center_offset", 0.0))
            width = float(meta.get("width", 0.0))
            center_x = float(node.getX()) + center_offset
            self.goal_x = center_x - width * 0.5
        else:
            self.goal_x = self.max_x - 2.0

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

    def _get_hero_damage(self, combo_multiplier: float = 1.0) -> int:
        base_damage = HERO_DAMAGE + self.hero_level * HERO_DAMAGE_PER_LEVEL
        return max(1, int(base_damage * combo_multiplier))

    def _hero_is_boss_ready(self) -> bool:
        return self._get_hero_damage() >= MOB_MAX_HP or self.hero_level >= BOSS_READY_HERO_LEVEL

    def _apply_hero_mob_kill_reward(self, kills: int = 1, announce: bool = True, is_kayou: bool = False):
        kills = max(1, int(kills))
        self.hero_mob_kills += kills
        self.hero_level += (kills * 2) if is_kayou else kills
        if self.player_id == 0:
            self.hero_hp = min(HERO_MAX_HP, self.hero_hp + HERO_HEAL_PER_MOB_KILL * (2 if is_kayou else 1) * kills)
            mana_reward = HERO_MANA_PER_MOB_KILL * (2.5 if is_kayou else 1.0) * kills
            self.hero_mana = min(HERO_MAX_MANA, self.hero_mana + mana_reward)
        if announce:
            damage = self._get_hero_damage()
            reward_type = "Kayou" if is_kayou else "shade"
            if self._hero_is_boss_ready():
                self._set_status(f"Power {self.hero_level}: mobs fall in one hit. Reach the boss.")
            else:
                left = max(0, BOSS_READY_HERO_LEVEL - self.hero_level)
                self._set_status(f"Defeated {reward_type}! Level {self.hero_level}. {left} kills until boss-ready.")

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
            self._set_status(f"{label} recharging ({left:.1f}s).")
            return False
        if self.boss_mana + 1e-5 < mana_cost:
            self._set_status(f"Need {int(mana_cost)} MP for {label}.")
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
        is_big: bool = False,
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
            "is_big": is_big,
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
            self.hero_level = max(self.hero_level, int(payload.get("hero_level", self.hero_level)))
            self.hero_mob_kills = max(self.hero_mob_kills, int(payload.get("hero_mob_kills", self.hero_mob_kills)))
            if bool(payload.get("unlocked", False)):
                self._unlock_boss_phase(announce=False)
            else:
                self._reset_boss_phase(announce=False)
        elif payload_type == "hero_progress":
            self._apply_remote_hero_progress(payload)
        elif payload_type == "game_over":
            winner = payload.get("winner")
            if winner in ("hero", "boss"):
                self._declare_winner(winner, announce=False)
        elif payload_type == "hero_respawn":
            self._apply_remote_hero_respawn(payload)

    def _apply_remote_hero_respawn(self, payload: dict[str, Any]):
        """Handle hero respawn notification from network."""
        self.hero_respawn_count = max(self.hero_respawn_count, int(payload.get("respawn_count", self.hero_respawn_count)))
        self.hero_level = max(self.hero_level, int(payload.get("hero_level", self.hero_level)))
        self.hero_mob_kills = max(self.hero_mob_kills, int(payload.get("hero_mob_kills", self.hero_mob_kills)))
        self.hero_hp = int(payload.get("hero_hp", self.hero_hp))

    def _apply_remote_hero_progress(self, payload: dict[str, Any]):
        level = payload.get("level")
        kills = payload.get("kills")
        try:
            level_value = int(level)
            kills_value = int(kills)
        except (TypeError, ValueError):
            return
        if level_value <= self.hero_level and kills_value <= self.hero_mob_kills:
            return
        gained = max(1, level_value - self.hero_level)
        self.hero_level = max(self.hero_level, level_value - gained)
        self.hero_mob_kills = max(self.hero_mob_kills, kills_value - gained)
        self._apply_hero_mob_kill_reward(gained, announce=True)

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
                bool(hero.get("is_big", False)),
            )

        self.hero_hp = int(payload.get("hero_hp", self.hero_hp))
        self.hero_level = max(self.hero_level, int(payload.get("hero_level", self.hero_level)))
        self.hero_mob_kills = max(self.hero_mob_kills, int(payload.get("hero_mob_kills", self.hero_mob_kills)))
        if bool(payload.get("boss_phase_unlocked", False)):
            self._unlock_boss_phase(announce=False)
        else:
            self._reset_boss_phase(announce=False)

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
        else:
            self._reset_boss_phase(announce=False)

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
        self._update_goal_x()
        self._sync_hero_map_from_world()

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
            mob_type = data.get("type", "shade")

            if mob_id not in self.remote_mobs:
                if mob_type == "kayou":
                    self.remote_mobs[mob_id] = Kayou(
                        self.game_config,
                        self.render,
                        self.loader,
                        self.physics,
                        start_pos=Vec3(x, 0, z),
                        mode="REMOTE",
                    )
                else:
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
                    "is_big": bool(hero_anim.get("is_big", False)),
                },
                "hero_hp": self.hero_hp,
                "hero_level": self.hero_level,
                "hero_mob_kills": self.hero_mob_kills,
                "hero_damage": self._get_hero_damage(),
                "boss_phase_unlocked": self.boss_phase_unlocked,
            }

        boss_anim = self.boss.get_network_anim_state()
        mobs_payload = []
        for mob_id, mob in self.local_mobs.items():
            anim = mob.get_network_anim_state()
            mobs_payload.append(
                {
                    "id": mob_id,
                    "type": "kayou" if isinstance(mob, Kayou) else "shade",
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
            self._queue_message(
                {
                    "type": "phase",
                    "unlocked": True,
                    "hero_level": self.hero_level,
                    "hero_mob_kills": self.hero_mob_kills,
                }
            )

    def _reset_boss_phase(self, announce: bool):
        if not self.boss_phase_unlocked:
            return
        self.boss_phase_unlocked = False
        self._set_status("Boss phase reset. Trapped walls removed.")

        # Base wall hiding removed — no invisible walls are created anymore.
        # (world.hide_base_walls call intentionally removed)

        if announce:
            self._queue_message(
                {
                    "type": "phase",
                    "unlocked": False,
                    "hero_level": self.hero_level,
                    "hero_mob_kills": self.hero_mob_kills,
                }
            )

    def _declare_winner(self, winner: str, announce: bool):
        if self.winner is not None:
            return
        self.winner = winner

        is_winner = (winner == "hero" and self.player_id == 0) or (winner == "boss" and self.player_id == 1)
        text = "YOU WON" if is_winner else "YOU LOST"
        color = self.ui_palette["gold"] if is_winner else self.ui_palette["hp"]
        self.game_over_title.setText(text)
        self.game_over_title.setFg(color)
        self.game_over_root.show()

        if winner == "hero":
            self._set_status("Hero wins.")
        else:
            self._set_status("Boss wins.")
        if announce:
            self._queue_message({"type": "game_over", "winner": winner})

    def _on_hero_death(self):
        """Handle hero death - either respawn or declare boss as winner."""
        self.hero_death_count += 1

        self.sfx_hero_death.play()
        
        if self.hero_respawn_count >= self.max_respawns:
            # Max respawns reached, boss wins
            self._set_status(f"Hero defeated! (Died {self.hero_death_count} times)")
            self._declare_winner("boss", announce=True)
        else:
            # Respawn the hero stronger
            self._respawn_hero()

    def _respawn_hero(self):
        """Respawn the hero at the starting position with stat bonuses."""
        if not self.hero or self.hero_start_pos is None:
            return
        
        self.hero_respawn_count += 1
        
        # Grant stat bonuses based on levels achieved
        # Bonus: +2 level per respawn + 50% of levels earned in last run
        stat_bonus = self.hero_respawn_count * 2 + max(0, self.hero_level // 2)
        self.hero_level += stat_bonus
        
        # Also increase mob kills proportionally to maintain progression
        self.hero_mob_kills += stat_bonus
        
        # Increase hero max HP per respawn (+15 HP per respawn)
        self.hero_max_hp = HERO_MAX_HP + (self.hero_respawn_count * 15)
        self.hero_hp = self.hero_max_hp
        
        # Clear velocity FIRST before repositioning to prevent physics ejection
        self.hero.node.setLinearVelocity(Vec3(0, 0, 0))
        self.hero.node.setAngularVelocity(Vec3(0, 0, 0))
        
        # Reset boss phase BEFORE repositioning - this hides the physics walls that trap the hero
        # Without this, physics engine will eject hero when repositioning near wall
        self._reset_boss_phase(announce=True)

        self.camera_follow_x = self.hero.np.getX()

        # Teleport hero back to the starting position of the dungeon
        # if self.boss_phase_unlocked:
        #     respawn_x = self.goal_x + 2.0
        #     respawn_z = self._get_spawn_z_on_base(respawn_x, "end", 10.0)
        #     respawn_pos = Vec3(respawn_x, 0, respawn_z)
        # else:
        #     respawn_pos = self.hero_start_pos

        self.hero.np.setPos(self.hero_start_pos)
        
        # Update camera to follow hero at the new position
        
        # Announce respawn
        self._set_status(f"Hero respawns! Power +{stat_bonus}, HP {self.hero_max_hp} (Respawn #{self.hero_respawn_count})")
        
        # Send respawn notification to network if needed
        self._queue_message({
            "type": "hero_respawn",
            "respawn_count": self.hero_respawn_count,
            "hero_level": self.hero_level,
            "hero_mob_kills": self.hero_mob_kills,
            "hero_hp": self.hero_hp,
        })
        
        # Update HUD
        self._update_hud()

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
                    bool(target.get("is_big", False)),
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
        is_big = (self.player_id == 0 and self.hero_mana >= HERO_MAX_MANA)
        if self.player_id == 0:
            animation_started = self.hero.perform_attack(restart=True, reverse_if_midpoint=True, is_big=is_big)
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

        if is_big:
            self.hero_mana = 0.0

        self.last_attack_times[cd_key] = now
        self.attack_buffer_until = 0.0

        combo_multiplier, combo_range_bonus = self._next_combo_multiplier(cd_key, now)
        if self.player_id == 0:
            self._send_hero_attack(combo_multiplier, combo_range_bonus, is_big=is_big)
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

    def _send_hero_attack(self, combo_multiplier: float, combo_range_bonus: float, is_big: bool = False):
        self._play_attack_vfx(self.hero.np)
        self._apply_attack_lunge(self.hero.np, 3.5 + combo_range_bonus * 4.0)
        sent = False
        damage = self._get_hero_damage(combo_multiplier)
        if is_big:
            damage = int(damage * BIG_ATTACK_DAMAGE_MULTIPLIER)
            self._set_status("ULTIMATE ATTACK!")
            self.sfx_hero_big_attack.play()

        hit_range = self.game_config.hero_attack_range + combo_range_bonus

        if self._entity_attack_distance(self.hero.np, self.boss.np) <= hit_range:
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

        if sent:
            self.sfx_hero_attack_hit.play()
        else:
            self.sfx_hero_attack_miss.play()
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
        
        if self.controlled_entity == "boss":
            hit_range = self.game_config.hero_attack_range + combo_range_bonus
            if self._entity_attack_distance(attacker_np, self.hero.np) <= hit_range:
                base_damage = BOSS_DAMAGE
                damage = int(base_damage * combo_multiplier)
                self._queue_message({"type": "attack", "target": "hero", "damage": damage})
                self._play_hit_vfx(self.hero.np, damage)
            else:
                self._set_status("Attack missed.")
        else:
            # Controlled mob attack delay
            mob_id = self.controlled_entity
            now = time.monotonic()
            
            # Check for combo to skip delay
            is_combo = False
            state = self.combo_state.get("mob")
            if state and state["step"] > 0 and now - state["last_time"] <= COMBO_WINDOW:
                is_combo = True
                
            if is_combo:
                # Instant hit for combo
                hit_range = self.game_config.hero_attack_range + combo_range_bonus
                if self._entity_attack_distance(attacker_np, self.hero.np) <= hit_range:
                    mob = self.local_mobs.get(mob_id)
                    base_damage = KAYOU_DAMAGE if isinstance(mob, Kayou) else MOB_DAMAGE
                    damage = int(base_damage * combo_multiplier)
                    self._queue_message({"type": "attack", "target": "hero", "damage": damage})
                    self._play_hit_vfx(self.hero.np, damage)
                else:
                    self._set_status("Attack missed.")
            else:
                # Delayed hit for opener
                self.mob_attack_pending[mob_id] = now + MOB_ATTACK_STARTUP_DELAY

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
                self._on_hero_death()
            return

        if self.player_id == 1 and target == "boss":
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
            mob_instance = self.local_mobs[mob_id]
            is_kayou = isinstance(mob_instance, Kayou)
            max_hp_mob = KAYOU_MAX_HP if is_kayou else MOB_MAX_HP
            
            hp = max(0, self.local_mob_hp.get(mob_id, max_hp_mob) - damage)
            self.local_mob_hp[mob_id] = hp
            self._play_hit_vfx(self.local_mobs[mob_id].np, damage)
            if hp == 0:
                self._destroy_local_mob(mob_id)
                self._apply_hero_mob_kill_reward(1, announce=False, is_kayou=is_kayou)
                self._queue_message(
                    {
                        "type": "hero_progress",
                        "level": self.hero_level,
                        "kills": self.hero_mob_kills,
                        "damage": self._get_hero_damage(),
                        "is_kayou": is_kayou,
                    }
                )

    def spawn_local_mob_request(self):
        if self.player_id != 1 or self.winner:
            return
        if not self.boss:
            return
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            self._set_status(f"Summon limit reached ({MAX_ACTIVE_MOBS}).")
            return

        if not self._try_spend_boss_action("spawn", MOB_SPAWN_MANA_COST, SPAWN_COOLDOWN, "Summon shade"):
            return
        self.last_spawn_time = self.last_boss_action_times["spawn"]

        source_np = self._get_controlled_np() or self.boss.np
        x = source_np.getX() + random.uniform(-1.5, 1.5)
        z = source_np.getZ() + 0.5
        self._spawn_local_mob_at(Vec3(x, 0, z), mob_type="shade")

    def _spawn_local_mob_at(self, pos: Vec3, mob_type: str = "shade", status_label: str = "Summoned shade"):
        if self.player_id != 1 or self.winner:
            return
        if len(self.local_mobs) >= MAX_ACTIVE_MOBS:
            self._set_status(f"Summon limit reached ({MAX_ACTIVE_MOBS}).")
            return
        mob_id = self.next_mob_id
        self.next_mob_id += 1

        if mob_type == "kayou":
            mob = Kayou(
                self.game_config,
                self.render,
                self.loader,
                self.physics,
                start_pos=pos,
                mode="AI",
            )
            max_hp = KAYOU_MAX_HP
        else:
            mob = Mob(
                self.game_config,
                self.render,
                self.loader,
                self.physics,
                start_pos=pos,
                mode="AI",
            )
            max_hp = MOB_MAX_HP

        self.local_mobs[mob_id] = mob
        self.local_mob_hp[mob_id] = max_hp
        self.ai_attack_clock[mob_id] = 0.0
        self._spawn_pulse_vfx(mob.np.getPos(self.render) + Vec3(0, 0, 1.3), (0.4, 0.95, 1.0, 0.9), 0.22, 0.28)
        slot = self._get_mob_slot(mob_id)
        slot_text = f" slot {slot}" if slot is not None else ""
        self._set_status(f"{status_label}{slot_text}.")

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

    def _boss_teleport_request(self):
        if self.player_id != 1 or self.winner or not self.boss:
            return
        if self.controlled_entity != "boss":
            self._set_status("Only the boss can teleport.")
            return

        if not self._try_spend_boss_action(
            "teleport",
            BOSS_TELEPORT_MANA_COST,
            BOSS_TELEPORT_COOLDOWN,
            "Boss Teleport",
        ):
            return

        anim_played = False
        if self.boss.TELEPORT_ANIM:
            anim_played = self.boss.play_named_animation(self.boss.TELEPORT_ANIM)
        
        if not anim_played:
            self.boss.perform_attack(restart=True)
        self._set_status("Casting teleport...")
        
        # Schedule the teleport to happen after the animation
        self.taskMgr.doMethodLater(
            BOSS_TELEPORT_ANIM_DELAY, self._execute_teleport_task, "boss_teleport_task"
        )

    def _perform_boss_teleport(self):
        if not self.boss:
            return

        bounds = self._get_endpoint_base_bounds("end")
        if bounds is None:
            self._set_status("Boss base bounds not found for teleportation.")
            return

        left, right, bottom, top = bounds
        padding_x = 2.0
        min_x_teleport = left + padding_x
        max_x_teleport = right - padding_x

        if min_x_teleport > max_x_teleport:
            min_x_teleport = (left + right) / 2.0
            max_x_teleport = min_x_teleport

        random_x = random.uniform(min_x_teleport, max_x_teleport)
        target_z = self._get_spawn_z_on_base(random_x, "end", self.boss.np.getZ())
        new_pos = Vec3(random_x, 0, target_z)

        # VFX at old position
        self._spawn_pulse_vfx(self.boss.np.getPos(self.render) + Vec3(0, 0, 1.5), (0.8, 0.2, 1.0, 0.9), 0.3, 0.4)

        self.boss.node.setLinearVelocity(Vec3(0, 0, 0))
        self.boss.node.setAngularVelocity(Vec3(0, 0, 0))
        self.boss.np.setPos(new_pos)
        self.boss.node.setActive(True)

        # VFX at new position
        self._spawn_pulse_vfx(new_pos + Vec3(0, 0, 1.5), (0.8, 0.2, 1.0, 0.9), 0.3, 0.4)
        self._set_status("Boss teleported!")
        self._queue_message(self._build_local_state_payload())

    def _execute_teleport_task(self, task):
        # Only complete teleport if the animation wasn't interrupted (e.g. by movement)
        if self.boss and (self.boss.is_attacking or self.boss.is_playing_action):
            self._perform_boss_teleport()
        else:
            self._set_status("Teleport interrupted.")
        return task.done

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
            mob = self.local_mobs.get(entity)
            mob_name = "kayou" if isinstance(mob, Kayou) else "shade"
            return f"{mob_name} {slot}" if slot is not None else f"{mob_name} {entity}"
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
        self._set_status(f"Commanding {self._control_label(self.controlled_entity)}.")

    def select_control_boss(self):
        if self.player_id != 1 or self.winner:
            return
        self._set_controlled_entity("boss")
        self._set_status("Commanding boss.")

    def select_control_slot(self, slot: int):
        if self.player_id != 1 or self.winner:
            return
        mob_ids = sorted(self.local_mobs.keys())
        if not mob_ids:
            self._set_status("No summons available.")
            return
        if slot < 1 or slot > len(mob_ids):
            self._set_status(f"Slot {slot} is empty.")
            return
        mob_id = mob_ids[slot - 1]
        self._set_controlled_entity(mob_id)
        self._set_status(f"Commanding {self._control_label(mob_id)}.")

    def _update_ai_attacks(self):
        if self.player_id != 1 or not self.hero or self.winner:
            return

        now = time.monotonic()
        
        # Process pending hits
        for mob_id in list(self.mob_attack_pending.keys()):
            if mob_id not in self.local_mobs:
                self.mob_attack_pending.pop(mob_id, None)
                continue
                
            hit_time = self.mob_attack_pending[mob_id]
            if now >= hit_time:
                self.mob_attack_pending.pop(mob_id)
                mob = self.local_mobs[mob_id]
                if self._entity_attack_distance(mob.np, self.hero.np) <= ATTACK_RANGE:
                    damage = KAYOU_DAMAGE if isinstance(mob, Kayou) else MOB_DAMAGE
                    self._queue_message({"type": "attack", "target": "hero", "damage": damage})
                    if self.hero:
                        self._play_hit_vfx(self.hero.np, damage)

        # Trigger new attacks
        for mob_id, mob in self.local_mobs.items():
            if mob.mode != "AI" or not mob.is_attacking:
                continue
            if self._entity_attack_distance(mob.np, self.hero.np) > ATTACK_RANGE:
                continue
            
            last_hit = self.ai_attack_clock.get(mob_id, 0.0)
            if now - last_hit >= AI_ATTACK_COOLDOWN:
                self.ai_attack_clock[mob_id] = now
                self._play_attack_vfx(mob.np)
                
                # Check for combo to skip delay
                is_combo = False
                state = self.combo_state.get("mob")
                if state and state["step"] > 0 and now - state["last_time"] <= COMBO_WINDOW:
                    is_combo = True
                
                if is_combo:
                    # Instant hit for combo
                    damage = KAYOU_DAMAGE if isinstance(mob, Kayou) else MOB_DAMAGE
                    self._queue_message({"type": "attack", "target": "hero", "damage": damage})
                    if self.hero:
                        self._play_hit_vfx(self.hero.np, damage)
                else:
                    # Delayed hit for opener
                    self.mob_attack_pending[mob_id] = now + MOB_ATTACK_STARTUP_DELAY

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
        self._update_ui_animations(dt)
        self._regen_boss_mana(dt)
        self._process_attack_buffer()

        if self.hitstop_remaining > 0.0:
            self.hitstop_remaining = max(0.0, self.hitstop_remaining - dt)
            self._update_vfx(dt)
            self._update_boss_map_player_icon()
            self._update_hero_map_player_icon()
            if self.boss_inventory_open:
                self._update_boss_free_camera(dt)
            self._update_status(dt)
            self._tick_hud(dt)
            return task.cont

        if self.hero:
            self.hero.update(dt)

            # Update running sound for the local hero
            if self.player_id == 0:
                is_jumping = getattr(self.hero, "is_jumping", False)
                if is_jumping and not self.hero_was_jumping:
                    self.sfx_hero_jump.play()
                self.hero_was_jumping = is_jumping

                is_moving = getattr(self.hero, "is_moving", False)
                is_in_air = is_jumping or getattr(self.hero, "is_climbing", False)
                
                # Play sound if moving on the ground, otherwise stop it
                if is_moving and not is_in_air:
                    if self.sfx_hero_run.status() != self.sfx_hero_run.PLAYING:
                        self.sfx_hero_run.play()
                else:
                    if self.sfx_hero_run.status() == self.sfx_hero_run.PLAYING:
                        self.sfx_hero_run.stop()

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
        self._update_hero_map_player_icon()
        self._update_status(dt)
        self._tick_hud(dt)
        return task.cont


if __name__ == "__main__":
    game = Game()
    game.run()
