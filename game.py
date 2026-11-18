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
                "boss_spawn": self.make(92, 38, 0.95, 0.15, "sin", 0.08),
                "boss_hit": [self.make(190, 82, 0.12, 0.075, "tri", 0.04),
                             self.make(145, 62, 0.16, 0.085, "sin", 0.06)],
                "enemy_shot": self.make(440, 260, 0.09, 0.028, "tri", 0.0),
                "boss_death": self.make(180, 28, 0.85, 0.13, "sin", 0.10),
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
        melody = (659, 0, 523, 659, 784, 0, 659, 523,
                  587, 0, 440, 587, 698, 0, 587, 440,
                  523, 659, 784, 0, 880, 784, 659, 523,
                  440, 0, 523, 659, 587, 523, 440, 0)
        bass = (82.4, 82.4, 110, 110, 73.4, 73.4, 98, 98)
        count = int(rate * 0.16)
        buf = array.array("h")
        for step, note in enumerate(melody):
            lead_phase = bass_phase = 0.0
            for i in range(count):
                t = i / count
                bass_phase += bass[(step // 4) % len(bass)] / rate
                env = min(1.0, i / 900) * min(1.0, (count - i) / 2600)
                low = math.sin(bass_phase * math.tau) * env * 0.055
                lead = 0.0
                if note:
                    lead_phase += note / rate
                    tri = 1.0 - 4.0 * abs(round(lead_phase) - lead_phase)
                    lead_env = min(1.0, i / 700) * min(1.0, (count - i) / 2100)
                    lead = tri * lead_env * 0.048
                kick = math.sin((72 - 42 * t) * math.tau * i / rate) * math.exp(-t * 18) * 0.15 if step % 4 == 0 else 0.0
                snare = random.uniform(-1, 1) * math.exp(-t * 24) * 0.045 if step % 8 == 4 else 0.0
                hat = random.uniform(-1, 1) * math.exp(-t * 38) * 0.018 if step % 2 else 0.0
                sample = max(-0.9, min(0.9, lead + low + kick + snare + hat))
                buf.append(int(sample * 32767))
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
        pygame.display.set_caption("NEON VOID")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        icon = pygame.Surface((64, 64), pygame.SRCALPHA)
        icon.fill((7, 13, 23))
        pygame.draw.polygon(icon, CYAN, [(32, 3), (57, 18), (57, 46), (32, 61), (7, 46), (7, 18)], 4)
        pygame.draw.polygon(icon, MAGENTA, [(32, 15), (45, 32), (32, 49), (19, 32)], 3)
        pygame.draw.circle(icon, WHITE, (32, 32), 5)
        pygame.display.set_icon(icon)
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
        self.state = "loading"
        self.loading_t = 0.0
        self.error_msg = ""
        self.tutorial_active = False
        self.tutorial_ready = False
        self.lobby_scroll = 0
        self.hud_scroll = 0
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

    def draw_fit_text(self, surface, value, color, rect, base_size=18, min_size=12):
        size = base_size
        f = font(size)
        while size > min_size and f.size(str(value))[0] > rect.width:
            size -= 1
            f = font(size)
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        text(surface, str(value), f, color, rect.center, outline=1)
        surface.set_clip(old_clip)

    def draw_wrapped_text(self, surface, value, f, color, rect, max_lines=2):
        words = str(value).split()
        lines, current = [], ""
        for word in words:
            candidate = (current + " " + word).strip()
            if current and f.size(candidate)[0] > rect.width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and f.size(last + "...")[0] > rect.width:
                last = last[:-1].rstrip()
            lines[-1] = last + "..."
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        line_h = f.get_linesize()
        y = rect.centery - len(lines) * line_h / 2 + line_h / 2
        for line in lines:
            text(surface, line, f, color, (rect.centerx, y), outline=1)
            y += line_h
        surface.set_clip(old_clip)

    def draw_button(self, surface, rect, label, color=CYAN, enabled=True):
        mouse = self.logical_mouse()
        hovered = enabled and rect.collidepoint(mouse)
        hover_key = (rect.x, rect.y, rect.w, rect.h, label)
        if hovered and self._last_hovered_button != hover_key:
            self.audio.play("ui_hover")
            self._last_hovered_button = hover_key
        elif not hovered and self._last_hovered_button == hover_key:
            self._last_hovered_button = None
        pulse = 1.0 + (0.018 * (0.5 + 0.5 * math.sin(self.t * 9.0)) if hovered else 0.0)
        r = pygame.Rect(0, 0, int(rect.w * pulse), int(rect.h * pulse))
        r.center = rect.center
        fill = (29, 43, 57) if hovered else (17, 27, 39)
        edge = color if enabled else (75, 82, 94)
        cut = min(16, r.height // 3)
        pts = [(r.left + cut, r.top), (r.right - cut, r.top),
               (r.right, r.top + cut), (r.right, r.bottom - cut),
               (r.right - cut, r.bottom), (r.left + cut, r.bottom),
               (r.left, r.bottom - cut), (r.left, r.top + cut)]
        pygame.draw.polygon(surface, (2, 5, 12), [(x + 5, y + 6) for x, y in pts])
        pygame.draw.polygon(surface, (7, 13, 23), pts)
        inner = [(r.left + cut + 3, r.top + 3), (r.right - cut - 3, r.top + 3),
                 (r.right - 3, r.top + cut + 3), (r.right - 3, r.bottom - cut - 3),
                 (r.right - cut - 3, r.bottom - 3), (r.left + cut + 3, r.bottom - 3),
                 (r.left + 3, r.bottom - cut - 3), (r.left + 3, r.top + cut + 3)]
        pygame.draw.polygon(surface, fill, inner)
        pygame.draw.line(surface, dim(edge, 0.95 if hovered else 0.58), pts[0], pts[1], 2)
        pygame.draw.line(surface, dim(edge, 0.75), pts[7], pts[0], 2)
        pygame.draw.line(surface, dim(edge, 0.22), pts[4], pts[5], 2)
        pygame.draw.polygon(surface, edge, pts, 1)
        if hovered:
            pygame.draw.line(surface, WHITE, (r.left + cut + 12, r.top + 7),
                             (r.right - cut - 12, r.top + 7), 1)
        self.draw_fit_text(surface, label, WHITE if enabled else (112, 120, 132),
                           r.inflate(-18, -8), 30 if r.height >= 50 else 18, 12)
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
        self.help_t = 0.0
        self.tutorial_active = True
        self.tutorial_ready = False
        for player in self.players.values():
            player.tutorial_ready = False
        self.state = "play"
        pygame.mouse.set_visible(False)
        self.camera.follow(self.players[self.my_id].p.x, self.players[self.my_id].p.y, 0, snap=True)
        pygame.mouse.set_visible(True)
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
        elif t == "tutorial_ready" and self.state == "play" and self.tutorial_active:
            p = self.players.get(cid)
            if p:
                p.tutorial_ready = True
                self.check_tutorial_ready()
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
            self.check_tutorial_ready()

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
            self.tutorial_active = True
            self.tutorial_ready = False
            pygame.mouse.set_visible(True)
        elif t == "begin":
            self.tutorial_active = False
            self.tutorial_ready = False
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
        elif t == "pause":
            self.paused = bool(m.get("paused", False))
            pygame.mouse.set_visible(self.paused or self.intermission)
        elif t == "dead":
            self.local_choices = []
            self.paused = False
            self.state = "dead"
            pygame.mouse.set_visible(True)
        elif t == "disconnect":
            self.handle_host_disconnect()

    def check_tutorial_ready(self):
        if not self.is_host or not self.tutorial_active:
            return
        if all((not p.alive) or p.tutorial_ready for p in self.players.values()):
            self.tutorial_active = False
            self.server.broadcast({"t": "begin"})
            pygame.mouse.set_visible(False)

    def set_paused(self, value):
        value = bool(value)
        if self.paused == value:
            return
        self.paused = value
        pygame.mouse.set_visible(value or self.intermission or self.state == "dead")
        if self.is_host and self.server:
            self.server.broadcast({"t": "pause", "paused": value})

    def confirm_tutorial(self):
        if not self.tutorial_active:
            return
        if self.is_host:
            p = self.players.get(self.my_id)
            if p:
                p.tutorial_ready = True
            self.tutorial_ready = True
            self.check_tutorial_ready()
        elif self.client and not self.tutorial_ready:
            self.tutorial_ready = True
            self.client.send({"t": "tutorial_ready"})

    def send_input(self):
        if self.tutorial_active or self.paused or self.is_host or not self.client or self.state != "play":
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
        if self.paused or self.state not in ("play", "dead") or not self.is_spectating():
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
                continue
            if self.paused and self.state == "play":
                if e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_p):
                    if self.is_host:
                        self.set_paused(False)
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    mx, my = self.logical_mouse(e.pos)
                    cx = W / 2
                    if self.is_host and pygame.Rect(cx - 175, H / 2 + 42, 350, 52).collidepoint(mx, my):
                        self.set_paused(False)
                    elif pygame.Rect(cx - 175, H / 2 + 108, 350, 48).collidepoint(mx, my):
                        self.leave_net()
                continue
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

                if self.state == "loading":
                    continue
                if self.tutorial_active and e.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.confirm_tutorial()
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
                        self.set_paused(not self.paused)
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
            elif e.type == pygame.MOUSEWHEEL:
                mx, my = self.logical_mouse()
                if self.state == "lobby" and pygame.Rect(245, 360, 790, H - 520).collidepoint(mx, my):
                    visible = max(1, (H - 532) // 34)
                    self.lobby_scroll = max(0, min(max(0, len(self.lobby_players) - visible), self.lobby_scroll - e.y))
                elif self.state in ("play", "dead") and pygame.Rect(14, 16, 238, min(H - 180, 340)).collidepoint(mx, my):
                    roster = self.players if self.is_host else ((self.snap or {}).get("players", []))
                    self.hud_scroll = max(0, min(max(0, len(roster) - 6), self.hud_scroll - e.y))
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if self.tutorial_active and e.button == 1:
                    self.confirm_tutorial()
                    continue
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
                    card_w, card_h, gap = 320, 238, 30
                    total = len(self.local_choices) * card_w + (len(self.local_choices) - 1) * gap
                    x0 = (W - total) / 2
                    card_y = H / 2 - card_h / 2 + 38
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
        if self.tutorial_active:
            return
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
        p.hurt_t = max(0.0, p.hurt_t - dt)
        p.cool = max(0.0, p.cool - dt)
        p.pulse_boost = max(0.0, p.pulse_boost - dt)
        p.shield_t = max(0.0, p.shield_t - dt)
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
                                           shot_damage * p.bullet_size, p.pierce, p.bullet_size))
            for i in range(p.multishot):
                spread = 0.12 * (i + 1)
                for sign in (-1, 1):
                    aa = p.ang + spread * sign
                    d = V(math.cos(aa), math.sin(aa))
                    shot_damage = p.dmg * (2.0 if random.random() < p.crit else 1.0)
                    self.bullets.append(Bullet(p.p + d * 22, d * (1100 * p.bullet_speed),
                                               p.pid, shot_damage * p.bullet_size, p.pierce, p.bullet_size))
            fwd = V(math.cos(p.ang), math.sin(p.ang))
            p.v -= fwd * 25
            self.burst(p.p + fwd * 24, CYAN, 3, 260, (0.08, 0.2), 2)
            self.audio.play("shoot")

    def do_pulse(self, p):
        p.charge = 0
        self.shake = max(self.shake, 34)
        p.inv = max(p.inv, 0.85)
        p.shield_t = 5.0
        p.shield_hits = min(5, 2 + p.upgrades.get("pulse_power", 0))
        p.pulse_boost = 5.0
        self.audio.play("pulse")
        self.rings.append(Ring(p.p, 18, 170, 520, CYAN, 5))
        self.rings.append(Ring(p.p, 12, 125, 760, WHITE, 2))
        self.burst(p.p, CYAN, 42, 420, (0.25, 0.7), 3)

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
                player_count = max(1, len(self.players))
                self.spawn_t = max(0.12, (0.7 - 0.018 * self.wave) / (1.0 + 0.08 * (player_count - 1)))
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
            p.pending_upgrades = 1
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
        player_count = max(1, sum(1 for p in self.players.values() if p.alive))
        n = min(80, int((7 + self.wave * 2.7) * (1.0 + 0.15 * (player_count - 1))))
        q = []
        for _ in range(n):
            r = random.random()
            if self.wave >= 6 and r < 0.08:
                q.append("bruiser")
            elif self.wave >= 4 and r < 0.17:
                q.append("orbiter")
            elif self.wave >= 3 and r < 0.27:
                q.append("tank")
            elif self.wave >= 4 and r < 0.37:
                q.append("splitter")
            elif self.wave >= 3 and r < 0.47:
                q.append("dasher")
            elif self.wave >= 5 and r < 0.56:
                q.append("mine")
            elif self.wave >= 2 and r < 0.68:
                q.append("shooter")
            elif self.wave >= 2 and r < 0.82:
                q.append("swarm")
            else:
                q.append("chaser")
        if self.wave % 5 == 0:
            bosses = ("boss", "boss_storm", "boss_hunter", "boss_void", "boss_siege")
            q.append(bosses[(self.wave // 5 - 1) % len(bosses)])
        self.queue = q
        if self.wave % 4 == 0:
            self.pickups.append([V(WORLD_W / 2, WORLD_H / 2), "heal", 12.0])

    def spawn(self, kind):
        alive_players = [p for p in self.players.values() if p.alive]
        if not alive_players or (len(self.enemies) >= 90 and not kind.startswith("boss")):
            return
        tgt = random.choice(alive_players)
        ang = random.uniform(0, math.tau)
        dist = random.uniform(420, 820)
        pos = tgt.p + V(math.cos(ang), math.sin(ang)) * dist
        pos.x = max(50, min(WORLD_W - 50, pos.x))
        pos.y = max(50, min(WORLD_H - 50, pos.y))
        enemy = Enemy(kind, pos, self.wave)
        player_scale = 1.0 + 0.20 * max(0, len(self.players) - 1)
        enemy.hp = max(1, math.ceil(enemy.hp * player_scale))
        enemy.max_hp = enemy.hp
        enemy.spd *= 1.0 + 0.035 * max(0, len(self.players) - 1)
        self.enemies.append(enemy)
        if kind.startswith("boss"):
            self.banner_t = max(self.banner_t, 2.8)
            self.shake = max(self.shake, 12)
            self.audio.play("boss_spawn")

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
                self.audio.play("enemy_shot")
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
                self.audio.play("enemy_shot")
        elif k == "orbiter":
            tangent = V(-d.y, d.x) * e.side
            desired = 300
            velocity = tangent * e.spd * 1.35
            if dist < desired - 55:
                velocity -= d * e.spd * 1.25
            elif dist > desired + 75:
                velocity += d * e.spd * 0.9
            e.v = e.v.lerp(velocity, min(1.0, 2.8 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = 1.65
                base = math.atan2(d.y, d.x)
                for offset in (-0.24, 0.0, 0.24):
                    a = base + offset
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 350, 6.0])
                self.audio.play("enemy_shot")
        elif k == "bruiser":
            e.cool -= dt
            if e.windup > 0:
                e.windup -= dt
                e.v *= math.exp(-8.0 * dt)
                if e.windup <= 0:
                    e.charge_t = 0.52
                    e.v = e.charge_dir * (e.spd * 5.2)
                    self.rings.append(Ring(e.p, 12, 115, 620, ORANGE, 4))
                    self.audio.play("dash")
            elif e.charge_t > 0:
                e.charge_t = max(0.0, e.charge_t - dt)
                e.v = e.charge_dir * (e.spd * 5.2)
            else:
                e.v = e.v.lerp(d * e.spd, min(1.0, 1.8 * dt))
                if e.cool <= 0:
                    e.cool = 3.4
                    e.windup = 0.62
                    e.charge_dir = V(d)
        elif k in ("boss", "boss_storm", "boss_hunter", "boss_void", "boss_siege"):
            e.v = e.v.lerp(d * e.spd, min(1.0, 1.25 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = max(1.25, 2.35 - self.wave * 0.018)
                base = math.atan2(d.y, d.x)
                if k == "boss":
                    for i in range(18):
                        a = i * math.tau / 18 + e.ang
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 320, 7.0])
                    for offset in (-0.34, 0.0, 0.34):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 410, 6.0])
                elif k == "boss_storm":
                    for i in range(30):
                        a = i * math.tau / 30 + e.ang
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 285, 7.5])
                    for i in range(8):
                        a = base + (i - 3.5) * 0.16
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 390, 6.0])
                    e.ang += 0.55
                elif k == "boss_hunter":
                    for offset in (-0.72, -0.48, -0.24, 0, 0.24, 0.48, 0.72):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 475, 6.0])
                    e.v += d * 680
                    self.rings.append(Ring(e.p, 10, 145, 720, ORANGE, 5))
                elif k == "boss_void":
                    side = V(-d.y, d.x) * random.choice((-1, 1))
                    e.p = target.p - d * random.uniform(250, 340) + side * random.uniform(100, 220)
                    e.p.x = max(80, min(WORLD_W - 80, e.p.x))
                    e.p.y = max(80, min(WORLD_H - 80, e.p.y))
                    e.v = V()
                    self.rings.append(Ring(e.p, 14, 230, 520, PURPLE, 6))
                    for i in range(12):
                        a = i * math.tau / 12 + e.ang
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 330, 7.0])
                    for offset in (-0.18, 0.0, 0.18):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 430, 6.0])
                else:
                    e.v *= 0.25
                    for i in range(24):
                        a = i * math.tau / 24 + e.ang
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 245, 8.0])
                    for offset in (-0.9, -0.45, 0.0, 0.45, 0.9):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 360, 7.0])
                    self.rings.append(Ring(e.p, 18, 185, 430, YELLOW, 8))
                self.shake = max(self.shake, 11 if k == "boss_siege" else 8)
                boss_sounds = {"boss": "boom", "boss_storm": "enemy_shot",
                               "boss_hunter": "dash", "boss_void": "pulse",
                               "boss_siege": "boss_spawn"}
                self.audio.play(boss_sounds.get(k, "boom"))
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
                owner_pid = pk[3] if len(pk) > 3 else None
                eligible = [p for p in alive_players if owner_pid is None or p.pid == owner_pid]
                if not eligible:
                    keep.append(pk)
                    continue
                target = min(eligible, key=lambda p: (p.p - pk[0]).length_squared())
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
            self.audio.play("boss_hit" if e.kind.startswith("boss") else "hit")

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
            src.combo_t = 2.5 + 0.6 * src.combo_bonus
            pts = int(d["score"] * src.mult() * src.score_gain)
            src.score += pts
            src.kills += 1
            if src.lifesteal:
                src.lifesteal_progress += src.lifesteal
                if src.lifesteal_progress >= 18:
                    src.lifesteal_progress -= 18
                    src.hp = min(src.max_hp, src.hp + 1)
                    self.pops.append([V(src.p), "+1 HP", 0.9, GREEN, src.pid])
            src.charge = min(100.0, src.charge + (26 if e.kind.startswith("boss") else 14 if e.kind == "tank" else 7) * src.pulse_gain)
            self.pops.append([V(e.p), "+%d" % pts, 0.8, e.col, src.pid])
            # Одно улучшение выдаётся в конце каждой волны.
        self.audio.play("boom")
        if e.kind in ("tank", "splitter"):
            for _ in range(4 if e.kind == "tank" else 3):
                c = Enemy("swarm", e.p + V(random.uniform(-30, 30), random.uniform(-30, 30)), self.wave)
                c.age = 0.45
                self.enemies.append(c)
        if e.kind.startswith("boss"):
            self.audio.play("boss_death")
            self.burst(e.p, MAGENTA, 180, 980, (0.5, 1.5), 5)
            self.rings.append(Ring(e.p, 10, 900, 700, YELLOW, 9))
            for player in self.players.values():
                if not player.alive:
                    continue
                reward = "heal" if player.hp < player.max_hp and random.random() < 0.55 else random.choice(("rapid", "spread"))
                self.pickups.append([V(player.p), reward, 18.0, player.pid])
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
        if p.shield_t > 0 and p.shield_hits > 0:
            p.shield_hits -= 1
            if p.shield_hits <= 0:
                p.shield_t = 0.0
            self.pops.append([V(p.p), "ЩИТ", 0.75, CYAN])
            self.rings.append(Ring(p.p, 20, 125, 620, CYAN, 4))
            self.burst(p.p, CYAN, 18, 300, (0.15, 0.35), 2)
            return
        p.armor_hits += 1
        if p.armor > 0 and p.armor_hits % max(2, 5 - p.armor) == 0:
            self.pops.append([V(p.p), "БРОНЯ", 0.8, CYAN])
            self.rings.append(Ring(p.p, 8, 100, 520, CYAN, 3))
            return
        p.hp -= 1
        p.inv = 0.58
        p.chain = 0
        self.shake = max(self.shake, 24)
        p.hurt_t = 0.52
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
        # пули игрока -> враги
        keep_b = []
        for b in self.bullets:
            hit = False
            for e in list(self.enemies):
                if e.dead or e.age < 0.7:
                    continue
                if id(e) in b.hit_ids:
                    continue
                rr = e.r + 5 * b.size
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

        # пули врагов -> игроки
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

        # враги <-> игроки
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
            "boss_in": 5 if self.wave == 0 else (5 - ((self.wave + (1 if self.intermission else 0)) % 5)) % 5,
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
                "shield_t": round(p.shield_t, 1), "shield_hits": p.shield_hits,
                "hurt_t": round(p.hurt_t, 2),
                "upgrade_choices": list(p.upgrade_choices),
                "upgrade_ready": p.upgrade_ready,
                "pending_upgrades": p.pending_upgrades,
                "buffs": {"rapid": round(p.rapid,1), "spread": round(p.spread,1),
                          "pulse_boost": round(p.pulse_boost,1)},
            })
        for b in self.bullets:
            snap["bullets"].append([round(b.p.x, 1), round(b.p.y, 1),
                                    round(b.v.x, 1), round(b.v.y, 1), round(b.size, 2)])
        for b in self.ebullets:
            snap["ebullets"].append([round(b[0].x, 1), round(b[0].y, 1)])
        for e in self.enemies:
            if e.dead:
                continue
            snap["enemies"].append({
                "k": e.kind, "x": round(e.p.x, 1), "y": round(e.p.y, 1),
                "r": e.r, "ang": round(e.ang, 2), "age": round(e.age, 2),
                "flash": round(e.flash, 2), "cool": round(e.cool, 2),
                "windup": round(e.windup, 2),
                "hp": e.hp, "max_hp": e.max_hp,
            })
        for pk in self.pickups:
            snap["pickups"].append([round(pk[0].x, 1), round(pk[0].y, 1), pk[1], round(pk[2], 1),
                                    pk[3] if len(pk) > 3 else -1])
        for pop in self.pops:
            pos, label, life, col = pop[:4]
            owner_pid = pop[4] if len(pop) > 4 else -1
            snap["pops"].append([round(pos.x, 1), round(pos.y, 1), label,
                                 round(life, 2), col, owner_pid])
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
        # имя игрока
        label = data["name"]
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
        elif kind in ("shooter", "mine", "orbiter"):
            pts = shape(HEX, e["ang"] * (0.8 if kind == "orbiter" else 0.4), (sx, sy), r)
        elif kind == "bruiser":
            pts = shape(SQ, e["ang"] * 0.35, (sx, sy), r * 1.12)
        elif kind.startswith("boss"):
            boss_shape = DIAMOND if kind == "boss_hunter" else SQ if kind == "boss_siege" else TRI if kind == "boss_void" else HEX
            pts = shape(boss_shape, e["ang"] * 0.3, (sx, sy), r * 1.35)
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
            if kind == "boss_void":
                pygame.draw.circle(sc, PURPLE, (int(sx), int(sy)), int(r * 1.1 + 8 * math.sin(self.t * 4)), 2)
            elif kind == "boss_siege":
                pygame.draw.rect(sc, YELLOW, pygame.Rect(int(sx-r*0.55), int(sy-r*0.55),
                                 int(r*1.1), int(r*1.1)), 3)
            for spoke in range(6):
                a = e["ang"] + spoke * math.tau / 6
                start = (sx + math.cos(a) * r * 0.48, sy + math.sin(a) * r * 0.48)
                end = (sx + math.cos(a) * r * 0.92, sy + math.sin(a) * r * 0.92)
                pygame.draw.line(sc, col, start, end, 3)
        elif kind == "mine":
            pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), max(3, int(r * 0.28)), 2)
            for spoke in range(4):
                a = e["ang"] + spoke * math.pi / 2
                pygame.draw.line(sc, col,
                                 (sx + math.cos(a) * r * 0.35, sy + math.sin(a) * r * 0.35),
                                 (sx + math.cos(a) * r * 0.95, sy + math.sin(a) * r * 0.95), 2)
        if kind == "orbiter":
            orbit = 1.0 + 0.18 * math.sin(self.t * 7 + e["ang"])
            pygame.draw.circle(sc, col, (int(sx), int(sy)), int(r * 1.5 * orbit), 1)
            pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), max(3, int(r * 0.24)), 2)
        elif kind == "bruiser":
            for spoke in range(4):
                a = e["ang"] + spoke * math.pi / 2
                pygame.draw.line(sc, col,
                                 (sx + math.cos(a) * r * 0.55, sy + math.sin(a) * r * 0.55),
                                 (sx + math.cos(a) * r * 1.2, sy + math.sin(a) * r * 1.2), 4)
            if e.get("windup", 0) > 0:
                pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), int(r * 1.5), 2)
        elif kind == "shooter":
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
            pygame.draw.line(sc, (0, 150, 200), p0, p0 - d * 0.035, max(3, int(5 * (b[4] if len(b) > 4 else 1))))
            pygame.draw.line(sc, WHITE, p0, p0 - d * 0.03, max(2, int(2 * (b[4] if len(b) > 4 else 1))))

        # игроки
        for pl in snap.get("players", []):
            self.draw_player(sc, pl, pl["pid"] == self.my_id, cam)

        # локальные эффекты - частицы, кольца (только у себя, т.к. в снапшоте их нет)
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
        for pop in snap.get("pops", []):
            px, py, label, life, col = pop[:5]
            owner_pid = pop[5] if len(pop) > 5 else -1
            if owner_pid not in (-1, self.my_id):
                continue
            sx, sy = cam.to_screen(px, py)
            if -60 <= sx <= W + 60 and -40 <= sy <= H + 40:
                text(sc, label, self.f_small, dim(col, min(1.0, life * 2)), (sx, sy), outline=1)

    # ================= HUD =================
    def draw_hint(self, sc):
        # Подсказки управления убраны из боя; клавиши способностей показаны у индикаторов.
        return

    def draw_hud(self, sc, snap):
        me = None
        for pl in snap.get("players", []):
            if pl["pid"] == self.my_id:
                me = pl
                break

        # Прокручиваемая панель игроков: число участников не раздвигает HUD.
        roster = snap.get("players", [])
        panel = pygame.Rect(14, 16, 238, min(H - 180, 340))
        pygame.draw.rect(sc, (5, 10, 18), panel)
        pygame.draw.rect(sc, (48, 72, 82), panel, 1)
        visible = max(1, (panel.h - 28) // 42)
        self.hud_scroll = max(0, min(self.hud_scroll, max(0, len(roster) - visible)))
        old_clip = sc.get_clip()
        sc.set_clip(panel.inflate(-4, -4))
        for idx, pl in enumerate(roster[self.hud_scroll:self.hud_scroll + visible]):
            y = panel.y + 9 + idx * 42
            col = PLAYER_COLORS[(pl["pid"] - 1) % len(PLAYER_COLORS)]
            label = pl["name"] + ("  -  ВЫ" if pl["pid"] == self.my_id else "")
            text(sc, label, self.f_small, col, (panel.x + 10, y + 2), "midleft", outline=1)
            text(sc, "%d" % pl["score"], self.f_small, WHITE, (panel.right - 12, y + 2), "midright", outline=1)
            for i in range(pl["max_hp"]):
                pts = shape(SHIP, -math.pi / 2, (panel.x + 17 + i * 18, y + 25), 6)
                pygame.draw.polygon(sc, col if i < pl["hp"] else (40, 50, 60), pts,
                                    1 if i >= pl["hp"] else 0)
        sc.set_clip(old_clip)
        if len(roster) > visible:
            text(sc, "^ %d/%d v" % (self.hud_scroll + 1, len(roster)),
                 self.f_small, (155, 180, 190), (panel.centerx, panel.bottom - 11), outline=1)

        # правый верх: волна
        wave = snap.get("wave", 1)
        text(sc, "ВОЛНА %d" % wave, self.f_mid, PURPLE, (W - 30, 34), "midright", outline=2)
        remaining = snap.get("enemies_left", 0)
        text(sc, "УГРОЗ: %d" % remaining, self.f_small, WHITE, (W - 30, 62), "midright", outline=1)
        boss_in = snap.get("boss_in", 5)
        boss_alive = any(e.get("k", "").startswith("boss") for e in snap.get("enemies", []))
        boss_label = "БОСС НА АРЕНЕ" if boss_alive else ("БОСС В ЭТОЙ ВОЛНЕ" if boss_in == 0
                                                          else "БОСС ЧЕРЕЗ %d ВОЛН" % boss_in)
        text(sc, boss_label, self.f_small, MAGENTA, (W - 30, 84), "midright", outline=1)

        # Стрелка к ближайшему врагу, если он за пределами экрана.
        if me and snap.get("enemies"):
            offscreen = []
            for enemy in snap["enemies"]:
                ex, ey = self.camera.to_screen(enemy["x"], enemy["y"])
                if ex < 18 or ex > W - 18 or ey < 18 or ey > H - 18:
                    dx, dy = ex - W / 2, ey - H / 2
                    offscreen.append((dx * dx + dy * dy, dx, dy))
            if offscreen:
                _, dx, dy = min(offscreen, key=lambda item: item[0])
                angle = math.atan2(dy, dx)
                scale = min((W / 2 - 30) / max(1, abs(dx)),
                            (H / 2 - 30) / max(1, abs(dy)))
                ax, ay = W / 2 + dx * scale, H / 2 + dy * scale
                tip = (ax + math.cos(angle) * 13, ay + math.sin(angle) * 13)
                left = (ax + math.cos(angle + 2.45) * 11, ay + math.sin(angle + 2.45) * 11)
                right = (ax + math.cos(angle - 2.45) * 11, ay + math.sin(angle - 2.45) * 11)
                pygame.draw.polygon(sc, MAGENTA, (tip, left, right))
                pygame.draw.circle(sc, WHITE, (int(ax), int(ay)), 3)

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
            boss_names = {
                "boss": "СТРАЖ АРЕНЫ",
                "boss_storm": "ШТОРМ",
                "boss_hunter": "ОХОТНИК",
                "boss_void": "ПУСТОТА",
                "boss_siege": "ОСАДА",
            }
            boss_name = boss_names.get(boss.get("k"), "БОСС")
            text(sc, "%s  -  %d%%" % (boss_name, int(ratio * 100)), self.f_small, WHITE,
                 (W / 2, by - 12), outline=1)

        if me:
            def bar(x, y, w, frac, col, label):
                pygame.draw.rect(sc, (20, 20, 40), (x, y, w, 12))
                pygame.draw.rect(sc, col, (x, y, int(w * frac), 12))
                pygame.draw.rect(sc, (60, 60, 100), (x, y, w, 12), 1)
                text(sc, label, self.f_small, col, (x + w + 12, y + 6), "midleft", outline=2)
            bar(24, H - 54, 154, 1 - me["dash_cd"] / 0.9, CYAN, "РЫВОК [SPACE]")
            full = me["charge"] >= 100
            pc = WHITE if full and int(self.t * 6) % 2 == 0 else MAGENTA
            bar(24, H - 30, 154, me["charge"] / 100, pc, "ЩИТ [ПКМ]")
            if me.get("shield_t", 0) > 0:
                text(sc, "ЩИТ  %d  -  %.1fс" % (me.get("shield_hits", 0), me["shield_t"]),
                     self.f_small, CYAN, (24, H - 82), "midleft", outline=1)

            # Временные баффы - отдельная компактная панель справа снизу, не под обучением.
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

        if me and me.get("shield_t", 0) > 0:
            sx, sy = self.camera.to_screen(me["x"], me["y"])
            pygame.draw.circle(sc, CYAN, (int(sx), int(sy)), 31 + int(2 * math.sin(self.t * 9)), 2)
            pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), 35, 1)

        if me and not me.get("alive", True) and self.state == "play":
            panel = pygame.Surface((460, 48), pygame.SRCALPHA)
            panel.fill((8, 10, 24, 190))
            sc.blit(panel, (W / 2 - 230, 142))
            text(sc, "YOU ARE OUT - SPECTATING",
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
            text(sc, "SPECTATOR MODE - WASD CAMERA",
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
        text(sc, "ПЕРЕДЫШКА МЕЖДУ ВОЛНАМИ", self.f_big, YELLOW, (W / 2, 88), outline=2)
        if self.local_choices:
            text(sc, "ВЫБЕРИ ОДНО УЛУЧШЕНИЕ", self.f_mid, WHITE, (W / 2, 145), outline=1)
            text(sc, "СЛЕДУЮЩАЯ ВОЛНА НАЧНЕТСЯ, КОГДА ВСЕ ВЫБЕРУТ", self.f_small,
                 (184, 195, 194), (W / 2, 180), outline=1)
        else:
            text(sc, "ВЫБОР ПРИНЯТ", self.f_mid, CYAN, (W / 2, 145), outline=1)
            text(sc, "ЖДИТЕ ОСТАЛЬНЫХ  -  %d / %d" % (ready_count, alive_count),
                 self.f_small, WHITE, (W / 2, 180), outline=1)
        card_w, card_h, gap = 320, 238, 30
        total = len(self.local_choices) * card_w + max(0, len(self.local_choices) - 1) * gap
        x0 = (W - total) / 2
        for i, up_id in enumerate(self.local_choices):
            u = UPGRADES_BY_ID.get(up_id)
            if not u:
                continue
            x, y = x0 + i * (card_w + gap), H / 2 - card_h / 2 + 38
            rect = pygame.Rect(x, y, card_w, card_h)
            col = u["color"]
            hovered = rect.collidepoint(self.logical_mouse())
            pulse = 1.0 + (0.012 * (0.5 + 0.5 * math.sin(self.t * 7 + i)) if hovered else 0.0)
            card = pygame.Rect(0, 0, int(card_w * pulse), int(card_h * pulse))
            card.center = rect.center
            draw_glow(sc, (card.centerx, card.y + 30), col, 110, 12 if hovered else 7)
            cut = 20
            pts = [(card.x + cut, card.y), (card.right - cut, card.y),
                   (card.right, card.y + cut), (card.right, card.bottom - cut),
                   (card.right - cut, card.bottom), (card.x + cut, card.bottom),
                   (card.x, card.bottom - cut), (card.x, card.y + cut)]
            pygame.draw.polygon(sc, (2, 5, 11), [(px + 5, py + 7) for px, py in pts])
            pygame.draw.polygon(sc, (15, 23, 34) if hovered else (10, 17, 27), pts)
            pygame.draw.polygon(sc, dim(col, 0.9 if hovered else 0.58), pts, 2 if hovered else 1)
            pygame.draw.line(sc, dim(col, 0.48), (card.x + 24, card.y + 8),
                             (card.right - 24, card.y + 8), 2)
            text(sc, "МОДУЛЬ %02d" % (i + 1), self.f_small, dim(col, 0.9),
                 (card.centerx, card.y + 29), outline=1)
            self.draw_wrapped_text(sc, u["name"], self.f_mid, col,
                                   pygame.Rect(card.x + 18, card.y + 48, card.w - 36, 72), 2)
            self.draw_wrapped_text(sc, u["desc"], self.f_small, WHITE,
                                   pygame.Rect(card.x + 24, card.y + 126, card.w - 48, 66), 3)
            pygame.draw.line(sc, dim(col, 0.35), (card.x + 18, card.bottom - 34),
                             (card.right - 18, card.bottom - 34), 1)
            text(sc, "ВЫБРАТЬ  -  ЛКМ", self.f_small, col,
                 (card.centerx, card.bottom - 17), outline=1)

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
            role, shown_ip = "ВЫ - ХОСТ", (self.lan_ips[0] if self.lan_ips else "IP НЕ НАЙДЕН")
        else:
            role, shown_ip = "ВЫ - КЛИЕНТ", (self.last_ip or "НЕИЗВЕСТНО")
        text(sc, role, self.f_mid, YELLOW, (cx - 175, 190), outline=2)
        text(sc, "IP: " + shown_ip, self.f_mid, WHITE, (cx + 190, 190), outline=2)

        py0 = 330
        text(sc, "ИГРОКИ В ЛОББИ  -  %d" % len(self.lobby_players), self.f_mid, WHITE, (cx, py0), outline=2)
        list_rect = pygame.Rect(245, 360, 790, H - 520)
        pygame.draw.rect(sc, (5, 10, 18), list_rect)
        pygame.draw.rect(sc, (48, 72, 82), list_rect, 1)
        visible = max(1, (list_rect.h - 12) // 34)
        self.lobby_scroll = max(0, min(self.lobby_scroll, max(0, len(self.lobby_players) - visible)))
        old_clip = sc.get_clip()
        sc.set_clip(list_rect.inflate(-4, -4))
        for i, (pid, name) in enumerate(self.lobby_players[self.lobby_scroll:self.lobby_scroll + visible]):
            col = PLAYER_COLORS[(pid - 1) % len(PLAYER_COLORS)] if pid > 0 else YELLOW
            mark = " - ВЫ" if pid == self.my_id else ""
            role = " - ХОСТ" if pid == 0 else ""
            text(sc, "%02d  %s%s%s" % (self.lobby_scroll + i + 1, name, role, mark),
                 self.f_small, col, (list_rect.x + 18, list_rect.y + 17 + i * 34), "midleft", outline=1)
        sc.set_clip(old_clip)
        if len(self.lobby_players) > visible:
            text(sc, "SCROLL  %d-%d OF %d" %
                 (self.lobby_scroll + 1, min(len(self.lobby_players), self.lobby_scroll + visible), len(self.lobby_players)),
                 self.f_small, (150, 175, 185), (cx, list_rect.bottom - 12), outline=1)
        if not self.lobby_players:
            text(sc, "ожидание подключений...", self.f_small, (150, 150, 180),
                 (cx, list_rect.centery), outline=2)

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

    def draw_pause_overlay(self, sc):
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((2, 4, 9, 205))
        sc.blit(shade, (0, 0))
        panel = pygame.Rect(W / 2 - 245, H / 2 - 145, 490, 320)
        pts = [(panel.x + 24, panel.y), (panel.right - 24, panel.y),
               (panel.right, panel.y + 24), (panel.right, panel.bottom - 24),
               (panel.right - 24, panel.bottom), (panel.x + 24, panel.bottom),
               (panel.x, panel.bottom - 24), (panel.x, panel.y + 24)]
        pygame.draw.polygon(sc, (4, 8, 15), pts)
        pygame.draw.polygon(sc, (60, 85, 98), pts, 1)
        pygame.draw.line(sc, CYAN, (panel.x + 28, panel.y + 70),
                         (panel.right - 28, panel.y + 70), 2)
        text(sc, "ПАУЗА", self.f_huge, WHITE, (W / 2, panel.y + 42), outline=2)
        text(sc, "АРЕНА ОСТАНОВЛЕНА", self.f_small, (155, 183, 192),
             (W / 2, panel.y + 98), outline=1)
        if self.is_host:
            self.draw_button(sc, pygame.Rect(W / 2 - 175, H / 2 + 42, 350, 52), "ПРОДОЛЖИТЬ", CYAN)
        else:
            text(sc, "ОЖИДАНИЕ ХОСТА", self.f_mid, YELLOW, (W / 2, H / 2 + 68), outline=1)
        self.draw_button(sc, pygame.Rect(W / 2 - 175, H / 2 + 108, 350, 48), "ПОКИНУТЬ СЕССИЮ", RED)

    def draw_dead(self, sc, snap):
        text(sc, "СЕССИЯ ЗАВЕРШЕНА", self.f_huge, RED, (W / 2, 100), outline=3)
        players = sorted(snap.get("players", []), key=lambda p: -p["score"])
        mvp_pid = players[0]["pid"] if players else -1

        # заголовки
        hdr_y = 220
        text(sc, "N", self.f_small, (150, 160, 200), (W / 2 - 380, hdr_y), "midleft", outline=2)
        text(sc, "ИМЯ", self.f_small, (150, 160, 200), (W / 2 - 320, hdr_y), "midleft", outline=2)
        text(sc, "ОЧКИ", self.f_small, (150, 160, 200), (W / 2 + 60, hdr_y), "midleft", outline=2)
        text(sc, "УБИЙСТВА", self.f_small, (150, 160, 200), (W / 2 + 200, hdr_y), "midleft", outline=2)
        text(sc, "ВОЛНЫ", self.f_small, (150, 160, 200), (W / 2 + 340, hdr_y), "midleft", outline=2)

        y = 260
        for i, pl in enumerate(players):
            col = PLAYER_COLORS[(pl["pid"] - 1) % len(PLAYER_COLORS)]
            is_mvp = pl["pid"] == mvp_pid
            row_col = YELLOW if is_mvp else col
            mark = "" if is_mvp else ""
            text(sc, "%d" % (i + 1), self.f_mid, row_col, (W / 2 - 380, y), "midleft", outline=2)
            text(sc, pl["name"] + mark, self.f_mid, row_col, (W / 2 - 320, y), "midleft", outline=2)
            text(sc, str(pl["score"]), self.f_mid, WHITE, (W / 2 + 60, y), "midleft", outline=2)
            text(sc, str(pl.get("kills", 0)), self.f_mid, WHITE, (W / 2 + 200, y), "midleft", outline=2)
            text(sc, str(snap.get("wave", 0)), self.f_mid, WHITE, (W / 2 + 340, y), "midleft", outline=2)
            y += 44

        if mvp_pid >= 0:
            mvp_name = next((p["name"] for p in players if p["pid"] == mvp_pid), "?")
            text(sc, "MVP: %s" % mvp_name, self.f_mid, YELLOW, (W / 2, y + 30), outline=2)

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

    # ================= заставка и обучение =================
    def draw_tutorial_overlay(self, sc):
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((3, 7, 13, 232))
        sc.blit(shade, (0, 0))
        panel = pygame.Rect(W / 2 - 330, H / 2 - 230, 660, 460)
        pygame.draw.rect(sc, (10, 18, 28), panel)
        pygame.draw.rect(sc, CYAN, panel, 2)
        pygame.draw.line(sc, MAGENTA, (panel.x + 22, panel.y + 64),
                         (panel.right - 22, panel.y + 64), 2)
        text(sc, "ПЕРЕД ПЕРВОЙ ВОЛНОЙ", self.f_big, CYAN, (W / 2, panel.y + 42), outline=2)
        rows = [
            ("WASD", "движение по арене"),
            ("МЫШЬ", "наводись на врагов"),
            ("ЛКМ", "стрельба"),
            ("SPACE", "рывок - быстрое уклонение"),
            ("ПКМ", "щит - блокирует несколько попаданий"),
            ("МЕЖДУ ВОЛНАМИ", "выбери одно улучшение мышью"),
        ]
        for i, (key, desc) in enumerate(rows):
            y = panel.y + 105 + i * 47
            text(sc, key, self.f_small, YELLOW if i < 4 else MAGENTA,
                 (panel.x + 34, y), "midleft", outline=1)
            text(sc, desc, self.f_small, WHITE, (panel.x + 210, y), "midleft", outline=1)
        if self.is_host and self.tutorial_ready:
            text(sc, "ГОТОВО - ОЖИДАНИЕ ОСТАЛЬНЫХ ИГРОКОВ",
                 self.f_small, GREEN, (W / 2, panel.bottom - 52), outline=1)
        elif self.is_host:
            text(sc, "ХОСТ: ENTER ИЛИ КЛИК - НАЧАТЬ, КОГДА ВСЕ ГОТОВЫ",
                 self.f_small, GREEN, (W / 2, panel.bottom - 52), outline=1)
        elif self.tutorial_ready:
            text(sc, "ГОТОВО - ОЖИДАНИЕ ОСТАЛЬНЫХ ИГРОКОВ",
                 self.f_small, GREEN, (W / 2, panel.bottom - 52), outline=1)
        else:
            text(sc, "ENTER ИЛИ КЛИК - ПОДТВЕРДИТЬ ГОТОВНОСТЬ",
                 self.f_small, GREEN, (W / 2, panel.bottom - 52), outline=1)

    def draw_splash(self, sc):
        sc.fill((5, 9, 17))
        cx, cy = W / 2, H / 2
        pulse = 0.75 + 0.25 * math.sin(self.t * 4.0)
        for i in range(7):
            radius = 45 + i * 42 + math.sin(self.t * 1.8 + i) * 8
            color = (CYAN, MAGENTA, PURPLE)[i % 3]
            pygame.draw.circle(sc, dim(color, 0.18 + 0.08 * pulse),
                               (int(cx), int(cy - 25)), int(radius), 1)
        pygame.draw.polygon(sc, CYAN, shape(HEX, self.t * 0.7, (cx, cy - 25), 88), 2)
        pygame.draw.polygon(sc, MAGENTA, shape(SQ, -self.t * 0.45, (cx, cy - 25), 120), 1)
        draw_glow(sc, (cx, cy - 25), CYAN, 160, 20)
        text(sc, "NEON VOID", self.f_huge, dim(WHITE, pulse), (cx, cy - 25), outline=3)
        text(sc, "INITIALIZING ARENA SYSTEM", self.f_small, CYAN, (cx, cy + 92), outline=1)
        progress = min(1.0, self.loading_t / 2.8)
        pygame.draw.rect(sc, (18, 30, 42), (cx - 180, cy + 128, 360, 8))
        pygame.draw.rect(sc, CYAN, (cx - 180, cy + 128, int(360 * progress), 8))
        text(sc, "%d%%" % int(progress * 100), self.f_small, WHITE, (cx, cy + 158), outline=1)

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
            # для меню/лобби - только звёзды и сетка "вокруг"
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
        # Hit feedback is rendered locally from the local player's snapshot.

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

        if snap is not None and self.state == "play":
            local_player = next((p for p in snap.get("players", [])
                                 if p.get("pid") == self.my_id), None)
            hurt_t = local_player.get("hurt_t", 0.0) if local_player else 0.0
            if hurt_t > 0:
                hurt_layer = pygame.Surface((W, H), pygame.SRCALPHA)
                hurt_layer.fill((155, 12, 24, int(105 * min(1.0, hurt_t / 0.52))))
                self.screen.blit(hurt_layer, (0, 0))

        # UI поверх игрового слоя: текст и кнопки остаются контрастными.
        if self.state == "loading":
            self.draw_splash(self.screen)
        elif self.state == "menu":
            self.draw_menu(self.screen)
        elif self.state == "lobby":
            self.draw_lobby(self.screen)
        elif self.state == "error":
            self.draw_error(self.screen)
        elif self.state in ("play", "dead"):
            if snap is not None:
                self.draw_hud(self.screen, snap)
                self.draw_upgrade_overlay(self.screen)
                if self.tutorial_active and self.state == "play":
                    self.draw_tutorial_overlay(self.screen)
                if self.state == "dead" and self.is_host:
                    end_tint = pygame.Surface((W, H), pygame.SRCALPHA)
                    end_tint.fill((135, 10, 22, 112))
                    self.screen.blit(end_tint, (0, 0))
                if self.state == "dead":
                    self.draw_dead(self.screen, snap)
                if self.paused:
                    self.draw_pause_overlay(self.screen)

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

            if self.state == "loading":
                self.loading_t += real_dt
                if self.loading_t >= 2.8:
                    self.state = "menu"
                    if self.first_run:
                        self.input_mode = "name"
            if self.state == "play" and not self.paused:
                if self.is_host:
                    if self.hitstop > 0 and not self.tutorial_active:
                        self.hitstop -= real_dt
                    elif not self.tutorial_active:
                        self.host_update(real_dt)
                    snap = self.build_snapshot()
                    self.server.broadcast(snap)
                else:
                    self.send_input()

            self.render()
            pygame.display.flip()