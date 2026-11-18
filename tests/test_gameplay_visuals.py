import random
import unittest

import pygame

from config import W, H
from draw_utils import bloom, make_overlay
from entities import Enemy, Player
from upgrades import UPGRADES, apply_upgrade, roll_upgrades


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.player = Player(1, "Tester")

    def test_enemy_stats_scale_with_wave(self):
        early = Enemy("tank", (100, 100), 1)
        late = Enemy("tank", (100, 100), 10)
        self.assertGreater(late.max_hp, early.max_hp)
        self.assertGreater(late.spd, early.spd)

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
        self.assertAlmostEqual(self.player.dmg, 1.12)

    def test_damage_upgrade_has_a_hard_cap(self):
        for _ in range(8):
            apply_upgrade(self.player, "dmg")
        self.assertEqual(self.player.upgrades["dmg"], 5)
        self.assertAlmostEqual(self.player.dmg, 1.6)

    def test_upgrade_pool_has_many_distinct_build_options(self):
        self.assertGreaterEqual(len(UPGRADES), 18)
        self.assertIn("pulse_power", {u["id"] for u in UPGRADES})
        self.assertIn("multishot", {u["id"] for u in UPGRADES})

    def test_new_combat_upgrades_change_stats(self):
        apply_upgrade(self.player, "pulse_power")
        apply_upgrade(self.player, "crit")
        apply_upgrade(self.player, "multishot")
        self.assertGreater(self.player.pulse_power, 1.0)
        self.assertGreater(self.player.crit, 0.0)
        self.assertEqual(self.player.multishot, 1)

    def test_roll_excludes_upgrades_at_their_cap(self):
        self.player.upgrades["dmg"] = 3
        result = roll_upgrades(random.Random(2), 3, self.player)
        self.assertNotIn("dmg", result)

    def test_lifesteal_is_limited_to_one_stack(self):
        for _ in range(3):
            apply_upgrade(self.player, "lifesteal")
        self.assertEqual(self.player.lifesteal, 1)
        self.assertEqual(self.player.upgrades["lifesteal"], 1)

    def test_pierce_is_limited_to_one_extra_enemy(self):
        for _ in range(3):
            apply_upgrade(self.player, "pierce")
        self.assertEqual(self.player.pierce, 3)
        self.assertEqual(self.player.upgrades["pierce"], 3)


class RetroRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_bloom_and_overlay_are_renderable(self):
        source = pygame.Surface((W, H))
        source.fill((10, 10, 20))
        pygame.draw.circle(source, (0, 235, 255), (W // 2, H // 2), 30)
        bloom(source, W, H, 0.16)
        overlay = make_overlay(W, H)
        self.assertEqual(overlay.get_size(), (W, H))


if __name__ == "__main__":
    unittest.main()
