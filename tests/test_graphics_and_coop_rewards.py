import random
import unittest
from types import SimpleNamespace

import pygame

from config import (
    GRAPHICS_QUALITIES,
    PARTICLE_STYLES,
    PARTICLE_DENSITIES,
    normalize_graphics_quality,
    normalize_particle_style,
    normalize_particle_density,
)
from entities import Player
from simulation import SimulationMixin


class GraphicsSettingsTests(unittest.TestCase):
    def test_graphics_settings_have_safe_defaults_for_invalid_values(self):
        self.assertEqual(normalize_graphics_quality("invalid"), "high")
        self.assertEqual(normalize_particle_style("invalid"), "spark")
        self.assertEqual(normalize_particle_density("invalid"), 100)

    def test_all_graphics_options_are_available(self):
        self.assertEqual(GRAPHICS_QUALITIES, ("low", "medium", "high", "ultra"))
        self.assertEqual(PARTICLE_STYLES, ("circle", "spark", "diamond"))
        self.assertEqual(PARTICLE_DENSITIES, (50, 75, 100, 150))
        self.assertEqual(normalize_particle_density(150), 150)


class FakeSimulation(SimulationMixin):
    def __init__(self):
        self.players = {
            1: Player(1, "One"),
            2: Player(2, "Two"),
        }
        self.parts = []
        self.rings = []
        self.pops = []
        self.pickups = []
        self.enemies = []
        self.bullets = []
        self.ebullets = []
        self.damage_contributions = {}
        self.wave = 1
        self.difficulty = "normal"
        self.shake = 0.0
        self.rng = random.Random(1)
        self.intermission = True
        self.local_choices = []
        self.local_upgrade_waiting = False
        self.next_wave_calls = 0
        self.state = "play"

    def burst(self, *args, **kwargs):
        pass

    def play_sound(self, *args, **kwargs):
        pass

    def next_wave(self):
        self.next_wave_calls += 1


class DamageRewardTests(unittest.TestCase):
    def setUp(self):
        self.game = FakeSimulation()
        self.enemy = SimpleNamespace(
            kind="chaser",
            hp=100.0,
            dead=False,
            p=pygame.Vector2(500, 500),
            col=(255, 72, 92),
            r=13,
        )

    def test_score_is_shared_by_damage_percentage(self):
        self.game.damage(self.enemy, 20, self.game.players[1])
        self.game.damage(self.enemy, 80, self.game.players[2])
        self.assertEqual(self.game.players[1].score, 0)
        self.game.kill(self.enemy, self.game.players[2])
        self.assertEqual(self.game.players[1].score, 2)
        self.assertEqual(self.game.players[2].score, 8)

    def test_small_damage_still_awards_at_least_one_point(self):
        self.game.damage(self.enemy, 1, self.game.players[1])
        self.game.damage(self.enemy, 99, self.game.players[2])
        self.game.kill(self.enemy, self.game.players[2])
        self.assertGreaterEqual(self.game.players[1].score, 1)
        self.assertGreaterEqual(self.game.players[2].score, 1)

    def test_dead_players_respawn_when_next_wave_starts(self):
        dead = self.game.players[2]
        dead.alive = False
        dead.hp = 0
        dead.upgrade_choices = ["dmg"]
        dead.upgrade_ready = True
        self.game.start_next_wave()
        self.assertTrue(dead.alive)
        self.assertEqual(dead.hp, dead.max_hp)
        self.assertGreaterEqual(dead.inv, 1.9)
        self.assertEqual(dead.upgrade_choices, [])
        self.assertEqual(self.game.next_wave_calls, 1)

    def test_session_ends_if_everyone_is_dead(self):
        for player in self.game.players.values():
            player.alive = False
        self.game.finish_session = lambda: setattr(self.game, "finished", True)
        self.game.start_next_wave()
        self.assertTrue(getattr(self.game, "finished", False))
        self.assertEqual(self.game.next_wave_calls, 0)


if __name__ == "__main__":
    unittest.main()
