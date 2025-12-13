from __future__ import annotations

import asyncio
import json
import random
import threading
import websockets
from typing import Optional

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
import socket


loadPrcFileData("", "win-size 1920 1080")
loadPrcFileData("", "basic-shaders-only #f")
ConfigVariableString("bullet-filter-algorithm").setValue("groups-mask")


class NetworkClient:
    """Handles WebSocket communication with the relay server"""
    
    def __init__(self, server_url: str = "ws://localhost:8765"):
        self.server_url = server_url
        self.ws = None
        self.is_connected = False
        self.player_id = None
        self.message_queue = asyncio.Queue()
        self.loop = None
        self.thread = None
        
    async def connect(self):
        """Connect to the relay server"""
        try:
            self.ws = await websockets.connect(self.server_url)
            self.is_connected = True
            print(f"Connected to server at {self.server_url}")
            await self._listen()
        except Exception as e:
            print(f"Connection failed: {e}")
            self.is_connected = False
    
    async def _listen(self):
        """Listen for incoming messages from server"""
        try:
            async for msg in self.ws:
                await self.message_queue.put(msg)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed by server")
            self.is_connected = False
        except Exception as e:
            print(f"Listen error: {e}")
            self.is_connected = False
    
    async def send_message(self, data: dict):
        """Send a message to the server"""
        if self.ws and self.is_connected:
            try:
                await self.ws.send(json.dumps(data))
            except Exception as e:
                print(f"Send error: {e}")
    
    def get_message(self) -> Optional[dict]:
        """Get a message from the queue (non-blocking)"""
        try:
            msg = self.message_queue.get_nowait()
            return json.loads(msg)
        except asyncio.QueueEmpty:
            return None
    
    def start(self):
        """Start the async event loop in a background thread"""
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.connect())
        
        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()
        
        # Wait for connection (with timeout)
        import time
        timeout = time.time() + 3
        while not self.is_connected and time.time() < timeout:
            time.sleep(0.1)
        
        if not self.is_connected:
            print("Warning: Could not connect to server. Running in single-player mode.")
    
    def send_async(self, data: dict):
        """Queue a message to send (thread-safe)"""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send_message(data), self.loop)
    
    def stop(self):
        """Stop the network client"""
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)


