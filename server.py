"""Authoritative WebSocket game server (clean version).

This server uses the modern websockets API where the connection handler is called
with a single `websocket` parameter.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict

import websockets

logging.basicConfig(level=logging.INFO)


@dataclass
class PlayerState:
    id: str
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = False
    last_seen: float = field(default_factory=time.time)
    input: Dict = field(default_factory=lambda: {"left": 0, "right": 0, "up": 0})


# Platforms: same as Main.py
PLATFORMS = [
    (0, 980, 1920, 250),
    (300, 800, 300, 20),
    (700, 600, 300, 20),
    (1100, 400, 300, 20),
]


TICK_RATE = 60
BROADCAST_RATE = 20

CONNECTED: Dict[websockets.WebSocketServerProtocol, str] = {}
PLAYERS: Dict[str, PlayerState] = {}


async def handler(websocket):
    client_id = str(uuid.uuid4())
    CONNECTED[websocket] = client_id
    p = PlayerState(id=client_id, x=100.0 + len(PLAYERS) * 50, y=300.0)
    PLAYERS[client_id] = p
    logging.info(f"Client connected: {client_id}")
    try:
        await websocket.send(json.dumps({"type": "welcome", "id": client_id}))
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "input":
                inp = {"left": int(bool(msg.get("left"))), "right": int(bool(msg.get("right"))), "up": int(bool(msg.get("up")))}
                if client_id in PLAYERS:
                    PLAYERS[client_id].input = inp
                    PLAYERS[client_id].last_seen = time.time()
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        logging.info(f"Client disconnected: {client_id}")
        CONNECTED.pop(websocket, None)
        PLAYERS.pop(client_id, None)


def aabb_collision(ax, ay, aw, ah, bx, by, bw, bh) -> bool:
    return not (ax + aw <= bx or ax >= bx + bw or ay + ah <= by or ay >= by + bh)


def physics_step(dt: float):
    gravity = 1500.0
    speed = 400.0
    jump_v = 700.0
    for p in PLAYERS.values():
        inp = p.input
        p.vx = (-1 * inp.get("left", 0) + inp.get("right", 0)) * speed
        if inp.get("up", 0) and p.on_ground:
            p.vy = -jump_v
            p.on_ground = False
        p.vy += gravity * dt
        p.x += p.vx * dt
        p.y += p.vy * dt
        p.on_ground = False
        for px, py, pw, ph in PLATFORMS:
            if aabb_collision(p.x, p.y, 40, 60, px, py, pw, ph):
                p.y = py - 60
                p.vy = 0
                p.on_ground = True
                break


async def broadcaster():
    interval = 1.0 / BROADCAST_RATE
    while True:
        if CONNECTED:
            state = {"type": "state", "tick": int(time.time() * 1000), "players": [
                {"id": p.id, "x": p.x, "y": p.y, "vx": p.vx, "vy": p.vy} for p in PLAYERS.values()
            ]}
            raw = json.dumps(state)
            webs = list(CONNECTED.keys())
            await asyncio.gather(*[safe_send(ws, raw) for ws in webs], return_exceptions=True)
        await asyncio.sleep(interval)


async def safe_send(ws, msg):
    try:
        await ws.send(msg)
    except Exception:
        pass


async def physics_loop():
    tick = 1.0 / TICK_RATE
    last = time.time()
    while True:
        now = time.time()
        dt = now - last
        if dt > 0.1:
            dt = 0.1
        physics_step(dt)
        last = now
        await asyncio.sleep(tick)


async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    logging.info("Authoritative server started on ws://0.0.0.0:8765")
    await asyncio.gather(physics_loop(), broadcaster())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped")
"""Authoritative WebSocket game server.

Protocol (JSON):
 - Client -> Server:
   {"type": "input", "left": 0/1, "right": 0/1, "up": 0/1}  # per-tick input

 - Server -> Client:
   {"type": "welcome", "id": <id>}  # assigned id
   {"type": "state", "tick": <int>, "players": [{"id":..., "x":..., "y":..., "vx":..., "vy":...}, ...]}

This server simulates simple physics for each player at fixed tick rate and broadcasts authoritative positions.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Tuple, List

