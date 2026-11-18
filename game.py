"""Основной класс игры: логика, рендер, сеть, состояния."""
import json
import logging
import math
import os
import random
import socket
import sys
import array
import pygame
from pygame import Vector2 as V

from config import (
    W, H, WORLD_W, WORLD_H, PORT, CONFIG_FILE,
    BG, CYAN, MAGENTA, YELLOW, RED, ORANGE, GREEN, PURPLE, PINK, WHITE,
    SHIP, DIAMOND, TRI, HEX, SQ,
    KINDS, PICK_COL, PICK_LET, PLAYER_COLORS,
)
from fonts import font, text
from draw_utils import shape, dim, make_overlay, bloom, read_clipboard
from camera import Camera
from entities import Player, Enemy, Particle, Ring, Bullet
from upgrades import UPGRADES_BY_ID, apply_upgrade, roll_upgrades
from network import HostServer, ClientConn
from visuals import draw_glow

log = logging.getLogger("neuro_game")


# ---------- конфиг ----------
def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


# ---------- звук ----------
class Audio:
    def __init__(self):
        self.s = {}
        self.ok = False
        if not pygame.mixer.get_init():
            return
        try:
            # Softer, more varied synth tones; avoid harsh square-wave blasts.
            self.s = {
                "shoot": [
                    self.make(760, 520, 0.055, 0.035, "tri", 0.0),
                    self.make(820, 560, 0.050, 0.030, "sin", 0.0),
                    self.make(690, 470, 0.060, 0.032, "tri", 0.0),
                ],
                "hit": [
                    self.make(260, 170, 0.075, 0.055, "sin", 0.08),
                    self.make(310, 190, 0.065, 0.045, "tri", 0.04),
                ],
                "boom": [
                    self.make(115, 42, 0.24, 0.10, "sin", 0.12),
                    self.make(95, 35, 0.28, 0.085, "sin", 0.08),
                    self.make(135, 48, 0.20, 0.09, "tri", 0.06),
                ],
                "dash": [
                    self.make(260, 920, 0.19, 0.065, "sin", 0.0),
                    self.make(310, 1080, 0.16, 0.055, "tri", 0.0),
                ],
                "pickup": [
                    self.make(520, 1040, 0.16, 0.055, "tri", 0.0),
                    self.make(620, 1240, 0.14, 0.050, "sin", 0.0),
                ],
                "pulse": self.make(520, 90, 0.42, 0.12, "sin", 0.04),
                "hurt": self.make(220, 85, 0.20, 0.10, "tri", 0.05),
                "levelup": self.make(440, 880, 0.28, 0.055, "sin", 0.0),
                "ui_click": self.make(520, 390, 0.045, 0.025, "sin", 0.0),
                "ui_hover": self.make(680, 760, 0.025, 0.012, "sin", 0.0),
                "ready": self.make(440, 990, 0.24, 0.06, "sin", 0.0),
                "wave": self.make(260, 520, 0.42, 0.06, "tri", 0.0),
            }
            self.ok = True
            self.music = self.make_music()
            self.music_channel = pygame.mixer.Channel(7)
            self.music_channel.set_volume(0.12)
            self.music_channel.play(self.music, loops=-1)
        except Exception:
            self.ok = False
            log.exception("Не удалось инициализировать аудио")

    @staticmethod
    def make_music():
        """Longer, quieter ambient chiptune with space between phrases."""
        rate = 44100
        melody = (440, 0, 523, 659, 0, 587, 523, 0, 392, 0, 440, 523, 0, 494, 440, 0,
                  349, 0, 392, 440, 0, 523, 494, 0, 330, 0, 392, 494, 0, 440, 392, 0)
        bass = (110, 110, 130.81, 130.81, 98, 98, 87.31, 87.31)
        count = int(rate * 0.28)
        buf = array.array("h")
        for step, note in enumerate(melody):
            lead_phase = bass_phase = 0.0
            for i in range(count):
                bass_phase += bass[(step // 4) % len(bass)] / rate
                env = min(1.0, i / 1800) * min(1.0, (count - i) / 3500)
                low = math.sin(bass_phase * math.tau) * env * 0.035
                lead = 0.0
                if note:
                    lead_phase += note / rate
                    tri = 1.0 - 4.0 * abs(round(lead_phase) - lead_phase)
                    lead_env = min(1.0, i / 1400) * min(1.0, (count - i) / 3000)
                    lead = tri * lead_env * 0.032
                buf.append(int(max(-1.0, min(1.0, lead + low)) * 32767))
        return pygame.mixer.Sound(buffer=buf.tobytes())
    @staticmethod
    def make(f0, f1, dur, vol, wave, noise):
        rate = 44100
        n = max(1, int(rate * dur))
        buf = array.array("h")
        phase = 0.0
        for i in range(n):
            t = i / n
            phase += (f0 + (f1 - f0) * t) / rate
            if wave == "sq":
                sample = 1.0 if phase % 1.0 < 0.5 else -1.0
            elif wave == "tri":
                sample = 1.0 - 4.0 * abs(round(phase) - phase)
            else:
                sample = math.sin(phase * math.tau)
            sample = sample * (1 - noise) + random.uniform(-1, 1) * noise
            envelope = min(1.0, i / max(1, int(rate * 0.008))) * (1 - t) ** 1.6
            buf.append(int(sample * envelope * vol * 32767))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def play(self, name):
        if self.ok and name in self.s:
            sound = self.s[name]
            if isinstance(sound, list):
                sound = random.choice(sound)
            sound.play()


# ---------- игра ----------
class Game:
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("NEON VOID — СЕТЕВАЯ")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.scene = pygame.Surface((W, H)).convert()

        self.audio = Audio()
        self.f_huge = font(96)
        self.f_big = font(52)
        self.f_mid = font(30)
        self.f_small = font(18)
        self.f_hint = font(20)

        self.overlay = make_overlay(W, H)
        self.stars = [[random.uniform(0, W), random.uniform(0, H), random.uniform(0.2, 1.0)] for _ in range(200)]
        self.t = 0.0
        self.state = "menu"
        self.error_msg = ""
        self.paused = False
        self.shake = 0.0
        self.spectator_speed = 620.0
        self.flash = 0.0
        self.banner_t = 0.0
        self.intermission = False
        self.local_upgrade_waiting = False
        self.wave = 0
        self.hitstop = 0.0
        self.show_help = True
        self.help_t = 10.0
        self.debug_overlay = False
        self.debug_timer = 0.0

        cfg = load_config()
        self.last_ip = cfg.get("last_ip", "")
        self.first_run = not bool(str(cfg.get("name", "")).strip())
        self.name_input = str(cfg.get("name", "")).strip() if not self.first_run else ""
        self.ip_input = self.last_ip
        self.lan_ips = get_lan_ips()

        self.is_host = False
        self.server = None
        self.client = None
        self.my_id = 0
        self.lobby_players = []
        self.input_mode = "name" if self.first_run else None
        self.connect_error = ""

        self.camera = Camera(W, H, WORLD_W, WORLD_H)

        self.players = {}
        self.bullets = []
        self.ebullets = []
        self.enemies = []
        self.parts = []
        self.rings = []
        self.pickups = []   # [pos, kind, ttl]
        self.pops = []      # [pos, text, ttl, color]
        self.queue = []
        self.spawn_t = 0.0
        self.wave_delay = 1.5
        self.rng = random.Random()

        # у клиента: локальные данные из снапшота
        self.snap = None
        self.local_choices = []   # id апгрейдов для оверлея выбора
        self._last_hovered_button = None

        pygame.mouse.set_visible(True)

    def persist(self):
        save_config({"last_ip": self.last_ip, "name": self.name_input})

    def logical_mouse(self, pos=None):
        if pos is None:
            pos = pygame.mouse.get_pos()
        sw, sh = self.screen.get_size()
        return (pos[0] * W / max(1, sw), pos[1] * H / max(1, sh))

    def draw_button(self, surface, rect, label, color=CYAN, enabled=True):
        # Старая панельная кнопка: тёмная эмаль, двойная рамка и светлая грань.
        mouse = self.logical_mouse()
        hovered = enabled and rect.collidepoint(mouse)
        hover_key = (rect.x, rect.y, rect.w, rect.h, label)
        if hovered and self._last_hovered_button != hover_key:
            self.audio.play("ui_hover")
            self._last_hovered_button = hover_key
        elif not hovered and self._last_hovered_button == hover_key:
            self._last_hovered_button = None
        fill = (25, 37, 52) if not hovered else (39, 57, 72)
        edge = color if enabled else (75, 82, 94)
        shadow = pygame.Rect(rect.x + 4, rect.y + 5, rect.w, rect.h)
        pygame.draw.rect(surface, (3, 7, 15), shadow)
        pygame.draw.rect(surface, (9, 15, 26), rect)
        inner = rect.inflate(-4, -4)
        pygame.draw.rect(surface, fill, inner)
        light = dim(edge, 0.82 if hovered else 0.52)
        dark = dim(edge, 0.28)
        pygame.draw.line(surface, light, (rect.left + 2, rect.top + 2),
                         (rect.right - 3, rect.top + 2), 2)
        pygame.draw.line(surface, light, (rect.left + 2, rect.top + 2),
                         (rect.left + 2, rect.bottom - 3), 2)
        pygame.draw.line(surface, dark, (rect.left + 2, rect.bottom - 2),
                         (rect.right - 2, rect.bottom - 2), 2)
        pygame.draw.line(surface, dark, (rect.right - 2, rect.top + 2),
                         (rect.right - 2, rect.bottom - 2), 2)
        pygame.draw.rect(surface, edge, rect, 1)
        if hovered:
            pygame.draw.rect(surface, dim(edge, 0.35), inner, 1)
        label_color = WHITE if enabled else (112, 120, 132)
        text(surface, label, self.f_mid if rect.height >= 50 else self.f_small,
             label_color, (rect.centerx, rect.centery - (1 if hovered else 0)), outline=1)
        return hovered
    # ================= сеть =================
    def start_host(self):
        log.info("Запуск лобби хоста")
        self.connect_error = ""
        try:
            self.server = HostServer()
        except Exception as e:
            self.set_error("Не удалось создать сервер: %s\nВозможно, порт %d занят." % (e, PORT))
            return
        self.is_host = True
        self.my_id = 0
        self.lobby_players = [(0, self.name_input or "Хост")]
        self.state = "lobby"

    def join_server(self, ip):
        log.info("Подключение к хосту %s:%d", ip, PORT)
        self.connect_error = ""
        ip = ip.strip()
        if not ip:
            self.set_error("Не указан IP-адрес хоста.")
            return
        try:
            self.client = ClientConn(ip)
        except Exception as e:
            log.exception("Не удалось подключиться к %s:%d", ip, PORT)
            self.set_error("ИГРА НЕ НАЙДЕНА\nПо адресу %s:%d никто не отвечает.\nПроверь IP и убедись, что хост запущен." % (ip, PORT))
            return
        self.is_host = False
        self.last_ip = ip
        self.persist()
        self.client.send({"t": "hello", "name": self.name_input or "Клиент"})
        self.state = "lobby"
        self.lobby_players = []

    def set_error(self, msg):
        log.error("Состояние ошибки: %s", msg.replace("\n", " | "))
        self.error_msg = msg
        self.state = "error"
        pygame.mouse.set_visible(True)

    def leave_net(self):
        if self.server:
            self.server.stop()
            self.server = None
        if self.client:
            self.client.stop()
            self.client = None
        self.is_host = False
        self.my_id = 0
        self.lobby_players = []
        self.players = {}
        self.bullets, self.ebullets, self.enemies = [], [], []
        self.parts, self.rings, self.pickups, self.pops = [], [], [], []
        self.queue = []
        self.local_choices = []
        self.local_upgrade_waiting = False
        self.intermission = False
        self.snap = None
        self.paused = False
        self.hitstop = 0.0
        self.shake = 0.0
        self.flash = 0.0
        self.camera.x = max(0, (WORLD_W - W) / 2)
        self.camera.y = max(0, (WORLD_H - H) / 2)
        self.state = "menu"
        pygame.mouse.set_visible(True)

    def host_start_game(self):
        if not self.is_host:
            return
        self.players = {}
        for pid, name in self.lobby_players:
            self.players[pid] = Player(pid, name)
        self.bullets, self.ebullets, self.enemies = [], [], []
        self.parts, self.rings, self.pickups, self.pops = [], [], [], []
        self.queue = []
        self.local_choices = []
        self.snap = None
        self.paused = False
        self.wave = 0
        self.wave_delay = 1.5
        self.spawn_t = 0.0
        self.intermission = False
        self.local_upgrade_waiting = False
        self.banner_t = 2.0
        self.help_t = 10.0
        self.state = "play"
        pygame.mouse.set_visible(False)
        self.camera.follow(self.players[self.my_id].p.x, self.players[self.my_id].p.y, 0, snap=True)
        self.server.broadcast({"t": "start"})

    def poll_network(self):
        if self.is_host and self.server:
            with self.server.lock:
                msgs = self.server.inbox[:]
                self.server.inbox.clear()
            for cid, m in msgs:
                self.on_host_msg(cid, m)
        elif (not self.is_host) and self.client:
            with self.client.lock:
                msgs = self.client.inbox[:]
                self.client.inbox.clear()
            for m in msgs:
                self.on_client_msg(m)

    def on_host_msg(self, cid, m):
        t = m.get("t")
        if t == "hello":
            name = (m.get("name") or "Игрок")[:16]
            self.lobby_players.append((cid, name))
            self.server.send(cid, {"t": "welcome", "id": cid})
            self.server.broadcast({"t": "lobby", "players": self.lobby_players})
        elif t == "input" and self.state == "play":
            p = self.players.get(cid)
            if p and p.alive:
                p.inp = V(m.get("mx", 0), m.get("my", 0))
                p.ang = float(m.get("ang", 0))
                p.shoot = bool(m.get("shoot", False))
                if m.get("dash"):
                    p.want_dash = True
                if m.get("pulse"):
                    p.want_pulse = True
        elif t == "upgrade" and self.state == "play" and self.intermission:
            p = self.players.get(cid)
            up_id = m.get("id")
            if p and p.alive and not p.upgrade_ready and up_id in p.upgrade_choices and apply_upgrade(p, up_id):
                p.pending_upgrades = max(0, p.pending_upgrades - 1)
                if p.pending_upgrades > 0:
                    p.upgrade_choices = roll_upgrades(self.rng, 3, p)
                    if not p.upgrade_choices:
                        p.pending_upgrades = 0
                if p.pending_upgrades <= 0:
                    p.upgrade_choices = []
                    p.upgrade_ready = True
        elif t == "disconnect":
            self.lobby_players = [x for x in self.lobby_players if x[0] != cid]
            if self.players:
                self.players.pop(cid, None)
            self.server.broadcast({"t": "lobby", "players": self.lobby_players})

    def handle_host_disconnect(self):
        log.warning("Соединение с хостом потеряно")
        if self.client:
            self.client.stop()
            self.client = None
        self.snap = None
        self.local_choices = []
        self.lobby_players = []
        self.players = {}
        self.paused = False
        self.is_host = False
        self.my_id = 0
        self.set_error("Связь с хостом потеряна.\nХост закрыл игру или соединение оборвалось.")

    def on_client_msg(self, m):
        t = m.get("t")
        if t == "welcome":
            self.my_id = int(m.get("id", 0))
            log.info("Подключено к хосту, client_id=%d", self.my_id)
        elif t == "lobby":
            self.lobby_players = [(int(a), b) for a, b in m.get("players", [])]
        elif t == "start":
            self.snap = None
            self.local_choices = []
            self.local_upgrade_waiting = False
            self.intermission = False
            self.state = "play"
            self.paused = False
            self.help_t = 10.0
            pygame.mouse.set_visible(False)
        elif t == "snap":
            self.snap = m
            self.banner_t = m.get("banner", 0)
            self.intermission = bool(m.get("intermission", False))
            for pl in m.get("players", []):
                if pl["pid"] == self.my_id:
                    self.local_choices = pl.get("upgrade_choices", []) if pl.get("alive", True) else []
                    self.local_upgrade_waiting = bool(pl.get("upgrade_ready", False))
                    break
            else:
                self.local_choices = []
                self.local_upgrade_waiting = False
            pygame.mouse.set_visible(not (self.state == "play" and self.intermission))
        elif t == "dead":
            self.local_choices = []
            self.state = "dead"
            pygame.mouse.set_visible(True)
        elif t == "disconnect":
            self.handle_host_disconnect()

    def send_input(self):
        if self.is_host or not self.client or self.state != "play":
            return
        k = pygame.key.get_pressed()
        x = int(k[pygame.K_d] or k[pygame.K_RIGHT]) - int(k[pygame.K_a] or k[pygame.K_LEFT])
        y = int(k[pygame.K_s] or k[pygame.K_DOWN]) - int(k[pygame.K_w] or k[pygame.K_UP])
        v = V(x, y)
        if v.length_squared() > 0:
            v.normalize_ip()
        # угол в мировых координатах
        ang = 0.0
        mx, my = pygame.mouse.get_pos()
        sw, sh = self.screen.get_size()
        if sw and sh:
            mx = mx * W / sw
            my = my * H / sh
        wmx, wmy = self.camera.to_world(mx, my)
        if self.snap:
            for pl in self.snap.get("players", []):
                if pl.get("pid") == self.my_id:
                    aim = V(wmx - pl["x"], wmy - pl["y"])
                    if aim.length_squared() > 1:
                        ang = math.atan2(aim.y, aim.x)
                    break
        dash = k[pygame.K_SPACE] or k[pygame.K_LSHIFT]
        pulse = bool(k[pygame.K_e]) or pygame.mouse.get_pressed()[2]
        self.client.send({
            "t": "input",
            "mx": v.x, "my": v.y,
            "ang": ang,
            "shoot": pygame.mouse.get_pressed()[0],
            "dash": bool(dash),
            "pulse": bool(pulse),
        })

    def pick_upgrade(self, upgrade_id):
        if not self.intermission or upgrade_id not in self.local_choices:
            return
        if self.is_host:
            p = self.players.get(self.my_id)
            if p and p.alive and not p.upgrade_ready and upgrade_id in p.upgrade_choices and apply_upgrade(p, upgrade_id):
                p.pending_upgrades = max(0, p.pending_upgrades - 1)
                if p.pending_upgrades > 0:
                    p.upgrade_choices = roll_upgrades(self.rng, 3, p)
                    if not p.upgrade_choices:
                        p.pending_upgrades = 0
                if p.pending_upgrades <= 0:
                    p.upgrade_choices = []
                    p.upgrade_ready = True
                    self.local_choices = []
                    self.local_upgrade_waiting = True
                else:
                    self.local_choices = list(p.upgrade_choices)
                self.audio.play("ready")
        elif self.client:
            self.client.send({"t": "upgrade", "id": upgrade_id})
            self.local_choices = []
            self.local_upgrade_waiting = True
            self.audio.play("ready")

    # ================= ввод =================
    def mouse_world(self):
        mx, my = pygame.mouse.get_pos()
        sw, sh = self.screen.get_size()
        if sw and sh:
            mx = mx * W / sw
            my = my * H / sh
        return self.camera.to_world(mx, my)

    def is_spectating(self):
        if self.is_host:
            p = self.players.get(self.my_id)
            return p is not None and not p.alive
        if self.snap:
            return any(pl.get("pid") == self.my_id and not pl.get("alive", True)
                       for pl in self.snap.get("players", []))
        return False

    def update_spectator_camera(self, dt):
        if self.state not in ("play", "dead") or not self.is_spectating():
            return
        keys = pygame.key.get_pressed()
        x = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT])
        y = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP])
        direction = V(x, y)
        if direction.length_squared() > 0:
            direction.normalize_ip()
            self.camera.x += direction.x * self.spectator_speed * dt
            self.camera.y += direction.y * self.spectator_speed * dt
            self.camera.x = max(0, min(WORLD_W - W, self.camera.x))
            self.camera.y = max(0, min(WORLD_H - H, self.camera.y))

    def gather_local_input(self):
        p = self.players.get(self.my_id)
        if p is None or not p.alive:
            return
        k = pygame.key.get_pressed()
        x = int(k[pygame.K_d] or k[pygame.K_RIGHT]) - int(k[pygame.K_a] or k[pygame.K_LEFT])
        y = int(k[pygame.K_s] or k[pygame.K_DOWN]) - int(k[pygame.K_w] or k[pygame.K_UP])
        v = V(x, y)
        if v.length_squared() > 0:
            v.normalize_ip()
        p.inp = v
        mx, my = self.mouse_world()
        aim = V(mx, my) - p.p
        if aim.length_squared() > 1:
            p.ang = math.atan2(aim.y, aim.x)
        p.shoot = pygame.mouse.get_pressed()[0]
        if k[pygame.K_SPACE] or k[pygame.K_LSHIFT]:
            p.want_dash = True

    def handle_events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.quit()
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
                    continue
                if e.key == pygame.K_F3 and not self.input_mode:
                    self.debug_overlay = not self.debug_overlay
                    continue
                if self.input_mode:
                    self._handle_input_event(e)
                    continue
                if e.key == pygame.K_h:
                    self.show_help = not self.show_help
                    if self.show_help:
                        self.help_t = 10.0
                    continue

                if self.state == "menu":
                    if e.key == pygame.K_1:
                        self.start_host()
                    elif e.key == pygame.K_2:
                        self.input_mode = "ip"
                        self.ip_input = self.last_ip
                    elif e.key == pygame.K_3:
                        self.input_mode = "name"
                    elif e.key == pygame.K_4 and self.last_ip:
                        self.join_server(self.last_ip)
                    elif e.key == pygame.K_ESCAPE:
                        self.quit()
                elif self.state == "lobby":
                    if e.key == pygame.K_ESCAPE:
                        self.leave_net()
                    elif e.key == pygame.K_RETURN and self.is_host:
                        self.host_start_game()
                elif self.state == "play":
                    if e.key in (pygame.K_p, pygame.K_ESCAPE) and self.is_host:
                        self.paused = not self.paused
                    elif e.key == pygame.K_e:
                        p = self.players.get(self.my_id)
                        if p:
                            p.want_pulse = True
                elif self.state == "dead":
                    if e.key == pygame.K_RETURN and self.is_host:
                        self.host_start_game()
                    elif e.key == pygame.K_ESCAPE:
                        self.leave_net()
                elif self.state == "error":
                    if e.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                        self.state = "menu"
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    self.audio.play("ui_click")
                mx, my = self.logical_mouse(e.pos)
                if self.input_mode and e.button == 1:
                    if pygame.Rect(W / 2 - 115, H / 2 + 32, 230, 38).collidepoint(mx, my):
                        self._paste_input()
                    elif pygame.Rect(W / 2 - 135, H / 2 + 80, 270, 46).collidepoint(mx, my):
                        mode = self.input_mode
                        self.input_mode = None
                        if mode == "name":
                            self.name_input = self.name_input.strip() or "Игрок"
                            self.first_run = False
                        self.persist()
                        if mode == "ip":
                            self.join_server(self.ip_input)
                    elif pygame.Rect(W / 2 - 135, H / 2 + 136, 270, 40).collidepoint(mx, my):
                        self.input_mode = None
                elif self.state == "menu" and e.button == 1:
                    cx, cy = W / 2, H / 2 - 140
                    if pygame.Rect(cx - 100, H - 58, 200, 38).collidepoint(mx, my):
                        self.quit()
                    y = cy + 160
                    if pygame.Rect(cx - 210, y - 20, 420, 52).collidepoint(mx, my):
                        self.start_host()
                    elif pygame.Rect(cx - 210, y + 42, 420, 52).collidepoint(mx, my):
                        self.input_mode = "ip"
                        self.ip_input = self.last_ip
                    elif pygame.Rect(cx - 210, y + 104, 420, 44).collidepoint(mx, my) and self.last_ip:
                        self.join_server(self.last_ip)
                    elif pygame.Rect(cx - 210, y + 158, 420, 44).collidepoint(mx, my):
                        self.input_mode = "name"
                elif self.state == "lobby" and e.button == 1:
                    if self.is_host and pygame.Rect(W / 2 - 190, H - 136, 380, 52).collidepoint(mx, my):
                        self.host_start_game()
                    elif pygame.Rect(W / 2 - 150, H - 66, 300, 42).collidepoint(mx, my):
                        self.leave_net()
                elif self.state == "play" and self.local_choices and e.button == 1:
                    card_w, card_h, gap = 320, 220, 30
                    total = len(self.local_choices) * card_w + (len(self.local_choices) - 1) * gap
                    x0 = (W - total) / 2
                    card_y = H / 2 - card_h / 2 + 40
                    for i, upgrade_id in enumerate(self.local_choices):
                        card = pygame.Rect(x0 + i * (card_w + gap), card_y, card_w, card_h)
                        if card.collidepoint(mx, my):
                            self.pick_upgrade(upgrade_id)
                            break
                elif self.state == "dead" and e.button == 1:
                    if self.is_host and pygame.Rect(W / 2 - 190, H - 126, 380, 52).collidepoint(mx, my):
                        self.host_start_game()
                    elif pygame.Rect(W / 2 - 150, H - 70, 300, 42).collidepoint(mx, my):
                        self.leave_net()
                elif self.state == "error" and e.button == 1:
                    if pygame.Rect(W / 2 - 150, H - 102, 300, 46).collidepoint(mx, my):
                        self.state = "menu"
                elif e.button == 3 and self.state == "play":
                    p = self.players.get(self.my_id)
                    if p:
                        p.want_pulse = True

    def _paste_input(self):
        value = read_clipboard()
        if not value:
            self.connect_error = "Буфер обмена пуст или недоступен"
            return
        self.connect_error = ""
        if self.input_mode == "ip":
            value = "".join(ch for ch in value.strip() if ch.isdigit() or ch == ".")
            self.ip_input = value[:15]
        elif self.input_mode == "name":
            self.name_input = value.replace("\n", " ").replace("\r", " ")[:16]

    def _handle_input_event(self, e):
        if e.key == pygame.K_RETURN:
            mode = self.input_mode
            self.input_mode = None
            if mode == "name":
                self.name_input = self.name_input.strip() or "Игрок"
                self.first_run = False
            self.persist()
            if mode == "ip":
                self.join_server(self.ip_input)
            return
        if e.key == pygame.K_ESCAPE:
            if self.input_mode == "name" and self.first_run:
                self.name_input = "Игрок"
                self.first_run = False
                self.persist()
            self.input_mode = None
            return
        if e.key == pygame.K_BACKSPACE:
            if self.input_mode == "ip":
                self.ip_input = self.ip_input[:-1]
            else:
                self.name_input = self.name_input[:-1]
            return
        if e.key == pygame.K_v and (e.mod & pygame.KMOD_CTRL):
            self._paste_input()
            return
        ch = e.unicode
        if ch and ch.isprintable():
            if self.input_mode == "ip":
                if ch.isdigit() or ch == ".":
                    self.ip_input = (self.ip_input + ch)[:15]
            else:
                self.name_input = (self.name_input + ch)[:16]

    def quit(self):
        self.leave_net()
        pygame.quit()
        sys.exit()

    # ================= симуляция (хост) =================
    def host_update(self, dt):
        if self.intermission:
            self.shake *= math.exp(-8 * dt)
            self.flash = max(0.0, self.flash - dt * 3.0)
            if all((not p.alive) or p.upgrade_ready for p in self.players.values()):
                self.start_next_wave()
            return
        self.gather_local_input()
        for p in self.players.values():
            if p.alive:
                self.update_player(p, dt)
        self.update_waves(dt)
        for e in self.enemies:
            self.update_enemy(e, dt)
        self.separate()
        self.update_pickups(dt)
        self.update_bullets(dt)
        self.collide()
        for lst in (self.parts, self.rings):
            for o in lst:
                o.update(dt)
        self.parts = [x for x in self.parts if x.life > 0]
        self.rings = [x for x in self.rings if x.r < x.max]
        for pop in self.pops:
            pop[0].y -= 40 * dt
            pop[2] -= dt
        self.pops = [x for x in self.pops if x[2] > 0]
        self.shake *= math.exp(-6 * dt)
        self.flash = max(0.0, self.flash - dt * 2.5)
        self.banner_t = max(0.0, self.banner_t - dt)
        self.help_t = max(0.0, self.help_t - dt)

        if not any(p.alive for p in self.players.values()):
            self.state = "dead"
            self.intermission = False
            self.local_upgrade_waiting = False
            self.local_choices = []
            for player in self.players.values():
                player.upgrade_choices = []
            self.server.broadcast({"t": "dead"})
            pygame.mouse.set_visible(True)

    def update_player(self, p, dt):
        p.dash_t = max(0.0, p.dash_t - dt)
        p.dash_cd = max(0.0, p.dash_cd - dt)
        p.inv = max(0.0, p.inv - dt)
        p.cool = max(0.0, p.cool - dt)
        p.pulse_boost = max(0.0, p.pulse_boost - dt)
        if p.regen > 0 and p.hp < p.max_hp:
            p.regen_timer += dt
            if p.regen_timer >= 1.0 / p.regen:
                p.regen_timer = 0.0
                p.hp = min(p.max_hp, p.hp + 1)
        p.rapid = max(0.0, p.rapid - dt)
        p.spread = max(0.0, p.spread - dt)
        p.combo_t -= dt
        if p.combo_t <= 0:
            p.chain = 0

        if p.want_dash:
            p.want_dash = False
            if p.dash_cd <= 0:
                d = p.inp if p.inp.length_squared() > 0 else V(math.cos(p.ang), math.sin(p.ang))
                # Dash always adds a strong burst, even when already moving fast.
                current_speed = p.v.length()
                p.v = d * max(1350.0, current_speed + 950.0)
                p.dash_t = 0.22
                p.inv = max(p.inv, 0.20)
                p.dash_cd = p.dash_cd_max
                self.audio.play("dash")
                self.rings.append(Ring(p.p, 10, 90, 400, CYAN, 3))

        if p.want_pulse:
            p.want_pulse = False
            if p.charge >= 100:
                self.do_pulse(p)

        if p.dash_t <= 0:
            p.v += p.inp * p.move_spd * dt
        p.v *= math.exp(-6.5 * dt)
        p.p += p.v * dt
        # границы МИРА
        p.p.x = max(22, min(WORLD_W - 22, p.p.x))
        p.p.y = max(22, min(WORLD_H - 22, p.p.y))

        back = -V(math.cos(p.ang), math.sin(p.ang))
        if p.v.length_squared() > 4000 or p.dash_t > 0:
            for _ in range(2 if p.dash_t > 0 else 1):
                self.parts.append(Particle(
                    p.p + back * 12,
                    back * random.uniform(60, 220) + V(random.uniform(-40, 40), random.uniform(-40, 40)),
                    random.uniform(0.2, 0.45),
                    CYAN if p.dash_t <= 0 else WHITE, 3, 3))

        if p.shoot and p.cool <= 0:
            p.cool = p.fire_rate if p.rapid <= 0 else p.fire_rate * 0.55
            angs = (-0.22, 0.0, 0.22) if p.spread > 0 else (0.0,)
            for a in angs:
                aa = p.ang + a + random.uniform(-0.025, 0.025)
                d = V(math.cos(aa), math.sin(aa))
                shot_damage = p.dmg * (2.0 if random.random() < p.crit else 1.0)
                self.bullets.append(Bullet(p.p + d * 22, d * (1100 * p.bullet_speed), p.pid,
                                           shot_damage * p.bullet_size, p.pierce))
            for i in range(p.multishot):
                spread = 0.12 * (i + 1)
                for sign in (-1, 1):
                    aa = p.ang + spread * sign
                    d = V(math.cos(aa), math.sin(aa))
                    shot_damage = p.dmg * (2.0 if random.random() < p.crit else 1.0)
                    self.bullets.append(Bullet(p.p + d * 22, d * (1100 * p.bullet_speed),
                                               p.pid, shot_damage * p.bullet_size, p.pierce))
            fwd = V(math.cos(p.ang), math.sin(p.ang))
            p.v -= fwd * 25
            self.burst(p.p + fwd * 24, CYAN, 3, 260, (0.08, 0.2), 2)
            self.audio.play("shoot")

    def do_pulse(self, p):
        p.charge = 0
        self.shake = max(self.shake, 34)
        self.flash = 0.85
        p.inv = max(p.inv, 0.85)
        p.pulse_boost = 3.5
        p.rapid = max(p.rapid, 3.5)
        self.audio.play("pulse")
        radius = 560 * (1.0 + 0.12 * (p.pulse_power - 1.0))
        for i, (r, speed, width) in enumerate(((radius * 0.72, 1100, 7), (radius, 850, 4), (radius * 0.48, 1250, 3))):
            self.rings.append(Ring(p.p, 5, r, speed, MAGENTA if i != 2 else WHITE, width))
        self.burst(p.p, MAGENTA, 110, 820, (0.35, 1.15), 4)
        self.ebullets = []
        for e in list(self.enemies):
            delta = e.p - p.p
            dist = delta.length()
            if not e.dead and dist < radius:
                self.damage(e, 12 * p.dmg * p.pulse_power, p)
                if dist > 0:
                    e.v += delta.normalize() * (900 * p.pulse_power * (1.0 - dist / radius * 0.35))
                    e.stun = max(e.stun, 0.45 if e.kind != "boss" else 0.18)

    def update_waves(self, dt):
        if self.intermission:
            return
        alive = any(not e.dead for e in self.enemies)
        if self.wave == 0 and not self.queue and not alive:
            self.wave_delay -= dt
            if self.wave_delay <= 0:
                self.next_wave()
        elif not self.queue and not alive:
            self.begin_intermission()
        elif self.queue:
            self.spawn_t -= dt
            if self.spawn_t <= 0:
                self.spawn_t = max(0.16, 0.7 - 0.018 * self.wave)
                self.spawn(self.queue.pop())

    def begin_intermission(self):
        if self.intermission:
            return
        self.intermission = True
        self.queue.clear()
        self.audio.play("wave")
        for p in self.players.values():
            if not p.alive:
                p.upgrade_choices = []
                p.upgrade_ready = True
                continue
            p.pending_upgrades = max(1, p.pending_upgrades)
            p.upgrade_ready = False
            p.upgrade_choices = roll_upgrades(self.rng, 3, p)
            if not p.upgrade_choices:
                p.pending_upgrades = 0
                p.upgrade_ready = True
        local = self.players.get(self.my_id)
        self.local_choices = list(local.upgrade_choices) if local and local.alive else []
        self.local_upgrade_waiting = bool(local and local.upgrade_ready)
        pygame.mouse.set_visible(False)

    def start_next_wave(self):
        if not self.intermission:
            return
        self.intermission = False
        self.local_choices = []
        self.local_upgrade_waiting = False
        for p in self.players.values():
            p.upgrade_choices = []
            p.upgrade_ready = False
        self.next_wave()

    def next_wave(self):
        self.wave += 1
        self.wave_delay = 2.0
        self.banner_t = 2.2
        n = min(64, 7 + int(self.wave * 2.7))
        q = []
        for _ in range(n):
            r = random.random()
            if self.wave >= 3 and r < 0.09:
                q.append("tank")
            elif self.wave >= 4 and r < 0.19:
                q.append("splitter")
            elif self.wave >= 3 and r < 0.29:
                q.append("dasher")
            elif self.wave >= 5 and r < 0.38:
                q.append("mine")
            elif self.wave >= 2 and r < 0.52:
                q.append("shooter")
            elif self.wave >= 2 and r < 0.66:
                q.append("swarm")
            else:
                q.append("chaser")
        # Every fifth wave ends with a unique-feeling arena boss encounter.
        if self.wave % 5 == 0:
            q.append(("boss", "boss_storm", "boss_hunter")[(self.wave // 5 - 1) % 3])
        self.queue = q
        if self.wave % 4 == 0:
            self.pickups.append([V(WORLD_W / 2, WORLD_H / 2), "heal", 12.0])

    def spawn(self, kind):
        alive_players = [p for p in self.players.values() if p.alive]
        if not alive_players or (len(self.enemies) >= 90 and kind != "boss"):
            return
        tgt = random.choice(alive_players)
        ang = random.uniform(0, math.tau)
        dist = random.uniform(420, 820)
        pos = tgt.p + V(math.cos(ang), math.sin(ang)) * dist
        pos.x = max(50, min(WORLD_W - 50, pos.x))
        pos.y = max(50, min(WORLD_H - 50, pos.y))
        self.enemies.append(Enemy(kind, pos, self.wave))

    def update_enemy(self, e, dt):
        alive_players = [p for p in self.players.values() if p.alive]
        if not alive_players:
            return
        e.age += dt
        e.flash = max(0.0, e.flash - dt)
        e.stun = max(0.0, e.stun - dt)
        e.ang += dt * (1.2 if e.kind in ("tank", "boss") else 2.5)
        if e.age < 0.7:
            return
        if e.stun > 0:
            e.v *= math.exp(-2.5 * dt)
            e.p += e.v * dt
            return
        target = min(alive_players, key=lambda pl: (pl.p - e.p).length_squared())
        to = target.p - e.p
        dist = to.length() or 1.0
        d = to / dist
        k = e.kind
        if k in ("chaser", "swarm", "splitter"):
            e.v = e.v.lerp(d * e.spd, min(1.0, 3 * dt))
        elif k == "dasher":
            e.cool -= dt
            if e.cool <= 0:
                e.cool = 2.0
                e.v = d * (e.spd * 5.2)
                self.rings.append(Ring(e.p, 8, 95, 500, e.col, 3))
            else:
                e.v = e.v.lerp(d * e.spd * 0.75, min(1.0, 2 * dt))
        elif k == "mine":
            e.v = e.v.lerp(d * (e.spd if dist > 230 else 0), min(1.0, 1.5 * dt))
            e.cool -= dt
            if e.cool <= 0 and dist < 560:
                e.cool = 2.8
                for i in range(8):
                    a = i * math.tau / 8 + e.ang
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 270, 5.5])
        elif k == "shooter":
            if dist > 400:
                tgt = d * e.spd
            elif dist < 300:
                tgt = -d * e.spd
            else:
                tgt = V(-d.y, d.x) * e.spd * 0.8 * e.side
            e.v = e.v.lerp(tgt, min(1.0, 3 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = max(0.72, 2.0 - 0.045 * self.wave)
                n = 1 if self.wave < 3 else (3 if self.wave < 8 else 5)
                base = math.atan2(d.y, d.x)
                for i in range(n):
                    a = base + (i - (n - 1) / 2) * 0.25
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * min(430, 300 + self.wave * 8), 6.0])
                self.audio.play("shoot")
        elif k in ("boss", "boss_storm", "boss_hunter"):
            e.v = e.v.lerp(d * e.spd, min(1.0, 1.4 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = max(1.25, 2.5 - self.wave * 0.025)
                count = 26 if k == "boss_storm" else 14 if k == "boss_hunter" else 18
                speed = 350 if k == "boss_storm" else 430 if k == "boss_hunter" else 300
                for i in range(count):
                    a = i * math.tau / count + e.ang
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * speed, 7.0])
                base = math.atan2(d.y, d.x)
                fan = (-0.62, -0.42, -0.21, 0, 0.21, 0.42, 0.62) if k == "boss_hunter" else (-0.42, -0.21, 0, 0.21, 0.42)
                for offset in fan:
                    a = base + offset
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * (470 if k == "boss_hunter" else 390), 6.0])
                if k == "boss_hunter":
                    e.v += d * 520
                self.shake = max(self.shake, 9)
                self.audio.play("boom")
        else:  # tank
            e.v = e.v.lerp(d * e.spd, min(1.0, 2 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = 3.4
                count = 10 if self.wave < 8 else 12
                for i in range(count):
                    a = i * math.tau / count + e.ang
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * min(340, 230 + self.wave * 5), 6.0])
                self.audio.play("boom")
        e.p += e.v * dt
        e.p.x = max(15, min(WORLD_W - 15, e.p.x))
        e.p.y = max(15, min(WORLD_H - 15, e.p.y))

    def separate(self):
        # Spatial hash avoids the old all-pairs O(n^2) pass when waves get dense.
        cell = 72
        buckets = {}
        for e in self.enemies:
            if e.age < 0.7 or e.dead:
                continue
            key = (int(e.p.x // cell), int(e.p.y // cell))
            buckets.setdefault(key, []).append(e)
        for (gx, gy), group in buckets.items():
            neighbors = [buckets.get((gx + ox, gy + oy), ())
                         for ox, oy in ((1,0), (0,1), (1,1), (-1,1))]
            pairs = []
            for i, a in enumerate(group):
                pairs.extend((a, group[j]) for j in range(i + 1, len(group)))
                for other in neighbors:
                    pairs.extend((a, other_enemy) for other_enemy in other)
            for a, other_enemy in pairs:
                d = a.p - other_enemy.p
                rr = a.r + other_enemy.r
                l2 = d.length_squared()
                if 0 < l2 < rr * rr:
                    l = math.sqrt(l2)
                    push = d / l * (rr - l) * 0.5
                    a.p += push
                    other_enemy.p -= push

    def update_bullets(self, dt):
        for b in self.bullets:
            b.update(dt)
        self.bullets = [b for b in self.bullets if b.life > 0
                        and -40 < b.p.x < WORLD_W + 40 and -40 < b.p.y < WORLD_H + 40]
        for b in self.ebullets:
            b[0] += b[1] * dt
            b[2] -= dt
        self.ebullets = [b for b in self.ebullets if b[2] > 0
                         and -40 < b[0].x < WORLD_W + 40
                         and -40 < b[0].y < WORLD_H + 40]

    def update_pickups(self, dt):
        keep = []
        alive_players = [p for p in self.players.values() if p.alive]
        for pk in self.pickups:
            pk[2] -= dt
            if alive_players:
                target = min(alive_players, key=lambda p: (p.p - pk[0]).length_squared())
                d = target.p - pk[0]
                dist = d.length()
                attract_r = 170 * target.magnet
                if 0 < dist < attract_r:
                    pk[0] += d / dist * (120 + 400 * (1 - dist / attract_r)) * dt
                if dist < 30:
                    self.collect(target, pk)
                    continue
            if pk[2] > 0:
                keep.append(pk)
        self.pickups = keep

    def collect(self, p, pk):
        kind = pk[1]
        if kind == "rapid":
            p.rapid = 10.0
        elif kind == "spread":
            p.spread = 10.0
        else:
            p.hp = min(p.max_hp, p.hp + 1)
        col = PICK_COL[kind]
        self.rings.append(Ring(pk[0], 8, 120, 450, col, 3))
        self.burst(pk[0], col, 20, 350)
        self.pops.append([V(pk[0]), {"rapid": "БЫСТРЫЙ ОГОНЬ", "spread": "ТРОЙНОЙ ВЫСТРЕЛ", "heal": "+1 HP"}[kind], 1.2, col])
        self.audio.play("pickup")

    def damage(self, e, n, src):
        e.hp -= n
        e.flash = 0.08
        if e.hp <= 0:
            self.kill(e, src)
        else:
            self.audio.play("hit")

    def kill(self, e, src):
        if e.dead:
            return
        e.dead = True
        d = KINDS[e.kind]
        self.burst(e.p, e.col, int(18 + e.r), 420, (0.3, 0.9), 3)
        self.burst(e.p, WHITE, 8, 300, (0.1, 0.3), 2)
        self.rings.append(Ring(e.p, e.r, e.r * 4 + 30, 520, e.col, 3))
        self.shake = max(self.shake, 5 + e.r * 0.4)
        if src:
            src.chain += 1
            src.combo_t = 2.5
            pts = d["score"] * src.mult()
            src.score += pts
            src.kills += 1
            if src.lifesteal:
                src.lifesteal_progress += src.lifesteal
                if src.lifesteal_progress >= 18:
                    src.lifesteal_progress -= 18
                    src.hp = min(src.max_hp, src.hp + 1)
                    self.pops.append([V(src.p), "+1 HP", 0.9, GREEN])
            src.charge = min(100.0, src.charge + (22 if e.kind == "boss" else 12 if e.kind == "tank" else 5) * src.pulse_gain)
            self.pops.append([V(e.p), "+%d" % pts, 0.8, e.col])
            # Уровень растёт сразу, но выбор переносится на перерыв между волнами.
            src.xp += int(d["xp"] * src.xp_gain)
            while src.xp >= src.xp_to_next():
                src.xp -= src.xp_to_next()
                src.level += 1
                src.pending_upgrades += 1
                self.audio.play("levelup")
        self.audio.play("boom")
        if e.kind in ("tank", "splitter"):
            for _ in range(4 if e.kind == "tank" else 3):
                c = Enemy("swarm", e.p + V(random.uniform(-30, 30), random.uniform(-30, 30)), self.wave)
                c.age = 0.45
                self.enemies.append(c)
        if e.kind.startswith("boss"):
            self.burst(e.p, MAGENTA, 180, 980, (0.5, 1.5), 5)
            self.rings.append(Ring(e.p, 10, 900, 700, YELLOW, 9))
            for _ in range(3):
                self.pickups.append([V(e.p), random.choice(("heal", "rapid", "spread")), 14.0])
        chance = {"shooter": 0.2, "tank": 0.6}.get(e.kind, 0.05)
        if random.random() < chance:
            kinds = ["rapid", "spread"]
            wts = [4, 4]
            any_low = any(p.hp < p.max_hp for p in self.players.values() if p.alive)
            if any_low:
                kinds.append("heal")
                wts.append(2)
            self.pickups.append([V(e.p), random.choices(kinds, wts)[0], 10.0])

    def hurt(self, p):
        if not p.alive:
            return
        p.armor_hits += 1
        if p.armor > 0 and p.armor_hits % 4 == 0:
            self.pops.append([V(p.p), "БРОНЯ", 0.8, CYAN])
            self.rings.append(Ring(p.p, 8, 100, 520, CYAN, 3))
            return
        p.hp -= 1
        p.inv = 0.58
        p.chain = 0
        self.shake = max(self.shake, 24)
        self.flash = 1.0
        self.hitstop = 0.07
        self.burst(p.p, CYAN, 40, 520, (0.3, 0.9), 3)
        self.rings.append(Ring(p.p, 10, 280, 900, RED, 5))
        self.audio.play("hurt")
        if p.hp <= 0:
            p.alive = False
            self.burst(p.p, p.color, 120, 800, (0.6, 1.8), 4)
            self.burst(p.p, WHITE, 40, 500, (0.3, 0.9), 3)
            for r, s in ((500, 500), (800, 800)):
                self.rings.append(Ring(p.p, 10, r, s, p.color, 6))
            self.shake = 40

    def collide(self):
        # пули игрока → враги
        keep_b = []
        for b in self.bullets:
            hit = False
            for e in list(self.enemies):
                if e.dead or e.age < 0.7:
                    continue
                if id(e) in b.hit_ids:
                    continue
                rr = e.r + 5
                if (b.p - e.p).length_squared() < rr * rr:
                    src = self.players.get(b.owner)
                    self.damage(e, b.dmg, src)
                    self.burst(b.p, e.col, 5, 260, (0.1, 0.3), 2)
                    b.hit_ids.add(id(e))
                    if b.pierce > 0:
                        b.pierce -= 1
                    else:
                        hit = True
                    break
            if not hit:
                keep_b.append(b)
        self.bullets = keep_b

        # пули врагов → игроки
        keep_e = []
        for b in self.ebullets:
            hit_p = None
            for p in self.players.values():
                if p.alive and p.inv <= 0 and (b[0] - p.p).length_squared() < 17 * 17:
                    hit_p = p
                    break
            if hit_p:
                self.hurt(hit_p)
                continue
            keep_e.append(b)
        self.ebullets = keep_e

        # враги ↔ игроки
        for e in list(self.enemies):
            if e.dead or e.age < 0.7:
                continue
            for p in list(self.players.values()):
                if not p.alive:
                    continue
                rr = e.r + 10
                if (e.p - p.p).length_squared() < rr * rr:
                    if p.dash_t > 0:
                        if e.flash <= 0:
                            self.damage(e, 6 * p.dmg * p.dash_damage, p)
                    elif p.inv <= 0:
                        self.hurt(p)
                        if e.kind in ("chaser", "swarm"):
                            self.kill(e, p)
                        else:
                            d = e.p - p.p
                            if d.length_squared() > 0:
                                e.v = d.normalize() * 400
                        break
        self.enemies = [e for e in self.enemies if not e.dead]

    def burst(self, pos, col, n=20, speed=300, life=(0.3, 0.8), size=3.0):
        if len(self.parts) > 950:
            return
        for _ in range(n):
            a = random.uniform(0, math.tau)
            sp = random.uniform(0.15, 1.0) * speed
            self.parts.append(Particle(pos, V(math.cos(a), math.sin(a)) * sp,
                                       random.uniform(*life), col, size * random.uniform(0.6, 1.3)))

    # ================= снапшот =================
    def build_snapshot(self):
        snap = {
            "t": "snap",
            "players": [],
            "bullets": [],
            "ebullets": [],
            "enemies": [],
            "pickups": [],
            "pops": [],
            "wave": self.wave,
            "intermission": self.intermission,
            "banner": round(self.banner_t, 2),
            "shake": round(self.shake, 1),
            "enemies_left": len(self.queue) + sum(1 for e in self.enemies if not e.dead),
            "boss_in": (5 - ((self.wave + (1 if self.intermission else 0)) % 5)) % 5,
        }
        for p in self.players.values():
            snap["players"].append({
                "pid": p.pid, "name": p.name,
                "x": round(p.p.x, 1), "y": round(p.p.y, 1),
                "ang": round(p.ang, 2), "hp": p.hp, "max_hp": p.max_hp,
                "dash_cd": round(p.dash_cd, 2), "charge": round(p.charge, 1),
                "rapid": round(p.rapid, 1), "spread": round(p.spread, 1),
                "score": p.score, "kills": p.kills,
                "chain": p.chain, "combo_t": round(p.combo_t, 2),
                "alive": p.alive, "inv": round(p.inv, 2), "dash_t": round(p.dash_t, 2),
                "level": p.level, "xp": p.xp, "xp_next": p.xp_to_next(),
                "upgrade_choices": list(p.upgrade_choices),
                "upgrade_ready": p.upgrade_ready,
                "pending_upgrades": p.pending_upgrades,
                "buffs": {"rapid": round(p.rapid,1), "spread": round(p.spread,1),
                          "pulse_boost": round(p.pulse_boost,1)},
            })
        for b in self.bullets:
            snap["bullets"].append([round(b.p.x, 1), round(b.p.y, 1),
                                    round(b.v.x, 1), round(b.v.y, 1)])
        for b in self.ebullets:
            snap["ebullets"].append([round(b[0].x, 1), round(b[0].y, 1)])
        for e in self.enemies:
            if e.dead:
                continue
            snap["enemies"].append({
                "k": e.kind, "x": round(e.p.x, 1), "y": round(e.p.y, 1),
                "r": e.r, "ang": round(e.ang, 2), "age": round(e.age, 2),
                "flash": round(e.flash, 2), "cool": round(e.cool, 2),
                "hp": e.hp, "max_hp": e.max_hp,
            })
        for pk in self.pickups:
            snap["pickups"].append([round(pk[0].x, 1), round(pk[0].y, 1), pk[1], round(pk[2], 1)])
        for pos, s, life, col in self.pops:
            snap["pops"].append([round(pos.x, 1), round(pos.y, 1), s, round(life, 2), col])
        return snap

    # ================= отрисовка мира =================
    def _player_screen_pos(self):
        """Текущая позиция локального игрока в мировых координатах для камеры."""
        if self.is_host:
            p = self.players.get(self.my_id)
            if p:
                return p.p.x, p.p.y
            return WORLD_W / 2, WORLD_H / 2
        if self.snap:
            for pl in self.snap.get("players", []):
                if pl["pid"] == self.my_id:
                    return pl["x"], pl["y"]
        return WORLD_W / 2, WORLD_H / 2

    def draw_grid(self, sc):
        cx, cy = self.camera.x, self.camera.y
        gs = 64
        x0 = int(cx // gs) * gs
        y0 = int(cy // gs) * gs
        for wx in range(x0, x0 + W + gs * 2, gs):
            sx = wx - cx
            if -1 <= sx <= W + 1:
                pygame.draw.line(sc, (15, 19, 44), (sx, 0), (sx, H))
        for wy in range(y0, y0 + H + gs * 2, gs):
            sy = wy - cy
            if -1 <= sy <= H + 1:
                pygame.draw.line(sc, (15, 19, 44), (0, sy), (W, sy))
        # граница мира
        bx = -cx
        by = -cy
        pygame.draw.rect(sc, (30, 40, 80), (bx, by, WORLD_W, WORLD_H), 3)

    def draw_player(self, sc, data, is_local, cam):
        sx, sy = cam.to_screen(data["x"], data["y"])
        if not (-40 <= sx <= W + 40 and -40 <= sy <= H + 40):
            return
        col = PLAYER_COLORS[(data["pid"] - 1) % len(PLAYER_COLORS)]
        if data.get("dash_t", 0) > 0:
            col = WHITE
        if data["alive"] and (data.get("inv", 0) <= 0 or data.get("dash_t", 0) > 0
                              or int(self.t * 22) % 2 == 0):
            draw_glow(sc, (sx, sy), col, 48, 28)
            pts = shape(SHIP, data["ang"], (sx, sy), 20)
            pygame.draw.polygon(sc, (6, 40, 56), pts)
            pygame.draw.polygon(sc, col, pts, 2)
            if data.get("inv", 0) > 0.3:
                pygame.draw.circle(sc, dim(col, 0.5), (int(sx), int(sy)), 30, 1)
        if is_local:
            pygame.draw.circle(sc, dim(col, 0.6), (int(sx), int(sy)), 26, 1)
        # имя + уровень
        label = "%s  ур.%d" % (data["name"], data.get("level", 1))
        text(sc, label, self.f_small, col, (sx, sy - 34), outline=2)

    def draw_enemy(self, sc, e, cam):
        sx, sy = cam.to_screen(e["x"], e["y"])
        if not (-60 <= sx <= W + 60 and -60 <= sy <= H + 60):
            return
        k = min(1.0, e["age"] / 0.7)
        base_col = KINDS[e["k"]]["col"]
        col = WHITE if e["flash"] > 0 else dim(base_col, 0.4 + 0.6 * k)
        r = e["r"] * (0.3 + 0.7 * k)
        if k < 1:
            pygame.draw.circle(sc, dim(base_col, 1 - k), (int(sx), int(sy)),
                               int(e["r"] * (2.2 - 1.2 * k)), 1)
        if self.wave >= 5:
            tier = min(3, (self.wave - 1) // 4)
            pygame.draw.circle(sc, dim(base_col, 0.22 + tier * 0.08),
                               (int(sx), int(sy)), int(r + 5 + tier * 2), 1)
        fill = dim(base_col, 0.12)
        kind = e["k"]
        draw_glow(sc, (sx, sy), base_col, int(r * 2.2 + 12), 22)
        if kind in ("chaser", "dasher"):
            pts = shape(DIAMOND, e["ang"], (sx, sy), r)
        elif kind in ("swarm", "splitter"):
            pts = shape(TRI, e["ang"], (sx, sy), r)
        elif kind in ("shooter", "mine"):
            pts = shape(HEX, e["ang"] * 0.4, (sx, sy), r)
        elif kind.startswith("boss"):
            pts = shape(HEX, e["ang"] * 0.3, (sx, sy), r * 1.35)
        else:
            pts = shape(SQ, e["ang"], (sx, sy), r)
        pygame.draw.polygon(sc, fill, pts)
        pygame.draw.polygon(sc, col, pts, 2)
        max_hp = max(1, e.get("max_hp", 1))
        hp_ratio = max(0.0, min(1.0, e.get("hp", max_hp) / max_hp))
        if max_hp > 1:
            bar_w = max(24, int(r * 2.2))
            bar = pygame.Rect(int(sx - bar_w / 2), int(sy - r - 12), bar_w, 4)
            pygame.draw.rect(sc, (18, 18, 22), bar)
            hp_color = GREEN if hp_ratio > 0.55 else ORANGE if hp_ratio > 0.25 else RED
            pygame.draw.rect(sc, hp_color, (bar.x, bar.y, int(bar.w * hp_ratio), bar.h))
            pygame.draw.rect(sc, (8, 10, 14), bar, 1)
        if kind.startswith("boss"):
            pygame.draw.circle(sc, dim(col, 0.25), (int(sx), int(sy)), int(r * 0.72), 5)
            pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), max(5, int(r * 0.24)), 2)
        if kind == "shooter":
            pygame.draw.circle(sc, col, (int(sx), int(sy)), max(2, int(r * 0.3)))
            if k >= 1 and e["cool"] < 0.35:
                pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), int(r + 6 + e["cool"] * 20), 2)
        elif kind == "tank":
            pygame.draw.polygon(sc, col, shape(SQ, -e["ang"] * 1.7, (sx, sy), r * 0.5), 2)
            if k >= 1 and e["cool"] < 0.5:
                pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), int(r + 8), 2)

    def draw_world(self, sc, snap, cam):
        # Полная очистка буфера обязательна каждый кадр: иначе старые позиции
        # объектов остаются на экране и создают эффект бесконечных копий.
        sc.fill(BG)

        # звёзды с параллаксом от камеры
        for x, y, z in self.stars:
            sx = (x - cam.x * 0.3 * z) % W
            sy = (y - cam.y * 0.3 * z) % H
            c = int(60 + 150 * z)
            if z > 0.7:
                pygame.draw.circle(sc, (c, c, min(255, c + 40)), (int(sx), int(sy)), 2)
            else:
                sc.set_at((int(sx), int(sy)), (c // 2, c // 2, c))

        self.draw_grid(sc)

        # пикапы
        for pk in snap.get("pickups", []):
            col = PICK_COL[pk[2]]
            if pk[3] > 3 or int(self.t * 10) % 2 == 0:
                sx, sy = cam.to_screen(pk[0], pk[1])
                if not (-40 <= sx <= W + 40 and -40 <= sy <= H + 40):
                    continue
                bob = math.sin(self.t * 5 + pk[0]) * 3
                pos = (sx, sy + bob)
                draw_glow(sc, pos, col, 34, 38)
                pygame.draw.polygon(sc, col, shape(HEX, self.t * 1.5, pos, 17), 2)
                text(sc, PICK_LET[pk[2]], self.f_small, col, pos, outline=1)

        # враги
        for e in snap.get("enemies", []):
            self.draw_enemy(sc, e, cam)

        # пули врагов
        for b in snap.get("ebullets", []):
            sx, sy = cam.to_screen(b[0], b[1])
            if -20 <= sx <= W + 20 and -20 <= sy <= H + 20:
                draw_glow(sc, (sx, sy), PINK, 22, 42)
                pygame.draw.circle(sc, PINK, (int(sx), int(sy)), 6)
                pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), 2)

        # пули игроков
        for b in snap.get("bullets", []):
            sx, sy = cam.to_screen(b[0], b[1])
            if not (-40 <= sx <= W + 40 and -40 <= sy <= H + 40):
                continue
            p0 = V(sx, sy)
            d = V(b[2], b[3])
            draw_glow(sc, (sx, sy), CYAN, 18, 30)
            pygame.draw.line(sc, (0, 150, 200), p0, p0 - d * 0.035, 5)
            pygame.draw.line(sc, WHITE, p0, p0 - d * 0.03, 2)

        # игроки
        for pl in snap.get("players", []):
            self.draw_player(sc, pl, pl["pid"] == self.my_id, cam)

        # локальные эффекты — частицы, кольца (только у себя, т.к. в снапшоте их нет)
        if self.is_host:
            for q in self.parts:
                sx, sy = cam.to_screen(q.p.x, q.p.y)
                if -20 <= sx <= W + 20 and -20 <= sy <= H + 20:
                    k = max(0.0, q.life / q.max)
                    col = dim(q.col, k)
                    w = max(1, int(q.size * k))
                    pygame.draw.circle(sc, col, (int(sx), int(sy)), w)
            for r in self.rings:
                sx, sy = cam.to_screen(r.p.x, r.p.y)
                if -r.max <= sx <= W + r.max and -r.max <= sy <= H + r.max:
                    k = 1 - r.r / r.max
                    if k > 0:
                        pygame.draw.circle(sc, dim(r.col, k), (int(sx), int(sy)),
                                           int(r.r), max(1, int(r.w * k)))

        # всплывающие надписи +XP
        for px, py, s, life, col in snap.get("pops", []):
            sx, sy = cam.to_screen(px, py)
            if -60 <= sx <= W + 60 and -40 <= sy <= H + 40:
                text(sc, s, self.f_small, dim(col, min(1.0, life * 2)), (sx, sy), outline=1)

    # ================= HUD =================
    def draw_hint(self, sc):
        if not self.show_help:
            return
        alpha = 255 if self.help_t > 2.0 else int(255 * self.help_t / 2.0)
        hint = [
            "WASD — движение   мышь — прицел   ЛКМ — огонь",
            "SPACE — рывок   ПКМ — импульс   улучшения выбираются мышью   H — скрыть",
        ]
        box = pygame.Surface((min(760, W - 32), 64), pygame.SRCALPHA)
        box.fill((0, 0, 0, int(145 * alpha / 255)))
        x = (W - box.get_width()) // 2
        y = H - 78
        sc.blit(box, (x, y))
        for i, line in enumerate(hint):
            text(sc, line, self.f_small, (220, 240, 255), (W / 2, y + 18 + i * 25), outline=1)

    def draw_hud(self, sc, snap):
        me = None
        for pl in snap.get("players", []):
            if pl["pid"] == self.my_id:
                me = pl
                break

        # левый верх: все игроки (соревнование)
        y = 26
        for pl in snap.get("players", []):
            col = PLAYER_COLORS[(pl["pid"] - 1) % len(PLAYER_COLORS)]
            text(sc, pl["name"] + (" (вы)" if pl["pid"] == self.my_id else ""),
                 self.f_small, col, (24, y), "midleft", outline=2)
            text(sc, "%d очк.  ур.%d" % (pl["score"], pl.get("level", 1)),
                 self.f_small, WHITE, (24, y + 22), "midleft", outline=2)
            text(sc, "убийств: %d" % pl.get("kills", 0),
                 self.f_small, (170, 180, 210), (200, y + 22), "midleft", outline=2)
            for i in range(pl["max_hp"]):
                pts = shape(SHIP, -math.pi / 2, (24 + i * 20, y + 44), 8)
                if i < pl["hp"]:
                    pygame.draw.polygon(sc, (6, 40, 56), pts)
                    pygame.draw.polygon(sc, col, pts, 2)
                else:
                    pygame.draw.polygon(sc, (40, 50, 70), pts, 1)
            y += 62

        # правый верх: волна
        wave = snap.get("wave", 1)
        text(sc, "ВОЛНА %d" % wave, self.f_mid, PURPLE, (W - 30, 34), "midright", outline=2)
        remaining = snap.get("enemies_left", 0)
        text(sc, "УГРОЗ: %d" % remaining, self.f_small, WHITE, (W - 30, 62), "midright", outline=1)
        boss_in = snap.get("boss_in", 5)
        boss_alive = any(e.get("k") == "boss" for e in snap.get("enemies", []))
        boss_label = "БОСС НА АРЕНЕ" if boss_alive else ("БОСС В ЭТОЙ ВОЛНЕ" if boss_in == 0
                                                          else "БОСС ЧЕРЕЗ %d ВОЛН" % boss_in)
        text(sc, boss_label, self.f_small, MAGENTA, (W - 30, 84), "midright", outline=1)

        bosses = [e for e in snap.get("enemies", []) if e.get("k", "").startswith("boss")]
        if bosses:
            boss = bosses[0]
            bw = 500
            bx = (W - bw) // 2
            by = 104
            ratio = max(0.0, min(1.0, boss.get("hp", 0) / max(1, boss.get("max_hp", 1))))
            pygame.draw.rect(sc, (12, 8, 18), (bx, by, bw, 14))
            pygame.draw.rect(sc, MAGENTA, (bx, by, int(bw * ratio), 14))
            pygame.draw.rect(sc, (230, 190, 220), (bx, by, bw, 14), 1)
            text(sc, "БОСС  •  %d%%" % int(ratio * 100), self.f_small, WHITE,
                 (W / 2, by - 12), outline=1)

        # XP / level локального игрока
        if me:
            need = me.get("xp_next", 1) or 1
            cur = me.get("xp", 0)
            bar_w = 260
            bx = W / 2 - bar_w / 2
            by = 20
            pygame.draw.rect(sc, (20, 20, 40), (bx, by, bar_w, 10))
            pygame.draw.rect(sc, YELLOW, (bx, by, int(bar_w * cur / need), 10))
            pygame.draw.rect(sc, (60, 60, 100), (bx, by, bar_w, 10), 1)
            text(sc, "УР. %d  •  ДО СЛЕДУЮЩЕГО: %d/%d" % (me["level"], cur, need), self.f_mid, YELLOW, (W / 2, by + 26), outline=2)

            def bar(x, y, w, frac, col, label):
                pygame.draw.rect(sc, (20, 20, 40), (x, y, w, 12))
                pygame.draw.rect(sc, col, (x, y, int(w * frac), 12))
                pygame.draw.rect(sc, (60, 60, 100), (x, y, w, 12), 1)
                text(sc, label, self.f_small, col, (x + w + 12, y + 6), "midleft", outline=2)
            bar(24, H - 54, 154, 1 - me["dash_cd"] / 0.9, CYAN, "РЫВОК")
            full = me["charge"] >= 100
            pc = WHITE if full and int(self.t * 6) % 2 == 0 else MAGENTA
            bar(24, H - 30, 154, me["charge"] / 100, pc, "ИМПУЛЬС [E]" if full else "ИМПУЛЬС")

            # Временные баффы — отдельная компактная панель справа снизу, не под обучением.
            buffs = me.get("buffs", {})
            active = [(name, buffs.get(name, 0)) for name in ("rapid", "spread", "pulse_boost") if buffs.get(name, 0) > 0]
            if active:
                panel = pygame.Rect(W - 230, H - 48 - len(active) * 24, 206, len(active) * 24 + 18)
                pygame.draw.rect(sc, (8, 13, 20), panel)
                pygame.draw.rect(sc, (80, 100, 112), panel, 1)
                for i, (name, value) in enumerate(active):
                    label = {"rapid":"СКОРОСТРЕЛЬНОСТЬ","spread":"ТРОЙНОЙ ОГОНЬ","pulse_boost":"ИМПУЛЬСНЫЙ БУСТ"}[name]
                    col = PICK_COL.get(name, MAGENTA)
                    text(sc, "%s  %.1fс" % (label, value), self.f_small, col,
                         (panel.x + 10, panel.y + 10 + i * 24), "midleft", outline=1)

            if me["chain"] >= 5:
                text(sc, "x%d" % min(10, 1 + me["chain"] // 5), self.f_mid, YELLOW,
                     (W / 2, 100), outline=2)
                pygame.draw.rect(sc, YELLOW, (W / 2 - 50, 120,
                                              int(100 * max(0, me["combo_t"]) / 2.5), 3))

        if me and not me.get("alive", True) and self.state == "play":
            panel = pygame.Surface((460, 48), pygame.SRCALPHA)
            panel.fill((8, 10, 24, 190))
            sc.blit(panel, (W / 2 - 230, 142))
            text(sc, "ВЫ ВЫБЫЛИ — МОЖНО НАБЛЮДАТЬ ЗА ИГРОЙ",
                 self.f_small, RED, (W / 2, 166), outline=2)

        # баннер волны
        if snap.get("banner", 0) > 0 and self.state == "play":
            k = min(1.0, snap["banner"])
            text(sc, "ВОЛНА %d" % snap.get("wave", 1), self.f_huge, dim(WHITE, k),
                 (W / 2, H / 2 - 140), outline=3)

        # прицел
        if self.state == "play" and not self.paused:
            mx, my = pygame.mouse.get_pos()
            sw, sh = self.screen.get_size()
            if sw and sh:
                mx = mx * W / sw
                my = my * H / sh
            pygame.draw.circle(sc, WHITE, (int(mx), int(my)), 12, 1)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                pygame.draw.line(sc, WHITE, (mx + dx * 16, my + dy * 16),
                                 (mx + dx * 22, my + dy * 22), 2)

        if self.is_spectating() and self.state == "play":
            panel = pygame.Rect(W / 2 - 190, 142, 380, 38)
            pygame.draw.rect(sc, (8, 15, 26), panel)
            pygame.draw.rect(sc, (90, 145, 165), panel, 1)
            text(sc, "РЕЖИМ НАБЛЮДАТЕЛЯ  •  WASD — КАМЕРА",
                 self.f_small, (185, 215, 225), panel.center, outline=1)

        self.draw_hint(sc)

    def draw_upgrade_overlay(self, sc):
        if not self.intermission:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((5, 8, 14, 218))
        sc.blit(overlay, (0, 0))
        roster = list(self.players.values()) if self.is_host else (self.snap or {}).get("players", [])
        if self.is_host:
            ready_count = sum(1 for p in roster if p.alive and p.upgrade_ready)
            alive_count = sum(1 for p in roster if p.alive)
        else:
            ready_count = sum(1 for p in roster if p.get("alive", True) and p.get("upgrade_ready", False))
            alive_count = sum(1 for p in roster if p.get("alive", True))
        text(sc, "ПЕРЕДЫШКА МЕЖДУ ВОЛНАМИ", self.f_big, YELLOW, (W / 2, 92), outline=2)
        if self.local_choices:
            text(sc, "ВЫБЕРИ ОДНО УЛУЧШЕНИЕ", self.f_mid, WHITE, (W / 2, 148), outline=1)
            text(sc, "Следующая волна начнётся, когда выберут все игроки", self.f_small, (184, 195, 194), (W / 2, 184), outline=1)
        else:
            text(sc, "ВЫБОР ПРИНЯТ", self.f_mid, CYAN, (W / 2, 150), outline=1)
            text(sc, "ЖДИТЕ, ПОКА ВСЕ ВЫБЕРУТ СПОСОБНОСТИ  •  %d / %d" % (ready_count, alive_count),
                 self.f_small, WHITE, (W / 2, 188), outline=1)
        card_w, card_h, gap = 320, 220, 30
        total = len(self.local_choices) * card_w + max(0, len(self.local_choices) - 1) * gap
        x0 = (W - total) / 2
        for i, up_id in enumerate(self.local_choices):
            u = UPGRADES_BY_ID.get(up_id)
            if not u:
                continue
            x, y = x0 + i * (card_w + gap), H / 2 - card_h / 2 + 40
            rect = pygame.Rect(x, y, card_w, card_h)
            col = u["color"]
            hovered = rect.collidepoint(self.logical_mouse())
            pygame.draw.rect(sc, (3, 6, 11), rect.move(5, 6))
            pygame.draw.rect(sc, (18, 27, 38) if hovered else (13, 20, 30), rect)
            pygame.draw.rect(sc, (42, 51, 60), rect.inflate(-8, -8), 1)
            pygame.draw.rect(sc, WHITE if hovered else col, rect, 2 if hovered else 1)
            pygame.draw.line(sc, dim(col, 0.55), (x + 18, y + 8), (x + card_w - 18, y + 8), 1)
            text(sc, u["name"], self.f_mid, col, (rect.centerx, y + 82), outline=1)
            words, lines, current = u["desc"].split(), [], ""
            for word in words:
                if len(current) + len(word) + 1 > 24:
                    lines.append(current)
                    current = word
                else:
                    current = (current + " " + word).strip()
            if current:
                lines.append(current)
            for li, line in enumerate(lines):
                text(sc, line, self.f_small, WHITE, (rect.centerx, y + 130 + li * 22), outline=1)
            pygame.draw.line(sc, dim(col, 0.35), (x + 12, y + card_h - 38), (x + card_w - 12, y + card_h - 38), 1)
            text(sc, "ВЫБРАТЬ  [ЛКМ]", self.f_small, col, (rect.centerx, rect.bottom - 18), outline=1)
    def draw_menu(self, sc):
        cx, cy = W / 2, H / 2 - 140
        for i in range(5):
            angle = self.t * (0.3 + i * 0.15) * (1 if i % 2 else -1)
            color = [CYAN, MAGENTA, PURPLE, YELLOW, RED][i]
            pygame.draw.polygon(sc, dim(color, 0.5),
                                shape(HEX if i % 2 else SQ, angle, (cx, cy), 120 + i * 30), 1)
        pulse = 0.8 + 0.2 * math.sin(self.t * 3)
        draw_glow(sc, (cx, cy), CYAN, 190, 18)
        text(sc, "NEON VOID", self.f_huge, dim(CYAN, pulse), (cx, cy), outline=3)
        text(sc, "СЕТЕВАЯ ИГРА ПО ЛОКАЛЬНОЙ СЕТИ", self.f_mid, MAGENTA,
             (cx, cy + 78), outline=2)

        y = cy + 160
        self.draw_button(sc, pygame.Rect(cx - 210, y - 20, 420, 52), "СОЗДАТЬ ЛОББИ", CYAN)
        self.draw_button(sc, pygame.Rect(cx - 210, y + 42, 420, 52), "ПОДКЛЮЧИТЬСЯ ПО IP", MAGENTA)
        quick = "ПОДКЛЮЧИТЬСЯ: " + (self.last_ip if self.last_ip else "НЕТ СОХРАНЁННОГО IP")
        self.draw_button(sc, pygame.Rect(cx - 210, y + 104, 420, 44), quick,
                         YELLOW, enabled=bool(self.last_ip))
        self.draw_button(sc, pygame.Rect(cx - 210, y + 158, 420, 44),
                         "ИМЯ ИГРОКА: " + (self.name_input or "НЕ ЗАДАНО"), PURPLE)
        self.draw_button(sc, pygame.Rect(cx - 100, H - 58, 200, 38), "ВЫХОД", RED)

    def draw_lobby(self, sc):
        cx = W / 2
        text(sc, "ЛОББИ", self.f_huge, CYAN, (cx, 90), outline=3)
        if self.is_host:
            text(sc, "ВЫ — ХОСТ", self.f_mid, YELLOW, (cx, 170), outline=2)
            text(sc, "Ваш IP для подключения:", self.f_small, (160, 170, 220), (cx, 215), outline=2)
            host_ip = self.lan_ips[0] if self.lan_ips else "IP НЕ НАЙДЕН"
            text(sc, host_ip, self.f_big, WHITE, (cx, 276), outline=2)
            text(sc, "Порт: %d" % PORT, self.f_small, (164, 174, 182), (cx, 326), outline=1)
            text(sc, "Подключайтесь из той же локальной сети", self.f_small, (164, 174, 182), (cx, 356), outline=1)
        else:
            text(sc, "ВЫ — КЛИЕНТ", self.f_mid, YELLOW, (cx, 170), outline=2)
            text(sc, "Подключение: %s" % self.last_ip, self.f_small,
                 (160, 170, 220), (cx, 215), outline=2)

        py0 = 400
        text(sc, "ИГРОКИ В ЛОББИ:", self.f_mid, WHITE, (cx, py0), outline=2)
        for i, (pid, name) in enumerate(self.lobby_players):
            col = PLAYER_COLORS[(pid - 1) % len(PLAYER_COLORS)] if pid > 0 else YELLOW
            mark = " (вы)" if pid == self.my_id else ""
            role = " [ХОСТ]" if pid == 0 else ""
            text(sc, "%d. %s%s%s" % (i + 1, name, role, mark), self.f_mid, col,
                 (cx, py0 + 55 + i * 46), outline=2)
        if not self.lobby_players:
            text(sc, "ожидание подключений...", self.f_small, (150, 150, 180),
                 (cx, py0 + 55), outline=2)

        if self.is_host:
            self.draw_button(sc, pygame.Rect(cx - 190, H - 136, 380, 52), "НАЧАТЬ ИГРУ", CYAN)
        else:
            text(sc, "Ожидание, пока хост начнёт игру...", self.f_mid, PURPLE,
                 (cx, H - 110), outline=2)
        if self.connect_error:
            text(sc, self.connect_error, self.f_small, RED, (cx, H - 82), outline=2)
        self.draw_button(sc, pygame.Rect(cx - 150, H - 66, 300, 42), "НАЗАД В МЕНЮ", RED)

    def draw_error(self, sc):
        text(sc, "ОШИБКА", self.f_huge, RED, (W / 2, 150), outline=3)
        for i, line in enumerate(self.error_msg.split("\n")):
            text(sc, line, self.f_mid, WHITE, (W / 2, 290 + i * 46), outline=2)
        self.draw_button(sc, pygame.Rect(W / 2 - 150, H - 102, 300, 46), "В МЕНЮ", CYAN)

    def draw_dead(self, sc, snap):
        text(sc, "СЕССИЯ ЗАВЕРШЕНА", self.f_huge, RED, (W / 2, 100), outline=3)
        players = sorted(snap.get("players", []), key=lambda p: -p["score"])
        mvp_pid = players[0]["pid"] if players else -1

        # заголовки
        hdr_y = 220
        text(sc, "№", self.f_small, (150, 160, 200), (W / 2 - 380, hdr_y), "midleft", outline=2)
        text(sc, "ИМЯ", self.f_small, (150, 160, 200), (W / 2 - 320, hdr_y), "midleft", outline=2)
        text(sc, "ОЧКИ", self.f_small, (150, 160, 200), (W / 2 + 60, hdr_y), "midleft", outline=2)
        text(sc, "УБИЙСТВА", self.f_small, (150, 160, 200), (W / 2 + 200, hdr_y), "midleft", outline=2)
        text(sc, "УРОВЕНЬ", self.f_small, (150, 160, 200), (W / 2 + 340, hdr_y), "midleft", outline=2)

        y = 260
        for i, pl in enumerate(players):
            col = PLAYER_COLORS[(pl["pid"] - 1) % len(PLAYER_COLORS)]
            is_mvp = pl["pid"] == mvp_pid
            row_col = YELLOW if is_mvp else col
            mark = " ★" if is_mvp else ""
            text(sc, "%d" % (i + 1), self.f_mid, row_col, (W / 2 - 380, y), "midleft", outline=2)
            text(sc, pl["name"] + mark, self.f_mid, row_col, (W / 2 - 320, y), "midleft", outline=2)
            text(sc, str(pl["score"]), self.f_mid, WHITE, (W / 2 + 60, y), "midleft", outline=2)
            text(sc, str(pl.get("kills", 0)), self.f_mid, WHITE, (W / 2 + 200, y), "midleft", outline=2)
            text(sc, str(pl.get("level", 1)), self.f_mid, WHITE, (W / 2 + 340, y), "midleft", outline=2)
            y += 44

        if mvp_pid >= 0:
            mvp_name = next((p["name"] for p in players if p["pid"] == mvp_pid), "?")
            text(sc, "★ MVP: %s" % mvp_name, self.f_mid, YELLOW, (W / 2, y + 30), outline=2)

        if self.is_host:
            self.draw_button(sc, pygame.Rect(W / 2 - 190, H - 126, 380, 52), "ИГРАТЬ СНОВА", CYAN)
        self.draw_button(sc, pygame.Rect(W / 2 - 150, H - 70, 300, 42), "В МЕНЮ", RED)

    def draw_input_overlay(self, sc):
        if not self.input_mode:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 205))
        sc.blit(overlay, (0, 0))
        label = "ВВЕДИТЕ IP ХОСТА" if self.input_mode == "ip" else "ВВЕДИТЕ ИМЯ"
        text(sc, label, self.f_big, CYAN, (W / 2, H / 2 - 110), outline=3)
        value = self.ip_input if self.input_mode == "ip" else self.name_input
        box = pygame.Rect(W / 2 - 280, H / 2 - 45, 560, 64)
        pygame.draw.rect(sc, (5, 12, 28), box)
        pygame.draw.rect(sc, CYAN, box, 2)
        shown = value + ("|" if int(self.t * 2) % 2 == 0 else "")
        if self.input_mode == "name" and self.first_run:
            text(sc, "ЭТО ИМЯ УВИДЯТ ДРУГИЕ ИГРОКИ", self.f_small, (164, 174, 182), (W / 2, H / 2 - 72), outline=1)
        text(sc, shown, self.f_big, WHITE, (W / 2, H / 2 - 13), outline=2)
        self.draw_button(sc, pygame.Rect(W / 2 - 115, H / 2 + 32, 230, 38),
                         "ВСТАВИТЬ ИЗ БУФЕРА", PURPLE)
        self.draw_button(sc, pygame.Rect(W / 2 - 135, H / 2 + 80, 270, 46),
                         "ПОДТВЕРДИТЬ", CYAN)
        self.draw_button(sc, pygame.Rect(W / 2 - 135, H / 2 + 136, 270, 40),
                         "ОТМЕНА", RED)
        if self.connect_error:
            text(sc, self.connect_error, self.f_small, RED, (W / 2, H / 2 + 190), outline=2)
        text(sc, "Можно также нажать Ctrl+V и Enter", self.f_small,
             (170, 190, 220), (W / 2, H / 2 + 220), outline=2)

    # ================= главный render =================
    def draw_ambient_background(self, sc):
        """Медленная параллакс-геометрия для меню, лобби и ошибок."""
        offset = (self.t * 9.0) % 96
        for x in range(-96, W + 96, 96):
            xx = x + offset
            pygame.draw.line(sc, (18, 25, 34), (xx, 0), (xx - 110, H), 1)
        for i, color in enumerate((CYAN, PURPLE, MAGENTA)):
            phase = self.t * (0.18 + i * 0.06) + i * 2.1
            cx = W * (0.22 + i * 0.28) + math.sin(phase) * 90
            cy = H * (0.32 + i * 0.17) + math.cos(phase * 0.8) * 55
            radius = 90 + 18 * math.sin(self.t * 0.7 + i)
            pygame.draw.circle(sc, dim(color, 0.12), (int(cx), int(cy)), int(radius), 1)
            pygame.draw.circle(sc, dim(color, 0.08), (int(cx), int(cy)), int(radius * 1.35), 1)

    def draw_mouse_cursor(self, sc):
        mx, my = self.logical_mouse()
        points = [(mx, my), (mx + 4, my + 24), (mx + 10, my + 17),
                  (mx + 17, my + 29), (mx + 22, my + 26), (mx + 15, my + 14),
                  (mx + 25, my + 12)]
        pygame.draw.polygon(sc, (8, 12, 18), [(x + 2, y + 2) for x, y in points])
        pygame.draw.polygon(sc, WHITE, points)
        pygame.draw.polygon(sc, (35, 48, 54), points, 1)

    def render(self):
        sc = self.scene

        # Живой игрок ведёт камеру за собой. В режиме наблюдателя камера
        # свободная и перемещается WASD/стрелками.
        if not self.is_spectating():
            tx, ty = self._player_screen_pos()
            self.camera.follow(tx, ty, self.clock.get_time() / 1000.0)

        snap = None
        if self.state in ("play", "dead"):
            snap = self.build_snapshot() if self.is_host else self.snap
            if snap is not None:
                self.wave = int(snap.get("wave", self.wave))

        # мир
        if snap is not None:
            self.draw_world(sc, snap, self.camera)
        else:
            # для меню/лобби — только звёзды и сетка «вокруг»
            sc.fill(BG)
            for x, y, z in self.stars:
                sx = (x - self.camera.x * 0.3 * z) % W
                sy = (y - self.camera.y * 0.3 * z) % H
                c = int(60 + 150 * z)
                sc.set_at((int(sx), int(sy)), (c // 2, c // 2, c))
            self.draw_ambient_background(sc)
            if self.state == "menu":
                cx, cy = W / 2, H / 2 - 140
                for i in range(5):
                    a = self.t * (0.3 + i * 0.15) * (1 if i % 2 else -1)
                    col = [CYAN, MAGENTA, PURPLE, YELLOW, RED][i]
                    pygame.draw.polygon(sc, dim(col, 0.5),
                                        shape(HEX if i % 2 else SQ, a, (cx, cy), 120 + i * 30), 1)

        # flash
        if self.flash > 0:
            sc.fill((int(70 * self.flash), 0, int(10 * self.flash)), special_flags=pygame.BLEND_RGB_ADD)

        # Мягкий CRT glow без геометрических искажений и размытия интерфейса.
        post = sc.copy()
        bloom(post, W, H, 0.08)

        # Screen shake is applied to the game image, not to the interface.
        shake_amount = self.shake if self.state == "play" and snap is not None else 0.0
        ox = random.uniform(-shake_amount, shake_amount) if shake_amount > 0.5 else 0
        oy = random.uniform(-shake_amount, shake_amount) if shake_amount > 0.5 else 0
        self.screen.fill((0, 0, 0))
        self.screen.blit(post, (ox, oy))
        self.screen.blit(self.overlay, (0, 0))

        # UI поверх игрового слоя: текст и кнопки остаются контрастными.
        if self.state == "menu":
            self.draw_menu(self.screen)
        elif self.state == "lobby":
            self.draw_lobby(self.screen)
        elif self.state == "error":
            self.draw_error(self.screen)
        elif self.state in ("play", "dead"):
            if snap is not None:
                self.draw_hud(self.screen, snap)
                self.draw_upgrade_overlay(self.screen)
                if self.state == "dead":
                    self.draw_dead(self.screen, snap)
                if self.paused:
                    text(self.screen, "ПАУЗА", self.f_huge, WHITE, (W / 2, H / 2), outline=3)

        self.draw_input_overlay(self.screen)

        if self.debug_overlay:
            snap_players = snap.get("players", []) if snap else []
            snap_enemies = snap.get("enemies", []) if snap else []
            debug_lines = [
                "DEBUG  F3: hide",
                "FPS: %.1f   STATE: %s" % (self.clock.get_fps(), self.state),
                "PLAYERS: %d   ENEMIES: %d" % (len(snap_players) if snap else len(self.players), len(snap_enemies) if snap else len(self.enemies)),
                "BULLETS: %d   PARTICLES: %d" % (len(snap.get("bullets", [])) if snap else len(self.bullets), len(self.parts)),
                "NETWORK: %s" % ("HOST" if self.is_host else ("CLIENT" if self.client else "OFFLINE")),
            ]
            panel = pygame.Surface((310, 126), pygame.SRCALPHA)
            panel.fill((4, 8, 18, 220))
            self.screen.blit(panel, (W - 322, H - 138))
            for i, line in enumerate(debug_lines):
                text(self.screen, line, self.f_small, GREEN, (W - 312, H - 126 + i * 23), "topleft", outline=1)

        # Курсор рисуется последним: он выше карточек, текста и debug-панели.
        if self.intermission and self.state == "play":
            self.draw_mouse_cursor(self.screen)

    # ================= главный цикл =================
    def run(self):
        log.info("Игра запущена | разрешение=%dx%d | порт=%d", W, H, PORT)
        while True:
            real_dt = min(self.clock.tick(60) / 1000.0, 1 / 20)
            self.t += real_dt
            self.debug_timer += real_dt
            if self.debug_timer >= 5.0:
                self.debug_timer = 0.0
                enemy_count = len(self.enemies) if self.is_host else len(self.snap.get("enemies", [])) if self.snap else 0
                player_count = len(self.players) if self.is_host else len(self.snap.get("players", [])) if self.snap else 0
                client_count = len(self.server.clients) if self.server else (1 if self.client else 0)
                log.info("FPS=%.1f state=%s players=%d enemies=%d bullets=%d particles=%d net_clients=%d", self.clock.get_fps(), self.state, player_count, enemy_count, len(self.bullets), len(self.parts), client_count)
            self.handle_events()
            self.poll_network()

            for s in self.stars:
                s[0] = (s[0] - 12 * s[2] * real_dt) % W
                s[1] = (s[1] - 6 * s[2] * real_dt) % H

            self.update_spectator_camera(real_dt)

            if self.state == "play" and not self.paused:
                if self.is_host:
                    if self.hitstop > 0:
                        self.hitstop -= real_dt
                    else:
                        self.host_update(real_dt)
                    snap = self.build_snapshot()
                    self.server.broadcast(snap)
                else:
                    self.send_input()

            self.render()
            pygame.display.flip()