import asyncio
import json
import os
import socket
import threading
from typing import Any

import websockets


PORT = int(os.getenv("DUNGEON_ARISE_PORT", "8765"))
DISCOVERY_PORT = int(os.getenv("DUNGEON_ARISE_DISCOVERY_PORT", "8766"))
DISCOVERY_REQUEST = b"DUNGEON_ARISE_DISCOVER_V1"
DISCOVERY_RESPONSE_TYPE = "dungeon_arise_server"
ROLE_HERO = 0
ROLE_BOSS = 1
clients: dict[int, Any] = {}
_discovery_thread: threading.Thread | None = None
_server_thread: threading.Thread | None = None


def get_available_role() -> int | None:
    for role in (ROLE_HERO, ROLE_BOSS):
        if role not in clients:
            return role
    return None


async def broadcast(payload: dict, exclude_role: int | None = None):
    if not clients:
        return

    encoded = json.dumps(payload)
    stale_roles: list[int] = []
    for role, ws in clients.items():
        if exclude_role is not None and role == exclude_role:
            continue
        try:
            await ws.send(encoded)
        except websockets.exceptions.ConnectionClosed:
            stale_roles.append(role)

    for role in stale_roles:
        clients.pop(role, None)


async def handler(ws):
    role = get_available_role()
    if role is None:
        await ws.close(code=4000, reason="Server full")
        return

    clients[role] = ws
    print(f"Client joined as role={role}")
    await ws.send(json.dumps({"type": "welcome", "player_id": role}))
    await broadcast({"type": "peer_status", "role": role, "status": "joined"}, exclude_role=role)

    try:
        async for message in ws:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue

            await broadcast(
                {"type": "relay", "from": role, "payload": payload},
                exclude_role=role,
            )
    finally:
        if clients.get(role) is ws:
            del clients[role]
        print(f"Client left role={role}")
        await broadcast({"type": "peer_status", "role": role, "status": "left"})


def _discovery_loop(port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
    except OSError as exc:
        print(f"LAN discovery unavailable on UDP {DISCOVERY_PORT}: {exc}")
        return

    print(f"LAN discovery running on udp://0.0.0.0:{DISCOVERY_PORT}")
    while True:
        try:
            data, addr = sock.recvfrom(512)
            if data != DISCOVERY_REQUEST:
                continue
            payload = {
                "type": DISCOVERY_RESPONSE_TYPE,
                "port": port,
            }
            sock.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), addr)
        except OSError:
            return
        except Exception as exc:
            print(f"LAN discovery error: {exc}")


def start_lan_discovery_thread(port: int = PORT):
    global _discovery_thread
    if _discovery_thread is not None and _discovery_thread.is_alive():
        return
    _discovery_thread = threading.Thread(target=_discovery_loop, args=(int(port),), daemon=True)
    _discovery_thread.start()


def start_server_thread(port: int = PORT):
    global PORT, _server_thread
    PORT = int(port)
    if _server_thread is not None and _server_thread.is_alive():
        return
    _server_thread = threading.Thread(target=lambda: asyncio.run(main(PORT)), daemon=True)
    _server_thread.start()


async def main(port: int = PORT):
    active_port = int(port)
    start_lan_discovery_thread(active_port)
    async with websockets.serve(handler, "0.0.0.0", active_port):
        print(f"Server running on ws://0.0.0.0:{active_port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main(PORT))
