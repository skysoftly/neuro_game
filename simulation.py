"""Симуляция матча: игроки, волны, враги, урон и снимки сети."""
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
    wave_enemy_count, boss_kind_for_wave,
)
from fonts import font, text
from draw_utils import shape, dim, make_overlay, bloom, read_clipboard
from camera import Camera
from entities import Player, Enemy, Particle, Ring, Bullet
from upgrades import UPGRADES_BY_ID, apply_upgrade, roll_upgrades
from network import HostServer, ClientConn
from visuals import draw_glow

log = logging.getLogger("neuro_game")



class SimulationMixin:
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
        # Лимит 64 относится к размеру одной очереди, а не к номеру волны.
        n = wave_enemy_count(self.wave, player_count)
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
        boss_kind = boss_kind_for_wave(self.wave)
        if boss_kind:
            q.append(boss_kind)
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
        # Выбывшие игроки не усиливают врагов; учитываем только живых.
        enemy = Enemy(kind, pos, self.wave, len(alive_players))
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
                if k == "boss":
                    e.cool = max(1.9, 2.8 - self.wave * 0.012)
                else:
                    e.cool = max(1.25, 2.35 - self.wave * 0.018)
                base = math.atan2(d.y, d.x)
                if k == "boss_minor":
                    for offset in (-0.22, 0.0, 0.22):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 300, 5.5])
                elif k == "boss":
                    # Первый большой босс: меньше снарядов и больше времени на реакцию.
                    for i in range(12):
                        a = i * math.tau / 12 + e.ang
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 285, 6.0])
                    for offset in (-0.32, 0.0, 0.32):
                        a = base + offset
                        self.ebullets.append([V(e.p), V(math.cos(a), math.sin(a)) * 360, 5.5])
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
