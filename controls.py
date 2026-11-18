"""Ввод игрока, управление камерой наблюдателя и события Pygame."""
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

log = logging.getLogger("neuro_game")



class ControlsMixin:
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