import websockets

logging.basicConfig(level=logging.INFO)


@dataclass
class PlayerState:
    id: str
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = False
    last_seen: float = field(default_factory=time.time)
    input: Dict = field(default_factory=lambda: {"left": 0, "right": 0, "up": 0})


# Simple static platforms matching Main.py
PLATFORMS = [
    (0, 980, 1920, 250),
    (300, 800, 300, 20),
    (700, 600, 300, 20),
    (1100, 400, 300, 20),
]


TICK_RATE = 60  # physics ticks per second
BROADCAST_RATE = 20  # how often to broadcast state

CONNECTED: Dict[websockets.WebSocketServerProtocol, str] = {}
PLAYERS: Dict[str, PlayerState] = {}


async def handler(ws, path):
    client_id = str(uuid.uuid4())
    CONNECTED[ws] = client_id
    # spawn player at a default location
    p = PlayerState(id=client_id, x=100.0 + len(PLAYERS) * 50, y=300.0)
    PLAYERS[client_id] = p
    logging.info(f"Client connected: {client_id}")
    try:
        await ws.send(json.dumps({"type": "welcome", "id": client_id}))
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "input":
                inp = {"left": int(bool(msg.get("left"))), "right": int(bool(msg.get("right"))), "up": int(bool(msg.get("up")))}
                if client_id in PLAYERS:
                    PLAYERS[client_id].input = inp
                    PLAYERS[client_id].last_seen = time.time()
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        logging.info(f"Client disconnected: {client_id}")
        CONNECTED.pop(ws, None)
        PLAYERS.pop(client_id, None)


def aabb_collision(ax, ay, aw, ah, bx, by, bw, bh) -> bool:
    return not (ax + aw <= bx or ax >= bx + bw or ay + ah <= by or ay >= by + bh)


def physics_step(dt: float):
    gravity = 1500.0  # px/s^2 (tuned)
    speed = 400.0  # horizontal speed px/s
    jump_v = 700.0  # initial jump velocity px/s

    for p in PLAYERS.values():
        inp = p.input
        # Horizontal
        target_vx = (-1 * inp.get("left", 0) + inp.get("right", 0)) * speed
        p.vx = target_vx

        # Jump
        if inp.get("up", 0) and p.on_ground:
            p.vy = -jump_v
            p.on_ground = False

        # Integrate
        p.vy += gravity * dt
        p.x += p.vx * dt
        p.y += p.vy * dt

        # Ground/platform collision
        # simple AABB check against all platforms; if colliding from above, snap to surface
        p.on_ground = False
        for px, py, pw, ph in PLATFORMS:
            if aabb_collision(p.x, p.y, 40, 60, px, py, pw, ph):
                # if previous y was above the platform (simple correction)
                # snap to top
                p.y = py - 60
                p.vy = 0
                p.on_ground = True
                break


async def broadcaster():
    interval = 1.0 / BROADCAST_RATE
    while True:
        if CONNECTED:
            state = {"type": "state", "tick": int(time.time() * 1000), "players": [
                {"id": p.id, "x": p.x, "y": p.y, "vx": p.vx, "vy": p.vy} for p in PLAYERS.values()
            ]}
            raw = json.dumps(state)
            webs = list(CONNECTED.keys())
            await asyncio.gather(*[safe_send(ws, raw) for ws in webs], return_exceptions=True)
        await asyncio.sleep(interval)


async def safe_send(ws, msg):
    try:
        await ws.send(msg)
    except Exception:
        pass


async def physics_loop():
    tick = 1.0 / TICK_RATE
    last = time.time()
    while True:
        now = time.time()
        dt = now - last
        # clamp dt to avoid large jumps
        if dt > 0.1:
            dt = 0.1
        physics_step(dt)
        last = now
        await asyncio.sleep(tick)


async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    logging.info("Authoritative server started on ws://0.0.0.0:8765")
    await asyncio.gather(physics_loop(), broadcaster())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped")
