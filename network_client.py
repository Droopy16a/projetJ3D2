import asyncio
import json
import logging
import threading
import time
from typing import Callable

import websockets

logging.basicConfig(level=logging.INFO)


class NetworkClient:
    """Runs an asyncio websocket client in a background thread and keeps remote players' state.

    Usage:
        client = NetworkClient('ws://localhost:8765')
        client.start()
        client.send_position(x, y, vx=0, vy=0)
        remote = client.get_players()
        client.stop()
    """

    def __init__(self, uri: str):
        self.uri = uri
        self.loop = None
        self.thread = None
        self.ws = None
        self.running = False
        self.id = None
        self.players = {}
        self.lock = threading.Lock()

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=1.0)

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            logging.exception('Network client error')

    async def _main(self):
        try:
            async with websockets.connect(self.uri) as ws:
                self.ws = ws
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    msg = json.loads(raw)
                    if msg.get('type') == 'welcome':
                        self.id = msg.get('id')
                except Exception:
                    pass

                receiver = asyncio.create_task(self._receiver(ws))
                await receiver
        except Exception:
            logging.exception('Failed to connect to server')

    async def _receiver(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get('type') == 'state':
                pl = msg.get('players', [])
                with self.lock:
                    self.players = {p['id']: p for p in pl}

    def send_position(self, x, y, vx=0, vy=0):
        if not self.ws or not self.loop:
            return
        data = json.dumps({'type': 'pos', 'x': x, 'y': y, 'vx': vx, 'vy': vy})
        asyncio.run_coroutine_threadsafe(self._safe_send(data), self.loop)

    def send_input(self, left: int, right: int, up: int):
        """Send input state to the server (left/right/up as 0/1)."""
        if not self.ws or not self.loop:
            return
        data = json.dumps({'type': 'input', 'left': int(bool(left)), 'right': int(bool(right)), 'up': int(bool(up))})
        asyncio.run_coroutine_threadsafe(self._safe_send(data), self.loop)

    async def _safe_send(self, data):
        try:
            await self.ws.send(data)
        except Exception:
            pass

    def get_players(self):
        with self.lock:
            return dict(self.players)
