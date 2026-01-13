from __future__ import annotations

import math
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

class Mob(DirectObject.DirectObject):
    def __init__(self, config: Config, render, loader, physics: PhysicsManager,
                 start_pos: Vec3 = Vec3(0, 0, 7), from_pos_bound = None, to_pos_bound = None,
                 mode: str = 'AI'):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics
        self.mode = mode.upper()

        self.is_attacking = False
        self.is_moving = False


        shape = BulletCapsuleShape(0.75, 1.0, 2)
        self.node = BulletRigidBodyNode('mob')
        self.node.setMass(config.mob_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        self.node.setLinearFactor(Vec3(1, 0, 1))

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        physics.attach(self.node, self.np)

        index = GLOBAL_STATE.increase_mob_number()
        self.np.setCollideMask(bit(index))

        self.actor = Actor(config.mob_model)
        self.actor.reparentTo(self.np)

        anims = set(self.actor.getAnimNames())
        self.ATTACK_ANIM = 'atack' if 'atack' in anims else None
        self.WALK_ANIM = 'run' if 'run' in anims else None
        self.IDLE_ANIM = ''

        if self.WALK_ANIM:
            self.actor.loop(self.WALK_ANIM)

        self.speed = 2.5
        self.direction = 1
        self.bounds = (from_pos_bound, to_pos_bound) if from_pos_bound and to_pos_bound else None
        self.np.setH(90)

        self.ray_vis = [LineSegs(), LineSegs()]
        self.ray_node = [None] * len(self.ray_vis)

        for r in range(len(self.ray_vis)):
            self.ray_vis[r].setThickness(2)
            self.ray_node[r] = self.render.attachNewNode(self.ray_vis[r].create())

        if self.mode == 'PLAYER':
            self.keys: Dict[str, bool] = {k: False for k in ('z', 'q', 's', 'd')}
            self.accept('z', self.set_key, ['z', True])
            self.accept('z-up', self.set_key, ['z', False])
            self.accept('s', self.set_key, ['s', True])
            self.accept('s-up', self.set_key, ['s', False])
            self.accept('q', self.set_key, ['q', True])
            self.accept('q-up', self.set_key, ['q', False])
            self.accept('d', self.set_key, ['d', True])
            self.accept('d-up', self.set_key, ['d', False])

            self.accept('mouse1', self.perform_attack)


    def set_key(self, key, value):
        self.keys[key] = value

    def update(self, dt: float):
        if self.mode == 'AI':
            self.update_ai(dt)
        elif self.mode == 'PLAYER':
            self.update_player(dt)

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

    def update_ai(self, dt: float):
        forward = self.np.getQuat().getForward()
        forward.normalize()

        current = self.actor.getCurrentAnim()

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

        for nb, i in enumerate([(from_hitzone, to_hitzone), (ledge_from, ledge_to)]):
            self.ray_vis[nb].reset()
            self.ray_vis[nb].setThickness(2)
            self.ray_vis[nb].setColor(1, 0, 0, 1)
            self.ray_vis[nb].moveTo(i[0])
            self.ray_vis[nb].drawTo(i[1])
            self.ray_node[nb].removeNode()
            self.ray_node[nb] = self.render.attachNewNode(self.ray_vis[nb].create())

        if hitzone.hasHit() and hitzone.getNode().getName() == 'Character':
            if current != 'atack' and 'atack' in self.actor.getAnimNames():
                self.actor.stop()
                self.actor.play('atack')
        elif result.hasHit() and result.getNode() != self.node and result.getNode().getName() != 'mob':
            self.direction *= -1
            self.np.setH(self.np.getH() + 180)

        if current == 'atack':
            ctrl = self.actor.getAnimControl('atack')
            if ctrl and ctrl.getFrame() >= ctrl.getNumFrames() - 1:
                self.actor.loop('run')
            if ctrl and ctrl.getFrame() == 17:
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

        if current != 'atack':
            self.np.setPos(pos + Vec3(self.direction * self.speed * dt, 0, 0))

    def update_player(self, dt: float):
        current = self.actor.getCurrentAnim()

        move_x = float(self.keys['d']) - float(self.keys['q'])
        move_y = float(self.keys['z']) - float(self.keys['s'])
        move_vec = Vec3(move_x, move_y, 0)

        if move_vec.length() > 0:
            move_vec.normalize()
            velocity = move_vec * self.speed * 1.5
            current_z = self.node.getLinearVelocity().z
            velocity.setZ(current_z)
            self.node.setLinearVelocity(velocity)

            angle = math.degrees(math.atan2(move_x, -move_y))
            self.np.setH(angle)

            if not self.is_moving and not self.is_attacking and self.WALK_ANIM:
                self.is_moving = True
                self.actor.loop(self.WALK_ANIM)
    
        else:
            self.is_moving = False
            self.actor.stop()
            self.actor.loop(self.IDLE_ANIM)

        if self.is_attacking:
            ctrl = self.actor.getAnimControl('atack')
            if ctrl and ctrl.getFrame() >= ctrl.getNumFrames() - 1:
                self.actor.loop('run')
            if ctrl and ctrl.getFrame() == 17:
                GLOBAL_STATE.get_camera().shake_camera(0.3, 0.2)


