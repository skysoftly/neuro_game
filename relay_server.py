"""NEON VOID public WebSocket relay.

Run with: python relay_server.py
The relay forwards authoritative game messages between one host and up to
11 clients. It does not simulate the game or trust client state.
"""
import asyncio
import json
import os
import re
from dataclasses import dataclass, field

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOM_RE = re.compile(r"^[A-Z0-9]{6}$")
MAX_CLIENTS = 11
MAX_MESSAGE = 1024 * 1024


@dataclass
class Room:
    host: object
    clients: dict = field(default_factory=dict)
    next_id: int = 1


rooms = {}
rooms_lock = asyncio.Lock()


async def send_json(ws, payload):
    await ws.send(json.dumps(payload, separators=(",", ":")))


async def handler(ws):
    room_code = ""
    role = ""
    client_id = None
    try:
        query = ws.request.path.partition("?")[2]
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        room_code = params.get("room", "").upper()
        role = params.get("role", "")
        if not ROOM_RE.fullmatch(room_code) or role not in ("host", "client"):
            await send_json(ws, {"t": "error", "message": "Invalid room or role"})
            return

        if role == "host":
            async with rooms_lock:
                if room_code in rooms:
                    await send_json(ws, {"t": "error", "message": "Room already exists"})
                    return
                rooms[room_code] = Room(host=ws)
            await send_json(ws, {"t": "connected", "role": "host", "room": room_code})
            async for raw in ws:
                try:
                    packet = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = packet.get("t")
                async with rooms_lock:
                    room = rooms.get(room_code)
                    recipients = list(room.clients.items()) if room and room.host is ws else []
                if not recipients:
                    continue
                if kind == "broadcast":
                    data = packet.get("data")
                    await asyncio.gather(
                        *(send_json(peer, data) for _cid, peer in recipients),
                        return_exceptions=True,
                    )
                elif kind == "send":
                    target = int(packet.get("cid", -1))
                    peer = dict(recipients).get(target)
                    if peer:
                        await send_json(peer, packet.get("data"))
        else:
            async with rooms_lock:
                room = rooms.get(room_code)
                if room is None:
                    await send_json(ws, {"t": "error", "message": "Room not found"})
                    return
                if len(room.clients) >= MAX_CLIENTS:
                    await send_json(ws, {"t": "error", "message": "Room is full"})
                    return
                client_id = room.next_id
                room.next_id += 1
                room.clients[client_id] = ws
            await send_json(ws, {"t": "welcome", "id": client_id, "room": room_code})
            async for raw in ws:
                try:
                    packet = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                async with rooms_lock:
                    room = rooms.get(room_code)
                    host = room.host if room else None
                if host:
                    await send_json(host, {
                        "t": "peer_message",
                        "cid": client_id,
                        "data": packet,
                    })
    except ConnectionClosed:
        pass
    finally:
        if room_code:
            async with rooms_lock:
                room = rooms.get(room_code)
                if room:
                    if role == "host" and room.host is ws:
                        peers = list(room.clients.values())
                        rooms.pop(room_code, None)
                    else:
                        peers = []
                        if client_id is not None and room.clients.get(client_id) is ws:
                            room.clients.pop(client_id, None)
                            peers = [room.host]
                else:
                    peers = []
            for peer in peers:
                try:
                    if role == "host":
                        await send_json(peer, {"t": "room_closed"})
                    elif client_id is not None:
                        await send_json(peer, {"t": "peer_disconnect", "cid": client_id})
                except Exception:
                    pass


async def main():
    port = int(os.environ.get("PORT", "10000"))
    async with serve(handler, "0.0.0.0", port, max_size=MAX_MESSAGE,
                     ping_interval=20, ping_timeout=20):
        print(f"NEON VOID relay listening on {port}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
