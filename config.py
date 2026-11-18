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
BG = (7, 7, 18)
CYAN = (0, 235, 255)
MAGENTA = (255, 50, 200)
YELLOW = (255, 225, 70)
RED = (255, 70, 90)
ORANGE = (255, 150, 50)
GREEN = (90, 255, 160)
PURPLE = (170, 100, 255)
PINK = (255, 90, 170)
WHITE = (255, 255, 255)

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
}

# ---------- подбираемое ----------
PICK_COL = {"rapid": YELLOW, "spread": CYAN, "heal": GREEN}
PICK_LET = {"rapid": "R", "spread": "S", "heal": "+"}
PLAYER_COLORS = [CYAN, YELLOW, GREEN, ORANGE]