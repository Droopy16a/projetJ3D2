from __future__ import annotations

from typing import Dict
from panda3d.core import (
    Vec3,
    TransformState, 
    BitMask32,
    LineSegs,
)
from direct.actor.Actor import Actor
from panda3d.bullet import (
    BulletRigidBodyNode,
    BulletCapsuleShape,
)
from assets.Config import Config
from assets.PhysicsManager import PhysicsManager
from assets.Global_state import GLOBAL_STATE
from direct.showbase import DirectObject
from direct.interval.IntervalGlobal import Sequence, ActorInterval, Func

def bit(gid: int) -> BitMask32:
    return BitMask32.bit(gid)

class Kayou(DirectObject.DirectObject):
    def __init__(self, config: Config, render, loader, physics: PhysicsManager,
                 start_pos: Vec3 = Vec3(0, 0, 7), from_pos_bound = None, to_pos_bound = None,
                 mode: str = 'AI'):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics
        self.mode = ""
        self.keys: Dict[str, bool] = {k: False for k in ('z', 'q', 's', 'd')}
        self._controls_bound = False

        self.is_attacking = False
        self.is_moving = False
        self.attack_id = 0
        self._remote_attack_latched = False
        self._remote_attack_id = 0


        shape = BulletCapsuleShape(0.75, 1.0, 2)
        self.node = BulletRigidBodyNode('kayou')
        self.node.setMass(config.kayou_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        self.node.setLinearFactor(Vec3(1, 0, 1))

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        physics.attach(self.node, self.np)

        index = GLOBAL_STATE.increase_mob_number()
        self.np.setCollideMask(bit(index))

        self.actor = Actor(self.config.kayou_model)
        self.actor.reparentTo(self.np)
        self.actor.setScale(float(self.config.kayou_visual_scale))
        ox, oy, oz = self.config.kayou_visual_offset
        # self.actor.setPos(float(ox), float(oy), float(oz))

        anims = set(self.actor.getAnimNames()) if self.actor else set()

        print(f"Kayou animations: {anims}")
        
        # Improved animation detection (case-insensitive and partial matching)
        self.ATTACK_ANIM = next((a for a in anims if 'Attack Gro Mob' in a or 'Attack Gro Mob' in a), None)
        self.WALK_ANIM = next((a for a in anims if 'Walk Gro mob' in a or 'Walk Gro mob' in a), None)
        self.IDLE_ANIM = next((a for a in anims if 'idle' in a), None)
        
        # Fallbacks
        if not self.IDLE_ANIM:
            self.IDLE_ANIM = self.WALK_ANIM or (next(iter(anims)) if anims else None)

        self.speed = 2.5
        self.control_speed = 5.0
        self.ground_accel = 38.0
        self.ground_friction = 50.0
        self.direction = 1
        self.bounds = (from_pos_bound, to_pos_bound) if from_pos_bound and to_pos_bound else None
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

        self.set_mode(mode)

    def _reset_controls(self):
        for k in self.keys:
            self.keys[k] = False

    def _ensure_ray_nodes(self):
        if not self.debug_rays:
            return
        for r in range(len(self.ray_vis)):
            node = self.ray_node[r]
            if node is None or node.isEmpty():
                self.ray_node[r] = self.render.attachNewNode(self.ray_vis[r].create())

    def _draw_debug_ray(self, idx: int, from_pos: Vec3, to_pos: Vec3):
        if not self.debug_rays:
            return
        self.ray_vis[idx].reset()
        self.ray_vis[idx].setThickness(2)
        self.ray_vis[idx].setColor(1, 0, 0, 1)
        self.ray_vis[idx].moveTo(from_pos)
        self.ray_vis[idx].drawTo(to_pos)
        node = self.ray_node[idx]
        if node and not node.isEmpty():
            node.removeNode()
        self.ray_node[idx] = self.render.attachNewNode(self.ray_vis[idx].create())

    def _cancel_attack(self):
        if hasattr(self, "attack_seq"):
            try:
                if self.attack_seq and self.attack_seq.isPlaying():
                    self.attack_seq.finish()
            except Exception:
                pass
        self.is_attacking = False

    def _current_anim(self):
        if not self.actor:
            return None
        return self.actor.getCurrentAnim()

    def _loop_anim(self, anim_name: str | None):
        if self.actor and anim_name:
            self.actor.loop(anim_name)

    def _stop_anim(self):
        if self.actor:
            self.actor.stop()

    def _bind_controls(self):
        if self._controls_bound:
            return
        self._controls_bound = True
        self.accept('z', self.set_key, ['z', True])
        self.accept('z-up', self.set_key, ['z', False])
        self.accept('s', self.set_key, ['s', True])
        self.accept('s-up', self.set_key, ['s', False])
        self.accept('q', self.set_key, ['q', True])
        self.accept('q-up', self.set_key, ['q', False])
        self.accept('d', self.set_key, ['d', True])
        self.accept('d-up', self.set_key, ['d', False])

    def set_mode(self, mode: str):
        next_mode = mode.upper()
        if next_mode == self.mode:
            return
        previous_mode = self.mode
        self.mode = next_mode

        if previous_mode == 'PLAYER' and self._controls_bound:
            self.ignoreAll()
            self._controls_bound = False
            self._reset_controls()
            self._cancel_attack()

        if self.mode in ('AI', 'PLAYER', 'IDLE'):
            self.enable_physics()
        elif self.mode == 'REMOTE':
            self.disable_physics()

        if self.mode == 'PLAYER':
            if GLOBAL_STATE.get_player_id() == 1:
                self._bind_controls()
                self._loop_anim(self.WALK_ANIM)
            else:
                self.disable_physics()
        elif self.mode == 'AI':
            heading = (self.np.getH() + 360.0) % 360.0
            if heading > 180.0:
                heading -= 360.0
            if abs(heading - 90.0) <= abs(heading + 90.0):
                self.direction = 1
                self.np.setH(90.0)
            else:
                self.direction = -1
                self.np.setH(-90.0)
            self._cancel_attack()
            self.is_moving = False
            vel = self.node.getLinearVelocity()
            vel.setX(0)
            vel.setY(0)
            self.node.setLinearVelocity(vel)
            self._ensure_ray_nodes()
            self._loop_anim(self.WALK_ANIM)
        elif self.mode == 'IDLE':
            vel = self.node.getLinearVelocity()
            vel.setX(0)
            vel.setY(0)
            self.node.setLinearVelocity(vel)
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

    def _approach(self, current: float, target: float, max_delta: float) -> float:
        if current < target:
            return min(current + max_delta, target)
        return max(current - max_delta, target)

    def update(self, dt: float):
        if self.mode == 'AI':
            self.update_ai(dt)
        elif self.mode == 'PLAYER':
            self.update_player(dt)
        elif self.mode == 'IDLE':
            self.update_idle()

    def update_idle(self):
        vel = self.node.getLinearVelocity()
        vel.setX(0)
        vel.setY(0)
        self.node.setLinearVelocity(vel)
        if self.IDLE_ANIM and self._current_anim() != self.IDLE_ANIM:
            self._loop_anim(self.IDLE_ANIM)

    def _get_attack_frame(self) -> tuple[int, int]:
        if not self.actor or not self.ATTACK_ANIM:
            return 0, 0
        ctrl = self.actor.getAnimControl(self.ATTACK_ANIM)
        if not ctrl:
            return 0, 0
        return int(ctrl.getFrame()), max(1, int(ctrl.getNumFrames()))

    def perform_attack(self, force: bool = False, restart: bool = False, reverse_if_midpoint: bool = False) -> bool:
        if self.mode != 'PLAYER' and not force:
            return False

        if not self.ATTACK_ANIM:
            self.attack_id += 1
            return True

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
        self._stop_anim()

        attack_interval = ActorInterval(
            self.actor,
            self.ATTACK_ANIM,
            startFrame=start_frame,
            endFrame=end_frame,
        )

        def finish():
            self.is_attacking = False
            if self.is_moving and self.WALK_ANIM:
                self._loop_anim(self.WALK_ANIM)
            elif self.IDLE_ANIM:
                self._loop_anim(self.IDLE_ANIM)

        self.attack_seq = Sequence(attack_interval, Func(finish))
        self.attack_seq.start()
        self.attack_id += 1
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

        if moving and self.WALK_ANIM:
            if self.actor.getCurrentAnim() != self.WALK_ANIM:
                self.actor.loop(self.WALK_ANIM)
            return

        if self.IDLE_ANIM and self.actor.getCurrentAnim() != self.IDLE_ANIM:
            self.actor.loop(self.IDLE_ANIM)

    def update_ai(self, dt: float):
        forward = self.np.getQuat().getForward()
        forward.normalize()

        current = self._current_anim()

        pos = self.np.getPos()
        start = pos + Vec3(0, 0, 0.5)
        from_pos = start + forward * 0.5
        to_pos = start + forward * -0.75

        from_hitzone = start + forward * 0.5
        to_hitzone = start + forward * -3.5

        ledge_from = pos - forward * 2.5 + Vec3(0, 0, -3)
        ledge_to   = ledge_from - Vec3(0, 0, -5.5)

        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        hitzone = self.physics.world.rayTestClosest(from_hitzone, to_hitzone)
        ledge = self.physics.world.rayTestClosest(ledge_from, ledge_to)

        self._draw_debug_ray(0, from_hitzone, to_hitzone)
        self._draw_debug_ray(1, ledge_from, ledge_to)

        if hitzone.hasHit() and hitzone.getNode().getName() == 'Character':
            if not self.is_attacking:
                self.perform_attack(force=True)
        elif result.hasHit() and result.getNode() != self.node and result.getNode().getName() != 'mob' and False:
            self.direction *= -1
            self.np.setH(self.np.getH() + 180)

        if self.ATTACK_ANIM and current == self.ATTACK_ANIM:
            ctrl = self.actor.getAnimControl(self.ATTACK_ANIM)
            if ctrl and ctrl.getFrame() >= ctrl.getNumFrames() - 1:
                if self.WALK_ANIM:
                    self._loop_anim(self.WALK_ANIM)
            if ctrl and ctrl.getFrame() == 42:
                GLOBAL_STATE.get_camera().shake_camera(0.3, 0.2)

        if not ledge.hasHit():
            self.direction *= -1
            self.np.setH(self.np.getH() + 180)
        if self.bounds and pos.x > self.bounds[1]:
            self.direction = -1
            self.np.setH(-90)
        elif self.bounds and pos.x < self.bounds[0]:
            self.direction = 1
            self.np.setH(90)

        vel = self.node.getLinearVelocity()
        if current != self.ATTACK_ANIM:
            vel.setX(self._approach(vel.x, self.direction * self.speed, self.ground_accel * dt))
        else:
            vel.setX(self._approach(vel.x, 0.0, self.ground_friction * dt))
        vel.setY(0.0)
        self.is_moving = abs(vel.x) > 0.1 or abs(vel.y) > 0.1
        self.node.setLinearVelocity(vel)

    def update_player(self, dt: float):
        current = self._current_anim()
        if GLOBAL_STATE.get_player_id() == 1:
            move_x = float(self.keys['d']) - float(self.keys['q'])
            has_move_input = abs(move_x) > 1e-5
            vel = self.node.getLinearVelocity()

            if has_move_input:
                desired_x = move_x * self.control_speed
                desired_y = 0.0
                vel.setX(self._approach(vel.x, desired_x, self.ground_accel * dt))
                vel.setY(self._approach(vel.y, desired_y, self.ground_accel * dt))
                self.node.setLinearVelocity(vel)

                angle = 90.0 if move_x > 0.0 else -90.0
                current_h = self.np.getH()
                h_lerp = min(1.0, dt * 20.0)
                self.np.setH(current_h + (((angle - current_h + 180.0) % 360.0) - 180.0) * h_lerp)

                if not self.is_moving and not self.is_attacking and self.WALK_ANIM:
                    self.is_moving = True
                    self._loop_anim(self.WALK_ANIM)
        
            else:
                self.is_moving = False
                vel.setX(self._approach(vel.x, 0.0, self.ground_friction * dt))
                vel.setY(self._approach(vel.y, 0.0, self.ground_friction * dt))
                self.node.setLinearVelocity(vel)
                if self.IDLE_ANIM:
                    self._stop_anim()
                    self._loop_anim(self.IDLE_ANIM)

            if self.is_attacking and self.ATTACK_ANIM:
                ctrl = self.actor.getAnimControl(self.ATTACK_ANIM)
                if ctrl and ctrl.getFrame() >= ctrl.getNumFrames() - 1:
                    if self.WALK_ANIM:
                        self._loop_anim(self.WALK_ANIM)
                if ctrl and ctrl.getFrame() == 42:
                    GLOBAL_STATE.get_camera().shake_camera(0.3, 0.2)

    def destroy(self):
        self.ignoreAll()
        if self.actor:
            self.actor.cleanup()
        self.physics.detach(self.node)
        for node in self.ray_node:
            if node and not node.isEmpty():
                node.removeNode()
        if self.np and not self.np.isEmpty():
            self.np.removeNode()
