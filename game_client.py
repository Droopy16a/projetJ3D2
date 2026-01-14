from __future__ import annotations

import json
import random

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
import socket


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

        self.world = World(self.config, self.render, self.loader, self.physics, index=1)

        self.player = Character(self.config, self.render, self.loader, self.physics)

        x,y = self.world.setLimit()

        self.mob = [
            Mob(self.config, self.render, self.loader, self.physics, Vec3(25, 0, 7), mode='PLAYER'),
            # Mob(self.config, self.render, self.loader, self.physics, Vec3(5, 0, 7), x, y)
        ]

        self.taskMgr.add(self._task_physics, 'physics_task')
        self.taskMgr.add(self._task_update, 'update_task')
        self.taskMgr.add(self._task_websocket, 'websocket_task')
        
        self.PORT = 8765
        self.websocket = None
        self.ws_uri = f"ws://192.168.1.17:{self.PORT}"
        self._event_loop = None
        self._connection_established = False
        self._ws_task = None
        
        # Rate limiting for network updates
        self.network_update_interval = 0.1  # Send updates every 100ms (10 times/sec)
        self.time_since_last_send = 0.0

    async def websocket_handler(self):
        """Background task to handle websocket communication"""
        while True:
            try:
                # Connect to server
                print(f"Attempting to connect to {self.ws_uri}...")
                async with websockets.connect(self.ws_uri) as websocket:
                    self.websocket = websocket
                    self._connection_established = True
                    print(f"Connected to server at {self.ws_uri}")
                    
                    # Keep connection alive and handle messages
                    while True:
                        try:
                            # Non-blocking check for incoming messages
                            response = await asyncio.wait_for(
                                websocket.recv(), 
                                timeout=0.001
                            )
                            print(f"You are player number {response}")
                            GLOBAL_STATE.set_player_id(int(response))
                        except asyncio.TimeoutError:
                            # No message received, continue
                            pass
                        
                        # Small sleep to prevent busy-waiting
                        await asyncio.sleep(0.01)
                        
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed, reconnecting in 2 seconds...")
                self._connection_established = False
                await asyncio.sleep(2)
            except Exception as e:
                print(f"Connection error: {e}, retrying in 2 seconds...")
                self._connection_established = False
                await asyncio.sleep(2)

    async def send_player_position(self):
        """Send player position to server"""
        if not self.websocket or not self._connection_established:
            return
        
        try:
            playermv = {
                "x": float(self.player.np.getX()),
                "y": float(self.player.np.getZ()),
            }
            await self.websocket.send(json.dumps(playermv))
        except Exception as e:
            print(f"Error sending position: {e}")
            self._connection_established = False

    def _task_websocket(self, task):
        """Manage websocket communication task"""
        dt = globalClock.getDt()
        
        # Initialize event loop and start websocket handler on first run
        if self._event_loop is None:
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
            
            # Start the background websocket handler
            self._ws_task = self._event_loop.create_task(self.websocket_handler())
        
        # Process pending async operations without blocking
        self._event_loop.stop()
        self._event_loop.run_forever()
        
        # Send player position at limited rate
        self.time_since_last_send += dt
        if self.time_since_last_send >= self.network_update_interval:
            self.time_since_last_send = 0.0
            if self._connection_established:
                # Schedule the send operation
                asyncio.ensure_future(self.send_player_position(), loop=self._event_loop)

        return task.cont

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