"""Simple WebSocket server for syncing player positions in the Pygame game.

Protocol (JSON messages):
 - From client -> server:
   {"type": "pos", "x": <float>, "y": <float>, "vx": <float>, "vy": <float>}  # update this client's position

 - From server -> client:
   {"type": "welcome", "id": <string>}  # assigned id for this client
   {"type": "state", "players": [ {"id":..., "x":..., "y":..., "vx":..., "vy":...}, ... ] }

This server trusts client positions (authoritative client). It's simple and intended for local or trusted usage.
"""

import asyncio
import json
import logging
import time
import uuid
import websockets

# Sanity check: make sure we imported the correct `websockets` package.
if not hasattr(websockets, "serve"):
	raise ImportError(
		"Imported module 'websockets' does not expose 'serve'.\n"
		"This usually happens if you have the wrong package installed (e.g. 'websocket-client')\n"
		"or a local file named 'websocket.py' that shadows the real 'websockets' package.\n"
		"Fix: run 'pip install websockets' and ensure there's no 'websocket.py' in your project or PYTHONPATH."
	)

logging.basicConfig(level=logging.INFO)

# Connected websockets and player state
CONNECTED = set()
WS_TO_ID = {}
PLAYERS = {}  # id -> {id,x,y,vx,vy,last_seen}


async def handler(ws, path):
	"""Handle a single client connection."""
	client_id = str(uuid.uuid4())
	CONNECTED.add(ws)
	WS_TO_ID[ws] = client_id
	PLAYERS[client_id] = {"id": client_id, "x": 0, "y": 0, "vx": 0, "vy": 0, "last_seen": time.time()}
	logging.info(f"Client connected: {client_id}")

	try:
		# Send welcome with assigned id
		await ws.send(json.dumps({"type": "welcome", "id": client_id}))

		async for raw in ws:
			try:
				msg = json.loads(raw)
			except Exception:
				continue

			t = msg.get("type")
			if t == "pos":
				p = PLAYERS.get(client_id)
				if p is None:
					continue
				# update player state
				p["x"] = float(msg.get("x", p["x"]))
				p["y"] = float(msg.get("y", p["y"]))
				p["vx"] = float(msg.get("vx", msg.get("vx", p.get("vx", 0))))
				p["vy"] = float(msg.get("vy", msg.get("vy", p.get("vy", 0))))
				p["last_seen"] = time.time()
			elif t == "ping":
				PLAYERS[client_id]["last_seen"] = time.time()
			# ignore other message types for now

	except websockets.exceptions.ConnectionClosed:
		pass
	finally:
		logging.info(f"Client disconnected: {client_id}")
		CONNECTED.discard(ws)
		WS_TO_ID.pop(ws, None)
		PLAYERS.pop(client_id, None)


async def broadcaster(tick_hz: int = 20):
	"""Broadcast the current players' state to all connected clients at tick_hz frequency."""
	interval = 1.0 / tick_hz
	while True:
		if CONNECTED:
			# Trim last_seen older than 10s
			now = time.time()
			stale = [pid for pid, p in PLAYERS.items() if now - p.get("last_seen", 0) > 10]
			for pid in stale:
				PLAYERS.pop(pid, None)

			state = {
				"type": "state",
				"players": [
					{"id": p["id"], "x": p["x"], "y": p["y"], "vx": p.get("vx", 0), "vy": p.get("vy", 0)}
					for p in PLAYERS.values()
				],
			}
			raw = json.dumps(state)
			webs = list(CONNECTED)
			# send concurrently, ignore failing sends
			await asyncio.gather(*[safe_send(ws, raw) for ws in webs], return_exceptions=True)

		await asyncio.sleep(interval)


async def safe_send(ws, msg):
	try:
		await ws.send(msg)
	except Exception:
		# ignore broken connections here; handler cleanup will run
		pass


def start(host: str = "0.0.0.0", port: int = 8765):
	loop = asyncio.get_event_loop()
	ws_server = websockets.serve(handler, host, port)
	loop.run_until_complete(ws_server)
	loop.create_task(broadcaster(20))
	logging.info(f"Server running on ws://{host}:{port}")
	try:
		loop.run_forever()
	except KeyboardInterrupt:
		logging.info("Server stopping")


if __name__ == "__main__":
	start()

