import asyncio
import hashlib
import ipaddress
import json
import os
import socket
from typing import Any

import websockets


PORT = int(os.getenv("DUNGEON_ARISE_PORT", "8765"))
DISCOVERY_PORT = 5000
ROLE_HERO = 0
ROLE_BOSS = 1
clients: dict[int, Any] = {}


def get_local_ip():
    """Get the local WiFi IP address of this machine."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_broadcast_addresses(local_ip: str) -> list[str]:
    """Return broadcast destinations for the local subnet."""
    result = ["<broadcast>"]
    try:
        network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
        result.append(str(network.broadcast_address))
    except Exception:
        result.append("255.255.255.255")
    return result


def get_world_seed(local_ip: str) -> int:
    """Derive the shared world seed from the server address."""
    seed_src = f"{local_ip}:{PORT}"
    return int(hashlib.sha256(seed_src.encode()).hexdigest()[:8], 16)


async def broadcast_discovery(local_ip: str):
    """Periodically broadcast server presence on the local network."""
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    
    seed = get_world_seed(local_ip)
    discovery_message = f"DUNGEON_SERVER:{local_ip}:{PORT}:{seed}".encode()
    broadcast_addresses = get_broadcast_addresses(local_ip)

    while True:
        for addr in broadcast_addresses:
            try:
                await loop.sock_sendto(sock, discovery_message, (addr, DISCOVERY_PORT))
            except Exception:
                pass
        await asyncio.sleep(1)


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


async def main():
    local_ip = get_local_ip()
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"\n{'='*50}")
        seed = get_world_seed(local_ip)
        print(f"Server running!")
        print(f"Local IP: {local_ip}")
        print(f"Port: {PORT}")
        print(f"World seed: {seed}")
        print(f"WebSocket URL: ws://{local_ip}:{PORT}")
        print(f"{'='*50}\n")
        print(f"Broadcasting server discovery on local network...")
        print(f"Clients will auto-connect automatically!\n")
        
        # Start broadcasting server presence
        asyncio.create_task(broadcast_discovery(local_ip))
        
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
