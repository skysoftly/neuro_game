"""Integration tests for the public WebSocket relay."""
import asyncio
import json
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import relay_server


class RelayServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_and_client_exchange_game_packets(self):
        room_code = "TST234"
        async with serve(
            relay_server.handler, "127.0.0.1", 0,
            max_size=relay_server.MAX_MESSAGE,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}/ws"
            async with connect(f"{url}?room={room_code}&role=host") as host:
                host_ready = json.loads(await asyncio.wait_for(host.recv(), 2))
                self.assertEqual(host_ready["t"], "connected")

                async with connect(f"{url}?room={room_code}&role=client") as client:
                    welcome = json.loads(await asyncio.wait_for(client.recv(), 2))
                    self.assertEqual(welcome["t"], "welcome")
                    self.assertEqual(welcome["id"], 1)

                    await client.send(json.dumps({"t": "hello", "name": "Tester"}))
                    forwarded = json.loads(await asyncio.wait_for(host.recv(), 2))
                    self.assertEqual(forwarded["t"], "peer_message")
                    self.assertEqual(forwarded["cid"], 1)
                    self.assertEqual(forwarded["data"]["name"], "Tester")

                    await host.send(json.dumps({
                        "t": "broadcast",
                        "data": {"t": "lobby", "players": [[0, "Host"], [1, "Tester"]]},
                    }))
                    lobby = json.loads(await asyncio.wait_for(client.recv(), 2))
                    self.assertEqual(lobby["t"], "lobby")
                    self.assertEqual(len(lobby["players"]), 2)

                    await client.close()
                    disconnected = json.loads(await asyncio.wait_for(host.recv(), 2))
                    self.assertEqual(disconnected, {"t": "peer_disconnect", "cid": 1})


if __name__ == "__main__":
    unittest.main()
