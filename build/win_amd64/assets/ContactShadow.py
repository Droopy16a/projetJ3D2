from __future__ import annotations

from math import cos, sin, tau

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
    TransparencyAttrib,
    Vec3,
)


class ContactShadow:
    def __init__(
        self,
        render: NodePath,
        physics,
        owner_np: NodePath,
        radius_x: float = 0.9,
        radius_y: float = 0.45,
        alpha: float = 0.34,
    ):
        self.render = render
        self.physics = physics
        self.owner_np = owner_np
        self.base_alpha = alpha
        self.max_ray_distance = 6.0

        self.np = render.attachNewNode(self._make_node(radius_x, radius_y))
        self.np.setTransparency(TransparencyAttrib.MAlpha)
        self.np.setDepthWrite(False)
        self.np.setBin("transparent", 10)
        self.np.setLightOff(1)

    def _make_node(self, radius_x: float, radius_y: float) -> GeomNode:
        fmt = GeomVertexFormat.getV3c4()
        vdata = GeomVertexData("contact_shadow", fmt, Geom.UHStatic)
        vertex = GeomVertexWriter(vdata, "vertex")
        color = GeomVertexWriter(vdata, "color")

        vertex.addData3(0, 0, 0)
        color.addData4(0, 0, 0, 1)

        segments = 36
        for i in range(segments):
            angle = tau * i / segments
            vertex.addData3(cos(angle) * radius_x, sin(angle) * radius_y, 0)
            color.addData4(0, 0, 0, 0)

        tris = GeomTriangles(Geom.UHStatic)
        for i in range(segments):
            tris.addVertices(0, i + 1, ((i + 1) % segments) + 1)

        geom = Geom(vdata)
        geom.addPrimitive(tris)

        node = GeomNode("contact_shadow")
        node.addGeom(geom)
        return node

    def update(self):
        if self.owner_np.isEmpty() or self.np.isEmpty():
            return

        pos = self.owner_np.getPos(self.render)
        from_pos = pos + Vec3(0, 0, 0.6)
        to_pos = pos - Vec3(0, 0, self.max_ray_distance)
        result = self.physics.world.rayTestClosest(from_pos, to_pos)

        if not result.hasHit():
            self.np.hide()
            return

        hit_pos = result.getHitPos()
        distance = max(0.0, pos.z - hit_pos.z)
        fade = max(0.0, min(1.0, 1.0 - distance / 4.0))

        self.np.show()
        self.np.setPos(pos.x, pos.y, hit_pos.z + 0.035)
        self.np.setScale(1.0 + distance * 0.08, 1.0 + distance * 0.04, 1.0)
        self.np.setAlphaScale(self.base_alpha * fade)

    def destroy(self):
        if not self.np.isEmpty():
            self.np.removeNode()
