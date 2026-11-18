"""Сетевой слой: сервер, клиент, протокол."""
import json
import socket
import struct
import threading

from config import PORT


def send_msg(sock, obj):
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)


def _recvn_blocking(sock, n):
    """
    Читает ровно n байт из блокирующего сокета.
    None  → сокет закрыт (реальный разрыв).
    b""   → «нет данных» (на блокирующем сокете не бывает, но пусть).
    """
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            return b""
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_msg_blocking(sock):
    hdr = _recvn_blocking(sock, 4)
    if hdr is None:
        return None
    if hdr == b"":
        return b""
    if len(hdr) < 4:
        return None
    n = struct.unpack(">I", hdr)[0]
    if n <= 0 or n > 8 * 1024 * 1024:
        return None
    data = _recvn_blocking(sock, n)
    if data is None or data == b"":
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


class HostServer:
    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("0.0.0.0", PORT))
        self.srv.listen(8)
        self.srv.settimeout(0.5)
        self.clients = {}   # cid -> (sock, send_lock, ip)
        self.inbox = []     # [(cid, msg)]
        self.lock = threading.Lock()
        self.next_id = 1
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(None)  # блокирующий
            with self.lock:
                cid = self.next_id
                self.next_id += 1
                self.clients[cid] = (sock, threading.Lock(), addr[0])
            threading.Thread(target=self._client_loop, args=(cid, sock), daemon=True).start()

    def _client_loop(self, cid, sock):
        while self.running:
            try:
                msg = _recv_msg_blocking(sock)
            except Exception:
                msg = None
            if msg is None:
                break
            if msg == b"":
                continue
            with self.lock:
                self.inbox.append((cid, msg))
        with self.lock:
            if cid in self.clients:
                try:
                    self.clients[cid][0].close()
                except Exception:
                    pass
                del self.clients[cid]
            self.inbox.append((cid, {"t": "disconnect"}))

    def send(self, cid, obj):
        with self.lock:
            if cid not in self.clients:
                return
            sock, slock, ip = self.clients[cid]
        try:
            with slock:
                send_msg(sock, obj)
        except Exception:
            pass

    def broadcast(self, obj):
        with self.lock:
            items = list(self.clients.items())
        for cid, (sock, slock, ip) in items:
            try:
                with slock:
                    send_msg(sock, obj)
            except Exception:
                pass

    def stop(self):
        self.running = False
        try:
            self.srv.close()
        except Exception:
            pass
        with self.lock:
            for cid, (sock, slock, ip) in list(self.clients.items()):
                try:
                    sock.close()
                except Exception:
                    pass
            self.clients.clear()


class ClientConn:
    def __init__(self, ip, connect_timeout=4.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(connect_timeout)
        try:
            self.sock.connect((ip, PORT))
        except OSError:
            self.sock.close()
            raise
        # After connect use blocking mode; short timeouts can corrupt partial frames.
        self.sock.settimeout(None)
        self.inbox = []
        self.lock = threading.Lock()
        self.running = True
        self.slock = threading.Lock()
        self.dead = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _mark_dead(self):
        with self.lock:
            if self.dead:
                return
            self.dead = True
            self.running = False
            self.inbox.append({"t": "disconnect"})
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _loop(self):
        while self.running:
            try:
                msg = _recv_msg_blocking(self.sock)
            except Exception:
                msg = None
            if msg is None:
                if self.running:
                    self._mark_dead()
                break
            if msg == b"":
                continue
            with self.lock:
                self.inbox.append(msg)

    def send(self, obj):
        if self.dead or not self.running:
            return
        try:
            with self.slock:
                send_msg(self.sock, obj)
        except (OSError, ValueError):
            self._mark_dead()

    def stop(self):
        self.running = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass