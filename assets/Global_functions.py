from panda3d.core import (
    NodePath, 
    Vec3, 
    TransformState
)

from panda3d.bullet import (
    BulletRigidBodyNode, 
    BulletBoxShape
)

def apply_bullet_hitboxes(model: NodePath, bullet_world, ignore = []):
    for np in model.find_all_matches("**/+GeomNode"):
        if np.get_name() in ignore:
            continue

        parent = np.get_parent()

        if parent.node().is_of_type(BulletRigidBodyNode):
            continue

        min_bound, max_bound = np.get_tight_bounds()
        if min_bound is None or max_bound is None:
            continue

        center = (min_bound + max_bound) * 0.5
        size = (max_bound - min_bound) * 0.5

        shape = BulletBoxShape(Vec3(size))

        body = BulletRigidBodyNode(f"hitbox_{np.get_name()}")
        body.set_kinematic(True)
        body.add_shape(shape, TransformState.make_pos(center))

        body_np = parent.attach_new_node(body)
        body_np.set_transform(np.get_transform(parent))

        bullet_world.attach(body)

    print("Bullet hitboxes applied")