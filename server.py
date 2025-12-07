import asyncio
import websockets
import json

PORT = 8765
CLIENTS = set()

async def handler(ws):
    print("Client connected")
    CLIENTS.add(ws)
    try:
        async for msg in ws:
            # relay to others
            for c in list(CLIENTS):
                if c is not ws:
                    try:
                        await c.send(msg)
                    except Exception:
                        CLIENTS.discard(c)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        CLIENTS.discard(ws)
        print("Client disconnected")

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        
        print(f"Relay server running on ws://0.0.0.0:{PORT}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
