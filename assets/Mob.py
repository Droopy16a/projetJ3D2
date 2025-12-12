from __future__ import annotations

from panda3d.core import (
    Vec3,
    TransformState, 
    BitMask32,
    LineSegs,
)
from direct.actor.Actor import Actor
from panda3d.bullet import (
    BulletRigidBodyNode,
    BulletBoxShape,
)
from assets.Config import Config
from assets.PhysicsManager import PhysicsManager
from assets.global_state import GLOBAL_STATE

def bit(gid: int) -> BitMask32:
    return BitMask32.bit(gid)

class Mob:
    def __init__(self, config: Config, render, loader, physics: PhysicsManager, start_pos: Vec3 = Vec3(0, 0, 7), index: int = 0):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        shape = BulletBoxShape(Vec3(0.5, 0.5, 1))
        self.node = BulletRigidBodyNode('mob')
        self.node.setMass(config.mob_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.node.setAngularFactor(Vec3(0, 0, 0))

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        physics.attach(self.node, self.np)

        self.np.setCollideMask(bit(index))

        self.actor = Actor(config.mob_model)
        self.actor.reparentTo(self.np)
        if 'run' in self.actor.getAnimNames():
            self.actor.loop('run')

        self.speed = 2.5
        self.direction = 1
        self.bounds = (-20, 20)
        self.np.setH(90)

        self.ray_vis = LineSegs()
        self.ray_vis.setThickness(2)
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())


    def update(self, dt: float):
        forward = self.np.getQuat().getForward()
        forward.normalize()

        current = self.actor.getCurrentAnim()

        pos = self.np.getPos()
        start = pos + Vec3(0, 0, 0.5)
        from_pos = start + forward * 0.5
        to_pos   = start + forward * -0.5

        from_hitzone = start + forward * 0.5
        to_hitzone   = start + forward * -3.5

        result = self.physics.world.rayTestClosest(from_pos, to_pos)
        hitzone = self.physics.world.rayTestClosest(from_hitzone, to_hitzone)

        self.ray_vis.reset()
        self.ray_vis.setThickness(2)

        self.ray_vis.setColor(1, 0, 0, 1)
        self.ray_vis.moveTo(from_hitzone)
        self.ray_vis.drawTo(to_hitzone)

        self.ray_node.removeNode()
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())

        if hitzone.hasHit() and hitzone.getNode().getName() == 'Character':
            if current != 'atack' and 'atack' in self.actor.getAnimNames():
                self.actor.stop()
                self.actor.play('atack')

        elif result.hasHit() and result.getNode() != self.node and result.getNode().getName() != 'mob':
            print("Mob hit:", result.getNode().getName())
            self.direction *= -1
            self.np.setH(self.np.getH() + 180)

        if current == 'atack':
            ctrl = self.actor.getAnimControl('atack')
            if ctrl and ctrl.getFrame() >= ctrl.getNumFrames() - 1:
                self.actor.loop('run')
            if ctrl and ctrl.getFrame() == 17:
                GLOBAL_STATE.get_camera().shake_camera(0.3, 0.2)

        
        if pos.x > self.bounds[1]:
            self.direction = -1
            self.np.setH(-90)
        elif pos.x < self.bounds[0]:
            self.direction = 1
            self.np.setH(90)
        
        if current != 'atack':
            self.np.setPos(pos + Vec3(self.direction * self.speed * dt, 0, 0))
