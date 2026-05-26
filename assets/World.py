from __future__ import annotations

import os
import random

from panda3d.core import (
    Filename,
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

END_WALL_THICKNESS = 1.0
END_WALL_Y_HALF_EXTENT = 8.0
END_WALL_HALF_HEIGHT = 256.0


class World:
    def __init__(self, config: Config, render, loader, physics: PhysicsManager, index : int = 0):
        self.config = config.levels[index] if index < len(config.levels) else {}
        self.c = config
        self.render = render
        self.loader = loader
        self.physics = physics
        self.level_root = render.attachNewNode("level_root")
        self.module_nodes: list = []
        self.module_meta: list[dict] = []
        self.module_spacing = float(self.c.module_spacing)

        # ground_shape = BulletBoxShape(config.ground_half_extents)
        # ground_node = BulletRigidBodyNode('Ground')
        # ground_node.addShape(ground_shape)
        # ground_node.setMass(0)
        # self.ground_np = render.attachNewNode(ground_node)
        # self.ground_np.setPos(0, 0, -10)
        # self.ground_np.setHpr(270, 0, 0)
        # physics.attach(ground_node, self.ground_np)

        if self.c.use_modular_world:
            built = self._build_modular_world()
            if not built:
                self._build_static_world()
        else:
            self._build_static_world()


        cube_shape = BulletBoxShape(Vec3(1, 1, 1))
        cube_node = BulletRigidBodyNode('Cube')
        cube_node.setMass(self.c.cube_mass)
        cube_node.addShape(cube_shape, TransformState.makePos(Vec3(0, 0, 1)))
        cube_node.setLinearFactor(Vec3(1, 0, 1))
        cube_node.setAngularFactor(Vec3(0, 1, 0))
        self.cube_np = render.attachNewNode(cube_node)
        self.cube_np.setPos(2, 0, 0)
        physics.attach(cube_node, self.cube_np)
        cube_vis = loader.loadModel(self.c.cube_model)
        cube_vis.reparentTo(self.cube_np)
        cube_vis.setScale(1)

        self.end_wall_nps: list = []
        self._min_bound, self._max_bound = self.level_root.get_tight_bounds()
        self._setup_end_walls()

    def _build_static_world(self):
        if not self.config:
            return
        self.level_model = self.loader.loadModel(self.config["level_model"])
        self.level_model.reparentTo(self.level_root)
        self.level_model.setScale(self.config["size"])
        self.level_model.setPos(self.config["pos"])
        self.level_model.setHpr(self.config["Hpr"])
        apply_bullet_hitboxes(
            self.level_model,
            self.physics.world,
            ignore=self.config["ignore"],
            debug_logs=bool(getattr(self.c, "debug_hitbox_logs", False)),
        )

    def _build_modular_world(self) -> bool:
        module_defs = list(self.c.levels) if getattr(self.c, "levels", None) else []
        if not module_defs:
            module_dir = os.path.abspath(self.c.module_dir)
            if not os.path.isdir(module_dir):
                return False

            module_paths = [
                os.path.join(module_dir, fname)
                for fname in os.listdir(module_dir)
                if fname.lower().endswith(".glb")
            ]
            module_paths.sort()
            if not module_paths:
                return False
            module_defs = [{"level_model": path, "ignore": [], "size": 1.0, "pos": (0, 0, 0), "Hpr": (0, 0, 0)} for path in module_paths]

        rng = random.Random(self.c.module_seed) if self.c.module_seed is not None else random
        module_count = max(2, int(self.c.module_count))
        current_x = 0.0
        base_def = self._find_base_module_def(module_defs)
        if base_def is not None:
            module_sequence = [base_def]
            module_sequence.extend(rng.choice(module_defs) for _ in range(module_count - 2))
            module_sequence.append(base_def)
        else:
            module_sequence = [rng.choice(module_defs) for _ in range(module_count)]

        for module_index, module_def in enumerate(module_sequence):
            path = module_def["level_model"]
            panda_path = Filename.fromOsSpecific(path)
            panda_path.makeTrueCase()
            module = self.loader.loadModel(panda_path)
            module.reparentTo(self.level_root)

            module.setScale(module_def.get("size", 1.0))
            module.setHpr(module_def.get("Hpr", (0, 0, 0)))

            min_bound, max_bound = module.get_tight_bounds()
            if min_bound is None or max_bound is None:
                min_bound = Vec3(0, 0, 0)
                max_bound = Vec3(1, 0, 1)

            width = float(max_bound.x - min_bound.x)
            center_offset = float((min_bound.x + max_bound.x) * 0.5)

            # For modular verticality, we must align by origins (floor level)
            # rather than forcing the bottom of the bounding box to Z=0.
            module.setPos(current_x - min_bound.x, 0, 0)
            apply_bullet_hitboxes(
                module,
                self.physics.world,
                ignore=module_def.get("ignore", []),
                debug_logs=bool(getattr(self.c, "debug_hitbox_logs", False)),
            )

            self.module_nodes.append(module)
            self.module_meta.append(
                {
                    "path": path,
                    "name": os.path.basename(path),
                    "def": module_def,
                    "min_bound": min_bound,
                    "max_bound": max_bound,
                    "width": width,
                    "center_offset": center_offset,
                    "base_z": 0.0,
                    "index": module_index,
                    "locked_endpoint": bool(
                        base_def is not None
                        and self._is_base_module_def(module_def)
                        and module_index in (0, len(module_sequence) - 1)
                    ),
                }
            )
            current_x += width + self.module_spacing

        self.level_model = self.level_root
        
        return True

    def _is_base_module_def(self, module_def: dict) -> bool:
        path = str(module_def.get("level_model", "")).replace("\\", "/").lower()
        name = os.path.splitext(os.path.basename(path))[0]
        return name == "base" or name.endswith("_base") or "base" in name.replace("-", "_").split("_")

    def _find_base_module_def(self, module_defs: list[dict]) -> dict | None:
        for module_def in module_defs:
            if self._is_base_module_def(module_def):
                return module_def
        return None

    def recompute_bounds(self):
        self._min_bound, self._max_bound = self.level_root.get_tight_bounds()
        self._update_end_walls()
    
    def setLimit(self) -> tuple[float, float]:
        if self._min_bound is None or self._max_bound is None:
            print("failed")
            return (-10.0, 10.0)

        return float(self._min_bound.x), float(self._max_bound.x)

    def _setup_end_walls(self):
        if self._min_bound is None or self._max_bound is None:
            return
        if self.end_wall_nps:
            self._update_end_walls()
            return
        for name in ("level_start_wall", "level_end_wall"):
            wall_node = BulletRigidBodyNode(name)
            wall_node.setMass(0)
            wall_node.addShape(
                BulletBoxShape(
                    Vec3(
                        END_WALL_THICKNESS * 0.5,
                        END_WALL_Y_HALF_EXTENT,
                        END_WALL_HALF_HEIGHT,
                    )
                )
            )
            wall_np = self.render.attachNewNode(wall_node)
            wall_np.hide()
            self.physics.attach(wall_node, wall_np)
            self.end_wall_nps.append(wall_np)
        self._update_end_walls()

    def _update_end_walls(self):
        if self._min_bound is None or self._max_bound is None or len(self.end_wall_nps) < 2:
            return
        center_z = float((self._min_bound.z + self._max_bound.z) * 0.5)
        wall_specs = (
            (self.end_wall_nps[0], float(self._min_bound.x) - END_WALL_THICKNESS * 0.5),
            (self.end_wall_nps[1], float(self._max_bound.x) + END_WALL_THICKNESS * 0.5),
        )
        for wall_np, x in wall_specs:
            wall_np.setPos(x, 0, center_z)
            wall_np.hide()
            if hasattr(wall_np.node(), "setTransformDirty"):
                wall_np.node().setTransformDirty()
            if hasattr(wall_np.node(), "setActive"):
                wall_np.node().setActive(True)
