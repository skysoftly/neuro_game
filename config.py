"""Константы игры: размеры, цвета, формы, характеристики."""
import math
import os

# Логическое разрешение (буфер рендера)
W, H = 1280, 720
# Размер игрового мира
WORLD_W, WORLD_H = 3000, 2000
# Сетевой порт и единый лимит игроков (включая хоста).
PORT = 5555
MAX_PLAYERS = 12
SIDE_SHOT_DAMAGE_RATIO = 0.33

DIFFICULTIES = ("easy", "normal", "hard", "impossible")
DIFFICULTY_LABELS = {
    "easy": "ЛЕГКО",
    "normal": "НОРМАЛЬНО",
    "hard": "СЛОЖНО",
    "impossible": "НЕВОЗМОЖНО",
}
DIFFICULTY_MULTIPLIERS = {
    # HP, скорость, атаки, количество врагов
    "easy": (0.78, 0.92, 0.86, 0.86),
    "normal": (1.00, 1.00, 1.00, 1.00),
    "hard": (1.35, 1.08, 1.16, 1.18),
    "impossible": (1.85, 1.18, 1.38, 1.42),
}


def difficulty_multipliers(difficulty="normal"):
    return DIFFICULTY_MULTIPLIERS.get(difficulty, DIFFICULTY_MULTIPLIERS["normal"])


def enemy_scaling(wave, player_count=1, boss=False, difficulty="normal"):
    """Плавный бесконечный рост характеристик без жёсткого лимита волн."""
    wave_steps = max(0, int(wave) - 1)
    players = max(1, min(MAX_PLAYERS, int(player_count)))
    if boss:
        wave_hp = 1.0 + 0.012 * wave_steps + 0.00003 * wave_steps ** 2
        player_hp = 1.0 + 0.025 * (players - 1)
        player_speed = 1.0 + 0.01 * (players - 1)
        speed_cap = 1.18
    else:
        wave_hp = 1.0 + 0.035 * wave_steps + 0.00008 * wave_steps ** 2
        player_hp = 1.0 + 0.05 * (players - 1)
        player_speed = 1.0 + 0.015 * (players - 1)
        speed_cap = 1.22
    hp_mult, speed_mult, _, _ = difficulty_multipliers(difficulty)
    return wave_hp * player_hp * hp_mult, min(speed_cap * speed_mult, (1.0 + 0.002 * wave_steps) * player_speed * speed_mult)


def wave_enemy_count(wave, player_count=1, difficulty="normal"):
    """Размер очереди волны растёт с онлайном, с лимитом активной толпы."""
    players = max(1, min(MAX_PLAYERS, int(player_count)))
    wave_number = max(1, int(wave))
    _, _, _, count_mult = difficulty_multipliers(difficulty)
    return min(72, max(1, int((10 + wave_number * 2.6) * (1.0 + 0.06 * (players - 1)) * count_mult)))


def boss_kind_for_wave(wave, rng=None, previous=None):
    """Малый босс на второй волне, далее случайный босс каждые пять волн."""
    wave_number = max(1, int(wave))
    if wave_number == 2:
        return "boss_minor"
    if wave_number % 5 != 0:
        return None
    import random
    chooser = rng if rng is not None else random
    bosses = ("boss", "boss_storm", "boss_hunter", "boss_void", "boss_siege")
    choices = [kind for kind in bosses if kind != previous] or list(bosses)
    return chooser.choice(choices)
# Пользовательские данные находятся вне каталога проекта и сборки.
# Windows: %APPDATA%/NEON VOID; Linux: ~/.local/share/NEON VOID.
_APP_DATA_ROOT = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
APP_DATA_DIR = os.path.join(_APP_DATA_ROOT, "NEON VOID")
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
STATS_FILE = os.path.join(APP_DATA_DIR, "stats.json")

# ---------- цвета ----------
BG = (6, 9, 18)
CYAN = (65, 220, 255)
MAGENTA = (245, 75, 205)
YELLOW = (255, 211, 92)
RED = (255, 76, 94)
ORANGE = (255, 145, 76)
GREEN = (95, 235, 155)
PURPLE = (165, 120, 255)
PINK = (255, 105, 185)
WHITE = (238, 244, 255)

