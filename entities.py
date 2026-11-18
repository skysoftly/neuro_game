"""Игровые сущности: Player, Enemy, Particle, Ring, Bullet."""
import math
import random
from pygame import Vector2 as V

from config import KINDS, PLAYER_COLORS, WORLD_W, WORLD_H, enemy_scaling


class Player:
    def __init__(self, pid, name):
        self.pid = pid
        self.name = name
        # стартуем около центра, но не в одной точке
        ang = random.uniform(0, math.tau)
        off = V(math.cos(ang), math.sin(ang)) * random.uniform(80, 200)
        self.p = V(WORLD_W / 2, WORLD_H / 2) + off
        self.v = V()
        self.ang = 0.0
        self.hp = 5
        self.max_hp = 5
        self.cool = 0.0
        self.inv = 0.0
        self.dash_t = 0.0
        self.dash_cd = 0.0
        self.rapid = 0.0
        self.spread = 0.0
        self.score = 0
        self.kills = 0
        self.charge = 0.0
        self.alive = True
        self.boundary_t = 0.0
        self.color = PLAYER_COLORS[(pid - 1) % len(PLAYER_COLORS)]
        self.color_index = (pid - 1) % len(PLAYER_COLORS)
        self.skin = 0
        self.hat = 0
        self.inp = V()
        self.shoot = False
        self.want_dash = False
        self.want_pulse = False
        # прокачка
        self.upgrades = {}
        self.upgrade_choices = []
        self.pending_upgrades = 0
        self.upgrade_ready = False
        # производные
        self.dmg = 1.0
        self.fire_rate = 0.14
        self.move_spd = 3000.0
        self.dash_cd_max = 0.9
        self.pierce = 0
        self.lifesteal = 0
        self.lifesteal_progress = 0
        self.magnet = 1.0
        self.pulse_gain = 1.0
        self.crit = 0.0
        self.multishot = 0
        self.bullet_speed = 1.0
        self.bullet_size = 1.0
        self.regen = 0.0
        self.regen_timer = 0.0
        self.armor = 0
        self.armor_hits = 0
        self.pulse_power = 1.0
        self.dash_damage = 1.0
        self.shield_t = 0.0
        self.shield_hits = 0
        self.hurt_t = 0.0
        self.tutorial_ready = False


class Enemy:
    def __init__(self, kind, pos, wave, player_count=1):
        d = KINDS[kind]
        self.kind = kind
        self.p = V(pos)
        self.v = V()
        # Рост HP продолжается и после сотой волны; онлайн учитывается сразу.
        hp_scale, speed_scale = enemy_scaling(wave, player_count, kind.startswith("boss"))
        wave_steps = max(0, int(wave) - 1)
        self.attack_scale = min(1.8, 1.0 + 0.004 * wave_steps)
        self.hp = max(1, math.ceil(d["hp"] * hp_scale))
        self.max_hp = self.hp
        self.r = d["r"]
        self.spd = d["spd"] * speed_scale
        self.col = d["col"]
        self.age = 0.0
        self.cool = random.uniform(0.8, 2.0)
        self.flash = 0.0
        self.ang = random.uniform(0, math.tau)
        self.side = random.choice((-1, 1))
        self.dead = False
        self.stun = 0.0
        self.windup = 0.0
        self.charge_t = 0.0
        self.charge_dir = V()
        self.phase = 0


class Particle:
    __slots__ = ("p", "v", "life", "max", "col", "size", "drag")

    def __init__(self, p, v, life, col, size=3.0, drag=2.5):
        self.p = V(p)
        self.v = V(v)
        self.life = life
        self.max = life
        self.col = col
        self.size = size
        self.drag = drag

    def update(self, dt):
        self.life -= dt
        self.p += self.v * dt
        self.v *= math.exp(-self.drag * dt)


class Ring:
    __slots__ = ("p", "r", "max", "spd", "col", "w")

    def __init__(self, p, r, maxr, spd, col, w):
        self.p = V(p)
        self.r = r
        self.max = maxr
        self.spd = spd
        self.col = col
        self.w = w

    def update(self, dt):
        self.r += self.spd * dt


class Bullet:
    """Пуля игрока. pierce — сколько ещё врагов может пробить."""
    __slots__ = ("p", "v", "life", "owner", "dmg", "pierce", "hit_ids", "size")

    def __init__(self, p, v, owner, dmg, pierce, size=1.0):
        self.p = V(p)
        self.v = V(v)
        self.life = 0.8
        self.owner = owner
        self.dmg = dmg
        self.pierce = pierce
        self.hit_ids = set()
        self.size = size

    def register_hit(self):
        """Return whether the bullet survives; each penetration loses 35% damage."""
        if self.pierce <= 0:
            return False
        self.pierce -= 1
        self.dmg *= 0.65
        return True

    def update(self, dt):
        self.p += self.v * dt
        self.life -= dt