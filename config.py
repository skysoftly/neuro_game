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
BG = (10, 14, 22)
CYAN = (112, 202, 196)
MAGENTA = (194, 135, 171)
YELLOW = (224, 190, 120)
RED = (208, 112, 112)
ORANGE = (214, 151, 103)
GREEN = (143, 190, 151)
PURPLE = (157, 145, 198)
PINK = (205, 132, 157)
WHITE = (224, 226, 215)

# ---------- формы ----------
SHIP = [(1.0, 0), (-0.75, -0.7), (-0.4, 0), (-0.75, 0.7)]
DIAMOND = [(1.2, 0), (0, 0.8), (-1.2, 0), (0, -0.8)]
TRI = [(1, 0), (-0.7, 0.8), (-0.7, -0.8)]
HEX = [(math.cos(i * math.tau / 6), math.sin(i * math.tau / 6)) for i in range(6)]
SQ = [(0.8, 0.8), (-0.8, 0.8), (-0.8, -0.8), (0.8, -0.8)]

# ---------- враги ----------
KINDS = {
    "chaser": dict(hp=1, r=13, spd=150, col=RED, score=10, xp=4),
    "swarm":  dict(hp=1, r=9, spd=215, col=ORANGE, score=5, xp=2),
    "shooter": dict(hp=3, r=17, spd=95, col=PURPLE, score=30, xp=8),
    "tank":   dict(hp=10, r=28, spd=60, col=YELLOW, score=60, xp=20),
    "dasher": dict(hp=3, r=15, spd=205, col=(255, 110, 120), score=24, xp=7),
    "splitter": dict(hp=5, r=21, spd=105, col=(120, 220, 150), score=35, xp=10),
    "mine": dict(hp=2, r=12, spd=75, col=(255, 180, 80), score=18, xp=6),
    "boss": dict(hp=110, r=54, spd=72, col=(245, 100, 190), score=500, xp=100),
}

# ---------- подбираемое ----------
PICK_COL = {"rapid": YELLOW, "spread": CYAN, "heal": GREEN}
PICK_LET = {"rapid": "R", "spread": "S", "heal": "+"}
PLAYER_COLORS = [CYAN, YELLOW, GREEN, ORANGE]