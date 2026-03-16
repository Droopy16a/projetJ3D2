from __future__ import annotations

import asyncio
import json
import os
import random
import time
import math
from typing import Any

from assets.Character import Character
from assets.Config import Config
from assets.Global_state import GLOBAL_STATE
from assets.Mob import Mob
from assets.PhysicsManager import PhysicsManager
from assets.World import World

from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    ConfigVariableString,
    DirectionalLight,
    TextNode,
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


class Game(ShowBase):
    def __init__(self, config: Config = Config()):
        super().__init__()
        self.config = config
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
            print("simplepbr not installed, continuing with Panda3D default rendering.")

        props = WindowProperties()
        props.setTitle(self.config.window_title)
        self.win.requestProperties(props)

        GLOBAL_STATE.set_camera(self)
        self.camera.setPos(0, -40, 6)
        self.camera.setHpr(0, 0, 0)

        dlight = DirectionalLight("sun")
        dlight.setColor(Vec4(0.8, 0.8, 0.8, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)
        dlight.setShadowCaster(True, 2048, 2048)

        self.setBackgroundColor(0, 0, 0, 1)
        self.render.setLight(dlnp)

        alight = AmbientLight("alight")
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        self.physics = PhysicsManager(self.config.gravity, self.render)
        self.world = World(self.config, self.render, self.loader, self.physics, index=1)
        self.min_x, self.max_x = self.world.setLimit()
        self.goal_x = self.max_x - 2.0

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

        self.PORT = int(os.getenv("DUNGEON_ARISE_PORT", str(DEFAULT_PORT)))
        self.ws_host = os.getenv("DUNGEON_ARISE_HOST", DEFAULT_HOST)
        self.ws_uri = f"ws://{self.ws_host}:{self.PORT}"
        self.websocket = None
        self._event_loop = None
        self._connection_established = False
        self._ws_task = None
        self._outbox: list[dict[str, Any]] = []
        self.network_update_interval = NETWORK_UPDATE_INTERVAL
        self.time_since_last_send = 0.0
        self.remote_targets: dict[str, dict[str, Any]] = {}
        self.active_vfx: list[dict[str, Any]] = []
        self.active_flashes: list[dict[str, Any]] = []

        self._setup_hud()

        self.accept("f", self.spawn_local_mob_request)
        self.accept("tab", self.cycle_control)
        self.accept("mouse1", self.on_attack_input)

        self.taskMgr.add(self._task_physics, "physics_task")
        self.taskMgr.add(self._task_update, "update_task")
        self.taskMgr.add(self._task_websocket, "websocket_task")

    def _setup_hud(self):
        self.role_text = OnscreenText(
            text="Connecting...",
            pos=(-1.31, 0.92),
            align=TextNode.ALeft,
            scale=0.048,
            fg=(1, 1, 1, 1),
            mayChange=True,
        )
        self.objective_text = OnscreenText(
            text="Waiting for server role assignment.",
            pos=(-1.31, 0.85),
            align=TextNode.ALeft,
            scale=0.042,
            fg=(0.9, 0.9, 0.9, 1),
            mayChange=True,
        )
        self.health_text = OnscreenText(
            text="",
            pos=(-1.31, 0.78),
            align=TextNode.ALeft,
            scale=0.042,
            fg=(0.95, 0.85, 0.65, 1),
            mayChange=True,
        )
        self.cooldown_text = OnscreenText(
            text="",
            pos=(-1.31, 0.71),
            align=TextNode.ALeft,
            scale=0.036,
            fg=(0.75, 0.95, 0.95, 1),
            mayChange=True,
        )
        self.fps_text = OnscreenText(
            text="",
            pos=(-1.31, 0.64),
            align=TextNode.ALeft,
            scale=0.034,
            fg=(0.8, 0.95, 0.8, 1),
            mayChange=True,
        )
        self.status_text = OnscreenText(
            text="",
            pos=(0, 0.9),
            align=TextNode.ACenter,
            scale=0.055,
            fg=(1, 0.95, 0.75, 1),
            mayChange=True,
        )

    def _set_status(self, text: str):
        self.status_text.setText(text)

    def _update_hud(self):
        if self.player_id == 0:
            self.role_text.setText("Role: Hero")
        elif self.player_id == 1:
            self.role_text.setText("Role: Boss")
        else:
            self.role_text.setText("Connecting...")

        if self.winner:
            self.objective_text.setText("Game over.")
        elif self.player_id == 0:
            if self.boss_phase_unlocked:
                self.objective_text.setText("Objective: defeat the boss.")
            else:
                self.objective_text.setText(f"Objective: reach X >= {self.goal_x:.1f}, then defeat the boss.")
        elif self.player_id == 1:
            self.objective_text.setText("Objective: kill the hero before they kill you.")
        else:
            self.objective_text.setText("Waiting for role assignment.")

        mob_count = len(self.local_mobs) if self.player_id == 1 else len(self.remote_mobs)
        self.health_text.setText(
            f"Hero HP: {self.hero_hp} | Boss HP: {self.boss_hp} | Mobs: {mob_count}"
        )

        attack_cd = self._get_current_attack_cooldown()
        cd_key = self._get_attack_cooldown_key()
        attack_left = max(0.0, attack_cd - (time.monotonic() - self.last_attack_times[cd_key]))
        combo_step = self.combo_state[cd_key]["step"] + 1 if self.combo_state[cd_key]["step"] >= 0 else 0
        if self.player_id == 1:
            spawn_left = max(0.0, SPAWN_COOLDOWN - (time.monotonic() - self.last_spawn_time))
            self.cooldown_text.setText(
                f"Attack CD: {attack_left:.2f}s | Combo: {combo_step} | Spawn CD: {spawn_left:.2f}s | Spawned: {len(self.local_mobs)}/{MAX_ACTIVE_MOBS}"
            )
        elif self.player_id == 0:
            self.cooldown_text.setText(f"Attack CD: {attack_left:.2f}s | Combo: {combo_step}")
        else:
            self.cooldown_text.setText("")

        fps = globalClock.getAverageFrameRate()
        if fps > 0:
            self.fps_text.setText(f"FPS: {fps:.1f}")
        else:
            self.fps_text.setText("FPS: --")

    def _init_entities_for_role(self):
        if self.hero or self.boss:
            return

        hero_start = Vec3(self.min_x + 2.0, 0, 7)
        boss_start = Vec3(self.max_x - 5.0, 0, 7)

        self.hero = Character(self.config, self.render, self.loader, self.physics, start_pos=hero_start)
        if self.player_id == 0:
            self.boss = Mob(self.config, self.render, self.loader, self.physics, boss_start, mode="REMOTE")
            self.controlled_entity = "hero"
            self._set_status("Hero ready. Reach the end to unlock the boss.")
        else:
            self.boss = Mob(self.config, self.render, self.loader, self.physics, boss_start, mode="PLAYER")
            self.controlled_entity = "boss"
            self._set_status("Boss ready. F=spawn (limit/cd), TAB=switch control.")

        self._update_hud()

    def _queue_message(self, payload: dict[str, Any]):
        if len(self._outbox) > 300:
            self._outbox = self._outbox[-150:]
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
            payload = self._outbox.pop(0)
            await self.websocket.send(json.dumps(payload))

    async def websocket_handler(self):
        while True:
            try:
                print(f"Connecting to {self.ws_uri}...")
                async with websockets.connect(self.ws_uri) as websocket:
                    self.websocket = websocket
                    self._connection_established = True
                    self._set_status(f"Connected to {self.ws_uri}")

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
                self._set_status(f"Disconnected ({exc}). Reconnecting...")
                await asyncio.sleep(1.5)
            except Exception as exc:  # keep retry loop alive on protocol or runtime errors
                self._connection_established = False
                self.websocket = None
                self._set_status(f"Network error ({exc}). Reconnecting...")
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
                    self.config,
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

        return {
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
        pulse = self.loader.loadModel("models/misc/sphere")
        pulse.reparentTo(self.render)
        pulse.setPos(pos)
        pulse.setScale(base_scale)
        pulse.setColor(*color)
        pulse.setTransparency(True)
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
        for fx in list(self.active_vfx):
            node = fx["np"]
            if node.isEmpty():
                self.active_vfx.remove(fx)
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
                self.active_vfx.remove(fx)

        for flash in list(self.active_flashes):
            node = flash["np"]
            flash["time_left"] -= dt
            if flash["time_left"] <= 0.0:
                if node is not None and not node.isEmpty():
                    node.clearColorScale()
                self.active_flashes.remove(flash)

    def _update_remote_motion(self, dt: float):
        now = time.monotonic()
        for key, target in list(self.remote_targets.items()):
            smoothing = NETWORK_SMOOTHING
            prediction_limit = NETWORK_PREDICTION_LIMIT
            if key.startswith("mob:"):
                smoothing *= 1.6
                prediction_limit *= 1.4
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
            self.config,
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
        self._set_status(f"Spawned mob #{mob_id}.")

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
        self._set_status(f"Control: {self.controlled_entity}")

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
        blend = min(1.0, dt * CAMERA_SMOOTHING)
        self.camera_follow_x += (target_x - self.camera_follow_x) * blend
        self.camera.setPos(self.camera_follow_x, camy, camz)

    def _task_update(self, task):
        dt = globalClock.getDt()
        self._process_attack_buffer()

        if self.hitstop_remaining > 0.0:
            self.hitstop_remaining = max(0.0, self.hitstop_remaining - dt)
            self._update_vfx(dt)
            self._update_hud()
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
        self._update_hud()
        return task.cont


if __name__ == "__main__":
    game = Game()
    game.run()
