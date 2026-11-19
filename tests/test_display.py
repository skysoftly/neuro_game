"""Regression tests for safe fullscreen/windowed display transitions."""
import unittest
from unittest.mock import patch

import pygame

from game import Game


class DisplayHarness:
    def __init__(self):
        self.screen = object()
        self.borderless_fullscreen = False
        self.persist_calls = 0

    def persist(self):
        self.persist_calls += 1

    def set_display_mode(self, fullscreen):
        return Game.set_display_mode(self, fullscreen)


class DisplayModeTests(unittest.TestCase):
    def test_repeated_f11_style_toggles_switch_both_directions(self):
        game = DisplayHarness()
        windowed = object()
        fullscreen = object()

        with patch("pygame.display.set_mode", side_effect=[fullscreen, windowed]) as set_mode, \
             patch("pygame.time.get_ticks", side_effect=[1000, 1300]):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertTrue(game.borderless_fullscreen)
            self.assertIs(game.screen, fullscreen)

            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(game.borderless_fullscreen)
            self.assertIs(game.screen, windowed)

        self.assertEqual(set_mode.call_count, 2)
        self.assertEqual(game.persist_calls, 2)
        self.assertEqual(set_mode.call_args_list[0].args[1], pygame.SCALED | pygame.FULLSCREEN | pygame.NOFRAME)
        self.assertEqual(set_mode.call_args_list[1].args[1], pygame.SCALED | pygame.RESIZABLE)

    def test_rapid_duplicate_toggle_is_ignored(self):
        game = DisplayHarness()
        screen = object()

        with patch("pygame.display.set_mode", return_value=screen) as set_mode, \
             patch("pygame.time.get_ticks", side_effect=[1000, 1050]):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(Game.toggle_borderless_fullscreen(game))

        self.assertEqual(set_mode.call_count, 1)
        self.assertTrue(game.borderless_fullscreen)
        self.assertEqual(game.persist_calls, 1)

    def test_borderless_mode_failure_does_not_use_exclusive_fallback(self):
        game = DisplayHarness()
        original_screen = game.screen

        with patch("pygame.display.set_mode",
                   side_effect=pygame.error("scaled unsupported")) as set_mode:
            self.assertFalse(Game.set_display_mode(game, True))

        self.assertIs(game.screen, original_screen)
        self.assertEqual(set_mode.call_count, 1)

    def test_failed_transition_keeps_previous_state(self):
        game = DisplayHarness()
        original_screen = game.screen

        with patch("pygame.display.set_mode",
                   side_effect=pygame.error("display unavailable")), \
             patch("pygame.time.get_ticks", return_value=1000):
            self.assertFalse(Game.toggle_borderless_fullscreen(game))

        self.assertFalse(game.borderless_fullscreen)
        self.assertIs(game.screen, original_screen)
        self.assertEqual(game.persist_calls, 0)


if __name__ == "__main__":
    unittest.main()
