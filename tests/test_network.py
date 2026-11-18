"""Small protocol regression tests; run with: python -m unittest discover -s tests."""
import socket
import unittest

from network import _recv_msg_blocking, send_msg


class NetworkProtocolTests(unittest.TestCase):
    def test_round_trip_message(self):
        sender, receiver = socket.socketpair()
        try:
            payload = {"t": "snap", "players": [{"pid": 1, "name": "Тест"}], "wave": 4}
            send_msg(sender, payload)
            self.assertEqual(_recv_msg_blocking(receiver), payload)
        finally:
            sender.close()
            receiver.close()

    def test_closed_socket_returns_disconnect_marker(self):
        sender, receiver = socket.socketpair()
        sender.close()
        try:
            self.assertIsNone(_recv_msg_blocking(receiver))
        finally:
            receiver.close()

    def test_oversized_frame_is_rejected(self):
        sender, receiver = socket.socketpair()
        try:
            sender.sendall((8 * 1024 * 1024 + 1).to_bytes(4, "big"))
            self.assertIsNone(_recv_msg_blocking(receiver))
        finally:
            sender.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
