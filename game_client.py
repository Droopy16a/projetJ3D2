from __future__ import annotations

import random
import socket

from assets.Character import Character
from assets.Config import Config
from assets.Mob import Mob
from assets.World import World
from assets.PhysicsManager import PhysicsManager

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    Vec3,
    DirectionalLight,
    AmbientLight,
    Vec4,
    WindowProperties,
    loadPrcFileData,
    ConfigVariableString,
)

import simplepbr
from assets.Global_state import GLOBAL_STATE

import asyncio
import websockets


loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #f")
ConfigVariableString("bullet-filter-algorithm").setValue("groups-mask")

class Game(ShowBase):
    def __init__(self, config: Config = Config()):
        super().__init__()
        self.config = config
        self.disableMouse()

        simplepbr.init(
            # use_normal_maps=True,
            enable_shadows=True,
            # use_emission_maps=True,
            env_map="./assets/env/cubemap.env",
        )
        
        props = WindowProperties()
        props.setTitle(self.config.window_title)
        self.win.requestProperties(props)

        GLOBAL_STATE.set_camera(self)
        self.camera.setPos(0, -40, 6)
        self.camera.setHpr(0, 0, 0)

        dlight = DirectionalLight('sun')
        dlight.setColor(Vec4(0.8, 0.8, 0.8, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)

        dlight.setShadowCaster(True, 2048, 2048)

        self.setBackgroundColor(0,0,0,1)
        self.render.setLight(dlnp)

        alight = AmbientLight('alight')
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        self.physics = PhysicsManager(self.config.gravity, self.render)
        # if self.config.debug_physics:
        #     self.physics.enable_debug()

        self.world = World(self.config, self.render, self.loader, self.physics, index=0)

        self.player = Character(self.config, self.render, self.loader, self.physics)

        self.mob = [
            Mob(self.config, self.render, self.loader, self.physics, Vec3(45, 0, 7), 30, 70),
            Mob(self.config, self.render, self.loader, self.physics, Vec3(35, 0, 7), 30, 70)
        ]

        self.accept('mouse1', self.player.perform_attack)

        self.taskMgr.add(self._task_physics, 'physics_task')
        self.taskMgr.add(self._task_update, 'update_task')

        self.PORT = 8765
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        self.IP = s.getsockname()[0]
        s.close()

        asyncio.run(self.connect_to_server(f"ws://{self.IP}:{self.PORT}"))

    async def connect_to_server(self, uri: str):
        async with websockets.connect(uri) as websocket:
            await websocket.send("Hello Server!")
            response = await websocket.recv()
            print(f"Received from server: {response}")

    def _task_physics(self, task):
        dt = globalClock.getDt()
        self.physics.step(dt)
        return task.cont
    
    def shake_camera(self, intensity: float = 0.5, duration: float = 0.5):
        original_pos = self.camera.getPos(self.render)

        self.taskMgr.remove("camera_shake_task")

        def shake_task(task):
            elapsed = task.time

            if elapsed >= duration:
                self.camera.setPos(self.render, original_pos)
                return task.done

            fade = 1 - (elapsed / duration)

            offset = Vec3(
                random.uniform(-1, 1) * intensity * fade,
                random.uniform(-1, 1) * intensity * fade,
                random.uniform(-1, 1) * intensity * fade
            )

            self.camera.setPos(self.render, original_pos + offset)
            return task.cont

        self.taskMgr.add(shake_task, "camera_shake_task")


    def _task_update(self, task):
        dt = globalClock.getDt()

        self.player.update(dt)
        for m in self.mob:
            m.update(dt)

        camx, camy, camz = self.camera.getPos()
        player_x = self.player.np.getPos()[0]

        min_x, max_x = self.world.setLimit()

        camx = max(min_x, min(player_x, max_x))

        self.camera.setPos(camx, camy, camz)

        return task.cont


if __name__ == '__main__':
    game = Game()
    game.run()
