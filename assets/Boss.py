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

class Boss(DirectObject.DirectObject):
    def __init__(self, config: Config, render, loader, physics: PhysicsManager,
                 start_pos: Vec3 = Vec3(0, 0, 7), from_pos_bound: int = -20, to_pos_bound: int = 20):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        shape = BulletCapsuleShape(1.5, 3.75, 2)
        self.node = BulletRigidBodyNode('boss')
        self.node.setMass(config.boss_mass)
        self.node.addShape(shape, TransformState.makePos(Vec3(0, 0, 0)))
        self.node.setAngularFactor(Vec3(0, 0, 0))
        self.node.setLinearFactor(Vec3(1, 0, 1))

        self.np = render.attachNewNode(self.node)
        self.np.setPos(start_pos)
        physics.attach(self.node, self.np)

        index = GLOBAL_STATE.increase_mob_number()
        self.np.setCollideMask(bit(index))

        self.actor = Actor(config.boss_model)
        self.actor.reparentTo(self.np)


        cube = [i for i in self.actor.find_all_matches("**/+GeomNode") if "Cube" in i.get_name()]
        print(self.actor.getAnimNames())

        if 'idle' in self.actor.getAnimNames():
            self.actor.loop('idle')

        self.speed = 2.5
        self.direction = 1
        self.bounds = (from_pos_bound, to_pos_bound)
        self.np.setH(90)

        self.ray_vis = LineSegs()
        self.ray_vis.setThickness(2)
        self.ray_node = self.render.attachNewNode(self.ray_vis.create())

    def set_key(self, key, value):
        self.key_map[key] = value

    def update(self, dt: float):
        self.update_ai(dt)

    def update_ai(self, dt: float):
        pos = self.np.getPos()
        if pos.x > self.bounds[1]:
            self.direction = -1
            self.np.setH(-90)
        elif pos.x < self.bounds[0]:
            self.direction = 1
            self.np.setH(90)

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
