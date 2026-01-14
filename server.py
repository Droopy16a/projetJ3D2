import asyncio
import websockets
import json

PORT = 8765

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
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"Server running on ws://0.0.0.0:{PORT}")
        await asyncio.Future()

asyncio.run(main())