# ---------- формы ----------
SHIP = [(1.0, 0), (-0.75, -0.7), (-0.4, 0), (-0.75, 0.7)]
DIAMOND = [(1.2, 0), (0, 0.8), (-1.2, 0), (0, -0.8)]
TRI = [(1, 0), (-0.7, 0.8), (-0.7, -0.8)]
HEX = [(math.cos(i * math.tau / 6), math.sin(i * math.tau / 6)) for i in range(6)]
SQ = [(0.8, 0.8), (-0.8, 0.8), (-0.8, -0.8), (0.8, -0.8)]

# ---------- враги ----------
KINDS = {
    "chaser": dict(hp=3, r=13, spd=150, col=(255, 72, 92), score=10),
    "swarm": dict(hp=2, r=9, spd=215, col=(255, 158, 55), score=5),
    "shooter": dict(hp=5, r=17, spd=95, col=(166, 105, 255), score=30),
    "tank": dict(hp=18, r=28, spd=60, col=(255, 220, 65), score=60),
    "dasher": dict(hp=5, r=15, spd=205, col=(255, 75, 165), score=24),
    "splitter": dict(hp=8, r=21, spd=105, col=(80, 235, 135), score=35),
    "mine": dict(hp=4, r=12, spd=75, col=(255, 112, 45), score=18),
    "orbiter": dict(hp=7, r=17, spd=132, col=(55, 220, 220), score=42),
    "bruiser": dict(hp=24, r=31, spd=48, col=(195, 105, 65), score=85),
    "boss": dict(hp=250, r=52, spd=66, col=(245, 100, 190), score=500),
    "boss_storm": dict(hp=330, r=58, spd=82, col=(110, 190, 255), score=650),
    "boss_hunter": dict(hp=390, r=62, spd=96, col=(255, 145, 90), score=800),
    "boss_void": dict(hp=450, r=66, spd=68, col=(165, 120, 245), score=950),
    "boss_siege": dict(hp=520, r=72, spd=48, col=(240, 185, 95), score=1200),
    "boss_minor": dict(hp=75, r=34, spd=58, col=(115, 225, 175), score=180),
}

# ---------- подбираемое ----------
PICK_COL = {"rapid": YELLOW, "spread": CYAN, "heal": GREEN}
PICK_LET = {"rapid": "R", "spread": "3", "heal": "+"}
# 15 уникальных оттенков для лобби (до 12 игроков одновременно).
PLAYER_COLORS = [
    (65, 220, 255), (255, 211, 92), (95, 235, 155), (255, 145, 76), (165, 120, 255),
    (255, 105, 185), (90, 145, 255), (225, 105, 85), (70, 220, 190), (210, 225, 100),
    (180, 125, 255), (255, 170, 210), (125, 205, 255), (190, 235, 150), (245, 195, 120),
]

# Геометрия корпусов: выбор скина меняет силуэт корабля, а не только оттенок.
PLAYER_SKINS = [
    SHIP,
    TRI,
    DIAMOND,
    HEX,
    SQ,
    [(1.15, 0), (0.25, -0.45), (0.05, -1.0), (-0.25, -0.45), (-0.9, -0.65), (-0.55, 0), (-0.9, 0.65), (-0.25, 0.45), (0.05, 1.0), (0.25, 0.45)],
    [(1.1, 0), (0.15, -0.8), (-0.15, -0.35), (-0.9, -0.55), (-0.55, 0), (-0.9, 0.55), (-0.15, 0.35), (0.15, 0.8)],
    [(1.0, 0), (0.25, -0.7), (-0.35, -0.7), (-0.8, 0), (-0.35, 0.7), (0.25, 0.7)],
    [(1.1, 0), (0.2, -0.35), (0.0, -0.85), (-0.2, -0.35), (-0.9, -0.35), (-0.5, 0), (-0.9, 0.35), (-0.2, 0.35), (0.0, 0.85), (0.2, 0.35)],
    [(1.0, 0), (0.35, -0.75), (-0.65, -0.75), (-0.95, 0), (-0.65, 0.75), (0.35, 0.75)],
]