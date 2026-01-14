import asyncio
import websockets
import json

PORT = 8765
players = {}

async def handler(ws):
    if len(players) >= 2:
        await ws.close()
        return

    player_id = str(id(ws))
    pidS = len(players)
    print("New client connected:", player_id)

    players[player_id] = {
        "ws": ws,
        "x": 0,
        "y": 0
    }

    await ws.send(str(pidS))

    try:
        async for msg in ws:
            data = json.loads(msg)

            players[player_id]["x"] = data.get("x", 0)
            players[player_id]["y"] = data.get("y", 0)

            payload = {
                pid: {"x": p["x"], "y": p["y"]}
                for pid, p in players.items()
            }

            for pid, p in players.items():
                if p["ws"] != ws:
                    await p["ws"].send(json.dumps(list(payload.values())[pidS]))

    finally:
        del players[player_id]
        print("Client disconnected:", player_id)

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"Server running on ws://0.0.0.0:{PORT}")
        await asyncio.Future()

asyncio.run(main())
