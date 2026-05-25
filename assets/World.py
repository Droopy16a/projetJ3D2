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

        self._min_bound, self._max_bound = self.level_root.get_tight_bounds()

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
        module_count = max(1, int(self.c.module_count))
        current_x = 0.0

        def add_module(
            module_def: dict,
            locked: bool = False,
            locked_position: str | None = None,
            is_waiting_room: bool = False,
            is_boss_room: bool = False,
        ):
            nonlocal current_x

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

            module.setPos(current_x - min_bound.x, 0, -min_bound.z)
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
                    "name": module_def.get("name", os.path.basename(path)),
                    "def": module_def,
                    "min_bound": min_bound,
                    "max_bound": max_bound,
                    "width": width,
                    "center_offset": center_offset,
                    "base_z": float(module.getZ()),
                    "locked": locked,
                    "locked_position": locked_position,
                    "is_waiting_room": is_waiting_room,
                    "is_boss_room": is_boss_room,
                }
            )
            current_x += width + self.module_spacing

        if getattr(self.c, "waiting_room_enabled", True):
            waiting_room_def = dict(module_defs[0])
            waiting_room_def["level_model"] = getattr(self.c, "waiting_room_model", waiting_room_def["level_model"])
            waiting_room_def["name"] = getattr(self.c, "waiting_room_name", "Salle d'attente")
            add_module(waiting_room_def, locked=True, locked_position="start", is_waiting_room=True)

        for _ in range(module_count):
            module_def = rng.choice(module_defs)
            add_module(module_def)

        if getattr(self.c, "boss_room_enabled", True):
            boss_room_def = dict(module_defs[0])
            boss_room_def["level_model"] = getattr(self.c, "boss_room_model", boss_room_def["level_model"])
            boss_room_def["name"] = getattr(self.c, "boss_room_name", "Salle du boss")
            add_module(boss_room_def, locked=True, locked_position="end", is_boss_room=True)

        self.level_model = self.level_root
        
        return True

    def recompute_bounds(self):
        self._min_bound, self._max_bound = self.level_root.get_tight_bounds()
    
    def setLimit(self) -> tuple[float, float]:
        if self._min_bound is None or self._max_bound is None:
            print("failed")
            return (-10.0, 10.0)

        return float(self._min_bound.x), float(self._max_bound.x)
