from __future__ import annotations

from dataclasses import dataclass, field
from panda3d.core import Vec3

@dataclass
class Config:
    window_title: str = "DZ jeu"
    gravity: Vec3 = Vec3(0, 0, -9.81)
    player_mass: float = 70.0
    mob_mass: float = 30.0
    cube_mass: float = 200.0
    boss_mass: float = 200.0
    ground_half_extents: Vec3 = Vec3(500, 500, 10)
    debug_physics: bool = True

    speed: float = 10.0
    jump_base: float = 7.0
    jump_charge_max: float = 10.0
    jump_charge_rate: float = 0.1

    player_model: str = "./assets/models/persoepe.glb"
    mob_model: str = "./assets/models/mobA_copy.glb"
    mob_visual_scale: float = 1.0
    mob_visual_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cube_model: str = "./assets/models/box.glb"
    sword_model: str = "./assets/models/sword.glb"
    boss_model : str = "./assets/models/mobAn.glb"

    levels: list = field(default_factory=lambda: [
        {
            "level_model": "./assets/models/plat3.glb",
            "ignore": ["mur_back", "plafond", "porte", "poteau"],
            "size": 1.0,
            "pos": (0, 0, 0),
            "Hpr": (0, 0, 0)
        },
        {
            "level_model": "./assets/models/plat4.glb",
            "ignore": ["mur", "tonneau", "box", "rid", "fontaine"],
            "size": 0.5,
            "pos": (0, 0, 0),
            "Hpr": (0, 0, 0)
        }
    ])
