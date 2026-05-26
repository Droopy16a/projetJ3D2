from __future__ import annotations

from typing import Dict

from direct.actor.Actor import Actor
from direct.interval.IntervalGlobal import ActorInterval, Func, Sequence
from direct.showbase import DirectObject
from panda3d.bullet import BulletCapsuleShape, BulletRigidBodyNode
from panda3d.core import BitMask32, LineSegs, TransformState, Vec3

from assets.Config import Config
from assets.Global_state import GLOBAL_STATE
from assets.PhysicsManager import PhysicsManager


def bit(gid: int) -> BitMask32:
    return BitMask32.bit(gid)


class Boss(DirectObject.DirectObject):
    MODEL_PATH = "./assets/models/Boss_Roche.glb"

    def __init__(
        self,
        config: Config,
        render,
        loader,
        physics: PhysicsManager,
        start_pos: Vec3 = Vec3(0, 0, 7),
        from_pos_bound=None,
        to_pos_bound=None,
        mode: str = "AI",
    ):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics
        self.mode = ""
        self.keys: Dict[str, bool] = {k: False for k in ("z", "q", "s", "d")}
        self._controls_bound = False

        self.is_attacking = False
        self.is_playing_action = False
        self.is_moving = False
        self.attack_id = 0
        self._remote_attack_latched = False
        self._remote_attack_id = 0

        shape = BulletCapsuleShape(1.5, 3.75, 2)
        self.node = BulletRigidBodyNode("boss")
        self.node.setMass(config.boss_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 2.0)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        self.node.setLinearFactor(Vec3(1, 0, 1))
        self.node.setDeactivationEnabled(False)

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        physics.attach(self.node, self.np)

        index = GLOBAL_STATE.increase_mob_number()
        self.np.setCollideMask(bit(index))

        self.actor = Actor(self.MODEL_PATH)
        self.actor.setHpr(-90, 0, 0)
        self.actor.reparentTo(self.np)

        self._anim_names = list(self.actor.getAnimNames()) if self.actor else []
        self.WALK_ANIM = None #self._find_anim("walk", "run")
        self.IDLE_ANIM = self._find_anim("idle") or self._find_anim("intro") or self.WALK_ANIM
        self.DIE_ANIM = self._find_anim("die", "death")
        self.INTRO_ANIM = self._find_anim("intro")
        self.TELEPORT_ANIM = self._find_anim("teleport")
        self.CUBE_ANIM = self._find_anim("cube")
        self.ATTACK_ANIMS = self._build_attack_sequence()

        self.speed = 2.8
        self.control_speed = 5.0
        self.ground_accel = 38.0
        self.ground_friction = 50.0
        self.direction = 1
        self.bounds = (from_pos_bound, to_pos_bound) if from_pos_bound is not None and to_pos_bound is not None else None
        self.np.setH(90)

        self.debug_rays = bool(getattr(self.config, "debug_rays", False))
        self.ray_vis: list[LineSegs] = []
        self.ray_node: list = []
        if self.debug_rays:
            self.ray_vis = [LineSegs(), LineSegs()]
            self.ray_node = [None] * len(self.ray_vis)
            for r in range(len(self.ray_vis)):
                self.ray_vis[r].setThickness(2)
                self.ray_node[r] = self.render.attachNewNode(self.ray_vis[r].create())

        self.animation_keys = {
            "i": self.INTRO_ANIM,
            "x": self.DIE_ANIM,
            "c": self.CUBE_ANIM,
        }
        self.animation_keys = {key: anim for key, anim in self.animation_keys.items() if anim}

        self.set_mode(mode)

    def _find_anim(self, *needles: str) -> str | None:
        lowered = [(anim.lower().strip(), anim) for anim in self._anim_names]
        for needle in needles:
            match = next((anim for lowered_name, anim in lowered if needle in lowered_name), None)
            if match:
                return match
        return None

    def _build_attack_sequence(self) -> list[tuple[str, ...]]:
        attacks = sorted(
            [anim for anim in self._anim_names if "attack" in anim.lower()],
            key=lambda name: (self._attack_number(name), name),
        )
        sequence: list[tuple[str, ...]] = []
        used: set[str] = set()

        activation = next((a for a in attacks if "activation" in a.lower()), None)
        release = next((a for a in attacks if "release" in a.lower()), None)
        for anim in attacks:
            if anim in used:
                continue
            if anim == activation and release:
                sequence.append((activation, release))
                used.add(activation)
                used.add(release)
            elif "release" not in anim.lower():
                sequence.append((anim,))
                used.add(anim)
        return sequence

    def _attack_number(self, name: str) -> int:
        digits = "".join(ch for ch in name if ch.isdigit())
        return int(digits) if digits else 999

    def _reset_controls(self):
        for key in self.keys:
            self.keys[key] = False

    def _bind_controls(self):
        if self._controls_bound:
            return
        self._controls_bound = True
        self.accept("z", self.set_key, ["z", True])
        self.accept("z-up", self.set_key, ["z", False])
        self.accept("s", self.set_key, ["s", True])
        self.accept("s-up", self.set_key, ["s", False])
        self.accept("q", self.set_key, ["q", True])
        self.accept("q-up", self.set_key, ["q", False])
        self.accept("d", self.set_key, ["d", True])
        self.accept("d-up", self.set_key, ["d", False])
        for key, anim in self.animation_keys.items():
            self.accept(key, self.play_named_animation, [anim])

    def set_mode(self, mode: str):
        next_mode = mode.upper()
        if next_mode == self.mode:
            return
        previous_mode = self.mode
        self.mode = next_mode

        if previous_mode == "PLAYER" and self._controls_bound:
            self.ignoreAll()
            self._controls_bound = False
            self._reset_controls()
            self._cancel_attack()
            self._cancel_action()

        if self.mode in ("AI", "PLAYER", "IDLE"):
            self.enable_physics()
        elif self.mode == "REMOTE":
            self.disable_physics()

        if self.mode == "PLAYER":
            if GLOBAL_STATE.get_player_id() == 1:
                self._bind_controls()
                self._loop_anim(self.IDLE_ANIM)
            else:
                self.disable_physics()
        elif self.mode == "AI":
            self.direction = 1
            self.np.setH(90.0)
            self._cancel_attack()
            self.is_moving = False
            self._loop_anim(self.WALK_ANIM)
        elif self.mode == "IDLE":
            self._stop_motion()
            self._loop_anim(self.IDLE_ANIM)

    def disable_physics(self):
        self.node.setKinematic(True)
        self.node.setGravity(Vec3(0))
        self.node.setLinearVelocity(Vec3(0))
        self.node.setAngularVelocity(Vec3(0))

    def enable_physics(self):
        self.node.setKinematic(False)
        self.node.setGravity(Vec3(0, 0, -9.81))

    def set_key(self, key, value):
        self.keys[key] = value

    def play_named_animation(self, anim_name: str | None):
        if not self.actor or not anim_name:
            return False
        self._cancel_attack()
        self._cancel_action()
        self.actor.stop()
        self.is_playing_action = True

        def finish():
            self.is_playing_action = False
            if self.is_moving and self.WALK_ANIM:
                self._loop_anim(self.WALK_ANIM)
            elif self.IDLE_ANIM:
                self._loop_anim(self.IDLE_ANIM)

        self.action_seq = Sequence(ActorInterval(self.actor, anim_name), Func(finish))
        self.action_seq.start()
        return True

    def _approach(self, current: float, target: float, max_delta: float) -> float:
        if current < target:
            return min(current + max_delta, target)
        return max(current - max_delta, target)

    def _cancel_attack(self):
        attack_seq = getattr(self, "attack_seq", None)
        if attack_seq:
            try:
                if attack_seq.isPlaying():
                    attack_seq.finish()
            except Exception:
                pass
        self.is_attacking = False

    def _cancel_action(self):
        action_seq = getattr(self, "action_seq", None)
        if action_seq:
            try:
                if action_seq.isPlaying():
                    action_seq.finish()
            except Exception:
                pass
        self.is_playing_action = False

    def _current_anim(self):
        return self.actor.getCurrentAnim() if self.actor else None

    def _loop_anim(self, anim_name: str | None):
        if self.actor and anim_name and self._current_anim() != anim_name:
            self.actor.loop(anim_name)

    def _stop_anim(self):
        if self.actor:
            self.actor.stop()

    def _stop_motion(self):
        vel = self.node.getLinearVelocity()
        vel.setX(0)
        vel.setY(0)
        self.node.setLinearVelocity(vel)
        self.is_moving = False

    def update(self, dt: float):
        if self.mode == "AI":
            self.update_ai(dt)
        elif self.mode == "PLAYER":
            self.update_player(dt)
        elif self.mode == "IDLE":
            self.update_idle()

    def update_idle(self):
        self._stop_motion()
        if self.is_playing_action:
            return
        if self.IDLE_ANIM and self._current_anim() != self.IDLE_ANIM:
            self._loop_anim(self.IDLE_ANIM)

    def _get_attack_frame(self) -> tuple[int, int]:
        anims = self._current_attack_anims()
        if not self.actor or not anims:
            return 0, 0
        ctrl = self.actor.getAnimControl(anims[0])
        if not ctrl:
            return 0, 0
        return int(ctrl.getFrame()), max(1, int(ctrl.getNumFrames()))

    def _current_attack_anims(self) -> tuple[str, ...]:
        if not self.ATTACK_ANIMS:
            return ()
        return self.ATTACK_ANIMS[self.attack_id % len(self.ATTACK_ANIMS)]

    def perform_attack(self, force: bool = False, restart: bool = False, reverse_if_midpoint: bool = False) -> bool:
        if self.mode != "PLAYER" and not force:
            return False
        if not self.ATTACK_ANIMS:
            self.attack_id += 1
            return True
        if not self._play_attack_animation(restart=restart, reverse_if_midpoint=reverse_if_midpoint):
            return False
        self.attack_id += 1
        return True

    def _play_attack_animation(self, restart: bool = False, reverse_if_midpoint: bool = False) -> bool:
        attack_anims = self._current_attack_anims()
        if not attack_anims:
            return False

        start_frame = None
        end_frame = None
        if self.is_attacking:
            if not restart:
                return False
            if reverse_if_midpoint:
                current_frame, total_frames = self._get_attack_frame()
                if current_frame < total_frames * 0.5:
                    return False
                start_frame = current_frame
                end_frame = 0
            attack_seq = getattr(self, "attack_seq", None)
            if attack_seq:
                try:
                    attack_seq.pause()
                except Exception:
                    pass

        self.is_attacking = True
        self._cancel_action()
        self._stop_anim()

        intervals = []
        for index, anim in enumerate(attack_anims):
            intervals.append(
                ActorInterval(
                    self.actor,
                    anim,
                    startFrame=start_frame if index == 0 else None,
                    endFrame=end_frame if len(attack_anims) == 1 else None,
                )
            )

        def finish():
            self.is_attacking = False
            if self.is_moving and self.WALK_ANIM:
                self._loop_anim(self.WALK_ANIM)
            elif self.IDLE_ANIM:
                self._loop_anim(self.IDLE_ANIM)

        self.attack_seq = Sequence(*intervals, Func(finish))
        self.attack_seq.start()
        return True

    def get_network_anim_state(self) -> dict[str, bool]:
        vel = self.node.getLinearVelocity()
        moving = self.is_moving or abs(vel.x) > 0.1 or abs(vel.y) > 0.1
        return {
            "moving": moving,
            "attacking": self.is_attacking,
            "attack_id": self.attack_id,
        }

    def apply_remote_animation(self, moving: bool, attacking: bool, attack_id: int = 0):
        self.is_moving = moving
        if attack_id > self._remote_attack_id:
            should_play_attack = attacking or self._remote_attack_id > 0
            if should_play_attack:
                if self.perform_attack(force=True, restart=True, reverse_if_midpoint=self.is_attacking):
                    self._remote_attack_id = attack_id
            else:
                self._remote_attack_id = attack_id
        elif attacking and not self._remote_attack_latched:
            self.perform_attack(force=True, restart=True)
        self._remote_attack_latched = attacking

        if self.is_attacking:
            return
        if self.is_playing_action:
            return

        if moving and self.WALK_ANIM:
            self._loop_anim(self.WALK_ANIM)
            return

        if self.IDLE_ANIM:
            self._loop_anim(self.IDLE_ANIM)

    def update_ai(self, dt: float):
        forward = self.np.getQuat().getForward()
        forward.normalize()
        pos = self.np.getPos()

        start = pos + Vec3(0, 0, 1.5)
        to_hitzone = start + forward * -self.config.boss_attack_range
        hitzone = self.physics.world.rayTestClosest(start, to_hitzone)
        self._draw_debug_ray(0, start, to_hitzone)

        if hitzone.hasHit() and hitzone.getNode().getName() == 'Character':
             if not self.is_attacking:
                self.perform_attack(force=True)

        if self.bounds and pos.x > self.bounds[1]:
            self.direction = -1
            self.np.setH(-90)
        elif self.bounds and pos.x < self.bounds[0]:
            self.direction = 1
            self.np.setH(90)

        vel = self.node.getLinearVelocity()
        if not self.is_attacking:
            vel.setX(self._approach(vel.x, self.direction * self.speed, self.ground_accel * dt))
            self.is_moving = abs(vel.x) > 0.1
            if self.WALK_ANIM:
                self._loop_anim(self.WALK_ANIM)
        else:
            vel.setX(self._approach(vel.x, 0.0, self.ground_friction * dt))
        vel.setY(0.0)
        self.node.setLinearVelocity(vel)

    def update_player(self, dt: float):
        move_x = float(self.keys["d"]) - float(self.keys["q"])
        has_move_input = abs(move_x) > 1e-5
        vel = self.node.getLinearVelocity()

        if has_move_input:
            # if self.is_playing_action:
            #     # Do not cancel the teleport animation if it's currently playing
            #     if self.TELEPORT_ANIM is None or self._current_anim() != self.TELEPORT_ANIM:
            #         self._cancel_action()
            desired_x = move_x * self.control_speed
            vel.setX(self._approach(vel.x, desired_x, self.ground_accel * dt))
            vel.setY(self._approach(vel.y, 0.0, self.ground_accel * dt))
            self.node.setLinearVelocity(vel)

            angle = 90.0 if move_x > 0.0 else -90.0
            current_h = self.np.getH()
            h_lerp = min(1.0, dt * 20.0)
            self.np.setH(current_h + (((angle - current_h + 180.0) % 360.0) - 180.0) * h_lerp)

            self.is_moving = True
            if not self.is_attacking and self.WALK_ANIM:
                self._loop_anim(self.WALK_ANIM)
        else:
            self.is_moving = False
            vel.setX(self._approach(vel.x, 0.0, self.ground_friction * dt))
            vel.setY(self._approach(vel.y, 0.0, self.ground_friction * dt))
            self.node.setLinearVelocity(vel)
            if not self.is_attacking and not self.is_playing_action and self.IDLE_ANIM:
                self._loop_anim(self.IDLE_ANIM)

    def destroy(self):
        self.ignoreAll()
        self._cancel_attack()
        self._cancel_action()
        if self.actor:
            self.actor.cleanup()
        self.physics.detach(self.node)
        for node in self.ray_node:
            if node and not node.isEmpty():
                node.removeNode()
        if self.np and not self.np.isEmpty():
            self.np.removeNode()
