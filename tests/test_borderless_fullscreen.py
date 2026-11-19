"""Regression tests for desktop-sized borderless display mode."""
import unittest
from unittest.mock import patch

import pygame

from game import Game


class BorderlessFullscreenTests(unittest.TestCase):
    def setUp(self):
        self.game = Game.__new__(Game)
        self.game.screen = object()

    def test_borderless_mode_uses_desktop_fullscreen_flags(self):
        expected_screen = object()
        with patch.object(pygame.display, "set_mode", return_value=expected_screen) as set_mode:
            self.assertTrue(self.game.set_display_mode(True))

        size, flags = set_mode.call_args.args
        self.assertEqual(size, (1280, 720))
        self.assertTrue(flags & pygame.FULLSCREEN)
        self.assertTrue(flags & pygame.SCALED)
        self.assertTrue(flags & pygame.NOFRAME)
        self.assertIs(self.game.screen, expected_screen)

    def test_borderless_failure_does_not_fall_back_to_exclusive_fullscreen(self):
        previous_screen = self.game.screen
        with patch.object(
            pygame.display, "set_mode",
            side_effect=pygame.error("desktop fullscreen unavailable"),
        ) as set_mode:
            self.assertFalse(self.game.set_display_mode(True))

        self.assertEqual(set_mode.call_count, 1)
        self.assertIs(self.game.screen, previous_screen)

    def test_windowed_mode_can_fall_back_without_scaled_flag(self):
        expected_screen = object()
        with patch.object(
            pygame.display, "set_mode",
            side_effect=[pygame.error("scaled unavailable"), expected_screen],
        ) as set_mode:
            self.assertTrue(self.game.set_display_mode(False))

        self.assertEqual(set_mode.call_count, 2)
        self.assertEqual(set_mode.call_args.args[0], (1280, 720))
        self.assertFalse(set_mode.call_args.args[1] & pygame.FULLSCREEN)
        self.assertIs(self.game.screen, expected_screen)


if __name__ == "__main__":
    unittest.main()
