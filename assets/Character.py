from __future__ import annotations

from typing import Optional, Dict
import math

from panda3d.core import (
    Vec3,
    TransformState, 
    LineSegs,
)
from direct.actor.Actor import Actor
from panda3d.bullet import (
    BulletRigidBodyNode,
    BulletCapsuleShape,
)
from direct.interval.IntervalGlobal import Sequence, ActorInterval, Func
from assets.Config import Config
from assets.Global_state import GLOBAL_STATE
from assets.PhysicsManager import PhysicsManager
from assets.Global_functions import apply_bullet_hitboxes
from direct.showbase import DirectObject

class Character(DirectObject.DirectObject):
    def __init__(self, config: Config, render, loader, physics: PhysicsManager, start_pos: Vec3 = Vec3(0, 0, 5)):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        self.actor = Actor(self.config.player_model)
        self.actor.reparentTo(render)

        shape = BulletCapsuleShape(0.75, 3.0, 2)
        self.node = BulletRigidBodyNode('Character')
        self.node.setMass(config.player_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 2.25)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        self.node.setLinearFactor(Vec3(1, 0, 1))
        self.node.setDeactivationEnabled(False)

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        self.actor.reparentTo(self.np)

        physics.attach(self.node, self.np)

        anims = set(self.actor.getAnimNames())
        self.IDLE_ANIM = 'idle' if 'idle' in anims else (next(iter(anims)) if anims else None)
        self.WALK_ANIM = 'running' if 'running' in anims else self.IDLE_ANIM
        self.JUMP_ANIM = 'jumping' if 'jumping' in anims else None
        self.ATTACK_ANIM = 'atack' if 'atack' in anims else None

        if self.IDLE_ANIM:
            self.actor.loop(self.IDLE_ANIM)

        self.keys: Dict[str, bool] = {k: False for k in ('z', 'q', 's', 'd')}
        self.is_moving = False
        self.is_jumping = False
        self.is_attacking = False
        self._remote_attack_latched = False
        self.jump_buffer_timer = 0.0
        self.jump_buffer_window = 0.14
        self.coyote_timer = 0.0
        self.coyote_window = 0.11
        self.ground_accel = 55.0
        self.air_accel = 28.0
        self.ground_friction = 70.0
        self.air_drag = 6.5
        self.jump_cut_multiplier = 0.55
        self.jump_impulse = self.config.jump_base * 1.30

        if GLOBAL_STATE.get_player_id() == 0:
            self.accept('z', self.set_key, ['z', True])
            self.accept('z-up', self.set_key, ['z', False])
            self.accept('s', self.set_key, ['s', True])
            self.accept('s-up', self.set_key, ['s', False])
            self.accept('q', self.set_key, ['q', True])
            self.accept('q-up', self.set_key, ['q', False])
            self.accept('d', self.set_key, ['d', True])
            self.accept('d-up', self.set_key, ['d', False])
            self.accept('space', self.request_jump)
            self.accept('space-up', self.cut_jump)
        elif GLOBAL_STATE.get_player_id() == 1:
            self.disable_physics()

        self.jump_crouch_frame = 10
        self.jump_fly_frame = 25
        self.jump_sequence: Optional[Sequence] = None

        self.speed = config.speed

        self.ray_vis = [LineSegs(), LineSegs(), LineSegs(), LineSegs()]
        self.ray_node = [None] * len(self.ray_vis)

        for r in range(len(self.ray_vis)):
            self.ray_vis[r].setThickness(2)
            self.ray_node[r] = self.render.attachNewNode(self.ray_vis[r].create())

        self.is_climbing = False
        self.climb_progress = 0.0
        self.climb_start_pos = Vec3(0)
        self.climb_target_pos = Vec3(0)
        self.climb_speed = 2.5

    def disable_physics(self):
        self.node.setKinematic(True)
        self.node.setGravity(Vec3(0))
        self.node.setLinearVelocity(Vec3(0))
        self.node.setAngularVelocity(Vec3(0))

    def set_key(self, key: str, value: bool):
        self.keys[key] = value

    def _approach(self, current: float, target: float, max_delta: float) -> float:
        if current < target:
            return min(current + max_delta, target)
        return max(current - max_delta, target)

    def perform_attack(self):
        self._play_attack_animation()

    def _play_attack_animation(self):
        if self.is_attacking:
            return

        if not self.ATTACK_ANIM:
            return

        self.is_attacking = True
        self.actor.stop()

        attack_interval = ActorInterval(self.actor, self.ATTACK_ANIM)

        def finish():
            self.is_attacking = False
            if self.is_moving and self.WALK_ANIM:
                self.actor.loop(self.WALK_ANIM)
            elif self.IDLE_ANIM:
                self.actor.loop(self.IDLE_ANIM)

        self.attack_seq = Sequence(attack_interval, Func(finish))
        self.attack_seq.start()

    def get_network_anim_state(self) -> dict[str, bool]:
        vel = self.node.getLinearVelocity()
        moving = abs(vel.x) > 0.15 or abs(vel.y) > 0.15
        return {
            "moving": moving,
            "jumping": self.is_jumping,
            "attacking": self.is_attacking,
        }

    def apply_remote_animation(self, moving: bool, attacking: bool, jumping: bool):
        self.is_moving = moving
        if attacking and not self._remote_attack_latched:
            self._play_attack_animation()
        self._remote_attack_latched = attacking

        if attacking:
            return

        if jumping and self.JUMP_ANIM:
            if self.actor.getCurrentAnim() != self.JUMP_ANIM:
                self.actor.loop(self.JUMP_ANIM)
            return

        if moving and self.WALK_ANIM:
            if self.actor.getCurrentAnim() != self.WALK_ANIM:
                self.actor.loop(self.WALK_ANIM)
            return

        if self.IDLE_ANIM and self.actor.getCurrentAnim() != self.IDLE_ANIM:
            self.actor.loop(self.IDLE_ANIM)

    def request_jump(self):
        self.jump_buffer_timer = self.jump_buffer_window

    def cut_jump(self):
        vel = self.node.getLinearVelocity()
        if vel.z > 0:
            vel.setZ(vel.z * self.jump_cut_multiplier)
            self.node.setLinearVelocity(vel)

    def perform_jump(self):
        self.is_jumping = True
        vel = self.node.getLinearVelocity()
        vel.setZ(max(vel.z, 0.0) + self.jump_impulse)
        self.node.setLinearVelocity(vel)

        if self.JUMP_ANIM and self.JUMP_ANIM in self.actor.getAnimNames():
            if self.jump_sequence:
                self.jump_sequence.finish()

            jump_anim = ActorInterval(self.actor, self.JUMP_ANIM, startFrame=self.jump_crouch_frame, endFrame=self.jump_fly_frame)
            finish_func = Func(self.actor.pose, self.JUMP_ANIM, self.jump_fly_frame + 1)
            self.jump_sequence = Sequence(jump_anim, finish_func)
            self.jump_sequence.start()

    def do_climb(self):
        forward = self.np.getQuat().getForward()
        forward.normalize()

        pos = self.np.getPos()

        chest_from = pos + Vec3(0, 0, 3)
        chest_to   = chest_from - forward * 1.2

        head_from = pos + Vec3(0, 0, 4.2)
        head_to   = head_from - forward * 1.2

        ledge_from = pos - forward * 1.0 + Vec3(0, 0, 5.2)
        ledge_to   = ledge_from - Vec3(0, 0, 3.5)

        chest_hit = self.physics.world.rayTestClosest(chest_from, chest_to)
        head_hit  = self.physics.world.rayTestClosest(head_from, head_to)
        ledge_hit = self.physics.world.rayTestClosest(ledge_from, ledge_to)

        for nb, (from_pos, to_pos) in enumerate([(chest_from, chest_to), (head_from, head_to), (ledge_from, ledge_to)]):
            self.ray_vis[nb + 1].reset()
            self.ray_vis[nb + 1].setThickness(2)

            self.ray_vis[nb + 1].setColor(1, 0, 0, 1)
            self.ray_vis[nb + 1].moveTo(from_pos)
            self.ray_vis[nb + 1].drawTo(to_pos)
            
            self.ray_node[nb + 1].removeNode()
            self.ray_node[nb + 1] = self.render.attachNewNode(self.ray_vis[nb + 1].create())

        if chest_hit.hasHit() and not head_hit.hasHit() and ledge_hit.hasHit():
            return True, ledge_hit.getHitPos(), chest_hit.getHitNormal()

        return False, None, None
    
    def start_climb(self, ledge_pos: Vec3, wall_normal: Vec3):
        if self.is_climbing:
            return

        self.is_climbing = True
        self.climb_progress = 0.0

        self.node.setLinearVelocity(Vec3(0))
        self.node.setAngularVelocity(Vec3(0))
        self.node.setGravity(Vec3(0))

        self.node.setKinematic(True)

        self.climb_start_pos = self.np.getPos()

        self.climb_target_pos = (
            ledge_pos +
            Vec3(0, 0, 0.6) -
            wall_normal * 0.6
        )

        self.actor.stop()

    def update_climb(self, dt: float):
        if not self.is_climbing:
            return

        self.climb_progress += dt * 2.5
        t = min(self.climb_progress, 1.0)

        t = t * t * (3 - 2 * t) 

        new_pos = self.climb_start_pos * (1 - t) + self.climb_target_pos * t
        self.np.setPos(new_pos)

        if t >= 1.0:
            self.finish_climb()

    def finish_climb(self):
        self.is_climbing = False

        self.node.setKinematic(False)
        self.node.setGravity(Vec3(0, 0, -9.81))
        self.node.setLinearVelocity(Vec3(0))

        if self.IDLE_ANIM:
            self.actor.loop(self.IDLE_ANIM)

    def on_ground(self) -> bool:
        from_pos = self.np.getPos() + Vec3(0, 0, 0.5)
        to_pos = self.np.getPos() - Vec3(0, 0, 0.75)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)

        self.ray_vis[0].reset()
        self.ray_vis[0].setThickness(2)

        self.ray_vis[0].setColor(1, 0, 0, 1)
        self.ray_vis[0].moveTo(from_pos)
        self.ray_vis[0].drawTo(to_pos)

        self.ray_node[0].removeNode()
        self.ray_node[0] = self.render.attachNewNode(self.ray_vis[0].create())

        return result.hasHit()

    def update(self, dt: float):
        playMode = GLOBAL_STATE.get_player_id()
        if playMode == 0:
            self.update_player_mode(dt)
        elif playMode == 1:
            self.update_boss_mode(dt)

    def update_player_mode(self, dt: float):
        if self.is_climbing:
            self.update_climb(dt)
            return

        move_x = float(self.keys['d']) - float(self.keys['q'])
        move_y = 0.0
        move_vec = Vec3(move_x, move_y, 0.0)

        on_ground = self.on_ground()
        if on_ground:
            self.coyote_timer = self.coyote_window
        else:
            self.coyote_timer = max(0.0, self.coyote_timer - dt)

        if self.jump_buffer_timer > 0.0:
            self.jump_buffer_timer = max(0.0, self.jump_buffer_timer - dt)
            if self.coyote_timer > 0.0 and not self.is_attacking:
                self.perform_jump()
                self.jump_buffer_timer = 0.0
                self.coyote_timer = 0.0

        can_climb, hit_pos, hit_normal = self.do_climb()
        if can_climb and not self.is_climbing and self.is_jumping:
            self.start_climb(hit_pos, hit_normal)
            return

        vel = self.node.getLinearVelocity()
        if move_vec.length() > 0:
            self.is_moving = True
            move_vec.normalize()
            desired_x = move_vec.x * self.speed
            desired_y = move_vec.y * self.speed
            accel = self.ground_accel if on_ground else self.air_accel
            vel.setX(self._approach(vel.x, desired_x, accel * dt))
            vel.setY(self._approach(vel.y, desired_y, accel * dt))
            self.node.setLinearVelocity(vel)

            angle = math.degrees(math.atan2(move_x, -move_y))
            current_h = self.np.getH()
            h_lerp = min(1.0, dt * 20.0)
            self.np.setH(current_h + (((angle - current_h + 180.0) % 360.0) - 180.0) * h_lerp)

            current = self.actor.getCurrentAnim()
            if on_ground and not self.is_jumping and not self.is_attacking:
                if current != self.WALK_ANIM and self.WALK_ANIM in self.actor.getAnimNames():
                    self.actor.stop()
                    self.actor.loop(self.WALK_ANIM)
        else:
            if on_ground:
                vel.setX(self._approach(vel.x, 0.0, self.ground_friction * dt))
                vel.setY(self._approach(vel.y, 0.0, self.ground_friction * dt))
            else:
                vel.setX(self._approach(vel.x, 0.0, self.air_drag * dt))
                vel.setY(self._approach(vel.y, 0.0, self.air_drag * dt))
            self.node.setLinearVelocity(vel)

            if on_ground and not self.is_jumping and not self.is_attacking:
                current = self.actor.getCurrentAnim()
                if self.IDLE_ANIM and current != self.IDLE_ANIM:
                    self.actor.stop()
                    self.actor.loop(self.IDLE_ANIM)
                self.is_moving = False

        if on_ground and self.is_jumping:
            self.is_jumping = False
            if self.JUMP_ANIM:
                self.actor.play(self.JUMP_ANIM, fromFrame=self.jump_fly_frame + 1)
        elif not on_ground:
            self.is_jumping = True

    def update_boss_mode(self, dt: float):
        pass
