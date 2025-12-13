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
from assets.PhysicsManager import PhysicsManager

class Character:
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
        self.is_charging_jump = False
        self.is_attacking = False

        self.jump_crouch_frame = 10
        self.jump_fly_frame = 25
        self.jump_sequence: Optional[Sequence] = None
        self.charge = self.config.jump_base

        self.speed = config.speed

        self.ray_vis = LineSegs()
        self.ray_vis.setThickness(2)
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())

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

    def on_ground(self) -> bool:
        from_pos = self.np.getPos() + Vec3(0, 0, 0.5)
        to_pos = self.np.getPos() - Vec3(0, 0, 0.75)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)

        self.ray_vis.reset()
        self.ray_vis.setThickness(2)

        self.ray_vis.setColor(1, 0, 0, 1)
        self.ray_vis.moveTo(from_pos)
        self.ray_vis.drawTo(to_pos)

        self.ray_node.removeNode()
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())

        return result.hasHit()

    def update(self, dt: float):
        if self.is_charging_jump:
            if self.charge < self.config.jump_charge_max:
                self.charge += self.config.jump_charge_rate
            else:
                self.perform_jump()

        move_x = float(self.keys['d']) - float(self.keys['q'])
        move_y = float(self.keys['z']) - float(self.keys['s'])
        move_vec = Vec3(move_x, move_y, 0)

        on_ground = self.on_ground()

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
