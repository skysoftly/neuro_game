import unittest

from config import (
    MAX_PLAYERS, boss_kind_for_wave, enemy_scaling, wave_enemy_count,
)
from entities import Enemy


class EndlessDifficultyTests(unittest.TestCase):
    def test_wave_scaling_keeps_growing_past_old_soft_cap(self):
        early = Enemy("chaser", (0, 0), 10)
        late = Enemy("chaser", (0, 0), 100)
        self.assertGreater(late.max_hp, early.max_hp)

    def test_wave_number_has_no_small_hard_limit(self):
        self.assertGreater(wave_enemy_count(10_000, 1), 0)
        self.assertEqual(boss_kind_for_wave(10_000), "boss")
        self.assertEqual(boss_kind_for_wave(10_005), "boss_storm")

    def test_bosses_continue_cycling_every_five_waves(self):
        self.assertEqual(
            [boss_kind_for_wave(wave) for wave in (5, 10, 15, 20, 25)],
            ["boss", "boss_storm", "boss_hunter", "boss_void", "boss_siege"],
        )
        self.assertEqual(boss_kind_for_wave(30), "boss")
        self.assertEqual(boss_kind_for_wave(2), "boss_minor")
        self.assertIsNone(boss_kind_for_wave(3))

    def test_more_players_increase_enemy_count_and_durability(self):
        self.assertEqual(MAX_PLAYERS, 12)
        self.assertGreater(wave_enemy_count(10, 4), wave_enemy_count(10, 1))
        solo = Enemy("chaser", (0, 0), 10, 1)
        co_op = Enemy("chaser", (0, 0), 10, 4)
        self.assertGreater(co_op.max_hp, solo.max_hp)
        self.assertGreater(co_op.spd, solo.spd)

    def test_player_scaling_is_clamped_to_lobby_capacity(self):
        at_capacity = enemy_scaling(20, MAX_PLAYERS)
        beyond_capacity = enemy_scaling(20, MAX_PLAYERS + 100)
        self.assertEqual(at_capacity, beyond_capacity)

    def test_fifth_wave_boss_is_less_durable_than_old_version(self):
        boss = Enemy("boss", (0, 0), 5)
        self.assertLess(boss.max_hp, 450)
        self.assertGreater(boss.max_hp, 350)


if __name__ == "__main__":
    unittest.main()
