"""Система прокачки: определения и применение."""
import random

UPGRADES = [
    {"id": "max_hp",   "name": "+1 макс. HP",         "desc": "Максимум здоровья +1, лечит на 1", "color": (90, 255, 160)},
    {"id": "dmg",      "name": "+20% урон",            "desc": "Урон пуль +20%",                   "color": (255, 70, 90)},
    {"id": "fire_rate","name": "+15% скорострельность","desc": "Стрельба быстрее",                 "color": (255, 225, 70)},
    {"id": "move",     "name": "+8% скорость",         "desc": "Двигаешься быстрее",               "color": (0, 235, 255)},
    {"id": "dash",     "name": "-20% кд рывка",        "desc": "Рывок доступен чаще",              "color": (0, 235, 255)},
    {"id": "pierce",   "name": "Пробивание",           "desc": "Пули пробивают +1 врага",          "color": (170, 100, 255)},
    {"id": "lifesteal","name": "Вампиризм",            "desc": "+1 HP за 8 убийств",                "color": (255, 90, 170)},
    {"id": "magnet",   "name": "Магнит",               "desc": "Радиус подбора пикапов +50%",      "color": (255, 150, 50)},
    {"id": "pulse_gain","name": "+Заряд импульса",     "desc": "+50% заряда за убийства",          "color": (255, 50, 200)},
]

UPGRADES_BY_ID = {u["id"]: u for u in UPGRADES}


def roll_upgrades(rng, n=3):
    return [u["id"] for u in rng.sample(UPGRADES, n)]


def apply_upgrade(player, upgrade_id):
    player.upgrades[upgrade_id] = player.upgrades.get(upgrade_id, 0) + 1
    recompute(player)
    if upgrade_id == "max_hp":
        player.hp = min(player.max_hp, player.hp + 1)
    if upgrade_id == "lifesteal":
        # накопленный вампиризм не лечит сразу, только множитель
        pass


def recompute(p):
    up = p.upgrades
    p.max_hp = 5 + up.get("max_hp", 0)
    p.dmg = 1.0 + 0.2 * up.get("dmg", 0)
    p.fire_rate = 0.14 / (1.0 + 0.15 * up.get("fire_rate", 0))
    p.move_spd = 3000.0 * (1.0 + 0.08 * up.get("move", 0))
    p.dash_cd_max = 0.9 * (0.8 ** up.get("dash", 0))
    p.pierce = up.get("pierce", 0)
    p.lifesteal = up.get("lifesteal", 0)
    p.magnet = 1.0 + 0.5 * up.get("magnet", 0)
    p.pulse_gain = 1.0 + 0.5 * up.get("pulse_gain", 0)