class Game(ShowBase):
    def __init__(self, config: Config = Config(), is_player1: bool = True, server_url: str = "ws://localhost:8765"):
        super().__init__()
        self.config = config
        self.is_player1 = is_player1
        self.disableMouse()

        simplepbr.init(
            enable_shadows=True,
            use_330=True,
            env_map="./assets/env/cubemap.env",
            calculate_normalmap_blue=True,
        )

        props = WindowProperties()
        title = f"{self.config.window_title} - {'Player 1' if is_player1 else 'Player 2 (Mob Control)'}"
        props.setTitle(title)
        self.win.requestProperties(props)

        GLOBAL_STATE.set_camera(self)
        self.camera.setPos(0, -40, 6)
        self.camera.setHpr(0, 0, 0)

        dlight = DirectionalLight('dlight')
        dlight.setColor(Vec4(0.8, 0.8, 0.8, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)
        self.render.setLight(dlnp)

        alight = AmbientLight('alight')
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        self.physics = PhysicsManager(self.config.gravity, self.render)
        if self.config.debug_physics:
            self.physics.enable_debug()

        self.world = World(self.config, self.render, self.loader, self.physics)

        # Create both player and mob for local display
        self.player = Character(self.config, self.render, self.loader, self.physics)
        self.mob = Mob(self.config, self.render, self.loader, self.physics)

        # Setup network client
        self.network = NetworkClient(server_url)
        self.network.start()

        if is_player1:
            # Player 1 controls the character
            self.accept('z', self.player.set_key, ['z', True])
            self.accept('z-up', self.player.set_key, ['z', False])
            self.accept('s', self.player.set_key, ['s', True])
            self.accept('s-up', self.player.set_key, ['s', False])
            self.accept('q', self.player.set_key, ['q', True])
            self.accept('q-up', self.player.set_key, ['q', False])
            self.accept('d', self.player.set_key, ['d', True])
            self.accept('d-up', self.player.set_key, ['d', False])
            self.accept('space', self.player.start_jump_charge)
            self.accept('space-up', self.player.perform_jump)
            self.accept('mouse1', self.player.perform_attack)

        self.taskMgr.add(self._task_physics, 'physics_task')
        self.taskMgr.add(self._task_update, 'update_task')
        self.taskMgr.add(self._task_network, 'network_task')

    def _task_physics(self, task):
        dt = globalClock.getDt()
        self.physics.step(dt)
        return task.cont

    def _task_network(self, task):
        """Handle network messages"""
        if not self.network.is_connected:
            return task.cont
        
        while True:
            msg = self.network.get_message()
            if msg is None:
                break
            
            self._process_network_message(msg)
        
        # Send local state
        if self.is_player1:
            self._send_player_state()
        else:
            self._send_mob_state()
        
        return task.cont

    def _send_player_state(self):
        """Send player state to other clients"""
        pos = self.player.np.getPos()
        vel = self.player.node.getLinearVelocity()
        
        state = {
            "type": "player_update",
            "pos": [pos.x, pos.y, pos.z],
            "vel": [vel.x, vel.y, vel.z],
            "h": self.player.np.getH(),
            "anim": self.player.actor.getCurrentAnim() if self.player.actor else None,
        }
        self.network.send_async(state)

    def _send_mob_state(self):
        """Send mob state to other clients"""
        pos = self.mob.np.getPos()
        vel = self.mob.node.getLinearVelocity()
        
        state = {
            "type": "mob_update",
            "pos": [pos.x, pos.y, pos.z],
            "vel": [vel.x, vel.y, vel.z],
            "h": self.mob.np.getH(),
            "anim": self.mob.actor.getCurrentAnim() if self.mob.actor else None,
        }
        self.network.send_async(state)

    def _process_network_message(self, msg: dict):
        """Process incoming network message"""
        msg_type = msg.get("type")
        
        if msg_type == "player_update" and not self.is_player1:
            # Update remote player display
            pos = Vec3(msg["pos"][0], msg["pos"][1], msg["pos"][2])
            vel = Vec3(msg["vel"][0], msg["vel"][1], msg["vel"][2])
            
            self.player.np.setPos(pos)
            self.player.node.setLinearVelocity(vel)
            self.player.np.setH(msg["h"])
            
            if msg.get("anim") and self.player.actor:
                if self.player.actor.getCurrentAnim() != msg["anim"]:
                    self.player.actor.loop(msg["anim"])
        
        elif msg_type == "mob_update" and self.is_player1:
            # Update remote mob display
            pos = Vec3(msg["pos"][0], msg["pos"][1], msg["pos"][2])
            vel = Vec3(msg["vel"][0], msg["vel"][1], msg["vel"][2])
            
            self.mob.np.setPos(pos)
            self.mob.node.setLinearVelocity(vel)
            self.mob.np.setH(msg["h"])
            
            if msg.get("anim") and self.mob.actor:
                if self.mob.actor.getCurrentAnim() != msg["anim"]:
                    self.mob.actor.loop(msg["anim"])

    def _task_update(self, task):
        dt = globalClock.getDt()

        if self.is_player1:
            self.player.update(dt)
            # Mob updates from network, but still run physics
            self.mob.update(dt)
            
            # Camera follows player
            camx, camy, camz = self.camera.getPos()
            player_x = self.player.np.getPos()[0]
            self.camera.setPos(player_x, camy, camz)
        else:
            # Player updates received from network
            self.player.update(dt)
            # Mob is controlled locally
            self.mob.update(dt)
            
            # Camera follows mob
            camx, camy, camz = self.camera.getPos()
            mob_x = self.mob.np.getPos()[0]
            self.camera.setPos(mob_x, camy, camz)

        return task.cont


if __name__ == '__main__':
    import sys
    
    # Determine if this is player 1 or player 2
    is_player1 = True
    if len(sys.argv) > 1:
        is_player1 = sys.argv[1].lower() != "player2"
    
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    IP = s.getsockname()[0]
    s.close()
    
    server_url = f"ws://{IP}:8765"
    if len(sys.argv) > 2:
        server_url = sys.argv[2]
    
    print(f"Starting {'Player 1' if is_player1 else 'Player 2 (Mob)'}")
    print(f"Server: {server_url}")
    
    game = Game(is_player1=is_player1, server_url=server_url)
    game.run()
