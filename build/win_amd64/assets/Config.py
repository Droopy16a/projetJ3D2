from __future__ import annotations

from dataclasses import dataclass, field
from panda3d.core import Vec3

@dataclass
class Config:
    window_title: str = "DZ jeu"
    gravity: Vec3 = Vec3(0, 0, -9.81)
    player_mass: float = 70.0
    mob_mass: float = 30.0
    kayou_mass: float = 100.0
    cube_mass: float = 200.0
    boss_mass: float = 200.0
    ground_half_extents: Vec3 = Vec3(500, 500, 10)
    debug_physics: bool = False
    debug_rays: bool = False
    debug_kayou_hitbox: bool = True
    debug_hitbox_logs: bool = False
    use_modular_world: bool = True
    module_dir: str = "./assets/models/modules"
    module_count: int = 12
    module_spacing: float = 0.2
    module_seed: int | None = None

    speed: float = 10.0
    jump_base: float = 7.0
    jump_charge_max: float = 10.0
    jump_charge_rate: float = 0.1

    player_model_visual_scale = 10.0

    player_model: str = "./assets/models/herolowpoly.glb"
    mob_model: str = "./assets/models/mobrw.glb"
    mob_visual_scale: float = 0.72
    kayou_model: str = "./assets/models/Kayou.glb"
    kayou_visual_scale: float = 1.0
    kayou_visual_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mob_visual_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cube_model: str = "./assets/models/box.glb"
    sword_model: str = "./assets/models/sword.glb"
    boss_model : str = "./assets/models/Boss_Roche.glb"

    levels: list = field(default_factory=lambda: [
        {
            "level_model": "./assets/models/modules/base.glb",
            "ignore": ["ignore*"],
            "size": 2.4,
            "pos": (0, 0, 0),
            "Hpr": (0, 0, 0)
        },
        {
            "level_model": "./assets/models/modules/stair_U.glb",
            "ignore": ["ignore*", "Stairs*"],
            "hitbox_include": ["collision*"],
            "size": 2.4,
            "pos": (0, 0, 0),
            "Hpr": (0, 0, 0)
        },
        {
            "level_model": "./assets/models/modules/stair_D.glb",
            "ignore": ["ignore*", "Stairs*"],
            "hitbox_include": ["collision*"],
            "size": 2.4,
            "pos": (0, 0, 0),
            "Hpr": (0, 0, 0)
        }
    ])
