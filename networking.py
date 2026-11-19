"""Сетевое лобби и обработка сообщений хоста/клиента."""
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
    W, H, WORLD_W, WORLD_H, PORT, CONFIG_FILE, MAX_PLAYERS,
    BG, CYAN, MAGENTA, YELLOW, RED, ORANGE, GREEN, PURPLE, PINK, WHITE,
    SHIP, DIAMOND, TRI, HEX, SQ,
    KINDS, PICK_COL, PICK_LET, PLAYER_COLORS, PLAYER_SKINS,
)
from fonts import font, text
from draw_utils import shape, dim, make_overlay, bloom, read_clipboard
from camera import Camera
from entities import Player, Enemy, Particle, Ring, Bullet
from upgrades import UPGRADES_BY_ID, apply_upgrade, roll_upgrades
from network import HostServer, ClientConn, OfflineServer
from visuals import draw_glow

log = logging.getLogger("neuro_game")



class NetworkingMixin:
    def start_host(self):
        log.info("Запуск лобби хоста")
        self.connect_error = ""
        try:
            self.server = OfflineServer() if sys.platform == "emscripten" else HostServer()
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
        if sys.platform == "emscripten":
            self.set_error("Сетевой режим пока недоступен в браузере. Пока можно играть одному; WebSocket-мультиплеер появится позже.")
            return
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
        self.last_boss_kind = None
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
        self.server.broadcast({"t": "start", "difficulty": self.difficulty})

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
            if len(self.lobby_players) >= MAX_PLAYERS:
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
            self.server.broadcast({"t": "lobby", "players": self.lobby_players, "difficulty": self.difficulty})
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
                self.server.broadcast({"t": "lobby", "players": self.lobby_players, "difficulty": self.difficulty})
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
            self.server.broadcast({"t": "lobby", "players": self.lobby_players, "difficulty": self.difficulty})
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
            self.difficulty = m.get("difficulty", self.difficulty) if m.get("difficulty") in ("easy", "normal", "hard", "impossible") else "normal"
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
            self.set_error(f"Лобби заполнено. Максимум игроков: {MAX_PLAYERS}.")
        elif t == "started":
            if self.client:
                self.client.stop()
                self.client = None
            self.is_host = False
            self.lobby_players = []
            self.lobby_ready = set()
            self.set_error("ИГРА УЖЕ ЗАПУЩЕНА\\nПодключиться можно будет после завершения текущей игры.")
        elif t == "start":
            self.difficulty = m.get("difficulty", "normal") if m.get("difficulty") in ("easy", "normal", "hard", "impossible") else "normal"
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
