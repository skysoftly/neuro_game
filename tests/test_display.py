"""Regression tests for SDL desktop-fullscreen transitions."""
import unittest
from unittest.mock import patch

import pygame

from game import Game


class FakeWindow:
    def __init__(self):
        self.position = (140, 90)
        self.size = (1280, 720)
        self.borderless = False
        self.display_index = 0
        self.fullscreen = False
        self.calls = []

    def set_fullscreen(self, desktop=False):
        self.calls.append(("fullscreen", desktop))
        if not desktop:
            raise AssertionError("Expected desktop fullscreen")
        self.fullscreen = True
        self.position = (0, 0)
        self.size = (1920, 1080)
        self.borderless = True

    def set_windowed(self):
        self.calls.append(("windowed",))
        self.fullscreen = False


class DisplayHarness:
    def __init__(self, window=None):
        self.screen = object()
        self.borderless_fullscreen = False
        self.persist_calls = 0
        self._display_window = window or FakeWindow()
        self._windowed_geometry = None

    def persist(self):
        self.persist_calls += 1


class DisplayModeTests(unittest.TestCase):
    def test_repeated_toggles_restore_exact_window_geometry(self):
        window = FakeWindow()
        game = DisplayHarness(window)
        original_screen = game.screen
        ticks = [1000 + i * 300 for i in range(12)]

        with (
            patch("pygame.time.get_ticks", side_effect=ticks),
            patch("pygame.display.get_surface", return_value=original_screen),
            patch("pygame.display.set_mode") as set_mode,
        ):
            for expected in (True, False) * 6:
                self.assertTrue(Game.set_display_mode(game, expected))
                self.assertIs(game.screen, original_screen)
                if expected:
                    self.assertTrue(window.fullscreen)
                    self.assertEqual(window.size, (1920, 1080))
                    self.assertEqual(window.calls[-1], ("fullscreen", True))
                else:
                    self.assertFalse(window.fullscreen)
                    self.assertEqual(window.position, (140, 90))
                    self.assertEqual(window.size, (1280, 720))
                    self.assertFalse(window.borderless)
                    self.assertEqual(window.calls[-1], ("windowed",))

        self.assertEqual(set_mode.call_count, 0)
        self.assertIsNone(game._windowed_geometry)

    def test_toggle_persists_only_after_success(self):
        game = DisplayHarness()
        with patch("pygame.time.get_ticks", side_effect=[1000, 1300]), patch(
            "pygame.display.get_surface", return_value=game.screen
        ):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertTrue(game.borderless_fullscreen)
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(game.borderless_fullscreen)
        self.assertEqual(game.persist_calls, 2)

    def test_rapid_duplicate_toggle_is_ignored(self):
        game = DisplayHarness()
        with patch("pygame.time.get_ticks", side_effect=[1000, 1050]), patch(
            "pygame.display.get_surface", return_value=game.screen
        ):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(Game.toggle_borderless_fullscreen(game))
        self.assertTrue(game.borderless_fullscreen)
        self.assertEqual(game.persist_calls, 1)

    def test_failed_enter_rolls_back_window_and_config(self):
        class BrokenWindow(FakeWindow):
            def set_fullscreen(self, desktop=False):
                super().set_fullscreen(desktop)
                raise pygame.error("simulated fullscreen failure")

        window = BrokenWindow()
        game = DisplayHarness(window)
        with patch("pygame.time.get_ticks", return_value=1000):
            self.assertFalse(Game.toggle_borderless_fullscreen(game))

        self.assertFalse(window.fullscreen)
        self.assertEqual(window.position, (140, 90))
        self.assertEqual(window.size, (1280, 720))
        self.assertFalse(window.borderless)
        self.assertFalse(game.borderless_fullscreen)
        self.assertIsNone(game._windowed_geometry)
        self.assertEqual(game.persist_calls, 0)


if __name__ == "__main__":
    unittest.main()
