"""Сбалансированные улучшения с ограничением силы накопления."""
import random

UPGRADES = [
    {"id": "max_hp", "name": "+1 максимум HP", "desc": "Максимум здоровья +1 и лечение", "color": (143, 190, 151)},
    {"id": "dmg", "name": "+8% урон", "desc": "Небольшое увеличение урона", "color": (208, 112, 112)},
    {"id": "fire_rate", "name": "+8% темп огня", "desc": "Немного быстрее стрельба", "color": (224, 190, 120)},
    {"id": "move", "name": "+4% скорость", "desc": "Немного быстрее перемещаешься", "color": (112, 202, 196)},
    {"id": "dash", "name": "-7% перезарядка", "desc": "Рывок чуть быстрее восстанавливается", "color": (112, 202, 196)},
    {"id": "pierce", "name": "Пробитие +1", "desc": "Пуля может задеть ещё одного врага", "color": (157, 145, 198)},
    {"id": "lifesteal", "name": "Слабый вампиризм", "desc": "Восстанавливает 1 HP за 18 убийств", "color": (194, 135, 171)},
    {"id": "magnet", "name": "Магнит", "desc": "Радиус подбора предметов +15%", "color": (214, 151, 103)},
    {"id": "pulse_gain", "name": "Заряд импульса", "desc": "Убийства дают на 10% больше заряда", "color": (194, 135, 171)},
]
MAX_STACKS = {"max_hp": 2, "dmg": 3, "fire_rate": 2, "move": 3, "dash": 2,
              "pierce": 1, "lifesteal": 1, "magnet": 2, "pulse_gain": 2}
UPGRADES_BY_ID = {u["id"]: u for u in UPGRADES}


def available_upgrades(player=None):
    if player is None:
        return list(UPGRADES)
    return [u for u in UPGRADES if player.upgrades.get(u["id"], 0) < MAX_STACKS[u["id"]]]


def roll_upgrades(rng, n=3, player=None):
    pool = available_upgrades(player)
    return [u["id"] for u in rng.sample(pool, min(n, len(pool)))]


def apply_upgrade(player, upgrade_id):
    if upgrade_id not in UPGRADES_BY_ID or player.upgrades.get(upgrade_id, 0) >= MAX_STACKS[upgrade_id]:
        return False
    player.upgrades[upgrade_id] = player.upgrades.get(upgrade_id, 0) + 1
    recompute(player)
    if upgrade_id == "max_hp":
        player.hp = min(player.max_hp, player.hp + 1)
    return True


def recompute(p):
    up = p.upgrades
    p.max_hp = 5 + min(2, up.get("max_hp", 0))
    p.dmg = 1.0 + 0.08 * min(3, up.get("dmg", 0))
    p.fire_rate = 0.14 / (1.0 + 0.08 * min(2, up.get("fire_rate", 0)))
    p.move_spd = 3000.0 * (1.0 + 0.04 * min(3, up.get("move", 0)))
    p.dash_cd_max = 0.9 * (0.93 ** min(2, up.get("dash", 0)))
    p.pierce = min(1, up.get("pierce", 0))
    p.lifesteal = min(1, up.get("lifesteal", 0))
    p.magnet = 1.0 + 0.15 * min(2, up.get("magnet", 0))
    p.pulse_gain = 1.0 + 0.1 * min(2, up.get("pulse_gain", 0))
