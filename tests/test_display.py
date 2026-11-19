"""Regression tests for safe fullscreen/windowed display transitions."""
import unittest
from unittest.mock import patch

import pygame

from game import Game


class FakeWindow:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def set_fullscreen(self, desktop=False):
        self.calls.append(desktop)
        if self.fail_on == desktop:
            raise pygame.error("simulated SDL window transition failure")


class DisplayHarness:
    def __init__(self, window=None):
        self.screen = object()
        self.borderless_fullscreen = False
        self.persist_calls = 0
        self._display_window = window or FakeWindow()

    def persist(self):
        self.persist_calls += 1


class DisplayModeTests(unittest.TestCase):
    def test_many_toggles_reuse_existing_window_and_surface(self):
        window = FakeWindow()
        game = DisplayHarness(window)
        original_screen = game.screen
        ticks = [1000 + i * 300 for i in range(8)]

        with patch("pygame.time.get_ticks", side_effect=ticks), \\
             patch("pygame.display.set_mode") as set_mode, \\
             patch("pygame.display.get_surface", return_value=original_screen):
            for expected in (True, False, True, False, True, False, True, False):
                self.assertTrue(Game.toggle_borderless_fullscreen(game))
                self.assertEqual(game.borderless_fullscreen, expected)
                self.assertIs(game.screen, original_screen)

        self.assertEqual(window.calls, [True, False, True, False, True, False, True, False])
        self.assertEqual(set_mode.call_count, 0)
        self.assertEqual(game.persist_calls, 8)

    def test_rapid_duplicate_toggle_is_ignored(self):
        window = FakeWindow()
        game = DisplayHarness(window)

        with patch("pygame.time.get_ticks", side_effect=[1000, 1050]):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(Game.toggle_borderless_fullscreen(game))

        self.assertEqual(window.calls, [True])
        self.assertTrue(game.borderless_fullscreen)
        self.assertEqual(game.persist_calls, 1)

    def test_failed_transition_keeps_previous_state_and_surface(self):
        window = FakeWindow(fail_on=True)
        game = DisplayHarness(window)
        original_screen = game.screen

        with patch("pygame.time.get_ticks", return_value=1000), \\
             patch("pygame.display.get_surface", return_value=original_screen):
            self.assertFalse(Game.toggle_borderless_fullscreen(game))

        self.assertFalse(game.borderless_fullscreen)
        self.assertIs(game.screen, original_screen)
        self.assertEqual(game.persist_calls, 0)
        self.assertEqual(window.calls, [True])


if __name__ == "__main__":
    unittest.main()
