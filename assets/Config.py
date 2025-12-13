from __future__ import annotations

from dataclasses import dataclass
from panda3d.core import Vec3

@dataclass
class Config:
    window_title: str = "DZ jeu"
    gravity: Vec3 = Vec3(0, 0, -9.81)
    player_mass: float = 70.0
    mob_mass: float = 30.0
    cube_mass: float = 200.0
    ground_half_extents: Vec3 = Vec3(500, 500, 10)
    debug_physics: bool = True

    speed: float = 10.0
    jump_base: float = 7.0
    jump_charge_max: float = 10.0
    jump_charge_rate: float = 0.1

    level_model: str = "./assets/models/plat4.glb"
    player_model: str = "./assets/models/persoepe.glb"
    mob_model: str = "./assets/models/mobA.glb"
    cube_model: str = "./assets/models/box.glb"
    sword_model: str = "./assets/models/sword.glb"