import random
import unittest

import pygame

from config import W, H, KINDS
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

    def test_five_boss_archetypes_exist_and_are_durable(self):
        for kind in ("boss", "boss_storm", "boss_hunter", "boss_void", "boss_siege"):
            self.assertIn(kind, KINDS)
            boss = Enemy(kind, (100, 100), 5)
            self.assertGreater(boss.max_hp, 500)

    def test_nine_regular_enemy_archetypes_exist(self):
        regular = {"chaser", "swarm", "shooter", "tank", "dasher",
                   "splitter", "mine", "orbiter", "bruiser"}
        self.assertEqual(len(regular), 9)
        self.assertTrue(regular.issubset(KINDS))

    def test_regular_enemy_colors_are_distinct(self):
        regular = ("chaser", "swarm", "shooter", "tank", "dasher",
                   "splitter", "mine", "orbiter", "bruiser")
        colors = [KINDS[kind]["col"] for kind in regular]
        self.assertEqual(len(colors), len(set(colors)))

    def test_shield_upgrade_uses_clear_name(self):
        shield = next(upgrade for upgrade in UPGRADES if upgrade["id"] == "pulse_power")
        self.assertIn("ЩИТ", shield["name"])

    def test_enemy_hp_scaling_is_noticeable(self):
        early = Enemy("chaser", (100, 100), 1)
        late = Enemy("chaser", (100, 100), 10)
        self.assertGreaterEqual(late.max_hp, early.max_hp * 2)

    def test_obsolete_upgrades_are_removed(self):
        ids = {upgrade["id"] for upgrade in UPGRADES}
        self.assertNotIn("combo", ids)
        self.assertNotIn("score_gain", ids)
        self.assertEqual(len(ids), len(UPGRADES))

    def test_player_has_local_damage_timer(self):
        self.assertEqual(self.player.hurt_t, 0.0)

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
        self.assertAlmostEqual(self.player.dmg, 1.09)

    def test_damage_upgrade_has_a_hard_cap(self):
        for _ in range(8):
            apply_upgrade(self.player, "dmg")
        self.assertEqual(self.player.upgrades["dmg"], 4)
        self.assertAlmostEqual(self.player.dmg, 1.36)

    def test_upgrade_pool_has_many_distinct_build_options(self):
        self.assertGreaterEqual(len(UPGRADES), 16)
        self.assertIn("pulse_power", {u["id"] for u in UPGRADES})
        self.assertIn("multishot", {u["id"] for u in UPGRADES})

    def test_shield_is_available_and_starts_empty(self):
        self.assertEqual(self.player.shield_t, 0.0)
        self.assertEqual(self.player.shield_hits, 0)

    def test_defensive_upgrades_have_reasonable_caps(self):
        for _ in range(5):
            apply_upgrade(self.player, "armor")
            apply_upgrade(self.player, "pulse_power")
        self.assertEqual(self.player.armor, 2)
        self.assertEqual(self.player.pulse_power, 1.5)

    def test_new_combat_upgrades_change_stats(self):
        apply_upgrade(self.player, "pulse_power")
        apply_upgrade(self.player, "crit")
        apply_upgrade(self.player, "multishot")
        self.assertGreater(self.player.pulse_power, 1.0)
        self.assertGreater(self.player.crit, 0.0)
        self.assertEqual(self.player.multishot, 1)

    def test_roll_excludes_upgrades_at_their_cap(self):
        self.player.upgrades["dmg"] = 4
        result = roll_upgrades(random.Random(2), 3, self.player)
        self.assertNotIn("dmg", result)

    def test_lifesteal_has_one_stack_cap(self):
        for _ in range(3):
            apply_upgrade(self.player, "lifesteal")
        self.assertEqual(self.player.lifesteal, 1)
        self.assertEqual(self.player.upgrades["lifesteal"], 1)

    def test_pierce_has_two_stack_cap(self):
        for _ in range(3):
            apply_upgrade(self.player, "pierce")
        self.assertEqual(self.player.pierce, 2)
        self.assertEqual(self.player.upgrades["pierce"], 2)


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

    def test_bloom_reuses_preallocated_surfaces(self):
        source = pygame.Surface((W, H)).convert()
        small = pygame.Surface((W // 8, H // 8)).convert()
        full = pygame.Surface((W, H)).convert()
        source.fill((12, 18, 24))
        bloom(source, W, H, 0.08, small, full)
        self.assertEqual(small.get_size(), (W // 8, H // 8))
        self.assertEqual(full.get_size(), (W, H))


if __name__ == "__main__":
    unittest.main()
