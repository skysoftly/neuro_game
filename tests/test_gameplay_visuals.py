import random
import unittest

import pygame

from config import W, H
from draw_utils import bloom, fisheye, make_overlay
from entities import Player
from upgrades import UPGRADES, apply_upgrade, roll_upgrades


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.player = Player(1, "Tester")

    def test_roll_returns_three_distinct_upgrades(self):
        result = roll_upgrades(random.Random(7), 3)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(set(result)), 3)
        self.assertTrue(set(result).issubset({u["id"] for u in UPGRADES}))

    def test_max_hp_upgrade_increases_capacity_and_heals(self):
        apply_upgrade(self.player, "max_hp")
        self.assertEqual(self.player.max_hp, 6)
        self.assertEqual(self.player.hp, 5)

    def test_damage_upgrade_changes_damage(self):
        apply_upgrade(self.player, "dmg")
        self.assertAlmostEqual(self.player.dmg, 1.2)

    def test_lifesteal_upgrade_is_tracked(self):
        apply_upgrade(self.player, "lifesteal")
        self.assertEqual(self.player.lifesteal, 1)
        self.assertEqual(self.player.lifesteal_progress, 0)


class RetroRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_lens_filter_preserves_surface_size(self):
        source = pygame.Surface((W, H))
        source.fill((12, 16, 30))
        result = fisheye(source, 0.075)
        self.assertEqual(result.get_size(), (W, H))

    def test_bloom_and_overlay_are_renderable(self):
        source = pygame.Surface((W, H))
        source.fill((10, 10, 20))
        pygame.draw.circle(source, (0, 235, 255), (W // 2, H // 2), 30)
        bloom(source, W, H, 0.16)
        overlay = make_overlay(W, H)
        self.assertEqual(overlay.get_size(), (W, H))


if __name__ == "__main__":
    unittest.main()
