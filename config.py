"""Константы игры: размеры, цвета, формы, характеристики."""
import math
import os

# Логическое разрешение (буфер рендера)
W, H = 1280, 720
# Размер игрового мира
WORLD_W, WORLD_H = 3000, 2000
# Сетевой порт
PORT = 5555
# Файл сохранения имени и последнего IP
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

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
    "chaser": dict(hp=3, r=13, spd=150, col=RED, score=10),
    "swarm": dict(hp=2, r=9, spd=215, col=ORANGE, score=5),
    "shooter": dict(hp=5, r=17, spd=95, col=PURPLE, score=30),
    "tank": dict(hp=18, r=28, spd=60, col=YELLOW, score=60),
    "dasher": dict(hp=5, r=15, spd=205, col=(255, 110, 120), score=24),
    "splitter": dict(hp=8, r=21, spd=105, col=(120, 220, 150), score=35),
    "mine": dict(hp=4, r=12, spd=75, col=(255, 180, 80), score=18),
    "orbiter": dict(hp=7, r=17, spd=132, col=(90, 210, 205), score=42),
    "bruiser": dict(hp=24, r=31, spd=48, col=(225, 130, 80), score=85),
    "boss": dict(hp=620, r=54, spd=72, col=(245, 100, 190), score=500),
    "boss_storm": dict(hp=760, r=58, spd=82, col=(110, 190, 255), score=650),
    "boss_hunter": dict(hp=880, r=62, spd=96, col=(255, 145, 90), score=800),
    "boss_void": dict(hp=1020, r=66, spd=68, col=(165, 120, 245), score=950),
    "boss_siege": dict(hp=1250, r=72, spd=48, col=(240, 185, 95), score=1200),
}

# ---------- подбираемое ----------
PICK_COL = {"rapid": YELLOW, "spread": CYAN, "heal": GREEN}
PICK_LET = {"rapid": "R", "spread": "3", "heal": "+"}
PLAYER_COLORS = [CYAN, YELLOW, GREEN, ORANGE]