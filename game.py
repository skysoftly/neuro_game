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
    KINDS, PICK_COL, PICK_LET, PLAYER_COLORS, PLAYER_SKINS,
)
from fonts import font, text
from draw_utils import shape, dim, make_overlay, bloom, read_clipboard
from camera import Camera
from entities import Player, Enemy, Particle, Ring, Bullet
from upgrades import UPGRADES_BY_ID, apply_upgrade, roll_upgrades
from network import HostServer, ClientConn
from visuals import draw_glow
from rendering import RenderingMixin

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
from audio import Audio


# ---------- игра ----------
class Game(RenderingMixin):
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
        self.bloom_small = pygame.Surface((max(1, W // 8), max(1, H // 8))).convert()
        self.bloom_full = pygame.Surface((W, H)).convert()
        self.pause_shade = pygame.Surface((W, H), pygame.SRCALPHA)
        self.pause_shade.fill((2, 4, 9, 205))
        self.tutorial_shade = pygame.Surface((W, H), pygame.SRCALPHA)
        self.tutorial_shade.fill((3, 7, 13, 232))
        self.intermission_shade = pygame.Surface((W, H), pygame.SRCALPHA)
        self.intermission_shade.fill((5, 8, 14, 218))
        self.upgrade_card_shade = pygame.Surface((320, 238), pygame.SRCALPHA)
        self.upgrade_card_shade.fill((0, 0, 0, 48))
        self.input_shade = pygame.Surface((W, H), pygame.SRCALPHA)
        self.input_shade.fill((0, 0, 0, 205))
        self.end_tint = pygame.Surface((W, H), pygame.SRCALPHA)
        self.end_tint.fill((135, 10, 22, 112))
        self.debug_panel_surface = pygame.Surface((310, 126), pygame.SRCALPHA)
        self.debug_panel_surface.fill((4, 8, 18, 220))
        vignette_small = pygame.Surface((64, 36), pygame.SRCALPHA)
        for vy in range(36):
            for vx in range(64):
                dx = (vx - 31.5) / 31.5
                dy = (vy - 17.5) / 17.5
                distance = math.sqrt(dx * dx + dy * dy)
                edge = max(0.0, min(1.0, (distance - 0.28) / 0.82))
                alpha = int(150 * edge * edge)
                vignette_small.set_at((vx, vy), (155, 8, 24, alpha))
        self.red_vignette = pygame.transform.smoothscale(vignette_small, (W, H)).convert_alpha()
        self.stars = [[random.uniform(0, W), random.uniform(0, H), random.uniform(0.2, 1.0)] for _ in range(200)]
        self.t = 0.0
        self.state = "loading"
        self.loading_t = 0.0
        self.error_msg = ""
        self.tutorial_active = False
        self.tutorial_ready = False
        self.lobby_scroll = 0
        self.paused = False
        self.snapshot_timer = 0.0
        self.input_send_timer = 0.0
        self.target_fps = 120
        self.audio_scene = "menu"
        self.last_ui_state = "loading"
        self.last_hover_sound_t = -10.0
        self.camera_target_previous = None
        self.camera_target_current = None
        self.camera_lerp_elapsed = 0.0
        self.camera_lerp_duration = 1.0 / 30.0
        self.screen_shake_enabled = True
        self.shake = 0.0
        self.spectator_speed = 620.0
        self.banner_t = 0.0
        self.intermission = False
        self.local_upgrade_waiting = False
        self.wave = 0
        self.wave_started = False
        self.debug_overlay = False
        self.debug_timer = 0.0

        cfg = load_config()
        self.last_ip = cfg.get("last_ip", "")
        self.local_color_index = max(0, min(len(PLAYER_COLORS) - 1, int(cfg.get("player_color", 0))))
        self.local_skin_index = max(0, min(len(PLAYER_SKINS) - 1, int(cfg.get("player_skin", 0))))
        self.local_hat_index = max(0, min(9, int(cfg.get("player_hat", 0))))
        self.music_volume = max(0.0, min(1.0, float(cfg.get("music_volume", 0.12))))
        self.sfx_volume = max(0.0, min(1.0, float(cfg.get("sfx_volume", 0.75))))
        self.screen_shake_enabled = bool(cfg.get("screen_shake", True))
        self.target_fps = int(cfg.get("target_fps", 120))
        if self.target_fps not in (60, 120, 144, 0):
            self.target_fps = 120
        self.borderless_fullscreen = bool(cfg.get("borderless_fullscreen", False))
        if self.borderless_fullscreen:
            self.set_display_mode(True)
        self.audio.set_volumes(self.music_volume, self.sfx_volume)
        self.first_run = not bool(str(cfg.get("name", "")).strip())
        self.name_input = str(cfg.get("name", "")).strip() if not self.first_run else ""
        self.ip_input = self.last_ip
        self.lan_ips = get_lan_ips()

        self.is_host = False
        self.server = None
        self.client = None
        self.my_id = 0
        self.lobby_players = []
        self.lobby_ready = set()
        self.input_mode = None
        self.connect_error = ""

        self.camera = Camera(W, H, WORLD_W, WORLD_H, margin=180)

        self.players = {}
        self.bullets = []
        self.ebullets = []
        self.enemies = []
        self.parts = []
        self.rings = []
        self.pickups = []   # [pos, kind, ttl]
        self.pops = []      # [pos, text, ttl, color]
        self.sound_events = []
        self.queue = []
        self.spawn_t = 0.0
        self.wave_delay = 1.5
        self.rng = random.Random()

        # у клиента: локальные данные из снапшота
        self.snap = None
        self.local_choices = []   # id апгрейдов для оверлея выбора
        self._last_hovered_button = None

        pygame.mouse.set_visible(True)

    def play_sound(self, sound_name, owner_pid=None):
        """Play locally and replicate simulation sounds to the correct LAN clients."""
        if not self.is_host:
            if owner_pid is None or owner_pid == self.my_id:
                self.audio.play(sound_name)
            return
        if owner_pid is None or owner_pid == self.my_id:
            self.audio.play(sound_name)
        self.sound_events.append([sound_name, -1 if owner_pid is None else int(owner_pid)])

    def persist(self):
        save_config({"last_ip": self.last_ip, "name": self.name_input,
                     "music_volume": self.music_volume, "sfx_volume": self.sfx_volume,
                     "screen_shake": self.screen_shake_enabled, "target_fps": self.target_fps,
                     "borderless_fullscreen": self.borderless_fullscreen,
                     "player_color": self.local_color_index, "player_skin": self.local_skin_index,
                     "player_hat": self.local_hat_index})

    def set_display_mode(self, fullscreen):
        """Use a desktop-sized borderless window while keeping 1280x720 logical rendering."""
        if fullscreen:
            self.screen = pygame.display.set_mode(
                (W, H), pygame.SCALED | pygame.NOFRAME, vsync=1
            )
            try:
                sizes = pygame.display.get_desktop_sizes()
                desktop_w, desktop_h = sizes[0] if sizes else (0, 0)
                if desktop_w <= 0 or desktop_h <= 0:
                    info = pygame.display.Info()
                    desktop_w, desktop_h = info.current_w, info.current_h
                if desktop_w > 0 and desktop_h > 0:
                    pygame.display.set_window_size(desktop_w, desktop_h)
                    pygame.display.set_window_position(0, 0)
            except (AttributeError, pygame.error):
                log.exception("Не удалось развернуть безрамочное окно на весь экран")
        else:
            self.screen = pygame.display.set_mode(
                (W, H), pygame.SCALED | pygame.RESIZABLE, vsync=1
            )

    def toggle_borderless_fullscreen(self):
        self.borderless_fullscreen = not self.borderless_fullscreen
        self.set_display_mode(self.borderless_fullscreen)
        self.persist()

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
        chosen_font = font(10)
        chosen_lines = []
        start_size = min(f.get_height(), 36)
        for size in range(start_size, 9, -1):
            candidate_font = font(size)
            lines, current = [], ""
            for word in words:
                candidate = (current + " " + word).strip()
                if current and candidate_font.size(candidate)[0] > rect.width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            chosen_font, chosen_lines = candidate_font, lines
            if len(lines) <= max_lines and all(candidate_font.size(line)[0] <= rect.width for line in lines):
                break
        chosen_lines = chosen_lines[:max_lines]
        for index, line in enumerate(chosen_lines):
            if chosen_font.size(line)[0] <= rect.width:
                continue
            suffix = "..." if len(line) > 3 else ""
            while line and chosen_font.size(line + suffix)[0] > rect.width:
                line = line[:-1].rstrip()
            chosen_lines[index] = line + suffix
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        line_h = chosen_font.get_linesize()
        if line_h * len(chosen_lines) > rect.height:
            chosen_font = font(max(9, rect.height // max(1, len(chosen_lines)) - 2))
            line_h = chosen_font.get_linesize()
        y = rect.centery - len(chosen_lines) * line_h / 2 + line_h / 2
        for line in chosen_lines:
            text(surface, line, chosen_font, color, (rect.centerx, y), outline=1)
            y += line_h
        surface.set_clip(old_clip)

    def draw_button(self, surface, rect, label, color=CYAN, enabled=True):
        mouse = self.logical_mouse()
        hovered = enabled and rect.collidepoint(mouse)
        hover_key = (rect.x, rect.y, rect.w, rect.h, label)
        if hovered and self._last_hovered_button != hover_key:
            if self.t - self.last_hover_sound_t >= 0.14:
                self.audio.play("ui_hover")
                self.last_hover_sound_t = self.t
            self._last_hovered_button = hover_key
        elif not hovered and self._last_hovered_button == hover_key:
            self._last_hovered_button = None
        pulse = 1.0 + (0.04 * (0.5 + 0.5 * math.sin(self.t * 9.0)) if hovered else 0.0)
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
        self.lobby_players = [(0, self.name_input or "Хост", self.local_color_index,
                               self.local_skin_index, self.local_hat_index)]
        self.lobby_ready = {0}
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
        self.client.send({"t": "hello", "name": self.name_input or "Клиент",
                           "color": self.local_color_index, "skin": self.local_skin_index,
                           "hat": self.local_hat_index})
        self.state = "lobby"
        self.lobby_players = []
        self.lobby_ready = set()

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
        self.lobby_ready = set()
        self.tutorial_active = False
        self.tutorial_ready = False
        self.input_mode = None
        self.players = {}
        self.bullets, self.ebullets, self.enemies = [], [], []
        self.parts, self.rings, self.pickups, self.pops = [], [], [], []
        self.queue = []
        self.local_choices = []
        self.local_upgrade_waiting = False
        self.intermission = False
        self.sound_events.clear()
        self.snapshot_timer = 0.0
        self.snap = None
        self.paused = False
        self.shake = 0.0
        self.camera.x = max(-180, min(WORLD_W + 180 - W, (WORLD_W - W) / 2))
        self.camera.y = max(-180, min(WORLD_H + 180 - H, (WORLD_H - H) / 2))
        self.state = "menu"
        pygame.mouse.set_visible(True)

    def host_start_game(self):
        if not self.is_host or self.state not in ("lobby", "dead"):
            return
        if self.state == "lobby":
            required = {entry[0] for entry in self.lobby_players}
            if not required.issubset(self.lobby_ready):
                return
        self.players = {}
        for pid, name, color_index, skin_index, hat_index in self.lobby_players:
            player = Player(pid, name)
            player.color_index = color_index
            player.color = PLAYER_COLORS[color_index]
            player.skin = skin_index
            player.hat = hat_index
            self.players[pid] = player
        self.bullets, self.ebullets, self.enemies = [], [], []
        self.parts, self.rings, self.pickups, self.pops = [], [], [], []
        self.queue = []
        self.local_choices = []
        self.sound_events.clear()
        self.snapshot_timer = 0.0
        self.snap = None
        self.paused = False
        self.wave = 0
        self.wave_started = False
        self.wave_delay = 1.5
        self.spawn_t = 0.0
        self.intermission = False
        self.local_upgrade_waiting = False
        self.banner_t = 2.0
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
            # Подключение разрешено только пока хост находится в лобби.
            if self.state != "lobby":
                self.server.send(cid, {"t": "started"})
                self.server._drop_client(cid)
                return
            if len(self.lobby_players) >= 12:
                self.server.send(cid, {"t": "full"})
                self.server._drop_client(cid)
                return
            name = (m.get("name") or "Игрок")[:16]
            used = {entry[2] for entry in self.lobby_players}
            requested = max(0, min(len(PLAYER_COLORS) - 1, int(m.get("color", 0))))
            color_index = requested if requested not in used else next(
                (index for index in range(len(PLAYER_COLORS)) if index not in used), 0)
            skin_index = max(0, min(len(PLAYER_SKINS) - 1, int(m.get("skin", 0))))
            hat_index = max(0, min(9, int(m.get("hat", 0))))
            self.lobby_players.append((cid, name, color_index, skin_index, hat_index))
            self.lobby_ready.discard(cid)
            self.server.send(cid, {"t": "welcome", "id": cid})
            self.server.broadcast({"t": "lobby", "players": self.lobby_players})
            self.server.broadcast({"t": "ready", "players": sorted(self.lobby_ready)})
        elif t == "customize" and self.state == "lobby":
            for index, entry in enumerate(self.lobby_players):
                if entry[0] != cid:
                    continue
                used = {other[2] for other in self.lobby_players if other[0] != cid}
                requested = max(0, min(len(PLAYER_COLORS) - 1, int(m.get("color", entry[2]))))
                color_index = requested if requested not in used else entry[2]
                skin_index = max(0, min(len(PLAYER_SKINS) - 1, int(m.get("skin", entry[3]))))
                hat_index = max(0, min(9, int(m.get("hat", entry[4]))))
                self.lobby_players[index] = (cid, entry[1], color_index, skin_index, hat_index)
                self.server.broadcast({"t": "lobby", "players": self.lobby_players})
                break
        elif t == "ready" and self.state == "lobby":
            if any(entry[0] == cid for entry in self.lobby_players):
                if bool(m.get("ready", False)):
                    self.lobby_ready.add(cid)
                else:
                    self.lobby_ready.discard(cid)
                self.server.broadcast({"t": "ready", "players": sorted(self.lobby_ready)})
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
            self.lobby_ready.discard(cid)
            if self.players:
                self.players.pop(cid, None)
            self.server.broadcast({"t": "lobby", "players": self.lobby_players})
            self.server.broadcast({"t": "ready", "players": sorted(self.lobby_ready)})
            self.check_tutorial_ready()

    def toggle_lobby_ready(self):
        if self.is_host or not self.client or self.state != "lobby":
            return
        ready = self.my_id not in self.lobby_ready
        self.client.send({"t": "ready", "ready": ready})

    def lobby_all_ready(self):
        return all(entry[0] in self.lobby_ready for entry in self.lobby_players)

    def handle_host_disconnect(self):
        log.warning("Соединение с хостом потеряно")
        if self.client:
            self.client.stop()
            self.client = None
        self.snap = None
        self.local_choices = []
        self.lobby_players = []
        self.lobby_ready = set()
        self.players = {}
        self.tutorial_active = False
        self.tutorial_ready = False
        self.input_mode = None
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
            parsed = []
            for item in m.get("players", []):
                pid, name = int(item[0]), str(item[1])
                color_index = int(item[2]) if len(item) > 2 else max(0, (pid - 1) % len(PLAYER_COLORS))
                skin_index = int(item[3]) if len(item) > 3 else 0
                hat_index = int(item[4]) if len(item) > 4 else 0
                parsed.append((pid, name,
                               max(0, min(len(PLAYER_COLORS) - 1, color_index)),
                               max(0, min(len(PLAYER_SKINS) - 1, skin_index)),
                               max(0, min(9, hat_index))))
            self.lobby_players = parsed
            mine = next((entry for entry in parsed if entry[0] == self.my_id), None)
            if mine:
                self.local_color_index, self.local_skin_index, self.local_hat_index = mine[2], mine[3], mine[4]
                self.persist()
        elif t == "ready":
            self.lobby_ready = {int(pid) for pid in m.get("players", [])}
        elif t == "full":
            if self.client:
                self.client.stop()
                self.client = None
            self.set_error("Лобби заполнено. Максимум игроков: 12.")
        elif t == "started":
            if self.client:
                self.client.stop()
                self.client = None
            self.is_host = False
            self.lobby_players = []
            self.lobby_ready = set()
            self.set_error("ИГРА УЖЕ ЗАПУЩЕНА\\nПодключиться можно будет после завершения текущей игры.")
        elif t == "start":
            self.snap = None
            self.camera_target_previous = None
            self.camera_target_current = None
            self.camera_lerp_elapsed = 0.0
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
            local_state = next((pl for pl in m.get("players", []) if pl.get("pid") == self.my_id), None)
            if local_state is not None:
                incoming = (float(local_state["x"]), float(local_state["y"]))
                self.camera_target_previous = self.camera_target_current or incoming
                self.camera_lerp_duration = max(1.0 / 60.0, min(0.10, self.camera_lerp_elapsed))
                self.camera_target_current = incoming
                self.camera_lerp_elapsed = 0.0
            for event in m.get("sfx", []):
                if len(event) >= 2 and (event[1] < 0 or event[1] == self.my_id):
                    self.audio.play(event[0])
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
            self.camera.x = max(-180, min(WORLD_W + 180 - W, self.camera.x))
            self.camera.y = max(-180, min(WORLD_H + 180 - H, self.camera.y))

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
            if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
                self.toggle_borderless_fullscreen()
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
                if e.key == pygame.K_F3 and not self.input_mode:
                    self.debug_overlay = not self.debug_overlay
                    continue
                if self.input_mode:
                    self._handle_input_event(e)
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
                        self.state = "settings"
                    elif e.key == pygame.K_4:
                        self.input_mode = "name"
                    elif e.key == pygame.K_ESCAPE:
                        self.quit()
                elif self.state == "settings":
                    if e.key == pygame.K_ESCAPE:
                        self.state = "menu"
                elif self.state == "lobby":
                    if e.key == pygame.K_ESCAPE:
                        self.leave_net()
                    elif e.key == pygame.K_RETURN and self.is_host:
                        self.host_start_game()
                    elif e.key == pygame.K_RETURN and not self.is_host and self.client:
                        self.toggle_lobby_ready()
                elif self.state == "play":
                    if e.key in (pygame.K_p, pygame.K_ESCAPE) and self.is_host:
                        self.set_paused(not self.paused)
                    elif e.key == pygame.K_e:
                        p = self.players.get(self.my_id)
                        if p:
                            p.want_pulse = True
                    elif e.key == pygame.K_F4 and self.is_host:
                        # DEBUG: добавить себе одно максимальное и текущее HP.
                        p = self.players.get(self.my_id)
                        if p and p.alive:
                            p.max_hp += 1
                            p.hp += 1
                            self.play_sound("heal", p.pid)
                elif self.state == "dead":
                    if e.key == pygame.K_RETURN and self.is_host:
                        self.host_start_game()
                    elif e.key == pygame.K_ESCAPE:
                        self.leave_net()
                elif self.state == "error":
                    if e.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                        self.tutorial_active = False
                        self.input_mode = None
                        self.state = "menu"
            elif e.type == pygame.MOUSEWHEEL:
                mx, my = self.logical_mouse()
                if self.state == "lobby" and pygame.Rect(130, 220, 470, 350).collidepoint(mx, my):
                    visible = max(1, (350 - 62) // 34)
                    self.lobby_scroll = max(0, min(max(0, len(self.lobby_players) - visible), self.lobby_scroll - e.y))
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if self.tutorial_active and self.state == "play" and e.button == 1:
                    self.confirm_tutorial()
                    continue
                mx, my = self.logical_mouse(e.pos)
                ui_click = bool(self.input_mode or self.tutorial_active or self.paused
                                or self.state in ("settings", "lobby", "dead", "error"))
                if self.state == "menu":
                    menu_cx, menu_y = W / 2, H / 2 - 140 + 160
                    ui_click = any(rect.collidepoint(mx, my) for rect in (
                        pygame.Rect(menu_cx - 100, H - 58, 200, 38),
                        pygame.Rect(menu_cx - 210, menu_y - 20, 420, 52),
                        pygame.Rect(menu_cx - 210, menu_y + 42, 420, 52),
                        pygame.Rect(menu_cx - 210, menu_y + 104, 420, 44),
                        pygame.Rect(menu_cx - 210, menu_y + 158, 420, 44),
                    ))
                if self.state == "play" and self.intermission and self.local_choices:
                    card_w, card_h, card_gap = 320, 238, 30
                    card_total = len(self.local_choices) * card_w + (len(self.local_choices) - 1) * card_gap
                    card_x0 = (W - card_total) / 2
                    card_y0 = H / 2 - card_h / 2 + 38
                    ui_click = any(pygame.Rect(card_x0 + i * (card_w + card_gap), card_y0,
                                               card_w, card_h).collidepoint(mx, my)
                                   for i in range(len(self.local_choices)))
                if e.button == 1 and ui_click:
                    self.audio.play("ui_click")
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
                    elif pygame.Rect(cx - 210, y + 104, 420, 44).collidepoint(mx, my):
                        self.input_mode = "name"
                    elif pygame.Rect(cx - 210, y + 158, 420, 44).collidepoint(mx, my):
                        self.state = "settings"
                elif self.state == "settings" and e.button == 1:
                    cx = W / 2
                    if pygame.Rect(cx - 205, 244, 70, 48).collidepoint(mx, my):
                        self.music_volume = max(0.0, self.music_volume - 0.05)
                        self.audio.set_volumes(music=self.music_volume)
                        self.persist()
                    elif pygame.Rect(cx + 135, 244, 70, 48).collidepoint(mx, my):
                        self.music_volume = min(1.0, self.music_volume + 0.05)
                        self.audio.set_volumes(music=self.music_volume)
                        self.persist()
                    elif pygame.Rect(cx - 205, 344, 70, 48).collidepoint(mx, my):
                        self.sfx_volume = max(0.0, self.sfx_volume - 0.05)
                        self.audio.set_volumes(sfx=self.sfx_volume)
                        self.persist()
                    elif pygame.Rect(cx + 135, 344, 70, 48).collidepoint(mx, my):
                        self.sfx_volume = min(1.0, self.sfx_volume + 0.05)
                        self.audio.set_volumes(sfx=self.sfx_volume)
                        self.persist()
                    elif pygame.Rect(cx - 210, 444, 420, 48).collidepoint(mx, my):
                        self.screen_shake_enabled = not self.screen_shake_enabled
                        self.persist()
                    elif pygame.Rect(cx - 210, 514, 420, 48).collidepoint(mx, my):
                        options = (60, 120, 144, 0)
                        self.target_fps = options[(options.index(self.target_fps) + 1) % len(options)]
                        self.persist()
                    elif pygame.Rect(cx - 210, 584, 420, 48).collidepoint(mx, my):
                        self.toggle_borderless_fullscreen()
                    elif pygame.Rect(cx - 150, H - 58, 300, 42).collidepoint(mx, my):
                        self.state = "menu"
                elif self.state == "lobby" and e.button == 1:
                    if pygame.Rect(W / 2 - 190, H - 136, 380, 52).collidepoint(mx, my):
                        if self.is_host:
                            self.host_start_game()
                        else:
                            self.toggle_lobby_ready()
                    elif pygame.Rect(W / 2 - 150, H - 66, 300, 42).collidepoint(mx, my):
                        self.leave_net()
                    else:
                        own = next((entry for entry in self.lobby_players if entry[0] == self.my_id), None)
                        current_color = own[2] if own else self.local_color_index
                        current_skin = own[3] if own else self.local_skin_index
                        current_hat = own[4] if own else self.local_hat_index
                        occupied = {entry[2] for entry in self.lobby_players if entry[0] != self.my_id}
                        changed = False
                        edit_x, edit_y = 620, 220
                        for idx in range(len(PLAYER_COLORS)):
                            row, column = divmod(idx, 5)
                            cell = pygame.Rect(edit_x + 22 + column * 48, edit_y + 82 + row * 27, 32, 20)
                            if cell.collidepoint(mx, my) and idx not in occupied:
                                current_color = idx
                                changed = True
                                break
                        if not changed:
                            for idx in range(len(PLAYER_SKINS)):
                                row, column = divmod(idx, 5)
                                cell = pygame.Rect(edit_x + 22 + column * 96, edit_y + 188 + row * 34, 76, 28)
                                if cell.collidepoint(mx, my):
                                    current_skin = idx
                                    changed = True
                                    break
                        if not changed:
                            for idx in range(10):
                                row, column = divmod(idx, 5)
                                cell = pygame.Rect(edit_x + 22 + column * 96, edit_y + 284 + row * 29, 76, 25)
                                if cell.collidepoint(mx, my):
                                    current_hat = idx
                                    changed = True
                                    break
                        if changed:
                            self.local_color_index = current_color
                            self.local_skin_index = current_skin
                            self.local_hat_index = current_hat
                            self.persist()
                            if self.is_host:
                                for index, entry in enumerate(self.lobby_players):
                                    if entry[0] == self.my_id:
                                        self.lobby_players[index] = (self.my_id, entry[1], current_color, current_skin, current_hat)
                                        self.server.broadcast({"t": "lobby", "players": self.lobby_players})
                                        break
                            elif self.client:
                                self.client.send({"t": "customize", "color": current_color,
                                                  "skin": current_skin, "hat": current_hat})
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
                        self.tutorial_active = False
                        self.input_mode = None
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
            value = "".join(ch for ch in value.strip() if ch.isalnum() or ch in ".:-_%")
            self.ip_input = value[:253]
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
                if ch.isalnum() or ch in ".:-_%":
                    self.ip_input = (self.ip_input + ch)[:253]
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
        if not any(player.alive for player in self.players.values()):
            self.finish_session()
            return
        if self.intermission:
            self.shake *= math.exp(-8 * dt)
            for player in self.players.values():
                if not player.alive:
                    player.hurt_t = max(0.0, player.hurt_t - dt)
            if all((not p.alive) or p.upgrade_ready for p in self.players.values()):
                self.start_next_wave()
            return
        self.gather_local_input()
        for p in self.players.values():
            if p.alive:
                self.update_player(p, dt)
            else:
                p.hurt_t = max(0.0, p.hurt_t - dt)
        self.update_waves(dt)
        for e in self.enemies:
            self.update_enemy(e, dt)
        self.separate()
        self.update_pickups(dt)
        self.update_bullets(dt)
        self.collide()
        if len(self.rings) > 120:
            self.rings = self.rings[-120:]
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
        self.banner_t = max(0.0, self.banner_t - dt)

        if not any(p.alive for p in self.players.values()):
            self.finish_session()

    def update_player(self, p, dt):
        p.dash_t = max(0.0, p.dash_t - dt)
        p.dash_cd = max(0.0, p.dash_cd - dt)
        p.inv = max(0.0, p.inv - dt)
        p.hurt_t = max(0.0, p.hurt_t - dt)
        p.cool = max(0.0, p.cool - dt)
        p.shield_t = max(0.0, p.shield_t - dt)
        if p.regen > 0 and p.hp < p.max_hp:
            p.regen_timer += dt
            if p.regen_timer >= 1.0 / p.regen:
                p.regen_timer = 0.0
                p.hp = min(p.max_hp, p.hp + 1)
                self.play_sound("heal", p.pid)
        p.rapid = max(0.0, p.rapid - dt)
        p.spread = max(0.0, p.spread - dt)
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
                self.play_sound("dash", p.pid)
                self.rings.append(Ring(p.p, 10, 90, 400, CYAN, 3))

        if p.want_pulse:
            p.want_pulse = False
            if p.charge >= 100:
                self.do_pulse(p)

        if p.dash_t <= 0:
            p.v += p.inp * p.move_spd * dt
        p.v *= math.exp(-6.5 * dt)
        p.p += p.v * dt
        # За пределами арены можно двигаться ещё немного, но там действует опасная зона.
        p.p.x = max(-180, min(WORLD_W + 180, p.p.x))
        p.p.y = max(-180, min(WORLD_H + 180, p.p.y))
        outside = p.p.x < 0 or p.p.x > WORLD_W or p.p.y < 0 or p.p.y > WORLD_H
        if outside:
            p.boundary_t += dt
            while p.boundary_t >= 1.0 and p.alive:
                p.boundary_t -= 1.0
                p.hp -= 1
                p.hurt_t = 0.35
                self.play_sound("hurt", p.pid)
                self.pops.append([V(p.p), "−1 ЗОНА", 0.7, RED, p.pid])
                if p.pid == self.my_id:
                    self.shake = max(self.shake, 10)
                    self.rings.append(Ring(p.p, 8, 90, 360, RED, 3))
                if p.hp <= 0:
                    p.alive = False
                    self.play_sound("player_death", p.pid)
                    self.burst(p.p, RED, 70, 620, (0.4, 1.0), 3)
        else:
            p.boundary_t = 0.0

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
                size_damage = 1.0 + 0.08 * p.upgrades.get("bullet_size", 0)
                self.bullets.append(Bullet(p.p + d * 22, d * (1100 * p.bullet_speed), p.pid,
                                           shot_damage * size_damage, p.pierce, p.bullet_size))
            for i in range(p.multishot):
                spread = 0.12 * (i + 1)
                for sign in (-1, 1):
                    aa = p.ang + spread * sign
                    d = V(math.cos(aa), math.sin(aa))
                    shot_damage = p.dmg * (2.0 if random.random() < p.crit else 1.0)
                    size_damage = 1.0 + 0.08 * p.upgrades.get("bullet_size", 0)
                    self.bullets.append(Bullet(p.p + d * 22, d * (1100 * p.bullet_speed),
                                               p.pid, shot_damage * 0.55 * size_damage, p.pierce, p.bullet_size))
            fwd = V(math.cos(p.ang), math.sin(p.ang))
            p.v -= fwd * 25
            self.burst(p.p + fwd * 24, CYAN, 3, 260, (0.08, 0.2), 2)
            self.play_sound("shoot", p.pid)

    def do_pulse(self, p):
        p.charge = 0
        if p.pid == self.my_id:
            self.shake = max(self.shake, 34)
        p.inv = max(p.inv, 0.35)
        p.shield_t = 3.5
        p.shield_hits = min(3, 1 + p.upgrades.get("pulse_power", 0))
        self.play_sound("pulse", p.pid)
        self.rings.append(Ring(p.p, 18, 170, 520, CYAN, 5))
        self.rings.append(Ring(p.p, 12, 125, 760, WHITE, 2))
        self.burst(p.p, CYAN, 42, 420, (0.25, 0.7), 3)

    def update_waves(self, dt):
        if self.intermission or not any(player.alive for player in self.players.values()):
            return
        alive = any(not e.dead for e in self.enemies)

        # Номер первой волны уже равен 1; до её старта идёт короткая подготовка.
        if not self.wave_started:
            self.wave_delay = max(0.0, self.wave_delay - dt)
            if self.wave_delay <= 0:
                self.next_wave()
            return

        # Улучшение выдаётся только после полного завершения волны:
        # очередь спавна пуста и на арене не осталось живых врагов.
        if not self.queue and not alive:
            self.begin_intermission()
            return

        if self.queue:
            self.spawn_t = max(0.0, self.spawn_t - dt)
            if self.spawn_t <= 0:
                next_kind = self.queue[-1]
                # При заполненной арене ждём свободное место, не теряя мобов из очереди.
                if len(self.enemies) < 90 or next_kind.startswith("boss"):
                    self.spawn(self.queue.pop())
                    player_count = max(1, sum(1 for player in self.players.values() if player.alive))
                    self.spawn_t = max(0.16, (0.72 - 0.012 * self.wave) /
                                        (1.0 + 0.06 * (player_count - 1)))
                else:
                    self.spawn_t = 0.20

    def begin_intermission(self):
        if self.intermission or not self.wave_started:
            return
        # За одну завершённую волну каждому живому игроку полагается ровно один выбор.
        self.intermission = True
        self.queue.clear()
        self.play_sound("wave_clear")
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
        if not any(player.alive for player in self.players.values()):
            self.finish_session()
            return
        self.intermission = False
        self.local_choices = []
        self.local_upgrade_waiting = False
        for p in self.players.values():
            p.upgrade_choices = []
            p.upgrade_ready = False
        self.next_wave()

    def finish_session(self):
        if self.state == "dead":
            return
        self.state = "dead"
        self.intermission = False
        self.local_upgrade_waiting = False
        self.local_choices = []
        for player in self.players.values():
            player.upgrade_choices = []
        if self.server:
            self.server.broadcast({"t": "dead"})
        pygame.mouse.set_visible(True)

    def next_wave(self):
        # Номер увеличивается при каждом реальном запуске волны.
        # Новая игра начинается с wave=0, поэтому первая волна станет 1.
        self.wave += 1
        self.wave_started = True
        self.play_sound("wave_start")
        self.wave_delay = 0.0
        self.spawn_t = 1.25
        self.banner_t = 2.2
        player_count = max(1, sum(1 for p in self.players.values() if p.alive))
        # Рост количества врагов заметно плавнее: к 16-й волне толпа
        # становится плотнее, но не превращается в стену из противников.
        n = min(64, int((8 + self.wave * 2.2) * (1.0 + 0.12 * (player_count - 1))))
        q = []

        # Новые архетипы вводятся по одному, с интервалом в одну-две волны.
        unlocks = {
            2: "shooter",
            3: "swarm",
            4: "tank",
            5: "dasher",
            6: "splitter",
            7: "mine",
            8: "orbiter",
            10: "bruiser",
        }
        unlocked = [kind for wave_num, kind in unlocks.items() if self.wave >= wave_num]
        weights = {
            "chaser": 48, "shooter": 15, "swarm": 14, "tank": 7,
            "dasher": 5, "splitter": 5, "mine": 3, "orbiter": 3,
            "bruiser": 1,
        }
        pool = ["chaser"] + unlocked
        pool_weights = [weights[kind] for kind in pool]
        for _ in range(n):
            q.append(random.choices(pool, weights=pool_weights, k=1)[0])

        # Волну знакомства с новым типом гарантированно сопровождает
        # только один такой враг — остальные остаются привычными.
        new_kind = unlocks.get(self.wave)
        if new_kind:
            q[0] = new_kind
        if self.wave == 2:
            q.append("boss_minor")
        elif self.wave % 5 == 0:
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
        player_scale = 1.0 + 0.10 * max(0, len(self.players) - 1)
        enemy.hp = max(1, math.ceil(enemy.hp * player_scale))
        enemy.max_hp = enemy.hp
        enemy.spd *= 1.0 + 0.035 * max(0, len(self.players) - 1)
        self.enemies.append(enemy)
        if kind.startswith("boss"):
            self.banner_t = max(self.banner_t, 2.8)
            self.shake = max(self.shake, 12)
            self.play_sound("boss_spawn")

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
                e.cool = 2.8
                # Рывок должен быть опасным, но не пересекать арену за миг.
                e.v = d * (e.spd * 2.4)
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
                self.play_sound("enemy_shot")
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
                self.play_sound("enemy_shot")
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
                self.play_sound("enemy_shot")
        elif k == "bruiser":
            e.cool -= dt
            if e.windup > 0:
                e.windup -= dt
                e.v *= math.exp(-8.0 * dt)
                if e.windup <= 0:
                    e.charge_t = 0.38
                    e.v = e.charge_dir * (e.spd * 3.0)
                    self.rings.append(Ring(e.p, 12, 115, 620, ORANGE, 4))
                    self.play_sound("dash")
            elif e.charge_t > 0:
                e.charge_t = max(0.0, e.charge_t - dt)
                e.v = e.charge_dir * (e.spd * 5.2)
            else:
                e.v = e.v.lerp(d * e.spd, min(1.0, 1.8 * dt))
                if e.cool <= 0:
                    e.cool = 3.4
                    e.windup = 0.62
                    e.charge_dir = V(d)
        elif k in ("boss", "boss_storm", "boss_hunter", "boss_void", "boss_siege", "boss_minor"):
            e.v = e.v.lerp(d * e.spd, min(1.0, 1.25 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = max(1.25, 2.35 - self.wave * 0.018)
                base = math.atan2(d.y, d.x)
                if k == "boss_minor":
                    for offset in (-0.22, 0.0, 0.22):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 300, 5.5])
                elif k == "boss":
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
                self.play_sound(boss_sounds.get(k, "boom"))
        else:  # tank
            e.v = e.v.lerp(d * e.spd, min(1.0, 2 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = 3.4
                count = 10 if self.wave < 8 else 12
                for i in range(count):
                    a = i * math.tau / count + e.ang
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * min(340, 230 + self.wave * 5), 6.0])
                self.play_sound("boom")
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
        self.pops.append([V(pk[0]), {"rapid": "БЫСТРЫЙ ОГОНЬ", "spread": "ТРОЙНОЙ ВЫСТРЕЛ", "heal": "+1 HP"}[kind], 1.2, col, p.pid])
        self.play_sound("heal" if kind == "heal" else "pickup", p.pid)

    def damage(self, e, n, src):
        e.hp -= n
        e.flash = 0.08
        if e.hp <= 0:
            self.kill(e, src)
        else:
            self.play_sound("boss_hit" if e.kind.startswith("boss") else "hit")

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
            pts = int(d["score"])
            src.score += pts
            src.kills += 1
            if src.lifesteal:
                src.lifesteal_progress += src.lifesteal
                if src.lifesteal_progress >= 18:
                    src.lifesteal_progress -= 18
                    src.hp = min(src.max_hp, src.hp + 1)
                    self.play_sound("heal", src.pid)
                    self.pops.append([V(src.p), "+1 HP", 0.9, GREEN, src.pid])
            src.charge = min(100.0, src.charge + (26 if e.kind.startswith("boss") else 14 if e.kind == "tank" else 7) * src.pulse_gain)
            self.pops.append([V(e.p), "+%d" % pts, 0.8, e.col, src.pid])
            # Одно улучшение выдаётся в конце каждой волны.
        self.play_sound("boom")
        if e.kind in ("tank", "splitter"):
            for _ in range(4 if e.kind == "tank" else 3):
                c = Enemy("swarm", e.p + V(random.uniform(-30, 30), random.uniform(-30, 30)), self.wave)
                c.age = 0.45
                self.enemies.append(c)
        if e.kind.startswith("boss"):
            self.play_sound("boss_death")
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
            self.play_sound("shield_block", p.pid)
            self.pops.append([V(p.p), "ЩИТ", 0.75, CYAN, p.pid])
            if p.pid == self.my_id:
                self.rings.append(Ring(p.p, 20, 125, 620, CYAN, 4))
                self.burst(p.p, CYAN, 18, 300, (0.15, 0.35), 2)
            return
        p.armor_hits += 1
        if p.armor > 0 and p.armor_hits % max(3, 6 - p.armor) == 0:
            self.play_sound("armor_block", p.pid)
            self.pops.append([V(p.p), "БРОНЯ", 0.8, CYAN, p.pid])
            if p.pid == self.my_id:
                self.rings.append(Ring(p.p, 8, 100, 520, CYAN, 3))
            return
        p.hp -= 1
        p.inv = 0.58
        if p.pid == self.my_id:
            self.shake = max(self.shake, 18)
        p.hurt_t = 0.52
        self.play_sound("hurt", p.pid)
        if p.pid == self.my_id:
            self.burst(p.p, CYAN, 40, 520, (0.3, 0.9), 3)
            self.rings.append(Ring(p.p, 10, 280, 900, RED, 5))
        if p.hp <= 0:
            p.alive = False
            self.play_sound("player_death", p.pid)
            self.burst(p.p, p.color, 120, 800, (0.6, 1.8), 4)
            self.burst(p.p, WHITE, 40, 500, (0.3, 0.9), 3)
            for r, s in ((500, 500), (800, 800)):
                self.rings.append(Ring(p.p, 10, r, s, p.color, 6))
            if p.pid == self.my_id:
                self.shake = 40

    def collide(self):
        # Пространственная сетка: пуля проверяет только ближайшие клетки,
        # а не каждого врага на арене.
        cell_size = 112
        enemy_grid = {}
        for enemy in self.enemies:
            if not enemy.dead and enemy.age >= 0.7:
                key = (int(enemy.p.x // cell_size), int(enemy.p.y // cell_size))
                enemy_grid.setdefault(key, []).append(enemy)
        keep_b = []
        for bullet in self.bullets:
            hit = False
            gx, gy = int(bullet.p.x // cell_size), int(bullet.p.y // cell_size)
            candidates = []
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    candidates.extend(enemy_grid.get((gx + ox, gy + oy), ()))
            for enemy in candidates:
                if enemy.dead or id(enemy) in bullet.hit_ids:
                    continue
                rr = enemy.r + 5 * bullet.size
                if (bullet.p - enemy.p).length_squared() < rr * rr:
                    source = self.players.get(bullet.owner)
                    self.damage(enemy, bullet.dmg, source)
                    self.burst(bullet.p, enemy.col, 5, 260, (0.1, 0.3), 2)
                    bullet.hit_ids.add(id(enemy))
                    if bullet.pierce > 0:
                        bullet.pierce -= 1
                    else:
                        hit = True
                    break
            if not hit:
                keep_b.append(bullet)
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
        particle_budget = max(0, 520 - len(self.parts))
        n = min(n, particle_budget)
        for _ in range(n):
            a = random.uniform(0, math.tau)
            sp = random.uniform(0.15, 1.0) * speed
            self.parts.append(Particle(pos, V(math.cos(a), math.sin(a)) * sp,
                                       random.uniform(*life), col, size * random.uniform(0.6, 1.3)))

    # ================= снапшот =================
    def build_snapshot(self):
        snap = {
            "t": "snap",
            "sfx": self.sound_events[:],
            "players": [],
            "bullets": [],
            "ebullets": [],
            "enemies": [],
            "pickups": [],
            "pops": [],
            "wave": self.wave,
            "wave_started": self.wave_started,
            "intermission": self.intermission,
            "banner": round(self.banner_t, 2),
            "shake": round(self.shake, 1),
            "enemies_left": len(self.queue) + sum(1 for e in self.enemies if not e.dead),
            "boss_in": 5 if not self.wave_started else (5 - ((self.wave + (1 if self.intermission else 0)) % 5)) % 5,
        }
        for p in self.players.values():
            snap["players"].append({
                "pid": p.pid, "name": p.name,
                "color": list(p.color), "skin": p.skin, "hat": p.hat,
                "x": round(p.p.x, 1), "y": round(p.p.y, 1),
                "ang": round(p.ang, 2), "hp": p.hp, "max_hp": p.max_hp,
                "dash_cd": round(p.dash_cd, 2), "charge": round(p.charge, 1),
                "rapid": round(p.rapid, 1), "spread": round(p.spread, 1),
                "score": p.score, "kills": p.kills,
                "alive": p.alive, "inv": round(p.inv, 2), "dash_t": round(p.dash_t, 2),
                "shield_t": round(p.shield_t, 1), "shield_hits": p.shield_hits,
                "hurt_t": round(p.hurt_t, 2),
                "upgrade_choices": list(p.upgrade_choices),
                "upgrade_ready": p.upgrade_ready,
                "pending_upgrades": p.pending_upgrades,
                "buffs": {"rapid": round(p.rapid,1), "spread": round(p.spread,1),
                          "shield": round(p.shield_t,1)},
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
        self.sound_events.clear()
        return snap

    # ================= отрисовка мира =================
    def run(self):
        log.info("Игра запущена | разрешение=%dx%d | порт=%d", W, H, PORT)
        while True:
            real_dt = min(self.clock.tick(self.target_fps) / 1000.0, 1 / 20)
            self.t += real_dt
            self.camera_lerp_elapsed += real_dt
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
                    if not self.tutorial_active:
                        self.host_update(real_dt)
                    self.snapshot_timer += real_dt
                    if self.snap is None or self.snapshot_timer >= 1.0 / 30.0 or self.state == "dead":
                        self.snap = self.build_snapshot()
                        self.server.broadcast(self.snap)
                        self.snapshot_timer %= 1.0 / 30.0
                else:
                    self.input_send_timer += real_dt
                    if self.input_send_timer >= 1.0 / 60.0:
                        self.send_input()
                        self.input_send_timer %= 1.0 / 60.0

            scene = "dead" if self.state == "dead" else "play" if self.state == "play" else "menu"
            if scene != self.audio_scene:
                self.audio_scene = scene
                self.audio.set_scene(scene)
            if self.state != self.last_ui_state:
                self.last_ui_state = self.state
                if self.state != "dead":
                    self.audio.play("scene")

            self.render()
            pygame.display.flip()