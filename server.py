import asyncio
import json
import logging
import time
import uuid
import websockets

logging.basicConfig(level=logging.INFO)

CONNECTED = set()
WS_TO_ID = {}
PLAYERS = {} 


async def handler(ws):
    """Handle a single client connection."""
    client_id = str(uuid.uuid4())
    CONNECTED.add(ws)
    WS_TO_ID[ws] = client_id
    PLAYERS[client_id] = {"id": client_id, "x": 0, "y": 0, "vx": 0, "vy": 0, "last_seen": time.time()}
    logging.info(f"Client connected: {client_id}")

    try:
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
                p["x"] = float(msg.get("x", p["x"]))
                p["y"] = float(msg.get("y", p["y"]))
                p["vx"] = float(msg.get("vx", p.get("vx", 0)))
                p["vy"] = float(msg.get("vy", p.get("vy", 0)))
                p["last_seen"] = time.time()
            elif t == "ping":
                PLAYERS[client_id]["last_seen"] = time.time()

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        logging.info(f"Client disconnected: {client_id}")
        CONNECTED.discard(ws)
        WS_TO_ID.pop(ws, None)
        PLAYERS.pop(client_id, None)


async def broadcaster(tick_hz: int = 20):
    """Broadcast all players' state at a fixed frequency."""
    interval = 1.0 / tick_hz
    while True:
        if CONNECTED:
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
            await asyncio.gather(*[safe_send(ws, raw) for ws in webs], return_exceptions=True)

        await asyncio.sleep(interval)


async def safe_send(ws, msg):
    try:
        await ws.send(msg)
    except Exception:
        pass


async def main(host: str = "0.0.0.0", port: int = 8765):
    async with websockets.serve(handler, host, port):
        logging.info(f"Server running on ws://{host}:{port}")
        await broadcaster()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped")
