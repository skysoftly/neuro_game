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
    W, H, WORLD_W, WORLD_H, PORT, CONFIG_FILE, STATS_FILE,
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
from networking import NetworkingMixin
from controls import ControlsMixin
from simulation import SimulationMixin

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
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        log.exception("Не удалось сохранить настройки")


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
class Game(RenderingMixin, NetworkingMixin, ControlsMixin, SimulationMixin):
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
        self.session_recorded = False

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
        self.last_boss_kind = None
        self.difficulty = "normal"

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

    def record_session(self):
        """Сохранить личную статистику завершённого матча в AppData."""
        if self.session_recorded:
            return
        if self.is_host:
            player = self.players.get(self.my_id)
            if player is None:
                return
            score, kills, wave = player.score, player.kills, self.wave
        else:
            if not self.snap:
                return
            player = next((p for p in self.snap.get("players", [])
                           if int(p.get("pid", -1)) == self.my_id), None)
            if player is None:
                return
            score, kills, wave = player.get("score", 0), player.get("kills", 0), self.snap.get("wave", self.wave)
        try:
            os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
            try:
                with open(STATS_FILE, "r", encoding="utf-8") as f:
                    stats = json.load(f)
            except (OSError, ValueError):
                stats = {}
            stats["games_played"] = int(stats.get("games_played", 0)) + 1
            stats["total_kills"] = int(stats.get("total_kills", 0)) + int(kills)
            stats["best_score"] = max(int(stats.get("best_score", 0)), int(score))
            stats["best_wave"] = max(int(stats.get("best_wave", 0)), int(wave))
            with open(STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            self.session_recorded = True
        except (OSError, TypeError, ValueError):
            log.exception("Не удалось сохранить статистику")

    def persist(self):
        save_config({"last_ip": self.last_ip, "name": self.name_input,
                     "music_volume": self.music_volume, "sfx_volume": self.sfx_volume,
                     "screen_shake": self.screen_shake_enabled, "target_fps": self.target_fps,
                     "borderless_fullscreen": self.borderless_fullscreen,
                     "player_color": self.local_color_index, "player_skin": self.local_skin_index,
                     "player_hat": self.local_hat_index})

    def set_display_mode(self, fullscreen):
        """Switch between windowed and SDL desktop-fullscreen modes."""
        window = None
        previous = None
        entering = bool(fullscreen) and getattr(self, "_windowed_geometry", None) is None
        try:
            from pygame._sdl2.video import Window

            window = getattr(self, "_display_window", None)
            if window is None:
                window = Window.from_display_module()
                self._display_window = window

            previous = {
                "position": tuple(window.position),
                "size": tuple(window.size),
                "borderless": bool(window.borderless),
            }

            if fullscreen:
                if getattr(self, "_windowed_geometry", None) is None:
                    self._windowed_geometry = previous.copy()
                # SDL handles the desktop-sized borderless window itself.
                # Manually changing the window size was unreliable on Windows.
                window.set_fullscreen(desktop=True)
            else:
                geometry = getattr(self, "_windowed_geometry", None)
                window.set_windowed()
                if geometry is not None:
                    window.borderless = geometry["borderless"]
                    window.size = geometry["size"]
                    window.position = geometry["position"]
                if geometry is not None:
                    self._windowed_geometry = None

            self.screen = pygame.display.get_surface() or self.screen
            return True
        except (pygame.error, RuntimeError, AttributeError, TypeError, IndexError, ValueError):
            if window is not None:
                try:
                    if entering:
                        window.set_windowed()
                        if previous is not None:
                            window.borderless = previous["borderless"]
                            window.size = previous["size"]
                            window.position = previous["position"]
                    elif fullscreen is False:
                        window.set_fullscreen(desktop=True)
                    if entering:
                        self._windowed_geometry = None
                except Exception:
                    log.exception("Не удалось восстановить окно после ошибки переключения")
            log.exception("Не удалось переключить безрамочный режим")
            return False

    def toggle_borderless_fullscreen(self):
        # Ignore duplicate KEYDOWN events generated while a display transition
        # is still settling. This prevents rapid swap-chain recreation.
        now = pygame.time.get_ticks()
        if now - getattr(self, "_last_fullscreen_toggle_ms", -1000) < 220:
            return False
        self._last_fullscreen_toggle_ms = now

        target = not self.borderless_fullscreen
        if not self.set_display_mode(target):
            return False
        self.borderless_fullscreen = target
        self.persist()
        return True

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
    def quit(self):
        self.leave_net()
        pygame.quit()
        sys.exit()

    # ================= симуляция (хост) =================
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