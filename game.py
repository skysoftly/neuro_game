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
from draw_utils import shape, dim, make_overlay, read_clipboard
from camera import Camera
from entities import Player, Enemy, Particle, Ring, Bullet
from upgrades import UPGRADES_BY_ID, apply_upgrade, roll_upgrades
from network import HostServer, ClientConn

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
    return ips or ["127.0.0.1"]


# ---------- звук ----------
class Audio:
    def __init__(self):
        self.s = {}
        self.ok = False
        if not pygame.mixer.get_init():
            return
        try:
            self.s = {
                "shoot": self.make(900, 300, 0.07, 0.10, "sq", 0.1),
                "hit": self.make(300, 120, 0.05, 0.12, "sq", 0.5),
                "boom": self.make(180, 30, 0.35, 0.35, "sq", 0.8),
                "dash": self.make(300, 1200, 0.15, 0.18, "sin", 0.2),
                "pickup": self.make(600, 1400, 0.18, 0.20, "sin", 0.0),
                "pulse": self.make(900, 60, 0.60, 0.40, "sin", 0.4),
                "hurt": self.make(400, 50, 0.40, 0.40, "sq", 0.6),
                "levelup": self.make(500, 1600, 0.35, 0.25, "sin", 0.0),
            }
            self.ok = True
            self.music = self.make_music()
            self.music_channel = pygame.mixer.Channel(7)
            self.music_channel.set_volume(0.16)
            self.music_channel.play(self.music, loops=-1)
        except Exception:
            self.ok = False
            log.exception("Не удалось инициализировать аудио")

    @staticmethod
    def make_music():
        """Небольшой оригинальный чиптюн-луп без внешних аудиофайлов."""
        rate = 44100
        notes = (220, 277, 330, 440, 330, 277, 247, 330,
                 196, 247, 294, 392, 294, 247, 220, 277)
        beat = 0.16
        buf = array.array("h")
        phase = 0.0
        for note in notes:
            count = int(rate * beat)
            for i in range(count):
                phase += note / rate
                square = 1.0 if phase % 1.0 < 0.5 else -1.0
                envelope = min(1.0, i / 180) * min(1.0, (count - i) / 300)
                buf.append(int(square * envelope * 2300))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    @staticmethod
    def make(f0, f1, dur, vol, wave, noise):
        rate = 44100
        n = int(rate * dur)
        buf = array.array("h")
        ph = 0.0
        for i in range(n):
            t = i / n
            ph += (f0 + (f1 - f0) * t) / rate
            if wave == "sq":
                s = 1.0 if (ph % 1.0) < 0.5 else -1.0
            else:
                s = math.sin(ph * math.tau)
            s = s * (1 - noise) + random.uniform(-1, 1) * noise
            buf.append(int(s * (1 - t) ** 2 * vol * 32767))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def play(self, name):
        if self.ok and name in self.s:
            self.s[name].play()


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
        self.flash = 0.0
        self.banner_t = 0.0
        self.wave = 0
        self.hitstop = 0.0
        self.show_help = True
        self.help_t = 10.0
        self.debug_overlay = False
        self.debug_timer = 0.0

        cfg = load_config()
        self.last_ip = cfg.get("last_ip", "")
        self.name_input = cfg.get("name", "Игрок")
        self.ip_input = self.last_ip
        self.lan_ips = get_lan_ips()

        self.is_host = False
        self.server = None
        self.client = None
        self.my_id = 0
        self.lobby_players = []
        self.input_mode = None
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

        pygame.mouse.set_visible(True)

    def persist(self):
        save_config({"last_ip": self.last_ip, "name": self.name_input})

    # ================= сеть =================
    def start_host(self):
        log.info("Запуск лобби хоста")
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
            self.connect_error = "Пустой IP"
            return
        try:
            self.client = ClientConn(ip)
        except Exception as e:
            log.exception("Не удалось подключиться к %s:%d", ip, PORT)
            self.connect_error = "Ошибка: %s" % e
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
        self.snap = None
        self.paused = False
        self.hitstop = 0.0
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
        elif t == "upgrade" and self.state == "play":
            p = self.players.get(cid)
            up_id = m.get("id")
            if p and up_id in p.upgrade_choices:
                apply_upgrade(p, up_id)
                p.upgrade_choices = []
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
            self.state = "play"
            self.paused = False
            self.help_t = 10.0
            pygame.mouse.set_visible(False)
        elif t == "snap":
            self.snap = m
            self.banner_t = m.get("banner", 0)
            # выбрать апгрейды локального игрока
            for pl in m.get("players", []):
                if pl["pid"] == self.my_id:
                    self.local_choices = pl.get("upgrade_choices", [])
                    break
            else:
                self.local_choices = []
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
        if upgrade_id not in self.local_choices:
            return
        if self.is_host:
            p = self.players.get(self.my_id)
            if p and upgrade_id in p.upgrade_choices:
                apply_upgrade(p, upgrade_id)
                p.upgrade_choices = []
                self.local_choices = []
                self.audio.play("levelup")
        elif self.client:
            self.client.send({"t": "upgrade", "id": upgrade_id})
            self.local_choices = []

    # ================= ввод =================
    def mouse_world(self):
        mx, my = pygame.mouse.get_pos()
        sw, sh = self.screen.get_size()
        if sw and sh:
            mx = mx * W / sw
            my = my * H / sh
        return self.camera.to_world(mx, my)

    def gather_local_input(self):
        p = self.players.get(self.my_id)
        if p is None:
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

                # выбор апгрейда
                if self.state == "play" and self.local_choices:
                    if e.key in (pygame.K_1, pygame.K_KP1) and len(self.local_choices) >= 1:
                        self.pick_upgrade(self.local_choices[0]); continue
                    if e.key in (pygame.K_2, pygame.K_KP2) and len(self.local_choices) >= 2:
                        self.pick_upgrade(self.local_choices[1]); continue
                    if e.key in (pygame.K_3, pygame.K_KP3) and len(self.local_choices) >= 3:
                        self.pick_upgrade(self.local_choices[2]); continue

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
                if e.button == 1 and self.state == "play" and self.local_choices:
                    sw, sh = self.screen.get_size()
                    mx = e.pos[0] * W / max(1, sw)
                    my = e.pos[1] * H / max(1, sh)
                    card_w, card_h, gap = 320, 220, 30
                    total = len(self.local_choices) * card_w + (len(self.local_choices) - 1) * gap
                    x0 = (W - total) / 2
                    card_y = H / 2 - card_h / 2 + 40
                    for i, upgrade_id in enumerate(self.local_choices):
                        card = pygame.Rect(x0 + i * (card_w + gap), card_y, card_w, card_h)
                        if card.collidepoint(mx, my):
                            self.pick_upgrade(upgrade_id)
                            break
                elif e.button == 3 and self.state == "play":
                    p = self.players.get(self.my_id)
                    if p:
                        p.want_pulse = True

    def _handle_input_event(self, e):
        if e.key == pygame.K_RETURN:
            mode = self.input_mode
            self.input_mode = None
            self.persist()
            if mode == "ip" and self.ip_input.strip():
                self.join_server(self.ip_input)
            return
        if e.key == pygame.K_ESCAPE:
            self.input_mode = None
            return
        if e.key == pygame.K_BACKSPACE:
            if self.input_mode == "ip":
                self.ip_input = self.ip_input[:-1]
            else:
                self.name_input = self.name_input[:-1]
            return
        if e.key == pygame.K_v and (e.mod & pygame.KMOD_CTRL):
            s = read_clipboard()
            if s:
                if self.input_mode == "ip":
                    s = "".join(ch for ch in s if ch.isdigit() or ch == ".")
                    self.ip_input = s
                else:
                    self.name_input = s[:16]
            return
        ch = e.unicode
        if ch and ch.isprintable():
            if self.input_mode == "ip":
                self.ip_input += ch
            else:
                self.name_input += ch

    def quit(self):
        self.leave_net()
        pygame.quit()
        sys.exit()

    # ================= симуляция (хост) =================
    def host_update(self, dt):
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
            self.server.broadcast({"t": "dead"})
            pygame.mouse.set_visible(True)

    def update_player(self, p, dt):
        p.dash_t = max(0.0, p.dash_t - dt)
        p.dash_cd = max(0.0, p.dash_cd - dt)
        p.inv = max(0.0, p.inv - dt)
        p.cool = max(0.0, p.cool - dt)
        p.rapid = max(0.0, p.rapid - dt)
        p.spread = max(0.0, p.spread - dt)
        p.combo_t -= dt
        if p.combo_t <= 0:
            p.chain = 0

        if p.want_dash:
            p.want_dash = False
            if p.dash_cd <= 0:
                d = p.inp if p.inp.length_squared() > 0 else V(math.cos(p.ang), math.sin(p.ang))
                p.v = d * 1150
                p.dash_t = 0.18
                p.inv = max(p.inv, 0.28)
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
                self.bullets.append(Bullet(p.p + d * 22, d * 1100, p.pid, p.dmg, p.pierce))
            fwd = V(math.cos(p.ang), math.sin(p.ang))
            p.v -= fwd * 25
            self.burst(p.p + fwd * 24, CYAN, 3, 260, (0.08, 0.2), 2)
            self.audio.play("shoot")

    def do_pulse(self, p):
        p.charge = 0
        self.shake = max(self.shake, 28)
        self.flash = 0.6
        self.audio.play("pulse")
        for i, (r, s, w) in enumerate(((420, 900, 6), (520, 700, 3), (300, 1100, 2))):
            self.rings.append(Ring(p.p, 5, r + 120, s, MAGENTA if i != 2 else WHITE, w))
        self.burst(p.p, MAGENTA, 60, 700, (0.4, 1.0), 3)
        self.ebullets = []
        for e in list(self.enemies):
            if not e.dead and (e.p - p.p).length_squared() < 440 ** 2:
                self.damage(e, 6 * p.dmg, p)

    def update_waves(self, dt):
        alive = any(not e.dead for e in self.enemies)
        if not self.queue and not alive:
            self.wave_delay -= dt
            if self.wave_delay <= 0:
                self.next_wave()
        elif self.queue:
            self.spawn_t -= dt
            if self.spawn_t <= 0:
                self.spawn_t = max(0.18, 0.7 - 0.035 * self.wave)
                self.spawn(self.queue.pop())

    def next_wave(self):
        self.wave += 1
        self.wave_delay = 2.0
        self.banner_t = 2.2
        n = 6 + int(self.wave * 2.2)
        q = []
        for _ in range(n):
            r = random.random()
            if self.wave >= 3 and r < 0.12:
                q.append("tank")
            elif self.wave >= 2 and r < 0.35:
                q.append("shooter")
            elif self.wave >= 2 and r < 0.5:
                q.append("swarm")
            else:
                q.append("chaser")
        self.queue = q
        if self.wave % 4 == 0:
            self.pickups.append([V(WORLD_W / 2, WORLD_H / 2), "heal", 12.0])

    def spawn(self, kind):
        alive_players = [p for p in self.players.values() if p.alive]
        if not alive_players:
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
        e.ang += dt * (2.5 if e.kind != "tank" else 1.0)
        if e.age < 0.7:
            return
        target = min(alive_players, key=lambda pl: (pl.p - e.p).length_squared())
        to = target.p - e.p
        dist = to.length() or 1.0
        d = to / dist
        k = e.kind
        if k in ("chaser", "swarm"):
            e.v = e.v.lerp(d * e.spd, min(1.0, 3 * dt))
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
                e.cool = max(0.9, 2.0 - 0.06 * self.wave)
                n = 1 if self.wave < 5 else 3
                base = math.atan2(d.y, d.x)
                for i in range(n):
                    a = base + (i - (n - 1) / 2) * 0.25
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 300, 6.0])
                self.audio.play("shoot")
        else:  # tank
            e.v = e.v.lerp(d * e.spd, min(1.0, 2 * dt))
            e.cool -= dt
            if e.cool <= 0:
                e.cool = 3.4
                for i in range(10):
                    a = i * math.tau / 10 + e.ang
                    self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 230, 6.0])
                self.audio.play("boom")
        e.p += e.v * dt
        e.p.x = max(15, min(WORLD_W - 15, e.p.x))
        e.p.y = max(15, min(WORLD_H - 15, e.p.y))

    def separate(self):
        es = [e for e in self.enemies if e.age >= 0.7 and not e.dead]
        for i in range(len(es)):
            a = es[i]
            for j in range(i + 1, len(es)):
                b = es[j]
                d = a.p - b.p
                rr = a.r + b.r
                l2 = d.length_squared()
                if 0 < l2 < rr * rr:
                    l = math.sqrt(l2)
                    push = d / l * (rr - l) * 0.5
                    a.p += push
                    b.p -= push

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
                if src.lifesteal_progress >= 8:
                    src.lifesteal_progress -= 8
                    src.hp = min(src.max_hp, src.hp + 1)
                    self.pops.append([V(src.p), "+1 HP", 0.9, GREEN])
            src.charge = min(100.0, src.charge + (12 if e.kind == "tank" else 4) * src.pulse_gain)
            self.pops.append([V(e.p), "+%d" % pts, 0.8, e.col])
            # XP
            src.xp += d["xp"]
            need = src.xp_to_next()
            if src.xp >= need:
                src.xp -= need
                src.level += 1
                src.upgrade_choices = roll_upgrades(self.rng, 3)
                if src.pid == self.my_id:
                    self.local_choices = list(src.upgrade_choices)
                    self.audio.play("levelup")
        self.audio.play("boom")
        if e.kind == "tank":
            for _ in range(4):
                c = Enemy("swarm", e.p + V(random.uniform(-30, 30), random.uniform(-30, 30)), self.wave)
                c.age = 0.45
                self.enemies.append(c)
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
        p.hp -= 1
        p.inv = 1.6
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
                            self.damage(e, 4 * p.dmg, p)
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
        if len(self.parts) > 1800:
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
            "banner": round(self.banner_t, 2),
            "shake": round(self.shake, 1),
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
        fill = dim(base_col, 0.12)
        kind = e["k"]
        if kind == "chaser":
            pts = shape(DIAMOND, e["ang"], (sx, sy), r)
        elif kind == "swarm":
            pts = shape(TRI, e["ang"], (sx, sy), r)
        elif kind == "shooter":
            pts = shape(HEX, e["ang"] * 0.4, (sx, sy), r)
        else:
            pts = shape(SQ, e["ang"], (sx, sy), r)
        pygame.draw.polygon(sc, fill, pts)
        pygame.draw.polygon(sc, col, pts, 2)
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
                pygame.draw.polygon(sc, col, shape(HEX, self.t * 1.5, pos, 17), 2)
                text(sc, PICK_LET[pk[2]], self.f_small, col, pos, outline=1)

        # враги
        for e in snap.get("enemies", []):
            self.draw_enemy(sc, e, cam)

        # пули врагов
        for b in snap.get("ebullets", []):
            sx, sy = cam.to_screen(b[0], b[1])
            if -20 <= sx <= W + 20 and -20 <= sy <= H + 20:
                pygame.draw.circle(sc, PINK, (int(sx), int(sy)), 6)
                pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), 2)

        # пули игроков
        for b in snap.get("bullets", []):
            sx, sy = cam.to_screen(b[0], b[1])
            if not (-40 <= sx <= W + 40 and -40 <= sy <= H + 40):
                continue
            p0 = V(sx, sy)
            d = V(b[2], b[3])
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
            "SPACE — рывок   E / ПКМ — импульс   1/2/3 — улучшения   H — скрыть",
        ]
        box = pygame.Surface((820, 76), pygame.SRCALPHA)
        box.fill((0, 0, 0, int(150 * alpha / 255)))
        sc.blit(box, (W / 2 - 410, H - 94))
        for i, line in enumerate(hint):
            text(sc, line, self.f_hint, (220, 240, 255), (W / 2, H - 72 + i * 26), outline=2)

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
        text(sc, "ВОЛНА %d" % snap.get("wave", 1), self.f_mid, PURPLE,
             (W - 30, 40), "midright", outline=2)

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
            text(sc, "УР. %d" % me["level"], self.f_mid, YELLOW, (W / 2, by + 26), outline=2)

            def bar(x, y, w, frac, col, label):
                pygame.draw.rect(sc, (20, 20, 40), (x, y, w, 12))
                pygame.draw.rect(sc, col, (x, y, int(w * frac), 12))
                pygame.draw.rect(sc, (60, 60, 100), (x, y, w, 12), 1)
                text(sc, label, self.f_small, col, (x + w + 12, y + 6), "midleft", outline=2)
            bar(24, H - 60, 170, 1 - me["dash_cd"] / 0.9, CYAN, "РЫВОК")
            full = me["charge"] >= 100
            pc = WHITE if full and int(self.t * 6) % 2 == 0 else MAGENTA
            bar(24, H - 36, 170, me["charge"] / 100, pc, "ИМПУЛЬС [E]" if full else "ИМПУЛЬС")

            # быстрые усиления
            x0 = W / 2 - 150
            for i, (name, val) in enumerate((("rapid", me["rapid"]), ("spread", me["spread"]))):
                if val > 0:
                    col = PICK_COL[name]
                    label = "БЫСТР" if name == "rapid" else "ТРОЙН"
                    text(sc, label, self.f_small, col, (x0 + i * 130, H - 44), outline=2)
                    pygame.draw.rect(sc, col, (x0 - 30 + i * 130, H - 28, int(60 * val / 10), 3))

            if me["chain"] >= 5:
                text(sc, "x%d" % min(10, 1 + me["chain"] // 5), self.f_mid, YELLOW,
                     (W / 2, 100), outline=2)
                pygame.draw.rect(sc, YELLOW, (W / 2 - 50, 120,
                                              int(100 * max(0, me["combo_t"]) / 2.5), 3))

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

        self.draw_hint(sc)

    def draw_upgrade_overlay(self, sc):
        if not self.local_choices:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        sc.blit(overlay, (0, 0))
        text(sc, "УРОВЕНЬ ПОВЫШЕН!", self.f_big, YELLOW, (W / 2, 100), outline=3)
        text(sc, "Выберите улучшение (1 / 2 / 3)", self.f_mid, WHITE, (W / 2, 160), outline=2)

        card_w, card_h = 320, 220
        gap = 30
        total = len(self.local_choices) * card_w + (len(self.local_choices) - 1) * gap
        x0 = (W - total) / 2
        for i, up_id in enumerate(self.local_choices):
            u = UPGRADES_BY_ID.get(up_id)
            if not u:
                continue
            x = x0 + i * (card_w + gap)
            y = H / 2 - card_h / 2 + 40
            rect = pygame.Rect(x, y, card_w, card_h)
            col = u["color"]
            pygame.draw.rect(sc, (20, 20, 40), rect)
            pygame.draw.rect(sc, col, rect, 3)
            # номер
            text(sc, str(i + 1), self.f_huge, dim(col, 0.8), (x + 40, y + 40), outline=3)
            # название + описание
            text(sc, u["name"], self.f_mid, col, (x + card_w / 2, y + 90), outline=2)
            # описание с переносом
            desc = u["desc"]
            words = desc.split()
            lines = []
            cur = ""
            max_chars = 22
            for wd in words:
                if len(cur) + len(wd) + 1 > max_chars:
                    lines.append(cur)
                    cur = wd
                else:
                    cur = (cur + " " + wd).strip()
            if cur:
                lines.append(cur)
            for li, line in enumerate(lines):
                text(sc, line, self.f_small, WHITE,
                     (x + card_w / 2, y + 140 + li * 22), outline=2)

    # ================= меню / лобби / ошибки =================
    def draw_menu(self, sc):
        cx, cy = W / 2, H / 2 - 140
        for i in range(5):
            a = self.t * (0.3 + i * 0.15) * (1 if i % 2 else -1)
            col = [CYAN, MAGENTA, PURPLE, YELLOW, RED][i]
            pygame.draw.polygon(sc, dim(col, 0.5),
                                shape(HEX if i % 2 else SQ, a, (cx, cy), 120 + i * 30), 1)
        pulse = 0.8 + 0.2 * math.sin(self.t * 3)
        text(sc, "NEON VOID", self.f_huge, dim(CYAN, pulse), (cx, cy), outline=3)
        text(sc, "СЕТЕВАЯ ИГРА ПО ЛОКАЛЬНОЙ СЕТИ", self.f_mid, MAGENTA, (cx, cy + 78), outline=2)

        y = cy + 160
        text(sc, "1 — СОЗДАТЬ ЛОББИ (ХОСТ)", self.f_mid, WHITE, (cx, y), outline=2)
        text(sc, "2 — ПОДКЛЮЧИТЬСЯ (ввести IP)", self.f_mid, WHITE, (cx, y + 44), outline=2)
        if self.last_ip:
            text(sc, "4 — БЫСТРО К ПОСЛЕДНЕМУ IP (%s)" % self.last_ip,
                 self.f_small, YELLOW, (cx, y + 86), outline=2)
        text(sc, "3 — СМЕНИТЬ ИМЯ   (сейчас: %s)" % self.name_input,
             self.f_small, (150, 170, 220), (cx, y + 122), outline=2)
        text(sc, "Esc — выход", self.f_small, (130, 140, 190), (cx, H - 40), outline=2)

    def draw_lobby(self, sc):
        cx = W / 2
        text(sc, "ЛОББИ", self.f_huge, CYAN, (cx, 90), outline=3)
        if self.is_host:
            text(sc, "ВЫ — ХОСТ", self.f_mid, YELLOW, (cx, 170), outline=2)
            text(sc, "Ваш IP для подключения:", self.f_small, (160, 170, 220), (cx, 215), outline=2)
            y = 260
            for ip in self.lan_ips:
                text(sc, ip, self.f_big, WHITE, (cx, y), outline=3)
                y += 60
            text(sc, "Порт: %d" % PORT, self.f_small, (140, 150, 200), (cx, y + 10), outline=2)
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
            text(sc, "Enter — НАЧАТЬ ИГРУ", self.f_mid, CYAN, (cx, H - 110), outline=2)
        else:
            text(sc, "Ожидание, пока хост начнёт игру...", self.f_mid, PURPLE,
                 (cx, H - 110), outline=2)
        if self.connect_error:
            text(sc, self.connect_error, self.f_small, RED, (cx, H - 66), outline=2)
        text(sc, "Esc — выйти из лобби", self.f_small, (140, 140, 180), (cx, H - 32), outline=2)

    def draw_error(self, sc):
        text(sc, "ОШИБКА", self.f_huge, RED, (W / 2, 150), outline=3)
        for i, ln in enumerate(self.error_msg.split("\n")):
            text(sc, ln, self.f_mid, WHITE, (W / 2, 290 + i * 46), outline=2)
        text(sc, "Enter / Esc — в меню", self.f_small, (160, 160, 200), (W / 2, H - 80), outline=2)

    def draw_dead(self, sc, snap):
        text(sc, "СИГНАЛ ПОТЕРЯН", self.f_huge, RED, (W / 2, 100), outline=3)
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
            text(sc, "Enter — сыграть снова", self.f_mid, CYAN, (W / 2, H - 100), outline=2)
        text(sc, "Esc — в меню", self.f_small, (160, 160, 200), (W / 2, H - 50), outline=2)

    def draw_input_overlay(self, sc):
        if not self.input_mode:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        sc.blit(overlay, (0, 0))
        label = "ВВЕДИТЕ IP ХОСТА" if self.input_mode == "ip" else "ВВЕДИТЕ ИМЯ"
        text(sc, label, self.f_big, CYAN, (W / 2, H / 2 - 90), outline=3)
        val = self.ip_input if self.input_mode == "ip" else self.name_input
        box = pygame.Rect(W / 2 - 280, H / 2 - 30, 560, 64)
        pygame.draw.rect(sc, (20, 20, 40), box)
        pygame.draw.rect(sc, CYAN, box, 2)
        shown = val + ("|" if int(self.t * 2) % 2 == 0 else "")
        text(sc, shown, self.f_big, WHITE, (W / 2, H / 2), outline=2)
        text(sc, "Enter — подтвердить    Esc — отмена",
             self.f_small, (170, 190, 220), (W / 2, H / 2 + 76), outline=2)
        text(sc, "Ctrl+V — вставить из буфера",
             self.f_small, (140, 170, 210), (W / 2, H / 2 + 108), outline=2)

    # ================= главный render =================
    def render(self):
        sc = self.scene

        # обновляем камеру
        tx, ty = self._player_screen_pos()
        self.camera.follow(tx, ty, self.clock.get_time() / 1000.0)

        snap = None
        if self.state in ("play", "dead"):
            snap = self.build_snapshot() if self.is_host else self.snap

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

        # Чёткий рендер без рыбьего глаза и размытого bloom.
        # Сканлайны и лёгкая виньетка остаются в overlay для ретро-атмосферы.

        # тряска
        ox = random.uniform(-self.shake, self.shake) if self.shake > 0.5 else 0
        oy = random.uniform(-self.shake, self.shake) if self.shake > 0.5 else 0
        self.screen.fill((0, 0, 0))
        self.screen.blit(sc, (ox, oy))
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