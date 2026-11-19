"""Small deterministic checks for online room addressing."""
import unittest

from online_network import ROOM_ALPHABET, _ws_url, make_room_code


class OnlineAddressTests(unittest.TestCase):
    def test_room_codes_are_six_safe_characters(self):
        for _ in range(30):
            code = make_room_code()
            self.assertEqual(len(code), 6)
            self.assertTrue(all(char in ROOM_ALPHABET for char in code))

    def test_websocket_url_uses_secure_transport(self):
        url = _ws_url("ABC234", "host")
        self.assertTrue(url.startswith("wss://"))
        self.assertIn("/ws?room=ABC234&role=host", url)


if __name__ == "__main__":
    unittest.main()
