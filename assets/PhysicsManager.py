from __future__ import annotations

from panda3d.core import (
    Vec3
)
from panda3d.bullet import (
    BulletWorld,
    BulletRigidBodyNode,
    BulletDebugNode,
)

class PhysicsManager:
    def __init__(self, gravity: Vec3, render):
        self.world = BulletWorld()
        self.world.setGravity(gravity)
        self._render = render
        self._debug_np = None

    def attach(self, node: BulletRigidBodyNode, np):
        self.world.attachRigidBody(node)

    def detach(self, node: BulletRigidBodyNode):
        self.world.removeRigidBody(node)

    def enable_debug(self):
        if self._debug_np is not None:
            return
        debug_node = BulletDebugNode('BulletDebug')
        self._debug_np = self._render.attachNewNode(debug_node)
        self._debug_np.show()
        self.world.setDebugNode(debug_node)

    def step(self, dt: float):
        clamped_dt = min(max(dt, 0.0), 1.0 / 30.0)
        self.world.doPhysics(clamped_dt, 12, 1.0 / 120.0)
