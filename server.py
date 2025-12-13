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

async def handler(ws):
    print("Client connected")
    CLIENTS.add(ws)
    try:
        async for msg in ws:
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
    async with websockets.serve(handler, IP, PORT):
        
        print(f"Relay server running on ws://{IP}:{PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
