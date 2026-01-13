from __future__ import annotations

from typing import Optional, Dict
import math

from panda3d.core import (
    Vec3,
    TransformState, 
    LineSegs,
    Shader,
)
from direct.actor.Actor import Actor
from panda3d.bullet import (
    BulletRigidBodyNode,
    BulletCapsuleShape,
    BulletBoxShape,
)
from direct.interval.IntervalGlobal import Sequence, ActorInterval, Func
from assets.Config import Config
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

        # shader = Shader.load(
        #     Shader.SL_GLSL,
        #     "assets/shadow.vert",
        #     "assets/shadow.frag"
        # )

        # self.actor.setShader(shader)

        # apply_bullet_hitboxes(self.actor, physics.world)

        shape = BulletCapsuleShape(0.75, 3.0, 2)
        self.node = BulletRigidBodyNode('Character')
        self.node.setMass(config.player_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 2.25)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        self.node.setLinearFactor(Vec3(1, 0, 1))
        self.node.setDeactivationEnabled(False)

        # np = self.actor.find("*/Object_4.007")

        # parent = np.get_parent()

        # if not parent.node().is_of_type(BulletRigidBodyNode):
        #     min_bound, max_bound = np.get_tight_bounds()
        #     if not (min_bound is None or max_bound is None):
        #         center = (min_bound + max_bound) * 0.5
        #         size = (max_bound - min_bound) * 0.5

        #         shape = BulletBoxShape(Vec3(size))

        #         body = BulletRigidBodyNode(f"hitbox_{np.get_name()}")
        #         body.set_kinematic(True)
        #         body.add_shape(shape, TransformState.make_pos(center))

        #         body_np = parent.attach_new_node(body)
        #         body_np.set_transform(np.get_transform(parent))

        #         self.physics.world.attach(body)

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
        self.is_charging_jump = False
        self.is_attacking = False

        self.accept('z', self.set_key, ['z', True])
        self.accept('z-up', self.set_key, ['z', False])
        self.accept('s', self.set_key, ['s', True])
        self.accept('s-up', self.set_key, ['s', False])
        self.accept('q', self.set_key, ['q', True])
        self.accept('q-up', self.set_key, ['q', False])
        self.accept('d', self.set_key, ['d', True])
        self.accept('d-up', self.set_key, ['d', False])
        self.accept('space', self.start_jump_charge)
        self.accept('space-up', self.perform_jump)

        self.accept('mouse1', self.perform_attack)

        self.jump_crouch_frame = 10
        self.jump_fly_frame = 25
        self.jump_sequence: Optional[Sequence] = None
        self.charge = self.config.jump_base

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

    def set_key(self, key: str, value: bool):
        self.keys[key] = value

    def perform_attack(self):
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

    def start_jump_charge(self):
        if self.on_ground() and not self.is_jumping:
            self.is_charging_jump = True
            self.actor.stop()

            if self.JUMP_ANIM and self.JUMP_ANIM in self.actor.getAnimNames():
                if self.jump_sequence:
                    self.jump_sequence.finish()

                crouch = ActorInterval(self.actor, self.JUMP_ANIM, startFrame=0, endFrame=self.jump_crouch_frame)
                crouch_func = Func(self.actor.pose, self.JUMP_ANIM, self.jump_crouch_frame + 1)
                self.crouch_sequence = Sequence(crouch, crouch_func)
                self.crouch_sequence.start()

    def perform_jump(self):
        if self.is_charging_jump and self.on_ground():
            self.is_charging_jump = False
            self.is_jumping = True
            
            move_vec = Vec3(0, 0, 1)
            move_vec.normalize()

            velocity = move_vec * self.charge
            
            current_x = self.node.getLinearVelocity().x
            current_y = self.node.getLinearVelocity().y
            velocity.setX(current_x)
            velocity.setY(current_y)
            self.node.setLinearVelocity(velocity)

            self.charge = self.config.jump_base

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
        if self.is_climbing:
            self.update_climb(dt)
            return
        
        if self.is_charging_jump:
            if self.charge < self.config.jump_charge_max:
                self.charge += self.config.jump_charge_rate
            else:
                self.perform_jump()

        move_x = float(self.keys['d']) - float(self.keys['q'])
        move_y = float(self.keys['z']) - float(self.keys['s'])
        move_vec = Vec3(move_x, move_y, 0)

        on_ground = self.on_ground()
        can_climb, hit_pos, hit_normal = self.do_climb()
        if can_climb and not self.is_climbing and self.is_jumping:
            self.start_climb(hit_pos, hit_normal)
            return

        if move_vec.length() > 0:
            self.is_moving = True
            move_vec.normalize()
            velocity = move_vec * self.speed
            current_z = self.node.getLinearVelocity().z
            velocity.setZ(current_z)
            self.node.setLinearVelocity(velocity)

            angle = math.degrees(math.atan2(move_x, -move_y))
            self.np.setH(angle)

            current = self.actor.getCurrentAnim()
            if on_ground and not self.is_jumping and not self.is_charging_jump and not self.is_attacking:
                if current != self.WALK_ANIM and self.WALK_ANIM in self.actor.getAnimNames():
                    self.actor.stop()
                    self.actor.loop(self.WALK_ANIM)
        else:
            vel = self.node.getLinearVelocity()
            vel.setX(0)
            vel.setY(0)
            self.node.setLinearVelocity(vel)

            if on_ground and not self.is_jumping and not self.is_charging_jump and not self.is_attacking:
                current = self.actor.getCurrentAnim()
                if self.IDLE_ANIM and current != self.IDLE_ANIM:
                    self.actor.stop()
                    self.actor.loop(self.IDLE_ANIM)
                self.is_moving = False

        if on_ground and self.is_jumping:
            self.is_jumping = False
            if not self.is_charging_jump and self.JUMP_ANIM:
                self.actor.play(self.JUMP_ANIM, fromFrame=self.jump_fly_frame + 1)
        elif not on_ground:
            self.is_jumping = True
