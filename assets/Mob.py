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
    BulletCapsuleShape,
)
from assets.Config import Config
from assets.PhysicsManager import PhysicsManager
from assets.Global_state import GLOBAL_STATE
from direct.showbase import DirectObject

def bit(gid: int) -> BitMask32:
    return BitMask32.bit(gid)

class Mob(DirectObject.DirectObject):
    def __init__(self, config: Config, render, loader, physics: PhysicsManager,
                 start_pos: Vec3 = Vec3(0, 0, 7), from_pos_bound: int = -20, to_pos_bound: int = 20,
                 mode: str = 'AI'):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics
        self.mode = mode.upper()

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
        if 'run' in self.actor.getAnimNames():
            self.actor.loop('run')

        self.speed = 2.5
        self.direction = 1
        self.bounds = (from_pos_bound, to_pos_bound)
        self.np.setH(90)

        self.ray_vis = LineSegs()
        self.ray_vis.setThickness(2)
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())

        if self.mode == 'PLAYER':
            self.key_map = {"forward": False, "backward": False, "left": False, "right": False}
            self.accept("w", self.set_key, ["forward", True])
            self.accept("w-up", self.set_key, ["forward", False])
            self.accept("s", self.set_key, ["backward", True])
            self.accept("s-up", self.set_key, ["backward", False])
            self.accept("a", self.set_key, ["left", True])
            self.accept("a-up", self.set_key, ["left", False])
            self.accept("d", self.set_key, ["right", True])
            self.accept("d-up", self.set_key, ["right", False])

    def set_key(self, key, value):
        self.key_map[key] = value

    def update(self, dt: float):
        if self.mode == 'AI':
            self.update_ai(dt)
        elif self.mode == 'PLAYER':
            self.update_player(dt)

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

    def update_player(self, dt: float):
        move_vec = Vec3(0, 0, 0)
        if self.key_map["forward"]:
            move_vec.y += self.speed * dt
        if self.key_map["backward"]:
            move_vec.y -= self.speed * dt
        if self.key_map["left"]:
            move_vec.x -= self.speed * dt
            self.np.setH(180)
        if self.key_map["right"]:
            move_vec.x += self.speed * dt
            self.np.setH(0)
        self.np.setPos(self.np.getPos() + move_vec)
