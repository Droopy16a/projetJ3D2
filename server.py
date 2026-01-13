import asyncio
import websockets
import json
import socket

PORT = 8765
CLIENTS = set()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("8.8.8.8", 80))
IP = s.getsockname()[0]
s.close()

players = {}

async def handler(ws):
    player_id = str(id(ws))
    players[player_id] = {"x": 0, "y": 0}

    try:
        async for msg in ws:
            data = json.loads(msg)
            p = players[player_id]
            p["x"] += data.get("dx",0)
            p["y"] += data.get("dy",0)

            await ws.send(json.dumps(players))
    finally:
        del players[player_id]

async def main():
    async with websockets.serve(handler, IP, PORT):
        print(f"Server running on ws://{IP}:{PORT}")
        await asyncio.Future()

asyncio.run(main())
