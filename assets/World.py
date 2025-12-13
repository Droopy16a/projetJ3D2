from __future__ import annotations

from panda3d.core import (
    Vec3,
    TransformState,
)
from panda3d.bullet import (
    BulletRigidBodyNode,
    BulletBoxShape,
)
from assets.Config import Config
from assets.PhysicsManager import PhysicsManager
from assets.Global_functions import apply_bullet_hitboxes

class World:
    def __init__(self, config: Config, render, loader, physics: PhysicsManager):
        self.config = config
        self.render = render
        self.loader = loader
        self.physics = physics

        # ground_shape = BulletBoxShape(config.ground_half_extents)
        # ground_node = BulletRigidBodyNode('Ground')
        # ground_node.addShape(ground_shape)
        # ground_node.setMass(0)
        # self.ground_np = render.attachNewNode(ground_node)
        # self.ground_np.setPos(0, 0, -10)
        # self.ground_np.setHpr(270, 0, 0)
        # physics.attach(ground_node, self.ground_np)

        self.level_model = loader.loadModel(self.config.level_model)
        self.level_model.reparentTo(render)
        self.level_model.setScale(2.5)
        self.level_model.setPos(0, 0, -10)
        self.level_model.setHpr(270, 0, 0)
        apply_bullet_hitboxes(self.level_model, self.physics.world, ignore = ["Icosphere.001"])


        cube_shape = BulletBoxShape(Vec3(1, 1, 1))
        cube_node = BulletRigidBodyNode('Cube')
        cube_node.setMass(self.config.cube_mass)
        cube_node.addShape(cube_shape, TransformState.makePos(Vec3(0, 0, 1)))
        self.cube_np = render.attachNewNode(cube_node)
        self.cube_np.setPos(2, 0, 0)
        physics.attach(cube_node, self.cube_np)
        cube_vis = loader.loadModel(self.config.cube_model)
        cube_vis.reparentTo(self.cube_np)
        cube_vis.setScale(1)
