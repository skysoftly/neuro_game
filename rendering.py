"""Методы отрисовки игровых сцен и интерфейса."""
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
    DIFFICULTY_LABELS,
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
from network import HostServer, ClientConn
from visuals import draw_glow

log = logging.getLogger("neuro_game")


class RenderingMixin:
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
        # Красная опасная зона за мягкой границей арены.
        left, top = -cx, -cy
        right, bottom = left + WORLD_W, top + WORLD_H
        # Пока камера внутри арены, красная заливка не видна:
        # не создаём полноэкранную alpha-поверхность каждый кадр.
        if left > 0 or right < W or top > 0 or bottom < H:
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.003)
            alpha = int(34 + pulse * 24)
            danger = pygame.Surface((W, H), pygame.SRCALPHA)
            red = (255, 35, 65, alpha)
            if left > 0:
                pygame.draw.rect(danger, red, (0, 0, min(W, int(left)), H))
            if right < W:
                pygame.draw.rect(danger, red, (max(0, int(right)), 0, W - max(0, int(right)), H))
            if top > 0:
                pygame.draw.rect(danger, red, (0, 0, W, min(H, int(top))))
            if bottom < H:
                pygame.draw.rect(danger, red, (0, max(0, int(bottom)), W, H - max(0, int(bottom))))
            sc.blit(danger, (0, 0))
        pygame.draw.rect(sc, (255, 55, 85), (left, top, WORLD_W, WORLD_H), 3)

    def draw_hat(self, surface, x, y, hat_index, color, scale=1.0):
        x, y = int(x), int(y)
        k = max(0.45, float(scale))
        def pt(dx, dy):
            return (int(x + dx * k), int(y + dy * k))
        dark = dim(color, 0.48)
        if hat_index == 0:  # кепка
            pygame.draw.polygon(surface, color, [pt(-8, 0), pt(-6, -6), pt(5, -6), pt(8, 0)])
            pygame.draw.line(surface, color, pt(-9, 1), pt(10, 1), max(1, int(2*k)))
        elif hat_index == 1:  # корона
            pygame.draw.polygon(surface, color, [pt(-8, 1), pt(-8, -6), pt(-3, -2), pt(0, -8), pt(3, -2), pt(8, -6), pt(8, 1)])
            pygame.draw.line(surface, dark, pt(-8, 2), pt(8, 2), max(1, int(2*k)))
        elif hat_index == 2:  # рожки
            pygame.draw.line(surface, color, pt(-5, 0), pt(-8, -8), max(2, int(3*k)))
            pygame.draw.line(surface, color, pt(5, 0), pt(8, -8), max(2, int(3*k)))
        elif hat_index == 3:  # нимб
            pygame.draw.ellipse(surface, color, pygame.Rect(int(x-9*k), int(y-9*k), int(18*k), int(5*k)), max(1, int(2*k)))
        elif hat_index == 4:  # колпак
            pygame.draw.polygon(surface, color, [pt(-7, 1), pt(1, -12), pt(8, 1)])
            pygame.draw.circle(surface, WHITE, pt(1, -12), max(2, int(2*k)))
        elif hat_index == 5:  # антенна
            pygame.draw.line(surface, color, pt(0, 0), pt(0, -10), max(1, int(2*k)))
            pygame.draw.circle(surface, color, pt(0, -11), max(2, int(3*k)))
        elif hat_index == 6:  # ушки
            pygame.draw.polygon(surface, color, [pt(-8, 1), pt(-8, -8), pt(-1, -2)])
            pygame.draw.polygon(surface, color, [pt(8, 1), pt(8, -8), pt(1, -2)])
        elif hat_index == 7:  # пропеллер
            pygame.draw.line(surface, color, pt(0, 0), pt(0, -7), max(1, int(2*k)))
            pygame.draw.line(surface, color, pt(-8, -8), pt(8, -8), max(2, int(3*k)))
            pygame.draw.circle(surface, WHITE, pt(0, -8), max(2, int(2*k)))
        elif hat_index == 8:  # цветок
            for dx, dy in ((0,-7), (6,-3), (4,4), (-4,4), (-6,-3)):
                pygame.draw.circle(surface, color, pt(dx, dy), max(2, int(3*k)))
            pygame.draw.circle(surface, YELLOW, pt(0, 0), max(2, int(2*k)))
        else:  # визор
            pygame.draw.line(surface, color, pt(-9, -2), pt(9, -2), max(3, int(4*k)))
            pygame.draw.line(surface, WHITE, pt(-5, -3), pt(5, -3), max(1, int(k)))

    def draw_player(self, sc, data, is_local, cam):
        sx, sy = cam.to_screen(data["x"], data["y"])
        if not (-40 <= sx <= W + 40 and -40 <= sy <= H + 40):
            return
        raw_color = data.get("color")
        col = tuple(raw_color) if isinstance(raw_color, (list, tuple)) and len(raw_color) == 3 else PLAYER_COLORS[(data["pid"] - 1) % len(PLAYER_COLORS)]
        if data.get("dash_t", 0) > 0:
            col = WHITE
        if data["alive"] and (data.get("inv", 0) <= 0 or data.get("dash_t", 0) > 0
                              or int(self.t * 22) % 2 == 0):
            draw_glow(sc, (sx, sy), col, 48, 28)
            skin_index = max(0, min(len(PLAYER_SKINS) - 1, int(data.get("skin", 0))))
            pts = shape(PLAYER_SKINS[skin_index], data["ang"], (sx, sy), 20)
            pygame.draw.polygon(sc, (6, 40, 56), pts)
            pygame.draw.polygon(sc, col, pts, 2)
            self.draw_hat(sc, sx, sy - 17, max(0, min(9, int(data.get("hat", 0)))), col, 0.9)
            if data.get("inv", 0) > 0.3:
                pygame.draw.circle(sc, dim(col, 0.5), (int(sx), int(sy)), 30, 1)
        if is_local:
            pygame.draw.circle(sc, dim(col, 0.6), (int(sx), int(sy)), 26, 1)
        # имя игрока
        label = data["name"]
        text(sc, label, self.f_small, col, (sx, sy - 47), outline=2)

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
        if kind not in ("chaser", "swarm"):
            # Glow radius is tied to the archetype, not the spawn animation.
            # This keeps the cached glow atlas stable instead of rebuilding it
            # for every intermediate radius while enemies fade in.
            draw_glow(sc, (sx, sy), base_col, int(e["r"] * 2.2 + 12), 22)
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

        # Контрастные внутренние метки помогают различать архетипы даже в толпе.
        accent = {
            "chaser": (255, 225, 190), "swarm": (255, 245, 180),
            "shooter": (225, 205, 255), "tank": (255, 245, 180),
            "dasher": (255, 225, 235), "splitter": (205, 255, 220),
            "mine": (255, 235, 175), "orbiter": (190, 255, 250),
            "bruiser": (255, 215, 180), "boss": (255, 215, 245),
            "boss_storm": (210, 240, 255), "boss_hunter": (255, 225, 195),
            "boss_void": (230, 210, 255), "boss_siege": (255, 245, 195),
        }.get(kind, WHITE)
        if kind == "chaser":
            pygame.draw.circle(sc, accent, (int(sx), int(sy)), max(2, int(r * 0.22)))
        elif kind == "swarm":
            pygame.draw.line(sc, accent, (sx - r * 0.28, sy), (sx + r * 0.38, sy), 2)
        elif kind == "dasher":
            pygame.draw.line(sc, accent, (sx - r * 0.55, sy), (sx + r * 0.45, sy), 3)
        elif kind == "splitter":
            pygame.draw.circle(sc, accent, (int(sx), int(sy)), max(3, int(r * 0.3)), 2)
        elif kind in ("shooter", "orbiter", "mine"):
            pygame.draw.circle(sc, accent, (int(sx), int(sy)), max(3, int(r * 0.24)), 2)
        elif kind in ("tank", "bruiser"):
            pygame.draw.polygon(sc, accent, shape(DIAMOND, -e["ang"], (sx, sy), r * 0.34), 2)
        elif kind.startswith("boss"):
            pygame.draw.circle(sc, accent, (int(sx), int(sy)), max(5, int(r * 0.34)), 2)
            pygame.draw.circle(sc, accent, (int(sx), int(sy)), max(2, int(r * 0.12)))
        max_hp = max(1, e.get("max_hp", 1))
        hp_ratio = max(0.0, min(1.0, e.get("hp", max_hp) / max_hp))
        if max_hp >= 5:
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

        # Хост рисует своего игрока из живой симуляции (120-160+ Гц),
        # а не из сетевого снапшота (30 Гц), иначе спрайт дёргается.
        # Клиент рисует локального игрока по той же интерполированной позиции,
        # относительно которой выше выставлена камера.
        for pl in snap.get("players", []):
            # Мёртвые игроки полностью исчезают из мира: без корабля,
            # подписи и локального маркера. Их камера остаётся свободной.
            if not pl.get("alive", True):
                continue
            if pl["pid"] == self.my_id and self.is_host:
                live_player = self.players.get(self.my_id)
                if live_player is not None:
                    pl = dict(pl)
                    pl.update({
                        "x": live_player.p.x, "y": live_player.p.y,
                        "ang": live_player.ang, "alive": live_player.alive,
                        "inv": live_player.inv, "dash_t": live_player.dash_t,
                        "name": live_player.name,
                    })
            elif pl["pid"] == self.my_id and self.camera_target_current is not None:
                alpha = min(1.0, self.camera_lerp_elapsed / max(1e-4, self.camera_lerp_duration))
                pl = dict(pl)
                pl["x"] = self.camera_target_previous[0] + (self.camera_target_current[0] - self.camera_target_previous[0]) * alpha
                pl["y"] = self.camera_target_previous[1] + (self.camera_target_current[1] - self.camera_target_previous[1]) * alpha
            self.draw_player(sc, pl, pl["pid"] == self.my_id, cam)

        # Указатель ближайшего противника рисуется в мировом слое, под HUD.
        if snap.get("enemies"):
            nearest = None
            for enemy in snap["enemies"]:
                ex, ey = cam.to_screen(enemy["x"], enemy["y"])
                if ex < 18 or ex > W - 18 or ey < 18 or ey > H - 18:
                    dx, dy = ex - W / 2, ey - H / 2
                    distance_sq = dx * dx + dy * dy
                    if nearest is None or distance_sq < nearest[0]:
                        nearest = (distance_sq, dx, dy)
            if nearest:
                _, dx, dy = nearest
                angle = math.atan2(dy, dx)
                scale = min((W / 2 - 34) / max(1, abs(dx)),
                            (H / 2 - 34) / max(1, abs(dy)))
                ax, ay = W / 2 + dx * scale, H / 2 + dy * scale
                tip = (ax + math.cos(angle) * 13, ay + math.sin(angle) * 13)
                left = (ax + math.cos(angle + 2.45) * 11, ay + math.sin(angle + 2.45) * 11)
                right = (ax + math.cos(angle - 2.45) * 11, ay + math.sin(angle - 2.45) * 11)
                pygame.draw.polygon(sc, MAGENTA, (tip, left, right))
                pygame.draw.circle(sc, WHITE, (int(ax), int(ay)), 3)

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

        # всплывающие очки и локальные уведомления
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

        # Таблица лидеров: отдельная колонка очков не заезжает на длинные ники.
        roster = sorted(snap.get("players", []), key=lambda player: player.get("score", 0), reverse=True)[:4]
        for rank, player in enumerate(roster):
            y = 24 + rank * 25
            is_me = player["pid"] == self.my_id
            raw_color = player.get("color")
            # Цвет в таблице лидеров всегда совпадает с цветом корабля.
            # Своего игрока выделяем подчёркиванием, а не заменой цвета на жёлтый.
            color = (tuple(raw_color) if isinstance(raw_color, (list, tuple)) and len(raw_color) == 3
                     else PLAYER_COLORS[(player["pid"] - 1) % len(PLAYER_COLORS)])
            rank_rect = pygame.Rect(18, y - 10, 18, 22)
            text(sc, "%d." % (rank + 1), self.f_small, color, rank_rect.midleft, "midleft", outline=1)
            name_rect = pygame.Rect(40, y - 10, 126, 22)
            name_font = font(16)
            while name_font.size(player["name"])[0] > name_rect.width and name_font.get_height() > 10:
                name_font = font(name_font.get_height() - 1)
            name_width = min(name_rect.width, name_font.size(player["name"])[0])
            text(sc, player["name"], name_font, color, name_rect.center, outline=1)
            if is_me:
                underline_left = name_rect.centerx - name_width // 2
                pygame.draw.line(sc, color, (underline_left, y + 9),
                                 (underline_left + name_width, y + 9), 2)
            score_rect = pygame.Rect(172, y - 10, 62, 22)
            self.draw_fit_text(sc, str(player.get("score", 0)), WHITE, score_rect, 16, 10)

        spectating = self.is_spectating()

        # Здоровье показывается только живому игроку. У наблюдателя нижняя
        # панель освобождена под отдельный статус SPECTATOR.
        if me and not spectating:
            hp = max(0, int(me["hp"]))
            max_hp = max(1, int(me["max_hp"]))
            hp_ratio = max(0.0, min(1.0, hp / max_hp))
            hp_color = GREEN if hp_ratio > 0.55 else ORANGE if hp_ratio > 0.25 else RED
            # На экране всегда до 10 ячеек: каждая заполненная ячейка —
            # одно текущее HP. При HP выше 10 уровень сердец пересчитывается
            # от текущего здоровья, поэтому урон снимает старшие сердца слева.
            slots = min(10, max(5, max_hp))
            crystal_w, crystal_gap = 17, 7
            total_w = slots * crystal_w + (slots - 1) * crystal_gap
            panel_w, panel_h = max(250, total_w + 30), 76
            panel = pygame.Rect((W - panel_w) // 2, H - panel_h - 8, panel_w, panel_h)
            panel_surface = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
            pygame.draw.rect(panel_surface, (7, 13, 23, 112), panel_surface.get_rect())
            pygame.draw.rect(panel_surface, (*dim(hp_color, 0.48), 150),
                             panel_surface.get_rect(), 1)
            sc.blit(panel_surface, panel.topleft)

            palette = (
                "#ffb52e", "#ff7138", "#ff4d68", "#ed55b5", "#ad65ff",
                "#687cff", "#42b9ff", "#39dfd0", "#72df70", "#d0df48",
            )
            start_x = panel.centerx - total_w // 2
            heart_y = panel.y + 8
            for slot in range(slots):
                x = int(start_x + slot * (crystal_w + crystal_gap))
                fill = max(0.0, min(1.0, hp - slot))

                # Уровень зависит от текущего HP, а не максимального:
                # 22 HP = 2 сердца III + 8 сердец II;
                # после 3 урона (19 HP) = 9 сердец II + 1 сердце I.
                bonus_level = max(1, (hp - slot + 9) // 10)
                cycle = (bonus_level - 1) // 10
                base = pygame.Color(palette[(bonus_level - 1) % 10])
                hue, saturation, value, _ = base.hsva
                base.hsva = ((hue + cycle * 17) % 360,
                             min(100, saturation + cycle * 2),
                             max(48, value - cycle * 3), 100)
                hue, saturation, value, _ = base.hsva

                points = [(x + 8, heart_y + 1), (x + 14, heart_y - 1),
                          (x + 17, heart_y + 5), (x + 8, heart_y + 18),
                          (x, heart_y + 5), (x + 3, heart_y - 1)]
                cx, cy = x + 8.5, heart_y + 8.5

                # Пустая часть сердца остаётся видимой, заполненная часть
                # постепенно проявляет внутренние слои по мере потери/лечения HP.
                dark = pygame.Color(base)
                dark.hsva = (hue, min(100, saturation * 0.42), 22, 100)
                pygame.draw.polygon(sc, tuple(dark), points)

                old_clip = sc.get_clip()
                fill_width = round(crystal_w * fill)
                if fill_width > 0:
                    sc.set_clip(pygame.Rect(x, heart_y - 2, fill_width, 22).clip(old_clip))
                    shadow = pygame.Color(0, 0, 0)
                    shadow.hsva = (hue, saturation, max(18, value * 0.38), 100)
                    pygame.draw.polygon(sc, tuple(shadow),
                                        [(px, py + 2) for px, py in points])
                    pygame.draw.polygon(sc, tuple(base), points)

                    layer_specs = (
                        (0.82, (hue, max(25, saturation * 0.78), min(100, value + 8))),
                        (0.64, (hue, max(15, saturation * 0.48), min(100, value + 15))),
                        (0.46, (hue, max(10, saturation * 0.68), min(100, value - 3))),
                        (0.28, (hue, max(5, saturation * 0.25), 100)),
                    )
                    visible_layers = min(4, int(fill * 4 + 0.0001))
                    for scale, (layer_hue, layer_sat, layer_value) in layer_specs[:visible_layers]:
                        layer_color = pygame.Color(0, 0, 0)
                        layer_color.hsva = (layer_hue, layer_sat, layer_value, 100)
                        layer = [(round(cx + (px - cx) * scale),
                                  round(cy + (py - cy) * scale))
                                 for px, py in points]
                        pygame.draw.polygon(sc, tuple(layer_color), layer)

                sc.set_clip(old_clip)
                outline = pygame.Color(base)
                outline.hsva = (hue, min(100, saturation * 0.35),
                                100 if fill > 0 else 55, 100)
                pygame.draw.polygon(sc, tuple(outline), points, 1)

            label = "ЗДОРОВЬЕ"
            label_font = self.f_small
            label_y = panel.bottom - 19
            label_width = label_font.render(label, True, hp_color).get_width()
            count_label = "%d / %d" % (hp, max_hp)
            count_width = label_font.render(count_label, True, WHITE).get_width()
            label_x = panel.centerx - (label_width + count_width + 12) / 2
            text(sc, label, label_font, hp_color, (label_x, label_y), "midleft", outline=1)
            count_x = label_x + label_width + 12
            text(sc, count_label, label_font, WHITE,
                 (count_x, label_y), "midleft", outline=1)

        # правый верх: волна
        wave = max(1, int(snap.get("wave", 1)))
        wave_label = "ПОДГОТОВКА К ВОЛНЕ 1" if not snap.get("wave_started", False) else "ВОЛНА %d" % wave
        text(sc, wave_label, self.f_mid, PURPLE, (W - 30, 34), "midright", outline=2)
        remaining = snap.get("enemies_left", 0)
        text(sc, "УГРОЗ: %d" % remaining, self.f_small, WHITE, (W - 30, 62), "midright", outline=1)
        boss_in = snap.get("boss_in", 5)
        boss_alive = any(e.get("k", "").startswith("boss") for e in snap.get("enemies", []))
        boss_label = "БОСС НА АРЕНЕ" if boss_alive else ("БОСС В ЭТОЙ ВОЛНЕ" if boss_in == 0
                                                          else "БОСС ЧЕРЕЗ %d ВОЛН" % boss_in)
        text(sc, boss_label, self.f_small, MAGENTA, (W - 30, 84), "midright", outline=1)

        bosses = [e for e in snap.get("enemies", []) if e.get("k", "").startswith("boss")]
        if bosses:
            boss = bosses[0]
            bw = 500
            bx = (W - bw) // 2
            by = 34
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
                "boss_minor": "РАЗВЕДЧИК",
            }
            boss_name = boss_names.get(boss.get("k"), "БОСС")
            text(sc, "%s  -  %d%%" % (boss_name, int(ratio * 100)), self.f_small, WHITE,
                 (W / 2, by - 12), outline=1)

        if me and not spectating:
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
            active = [(name, buffs.get(name, 0)) for name in ("rapid", "spread") if buffs.get(name, 0) > 0]
            if me.get("shield_t", 0) > 0:
                active.append(("shield", me["shield_t"]))
            if active:
                panel = pygame.Rect(W - 278, H - 48 - len(active) * 24, 254, len(active) * 24 + 18)
                pygame.draw.rect(sc, (8, 13, 20), panel)
                pygame.draw.rect(sc, (80, 100, 112), panel, 1)
                for i, (name, value) in enumerate(active):
                    label = {"rapid":"СКОРОСТРЕЛЬНОСТЬ","spread":"ТРОЙНОЙ ВЫСТРЕЛ","shield":"ЩИТ АКТИВЕН"}[name]
                    col = CYAN if name == "shield" else PICK_COL.get(name, MAGENTA)
                    self.draw_fit_text(sc, "%s  %.1fс" % (label, value), col,
                                       pygame.Rect(panel.x + 8, panel.y + 1 + i * 24,
                                                   panel.w - 16, 20), 18, 10)

        if me and not spectating and me.get("shield_t", 0) > 0:
            sx, sy = self.camera.to_screen(me["x"], me["y"])
            pygame.draw.circle(sc, CYAN, (int(sx), int(sy)), 31 + int(2 * math.sin(self.t * 9)), 2)
            pygame.draw.circle(sc, WHITE, (int(sx), int(sy)), 35, 1)


        # Баннер волны всегда помещается в экран независимо от номера волны.
        if snap.get("banner", 0) > 0 and self.state == "play":
            k = min(1.0, snap["banner"])
            current_wave = max(1, int(snap.get("wave", 1)))
            banner_label = "ПОДГОТОВКА К ВОЛНЕ 1" if not snap.get("wave_started", False) else "ВОЛНА %d" % current_wave
            self.draw_fit_text(sc, banner_label, dim(WHITE, k),
                               pygame.Rect(180, H / 2 - 205, W - 360, 130), 88, 48)

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

        if spectating:
            panel = pygame.Rect(W / 2 - 112, H - 58, 224, 38)
            pygame.draw.rect(sc, (7, 15, 25), panel)
            pygame.draw.rect(sc, (65, 220, 255), panel, 1)
            text(sc, "SPECTATOR", self.f_mid, CYAN, panel.center, outline=2)

        self.draw_hint(sc)

    def draw_upgrade_overlay(self, sc):
        if not self.intermission:
            return
        sc.blit(self.intermission_shade, (0, 0))
        roster = list(self.players.values()) if self.is_host else (self.snap or {}).get("players", [])
        if self.is_host:
            ready_count = sum(1 for p in roster if p.alive and p.upgrade_ready)
            alive_count = sum(1 for p in roster if p.alive)
        else:
            ready_count = sum(1 for p in roster if p.get("alive", True) and p.get("upgrade_ready", False))
            alive_count = sum(1 for p in roster if p.get("alive", True))
        self.draw_fit_text(sc, "ПЕРЕДЫШКА МЕЖДУ ВОЛНАМИ", YELLOW,
                           pygame.Rect(90, 58, W - 180, 62), 52, 34)
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
            pulse = 1.0 + (0.025 * (0.5 + 0.5 * math.sin(self.t * 7 + i)) if hovered else 0.0)
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
            if not hovered:
                shade_rect = self.upgrade_card_shade.get_rect(center=card.center)
                sc.blit(self.upgrade_card_shade, shade_rect)

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
        text(sc, "ВОЛНЫ. ХАОС. ВЫЖИВИ.", self.f_mid, MAGENTA,
             (cx, cy + 78), outline=2)

        y = cy + 160
        self.draw_button(sc, pygame.Rect(cx - 210, y - 20, 420, 52), "СОЗДАТЬ ЛОББИ", CYAN)
        self.draw_button(sc, pygame.Rect(cx - 210, y + 42, 420, 52), "ПОДКЛЮЧИТЬСЯ ПО IP", MAGENTA)
        self.draw_button(sc, pygame.Rect(cx - 210, y + 104, 420, 44),
                         "ИМЯ ИГРОКА: " + (self.name_input or "НЕ ЗАДАНО"), PURPLE)
        self.draw_button(sc, pygame.Rect(cx - 210, y + 158, 420, 44), "НАСТРОЙКИ", YELLOW)
        self.draw_button(sc, pygame.Rect(cx - 100, H - 58, 200, 38), "ВЫХОД", RED)

    def draw_settings(self, sc):
        cx = W / 2
        text(sc, "НАСТРОЙКИ", self.f_huge, CYAN, (cx, 112), outline=3)
        text(sc, "МУЗЫКА", self.f_mid, WHITE, (cx, 220), outline=1)
        self.draw_button(sc, pygame.Rect(cx - 205, 244, 70, 48), "-", RED)
        self.draw_button(sc, pygame.Rect(cx + 135, 244, 70, 48), "+", CYAN)
        text(sc, "%d%%" % round(self.music_volume * 100), self.f_big, YELLOW, (cx, 268), outline=2)
        text(sc, "ЗВУКОВЫЕ ЭФФЕКТЫ", self.f_mid, WHITE, (cx, 320), outline=1)
        self.draw_button(sc, pygame.Rect(cx - 205, 344, 70, 48), "-", RED)
        self.draw_button(sc, pygame.Rect(cx + 135, 344, 70, 48), "+", CYAN)
        text(sc, "%d%%" % round(self.sfx_volume * 100), self.f_big, YELLOW, (cx, 368), outline=2)
        self.draw_button(sc, pygame.Rect(cx - 210, 444, 420, 48),
                         "ТРЯСКА ЭКРАНА: " + ("ВКЛ" if self.screen_shake_enabled else "ВЫКЛ"),
                         CYAN if self.screen_shake_enabled else RED)
        fps_label = "БЕЗ ЛИМИТА" if self.target_fps == 0 else str(self.target_fps)
        self.draw_button(sc, pygame.Rect(cx - 210, 514, 420, 48),
                         "ЛИМИТ FPS: " + fps_label, PURPLE)
        self.draw_button(sc, pygame.Rect(cx - 210, 584, 420, 48),
                         "ПОЛНОЭКРАННЫЙ РЕЖИМ: " + ("ВКЛ" if self.borderless_fullscreen else "ВЫКЛ"),
                         CYAN if self.borderless_fullscreen else RED)
        text(sc, "F11 — переключить в любой момент", font(13), (135, 155, 175),
             (cx, 642), outline=1)
        self.draw_button(sc, pygame.Rect(cx - 150, H - 58, 300, 42), "НАЗАД", RED)

    def draw_lobby(self, sc):
        cx = W / 2
        text(sc, "ЛОББИ", self.f_huge, CYAN, (cx, 76), outline=3)
        if self.is_host:
            role, shown_ip = "ВЫ - ХОСТ", (self.lan_ips[0] if self.lan_ips else "IP НЕ НАЙДЕН")
        else:
            role, shown_ip = "ВЫ - КЛИЕНТ", (self.last_ip or "НЕИЗВЕСТНО")
        self.draw_fit_text(sc, role, YELLOW, pygame.Rect(cx - 380, 132, 360, 38), 27, 16)
        self.draw_fit_text(sc, "IP: " + shown_ip, WHITE, pygame.Rect(cx + 20, 132, 500, 38), 27, 12)

        diff_label = DIFFICULTY_LABELS.get(self.difficulty, "НОРМАЛЬНО")
        diff_rect = pygame.Rect(cx - 190, 174, 380, 34)
        if self.is_host:
            self.draw_button(sc, diff_rect, "СЛОЖНОСТЬ: " + diff_label + "  ‹ ›", YELLOW)
            text(sc, "ХОСТ МОЖЕТ МЕНЯТЬ ДО СТАРТА", font(11), (135, 155, 175), (cx, 210), outline=1)
        else:
            text(sc, "СЛОЖНОСТЬ: " + diff_label, self.f_small, YELLOW, (cx, 194), outline=2)

        list_rect = pygame.Rect(130, 220, 470, 350)
        edit_rect = pygame.Rect(620, 220, 530, 350)
        for panel, accent in ((list_rect, CYAN), (edit_rect, PURPLE)):
            pygame.draw.rect(sc, (5, 10, 18), panel)
            pygame.draw.rect(sc, (48, 72, 82), panel, 1)
            pygame.draw.line(sc, accent, (panel.x + 16, panel.y + 42),
                             (panel.right - 16, panel.y + 42), 2)

        text(sc, "ИГРОКИ  ·  %d / %d МАКС." % (len(self.lobby_players), MAX_PLAYERS), self.f_mid,
             WHITE, (list_rect.centerx, list_rect.y + 23), outline=2)
        visible = max(1, (list_rect.h - 62) // 34)
        self.lobby_scroll = max(0, min(self.lobby_scroll, max(0, len(self.lobby_players) - visible)))
        old_clip = sc.get_clip()
        sc.set_clip(list_rect.inflate(-8, -52))
        for i, (pid, name, color_index, skin_index, hat_index) in enumerate(
                self.lobby_players[self.lobby_scroll:self.lobby_scroll + visible]):
            col = PLAYER_COLORS[color_index]
            mark = "  ·  ВЫ" if pid == self.my_id else ""
            role_mark = "  ·  ХОСТ" if pid == 0 else ""
            ready_mark = "ГОТОВ" if pid in self.lobby_ready else "ЖДЁТ"
            row_y = list_rect.y + 62 + i * 34
            pygame.draw.circle(sc, col, (list_rect.x + 22, row_y), 7)
            text(sc, "%02d  %s%s%s" % (self.lobby_scroll + i + 1, name, role_mark, mark),
                 self.f_small, col, (list_rect.x + 42, row_y), "midleft", outline=1)
            text(sc, ready_mark, font(13), GREEN if pid in self.lobby_ready else (145, 150, 165),
                 (list_rect.right - 18, row_y), "midright", outline=1)
        sc.set_clip(old_clip)
        if len(self.lobby_players) > visible:
            text(sc, "ПРОКРУТКА: КОЛЁСИКО МЫШИ", font(12), (145, 165, 180),
                 (list_rect.centerx, list_rect.bottom - 14), outline=1)
        if not self.lobby_players:
            text(sc, "ожидание подключений...", self.f_small, (150, 150, 180),
                 (list_rect.centerx, list_rect.centery), outline=2)

        text(sc, "ВАШ ВНЕШНИЙ ВИД", self.f_mid, WHITE, (edit_rect.centerx, edit_rect.y + 23), outline=2)
        own = next((entry for entry in self.lobby_players if entry[0] == self.my_id), None)
        current_color = own[2] if own else self.local_color_index
        current_skin = own[3] if own else self.local_skin_index
        current_hat = own[4] if own else self.local_hat_index
        occupied = {entry[2] for entry in self.lobby_players if entry[0] != self.my_id}

        text(sc, "ЦВЕТ", font(15), CYAN, (edit_rect.x + 22, edit_rect.y + 66), "midleft", outline=1)
        for idx, col in enumerate(PLAYER_COLORS):
            row, column = divmod(idx, 5)
            cell = pygame.Rect(edit_rect.x + 22 + column * 48, edit_rect.y + 82 + row * 27, 32, 20)
            unavailable = idx in occupied
            pygame.draw.rect(sc, (25, 29, 38) if unavailable else col, cell)
            pygame.draw.rect(sc, (95, 105, 120) if unavailable else
                             (WHITE if idx == current_color else dim(col, 0.55)),
                             cell, 2 if idx == current_color else 1)
            if unavailable:
                pygame.draw.line(sc, (135, 75, 85), cell.topleft, cell.bottomright, 2)
                pygame.draw.line(sc, (135, 75, 85), cell.topright, cell.bottomleft, 2)

        text(sc, "КОРПУС", font(15), CYAN, (edit_rect.x + 22, edit_rect.y + 174), "midleft", outline=1)
        for idx, skin_shape in enumerate(PLAYER_SKINS):
            row, column = divmod(idx, 5)
            cell = pygame.Rect(edit_rect.x + 22 + column * 96, edit_rect.y + 188 + row * 34, 76, 28)
            selected = idx == current_skin
            pygame.draw.rect(sc, (15, 25, 38), cell)
            pygame.draw.rect(sc, CYAN if selected else (55, 72, 88), cell, 2 if selected else 1)
            pts = shape(skin_shape, -math.pi / 2, cell.center, 10)
            pygame.draw.polygon(sc, PLAYER_COLORS[current_color], pts, 2)
            text(sc, str(idx + 1), font(11), WHITE, (cell.right - 8, cell.centery), "midright", outline=1)

        text(sc, "ШАПОЧКА", font(15), CYAN, (edit_rect.x + 22, edit_rect.y + 270), "midleft", outline=1)
        for idx in range(10):
            row, column = divmod(idx, 5)
            cell = pygame.Rect(edit_rect.x + 22 + column * 96, edit_rect.y + 284 + row * 29, 76, 25)
            selected = idx == current_hat
            pygame.draw.rect(sc, (15, 25, 38), cell)
            pygame.draw.rect(sc, PURPLE if selected else (55, 72, 88), cell, 2 if selected else 1)
            self.draw_hat(sc, cell.centerx, cell.centery + 3, idx, PLAYER_COLORS[current_color], 0.52)
            text(sc, str(idx + 1), font(10), WHITE, (cell.right - 5, cell.centery), "midright", outline=1)

        action_rect = pygame.Rect(cx - 190, H - 136, 380, 52)
        if self.is_host:
            all_ready = self.lobby_all_ready()
            label = "НАЧАТЬ ИГРУ" if all_ready else "ЖДЁМ ГОТОВНОСТИ ИГРОКОВ"
            self.draw_button(sc, action_rect, label, CYAN, enabled=all_ready)
        else:
            is_ready = self.my_id in self.lobby_ready
            self.draw_button(sc, action_rect,
                             "НЕ ГОТОВ" if is_ready else "ГОТОВ",
                             GREEN if is_ready else CYAN)
            text(sc, "Ожидание запуска хостом...", self.f_small, PURPLE,
                 (cx, 194), outline=2)
        if self.connect_error:
            text(sc, self.connect_error, self.f_small, RED, (cx, H - 82), outline=2)
        self.draw_button(sc, pygame.Rect(cx - 150, H - 66, 300, 42), "НАЗАД В МЕНЮ", RED)

    def draw_error(self, sc):
        self.draw_fit_text(sc, "ОШИБКА", RED, pygame.Rect(220, 90, W - 440, 120), 96, 52)
        self.draw_wrapped_text(sc, self.error_msg, self.f_mid, WHITE,
                               pygame.Rect(120, 230, W - 240, 230), 5)
        self.draw_button(sc, pygame.Rect(W / 2 - 150, H - 102, 300, 46), "В МЕНЮ", CYAN)

    def draw_pause_overlay(self, sc):
        sc.blit(self.pause_shade, (0, 0))
        panel = pygame.Rect(W / 2 - 245, H / 2 - 145, 490, 320)
        pts = [(panel.x + 24, panel.y), (panel.right - 24, panel.y),
               (panel.right, panel.y + 24), (panel.right, panel.bottom - 24),
               (panel.right - 24, panel.bottom), (panel.x + 24, panel.bottom),
               (panel.x, panel.bottom - 24), (panel.x, panel.y + 24)]
        pygame.draw.polygon(sc, (4, 8, 15), pts)
        pygame.draw.polygon(sc, (60, 85, 98), pts, 1)
        pygame.draw.line(sc, CYAN, (panel.x + 28, panel.y + 70),
                         (panel.right - 28, panel.y + 70), 2)
        self.draw_fit_text(sc, "ПАУЗА", WHITE,
                           pygame.Rect(panel.x + 30, panel.y + 12, panel.w - 60, 48), 34, 26)
        text(sc, "АРЕНА ОСТАНОВЛЕНА", self.f_small, (155, 183, 192),
             (W / 2, panel.y + 98), outline=1)
        if self.is_host:
            self.draw_button(sc, pygame.Rect(W / 2 - 175, H / 2 + 42, 350, 52), "ПРОДОЛЖИТЬ", CYAN)
        else:
            text(sc, "ОЖИДАНИЕ ХОСТА", self.f_mid, YELLOW, (W / 2, H / 2 + 68), outline=1)
        self.draw_button(sc, pygame.Rect(W / 2 - 175, H / 2 + 108, 350, 48), "ПОКИНУТЬ СЕССИЮ", RED)

    def draw_dead(self, sc, snap):
        self.draw_fit_text(sc, "СЕССИЯ ЗАВЕРШЕНА", RED,
                           pygame.Rect(150, 42, W - 300, 112), 96, 52)
        players = sorted(snap.get("players", []), key=lambda p: -p["score"])
        mvp_pid = players[0]["pid"] if players else -1

        # Общая панель итогов одинакова для хоста и клиентов.
        panel = pygame.Rect(W / 2 - 420, 158, 840, 390)
        panel_surface = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(panel_surface, (5, 10, 22, 224), panel_surface.get_rect())
        pygame.draw.rect(panel_surface, (105, 48, 70, 220), panel_surface.get_rect(), 2)
        pygame.draw.line(panel_surface, RED, (22, 54), (panel.w - 22, 54), 2)
        sc.blit(panel_surface, panel.topleft)

        # заголовки
        hdr_y = 192
        text(sc, "N", self.f_small, (150, 160, 200), (W / 2 - 380, hdr_y), "midleft", outline=2)
        text(sc, "ИМЯ", self.f_small, (150, 160, 200), (W / 2 - 320, hdr_y), "midleft", outline=2)
        text(sc, "ОЧКИ", self.f_small, (150, 160, 200), (W / 2 + 60, hdr_y), "midleft", outline=2)
        text(sc, "УБИЙСТВА", self.f_small, (150, 160, 200), (W / 2 + 200, hdr_y), "midleft", outline=2)
        text(sc, "ВОЛНЫ", self.f_small, (150, 160, 200), (W / 2 + 340, hdr_y), "midleft", outline=2)

        y = 228
        for i, pl in enumerate(players):
            raw_color = pl.get("color")
            col = tuple(raw_color) if isinstance(raw_color, (list, tuple)) and len(raw_color) == 3 else PLAYER_COLORS[(pl["pid"] - 1) % len(PLAYER_COLORS)]
            is_mvp = pl["pid"] == mvp_pid
            row_col = YELLOW if is_mvp else col
            text(sc, "%d" % (i + 1), self.f_mid, row_col, (W / 2 - 380, y), "midleft", outline=2)
            name_rect = pygame.Rect(W / 2 - 320, y - 18, 360, 36)
            name_font = font(30)
            while name_font.size(pl["name"])[0] > name_rect.width and name_font.get_height() > 14:
                name_font = font(name_font.get_height() - 1)
            name_width = min(name_rect.width, name_font.size(pl["name"])[0])
            text(sc, pl["name"], name_font, row_col, name_rect.center, outline=2)
            if pl["pid"] == self.my_id:
                underline_left = name_rect.centerx - name_width // 2
                pygame.draw.line(sc, row_col, (underline_left, y + 17),
                                 (underline_left + name_width, y + 17), 2)
            text(sc, str(pl["score"]), self.f_mid, WHITE, (W / 2 + 60, y), "midleft", outline=2)
            text(sc, str(pl.get("kills", 0)), self.f_mid, WHITE, (W / 2 + 200, y), "midleft", outline=2)
            text(sc, str(snap.get("wave", 0)), self.f_mid, WHITE, (W / 2 + 340, y), "midleft", outline=2)
            y += 34

        if mvp_pid >= 0:
            mvp_name = next((p["name"] for p in players if p["pid"] == mvp_pid), "?")
            self.draw_fit_text(sc, "MVP: %s" % mvp_name, YELLOW,
                               pygame.Rect(W / 2 - 340, y + 8, 680, 42), 30, 14)

        if self.is_host:
            self.draw_button(sc, pygame.Rect(W / 2 - 190, H - 126, 380, 52), "ИГРАТЬ СНОВА", CYAN)
        else:
            text(sc, "ОЖИДАЙТЕ НАЧАЛА НОВОЙ ИГРЫ", self.f_small, YELLOW,
                 (W / 2, H - 104), outline=2)
        self.draw_button(sc, pygame.Rect(W / 2 - 150, H - 70, 300, 42), "В МЕНЮ", RED)

    def draw_input_overlay(self, sc):
        if not self.input_mode:
            return
        sc.blit(self.input_shade, (0, 0))
        label = "ВВЕДИТЕ IP ХОСТА" if self.input_mode == "ip" else "ВВЕДИТЕ ИМЯ"
        text(sc, label, self.f_big, CYAN, (W / 2, H / 2 - 110), outline=3)
        value = self.ip_input if self.input_mode == "ip" else self.name_input
        box = pygame.Rect(W / 2 - 280, H / 2 - 45, 560, 64)
        pygame.draw.rect(sc, (5, 12, 28), box)
        pygame.draw.rect(sc, CYAN, box, 2)
        shown = value + ("|" if int(self.t * 2) % 2 == 0 else "")
        if self.input_mode == "ip" and len(shown) > 45:
            shown = "..." + shown[-42:]
        if self.input_mode == "name" and self.first_run:
            text(sc, "ЭТО ИМЯ УВИДЯТ ДРУГИЕ ИГРОКИ", self.f_small, (164, 174, 182), (W / 2, H / 2 - 72), outline=1)
        self.draw_fit_text(sc, shown, WHITE, pygame.Rect(W / 2 - 260, H / 2 - 43, 520, 60), 52, 18)
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
        sc.blit(self.tutorial_shade, (0, 0))
        panel = pygame.Rect(W / 2 - 330, H / 2 - 230, 660, 460)
        pygame.draw.rect(sc, (10, 18, 28), panel)
        pygame.draw.rect(sc, CYAN, panel, 2)
        pygame.draw.line(sc, MAGENTA, (panel.x + 22, panel.y + 64),
                         (panel.right - 22, panel.y + 64), 2)
        self.draw_fit_text(sc, "ПЕРЕД ПЕРВОЙ ВОЛНОЙ", CYAN,
                           pygame.Rect(panel.x + 20, panel.y + 14, panel.w - 40, 56), 52, 30)
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
            self.draw_fit_text(sc, desc, WHITE,
                               pygame.Rect(panel.x + 210, y - 12, panel.w - 232, 26), 18, 11)
        if self.is_host and self.tutorial_ready:
            text(sc, "ГОТОВО - ОЖИДАНИЕ ОСТАЛЬНЫХ ИГРОКОВ",
                 self.f_small, GREEN, (W / 2, panel.bottom - 52), outline=1)
        elif self.is_host:
            self.draw_fit_text(sc, "ХОСТ: ENTER ИЛИ КЛИК - НАЧАТЬ, КОГДА ВСЕ ГОТОВЫ",
                               GREEN, pygame.Rect(panel.x + 20, panel.bottom - 66, panel.w - 40, 28), 18, 11)
        elif self.tutorial_ready:
            text(sc, "ГОТОВО - ОЖИДАНИЕ ОСТАЛЬНЫХ ИГРОКОВ",
                 self.f_small, GREEN, (W / 2, panel.bottom - 52), outline=1)
        else:
            self.draw_fit_text(sc, "ENTER ИЛИ КЛИК - ПОДТВЕРДИТЬ ГОТОВНОСТЬ",
                               GREEN, pygame.Rect(panel.x + 20, panel.bottom - 66, panel.w - 40, 28), 18, 11)

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
        snap = self.snap if self.state in ("play", "dead") else None
        camera_dt = min(self.clock.get_time() / 1000.0, 1 / 20)

        # Сначала определяем точную позицию локального игрока, которую нарисуем,
        # затем ставим камеру относительно неё и только после этого рисуем мир.
        if not self.is_spectating():
            local_draw_pos = None
            if self.is_host:
                live_player = self.players.get(self.my_id)
                if live_player is not None:
                    local_draw_pos = (live_player.p.x, live_player.p.y)
            elif snap is not None:
                local_state = next((pl for pl in snap.get("players", [])
                                    if pl.get("pid") == self.my_id), None)
                if local_state is not None:
                    local_draw_pos = (float(local_state["x"]), float(local_state["y"]))
                    if self.camera_target_current is not None:
                        alpha = min(1.0, self.camera_lerp_elapsed /
                                    max(1e-4, self.camera_lerp_duration))
                        local_draw_pos = (
                            self.camera_target_previous[0] +
                            (self.camera_target_current[0] - self.camera_target_previous[0]) * alpha,
                            self.camera_target_previous[1] +
                            (self.camera_target_current[1] - self.camera_target_previous[1]) * alpha,
                        )
            if local_draw_pos is None:
                local_draw_pos = self._player_screen_pos()
            # Камера и локальный спрайт используют одну и ту же мировую позицию.
            # Это убирает рассинхрон host simulation vs 30 Hz snapshot.
            self.camera.follow(local_draw_pos[0], local_draw_pos[1], camera_dt,
                               snap=not self.is_host)
        # Клиент получает номер волны из сетевого снапшота.
        # У хоста self.wave — авторитетное состояние симуляции: старый снапшот
        # может быть на долю секунды позади и не должен откатывать прогресс.
        if snap is not None and not self.is_host:
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

        # Low-cost bloom works directly on the scene buffer; no full-screen copy.
        bloom(sc, W, H, 0.055, self.bloom_small, self.bloom_full)

        local_player = None
        if snap is not None and self.state == "play":
            local_player = next((p for p in snap.get("players", [])
                                 if p.get("pid") == self.my_id), None)
        hurt_t = local_player.get("hurt_t", 0.0) if local_player else 0.0
        health_ratio = (local_player.get("hp", 1) / max(1, local_player.get("max_hp", 1))
                        if local_player and local_player.get("alive", True) else 1.0)
        low_hp = max(0.0, min(1.0, (0.55 - health_ratio) / 0.55))
        damage_flash = min(1.0, hurt_t / 0.52) * 0.68
        vignette_strength = max(low_hp, damage_flash)
        # Экранная тряска отключена: она сдвигала весь кадр независимо от камеры
        # и воспринималась как постоянное дрожание персонажа.
        ox = oy = 0
        self.screen.fill((0, 0, 0))
        self.screen.blit(sc, (ox, oy))
        self.screen.blit(self.overlay, (0, 0))
        if vignette_strength > 0.01 and self.state == "play":
            self.red_vignette.set_alpha(int(175 * vignette_strength))
            self.screen.blit(self.red_vignette, (0, 0))

        # UI поверх игрового слоя: текст и кнопки остаются контрастными.
        if self.state == "loading":
            self.draw_splash(self.screen)
        elif self.state == "menu":
            self.draw_menu(self.screen)
        elif self.state == "settings":
            self.draw_settings(self.screen)
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
                if self.state == "dead":
                    self.screen.blit(self.end_tint, (0, 0))
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
            self.screen.blit(self.debug_panel_surface, (W - 322, H - 138))
            for i, line in enumerate(debug_lines):
                text(self.screen, line, self.f_small, GREEN, (W - 312, H - 126 + i * 23), "topleft", outline=1)

        # Курсор рисуется последним: он выше карточек, текста и debug-панели.
        if self.intermission and self.state == "play":
            self.draw_mouse_cursor(self.screen)

    # ================= главный цикл =================
