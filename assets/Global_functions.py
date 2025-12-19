from panda3d.core import (
    NodePath,
    TransformState
)

from panda3d.bullet import (
    BulletRigidBodyNode,
    BulletTriangleMesh,
    BulletTriangleMeshShape
)


def apply_bullet_hitboxes(model: NodePath, bullet_world, ignore=[]):
    for np in model.find_all_matches("**/+GeomNode"):
        print("Processing node:", np.get_name())

        if np.get_name() in ignore:
            continue

        parent = np.get_parent()

        if parent.node().is_of_type(BulletRigidBodyNode):
            continue

        geom_node = np.node()

        tri_mesh = BulletTriangleMesh()
        for i in range(geom_node.get_num_geoms()):
            tri_mesh.add_geom(geom_node.get_geom(i))

        if tri_mesh.get_num_triangles() == 0:
            continue

        shape = BulletTriangleMeshShape(tri_mesh, dynamic=False)

        body = BulletRigidBodyNode(f"hitbox_{np.get_name()}")
        body.set_kinematic(True)
        body.add_shape(shape)

        body_np = parent.attach_new_node(body)

        body_np.set_transform(np.get_transform(parent))

        bullet_world.attach(body)

    print("Bullet triangle-mesh hitboxes applied")
