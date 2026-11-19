"""Regression tests for borderless fullscreen and logical-frame scaling."""
import unittest
from unittest.mock import patch

import pygame

from game import Game


class FakeWindow:
    def __init__(self):
        self.position = (140, 90)
        self.size = (1280, 720)
        self.display_index = 0


class DisplayHarness:
    def __init__(self):
        self.screen = pygame.Surface((1280, 720))
        self.display_surface = pygame.Surface((1280, 720))
        self.borderless_fullscreen = False
        self.persist_calls = 0
        self._windowed_geometry = None
        self.window = FakeWindow()

    def persist(self):
        self.persist_calls += 1

    def set_display_mode(self, fullscreen):
        return Game.set_display_mode(self, fullscreen)


class DisplayModeTests(unittest.TestCase):
    def _mock_display(self, game):
        def set_mode(size, flags):
            game.display_surface = pygame.Surface(size)
            game.window.size = tuple(size)
            if flags == pygame.NOFRAME:
                game.window.position = (0, 0)
            return game.display_surface

        return (
            patch("pygame.display.get_desktop_sizes", return_value=[(1920, 1080)]),
            patch("pygame.display.set_mode", side_effect=set_mode),
            patch("pygame._sdl2.video.Window.from_display_module", return_value=game.window),
        )

    def test_fullscreen_uses_desktop_size_and_restores_window(self):
        game = DisplayHarness()
        mocks = self._mock_display(game)
        with mocks[0], mocks[1] as set_mode, mocks[2]:
            self.assertTrue(Game.set_display_mode(game, True))
            self.assertEqual(game.display_surface.get_size(), (1920, 1080))
            self.assertEqual(game.window.position, (0, 0))
            self.assertEqual(set_mode.call_args.args, ((1920, 1080), pygame.NOFRAME))

            self.assertTrue(Game.set_display_mode(game, False))
            self.assertEqual(game.display_surface.get_size(), (1280, 720))
            self.assertEqual(game.window.position, (140, 90))
            self.assertIsNone(game._windowed_geometry)

    def test_repeated_toggles_keep_restoring_original_geometry(self):
        game = DisplayHarness()
        mocks = self._mock_display(game)
        with mocks[0], mocks[1], mocks[2]:
            for _ in range(6):
                self.assertTrue(Game.set_display_mode(game, True))
                self.assertEqual(game.display_surface.get_size(), (1920, 1080))
                self.assertTrue(Game.set_display_mode(game, False))
                self.assertEqual(game.display_surface.get_size(), (1280, 720))
                self.assertEqual(game.window.position, (140, 90))

    def test_toggle_persists_only_after_success(self):
        game = DisplayHarness()
        mocks = self._mock_display(game)
        with mocks[0], mocks[1], mocks[2], patch(
            "pygame.time.get_ticks", side_effect=[1000, 1300]
        ):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertTrue(game.borderless_fullscreen)
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(game.borderless_fullscreen)
        self.assertEqual(game.persist_calls, 2)

    def test_rapid_duplicate_toggle_is_ignored(self):
        game = DisplayHarness()
        mocks = self._mock_display(game)
        with mocks[0], mocks[1], mocks[2], patch(
            "pygame.time.get_ticks", side_effect=[1000, 1050]
        ):
            self.assertTrue(Game.toggle_borderless_fullscreen(game))
            self.assertFalse(Game.toggle_borderless_fullscreen(game))
        self.assertTrue(game.borderless_fullscreen)
        self.assertEqual(game.persist_calls, 1)


if __name__ == "__main__":
    unittest.main()
