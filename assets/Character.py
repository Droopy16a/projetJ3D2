from __future__ import annotations

from typing import Optional, Dict

from panda3d.core import (
    Vec3,
    TransformState, 
    LineSegs,
    BitMask32,
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
from direct.showbase import DirectObject

class Character(DirectObject.DirectObject):
    def __init__(self, config: Config, render, loader, physics: PhysicsManager, start_pos: Vec3 = Vec3(0, 0, 15)):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        self.actor = Actor(self.config.player_model)
        self.actor.setScale(self.config.player_model_visual_scale)
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

        # Exclude the shared mob collision bit so the hero won't physically collide with mobs/kayous/bosses
        mask = BitMask32.allOn()
        mask.clearBit(30)
        self.np.setCollideMask(mask)

        self._anim_names = set(self.actor.getAnimNames())
        self.IDLE_ANIM = 'Idle' if 'Idle' in self._anim_names else None
        self.WALK_ANIM = 'Run' if 'Run' in self._anim_names else self.IDLE_ANIM
        self.JUMP_ANIM = 'Jump' if 'Jump' in self._anim_names else None
        self.ATTACK_ANIM = 'Basic Attack' if 'Basic Attack' in self._anim_names else None
        self.BIG_ATTACK_ANIM = 'Big attack' if 'Big attack' in self._anim_names else None

        if self.IDLE_ANIM:
            self.actor.loop(self.IDLE_ANIM)

        self.keys: Dict[str, bool] = {k: False for k in ('z', 'q', 's', 'd')}
        self.is_moving = False
        self.is_jumping = False
        self.is_attacking = False
        self.is_big_attack = False
        self.attack_id = 0
        self._remote_attack_latched = False
        self._remote_attack_id = 0
        self._remote_jump_latched = False
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

        self.jump_crouch_frame = 5
        self.jump_fly_frame = 15
        self.jump_sequence: Optional[Sequence] = None

        self.speed = config.speed

        self.debug_rays = bool(getattr(self.config, "debug_rays", False))
        self.ray_vis: list[LineSegs] = []
        self.ray_node: list = []
        if self.debug_rays:
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

    def perform_attack(self, restart: bool = False, reverse_if_midpoint: bool = False, is_big: bool = False) -> bool:
        if not self.ATTACK_ANIM:
            self.attack_id += 1
            return True
        if not self._play_attack_animation(restart=restart, reverse_if_midpoint=reverse_if_midpoint, is_big=is_big):
            return False
        self.attack_id += 1
        return True

    def _get_attack_frame(self) -> tuple[int, int]:
        if not self.ATTACK_ANIM:
            return 0, 0
        ctrl = self.actor.getAnimControl(self.ATTACK_ANIM)
        if not ctrl:
            return 0, 0
        return int(ctrl.getFrame()), max(1, int(ctrl.getNumFrames()))

    def _play_attack_animation(self, restart: bool = False, reverse_if_midpoint: bool = False, is_big: bool = False) -> bool:
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

        anim_to_play = self.BIG_ATTACK_ANIM if is_big and self.BIG_ATTACK_ANIM else self.ATTACK_ANIM
        if not anim_to_play:
            return False

        self.is_attacking = True
        self.is_big_attack = is_big
        self.actor.stop()

        attack_interval = ActorInterval(
            self.actor,
            anim_to_play,
            startFrame=start_frame,
            endFrame=end_frame,
        )

        def finish():
            self.is_attacking = False
            self.is_big_attack = False
            if self.is_moving and self.WALK_ANIM:
                self.actor.loop(self.WALK_ANIM)
            elif self.IDLE_ANIM:
                self.actor.loop(self.IDLE_ANIM)

        self.attack_seq = Sequence(attack_interval, Func(finish))
        self.attack_seq.start()
        return True

    def get_network_anim_state(self) -> dict[str, Any]:
        vel = self.node.getLinearVelocity()
        moving = self.is_moving or abs(vel.x) > 0.15 or abs(vel.y) > 0.15
        return {
            "moving": moving,
            "jumping": self.is_jumping,
            "attacking": self.is_attacking,
            "attack_id": self.attack_id,
            "is_big": self.is_big_attack,
        }

    def apply_remote_animation(self, moving: bool, attacking: bool, jumping: bool, attack_id: int = 0, is_big: bool = False):
        self.is_moving = moving
        if attack_id > self._remote_attack_id:
            should_play_attack = attacking or self._remote_attack_id > 0
            if should_play_attack:
                if self._play_attack_animation(restart=True, reverse_if_midpoint=self.is_attacking, is_big=is_big):
                    self._remote_attack_id = attack_id
            else:
                self._remote_attack_id = attack_id
        elif attacking and not self._remote_attack_latched:
            self._play_attack_animation(restart=True, is_big=is_big)
        self._remote_attack_latched = attacking

        jump_started = jumping and not self._remote_jump_latched
        jump_ended = (not jumping) and self._remote_jump_latched
        self._remote_jump_latched = jumping

        if attacking:
            return

        if jump_started and self.JUMP_ANIM and self.JUMP_ANIM in self._anim_names:
            if self.jump_sequence:
                self.jump_sequence.finish()

            jump_anim = ActorInterval(
                self.actor,
                self.JUMP_ANIM,
                startFrame=self.jump_crouch_frame,
                endFrame=self.jump_fly_frame,
            )
            finish_func = Func(self.actor.pose, self.JUMP_ANIM, self.jump_fly_frame + 1)
            self.jump_sequence = Sequence(jump_anim, finish_func)
            self.jump_sequence.start()
            return

        if jumping and self.JUMP_ANIM:
            return

        if jump_ended and self.JUMP_ANIM:
            self.actor.play(self.JUMP_ANIM, fromFrame=self.jump_fly_frame + 1)
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

        if self.JUMP_ANIM and self.JUMP_ANIM in self._anim_names:
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

        self._draw_debug_ray(1, chest_from, chest_to)
        self._draw_debug_ray(2, head_from, head_to)
        self._draw_debug_ray(3, ledge_from, ledge_to)

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

        self._draw_debug_ray(0, from_pos, to_pos)

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
        has_move_input = abs(move_x) > 1e-5

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
        if has_move_input:
            self.is_moving = True
            desired_x = move_x * self.speed
            desired_y = 0.0
            accel = self.ground_accel if on_ground else self.air_accel
            vel.setX(self._approach(vel.x, desired_x, accel * dt))
            vel.setY(self._approach(vel.y, desired_y, accel * dt))
            self.node.setLinearVelocity(vel)

            angle = 90.0 if move_x > 0.0 else -90.0
            current_h = self.np.getH()
            h_lerp = min(1.0, dt * 20.0)
            self.np.setH(current_h + (((angle - current_h + 180.0) % 360.0) - 180.0) * h_lerp)

            current = self.actor.getCurrentAnim()
            if on_ground and not self.is_jumping and not self.is_attacking:
                if current != self.WALK_ANIM and self.WALK_ANIM in self._anim_names:
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
