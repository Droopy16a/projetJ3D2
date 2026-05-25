import asyncio
import json
import os
from typing import Any

import websockets


PORT = int(os.getenv("DUNGEON_ARISE_PORT", "8765"))
ROLE_HERO = 0
ROLE_BOSS = 1
clients: dict[int, Any] = {}


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
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"Server running on ws://0.0.0.0:{PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
