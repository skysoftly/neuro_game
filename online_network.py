"""WebSocket transport used by NEON VOID online rooms."""
import json
import os
import sys
import threading
import time
from urllib.parse import urlencode

RELAY_URL = os.environ.get(
    "NEON_VOID_RELAY_URL", "wss://neon-void-relay.onrender.com"
).rstrip("/")
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_room_code():
    import random
    return "".join(random.SystemRandom().choice(ROOM_ALPHABET) for _ in range(6))


def _ws_url(room, role):
    base = RELAY_URL
    if base.startswith("https://"):
        base = "wss://" + base[8:]
    elif base.startswith("http://"):
        base = "ws://" + base[7:]
    if not base.startswith(("ws://", "wss://")):
        base = "wss://" + base
    return base + "/ws?" + urlencode({"room": room, "role": role})


class _NativeSocket:
    def __init__(self, url, on_message, on_open=None, on_close=None):
        import importlib
        websocket = importlib.import_module("websocket")
        self._websocket = websocket.create_connection(url, timeout=45, enable_multithread=True)
        self._websocket.settimeout(1)
        self._on_message = on_message
        self._on_close = on_close
        self._running = True
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        if on_open:
            on_open()

    def _read_loop(self):
        while self._running:
            try:
                raw = self._websocket.recv()
                if raw is None:
                    break
                if raw:
                    self._on_message(raw)
            except Exception as exc:
                if self._running and exc.__class__.__name__ not in ("WebSocketTimeoutException",):
                    break
        self._running = False
        if self._on_close:
            self._on_close()

    def send(self, payload):
        if not self._running:
            return False
        try:
            raw = json.dumps(payload, separators=(",", ":"))
            with self._send_lock:
                self._websocket.send(raw)
            return True
        except Exception:
            self._running = False
            return False

    def close(self):
        self._running = False
        try:
            self._websocket.close()
        except Exception:
            pass


class _BrowserSocket:
    def __init__(self, url, on_message, on_open=None, on_close=None):
        import platform
        self._on_message = on_message
        self._on_close = on_close
        self._queue = []
        self._closed = False
        self._ws = platform.window.WebSocket.new(url)
        self._ws.onopen = self._opened
        self._ws.onmessage = self._message
        self._ws.onerror = self._error
        self._ws.onclose = self._closed_event
        self._on_open = on_open

    def _opened(self, _event):
        for payload in self._queue:
            self._send_now(payload)
        self._queue.clear()
        if self._on_open:
            self._on_open()

    def _message(self, event):
        self._on_message(str(event.data))

    def _error(self, _event):
        pass

    def _closed_event(self, _event):
        self._closed = True
        if self._on_close:
            self._on_close()

    def _send_now(self, payload):
        import json
        try:
            self._ws.send(json.dumps(payload, separators=(",", ":")))
            return True
        except Exception:
            return False

    def send(self, payload):
        if self._closed:
            return False
        if int(self._ws.readyState) == 1:
            return self._send_now(payload)
        self._queue.append(payload)
        return True

    def close(self):
        self._closed = True
        try:
            self._ws.close()
        except Exception:
            pass


def _make_socket(room, role, on_message, on_open=None, on_close=None):
    url = _ws_url(room, role)
    if sys.platform == "emscripten":
        return _BrowserSocket(url, on_message, on_open, on_close)
    return _NativeSocket(url, on_message, on_open, on_close)


class RelayHostServer:
    def __init__(self, room_code):
        self.room_code = room_code
        self.clients = {}
        self.inbox = []
        self.lock = threading.Lock()
        self.connection_error = ""
        self.connected = False
        self.socket = _make_socket(
            room_code, "host", self._on_message,
            on_open=lambda: setattr(self, "connected", True),
            on_close=self._on_close,
        )

    def _on_message(self, raw):
        try:
            packet = json.loads(raw)
        except Exception:
            return
        kind = packet.get("t")
        if kind == "peer_message":
            cid = int(packet.get("cid", 0))
            with self.lock:
                self.clients.setdefault(cid, (None, None, "online"))
                self.inbox.append((cid, packet.get("data", {})))
        elif kind == "peer_disconnect":
            cid = int(packet.get("cid", 0))
            with self.lock:
                self.clients.pop(cid, None)
                self.inbox.append((cid, {"t": "disconnect"}))
        elif kind == "error":
            self.connection_error = str(packet.get("message", "Relay error"))
        elif kind == "room_closed":
            self.connection_error = "Комната закрыта сервером"

    def _on_close(self):
        self.connected = False
        with self.lock:
            self.inbox.append((-1, {"t": "relay_disconnect"}))

    def _drop_client(self, cid):
        self.socket.send({"t": "kick", "cid": int(cid)})
        with self.lock:
            self.clients.pop(int(cid), None)

    def broadcast(self, obj):
        self.socket.send({"t": "broadcast", "data": obj})

    def send(self, cid, obj):
        self.socket.send({"t": "send", "cid": int(cid), "data": obj})

    def stop(self):
        self.socket.close()
        with self.lock:
            self.clients.clear()
            self.inbox.clear()


class RelayClientConn:
    def __init__(self, room_code):
        self.inbox = []
        self.lock = threading.Lock()
        self.running = True
        self.dead = False
        self.client_id = None
        self.connection_error = ""
        self._pending = []
        self.socket = _make_socket(
            room_code, "client", self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
        )
        if sys.platform != "emscripten":
            deadline = time.monotonic() + 10
            while self.client_id is None and not self.connection_error and time.monotonic() < deadline:
                time.sleep(0.02)
            if self.client_id is None:
                self.stop()
                raise ConnectionError(self.connection_error or "Тайм-аут подключения к комнате")

    def _on_open(self):
        pass

    def _on_message(self, raw):
        try:
            packet = json.loads(raw)
        except Exception:
            return
        if packet.get("t") == "welcome":
            self.client_id = int(packet.get("id", 0))
            with self.lock:
                self.inbox.append(packet)
            pending, self._pending = self._pending, []
            for message in pending:
                self.socket.send(message)
        elif packet.get("t") == "error":
            self.connection_error = str(packet.get("message", "Ошибка подключения"))
        else:
            with self.lock:
                self.inbox.append(packet)

    def _on_close(self):
        self.dead = True
        self.running = False
        with self.lock:
            self.inbox.append({"t": "disconnect"})

    def send(self, obj):
        if self.dead or not self.running:
            return
        if self.client_id is None:
            self._pending.append(obj)
        else:
            self.socket.send(obj)

    def stop(self):
        self.running = False
        self.socket.close()
