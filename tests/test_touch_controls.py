"""Regression tests for mobile touch controls."""
import unittest
from types import SimpleNamespace

import pygame
from pygame import Vector2 as V

from config import W, H
from controls import ControlsMixin


class TouchControlsTests(unittest.TestCase):
    def setUp(self):
        self.game = SimpleNamespace(
            state="play",
            paused=False,
            tutorial_active=False,
            intermission=False,
            touch_points={},
            touch_move=V(),
            touch_aim=None,
            touch_shoot=False,
            touch_dash_pressed=False,
            touch_pulse_pressed=False,
        )

    def event(self, event_type, finger_id, x, y):
        return SimpleNamespace(
            type=event_type,
            touch_id=1,
            finger_id=finger_id,
            x=x,
            y=y,
        )

    def test_left_finger_controls_movement(self):
        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERDOWN, 1, 0.2, 0.8)
        )
        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERMOTION, 1, 0.32, 0.8)
        )
        self.assertGreater(self.game.touch_move.x, 0.5)
        self.assertAlmostEqual(self.game.touch_move.y, 0.0, places=5)

        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERUP, 1, 0.32, 0.8)
        )
        self.assertEqual(self.game.touch_move, V())

    def test_right_finger_aims_and_fires(self):
        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERDOWN, 2, 0.72, 0.45)
        )
        self.assertTrue(self.game.touch_shoot)
        self.assertAlmostEqual(self.game.touch_aim.x, W * 0.72)
        self.assertAlmostEqual(self.game.touch_aim.y, H * 0.45)

        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERUP, 2, 0.72, 0.45)
        )
        self.assertFalse(self.game.touch_shoot)
        self.assertIsNone(self.game.touch_aim)

    def test_action_buttons_trigger_once(self):
        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERDOWN, 3, 0.77, 0.86)
        )
        self.assertTrue(self.game.touch_dash_pressed)
        self.assertFalse(self.game.touch_pulse_pressed)

        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERDOWN, 4, 0.91, 0.86)
        )
        self.assertTrue(self.game.touch_pulse_pressed)

    def test_touch_input_is_ignored_outside_gameplay(self):
        self.game.state = "menu"
        ControlsMixin._handle_touch_event(
            self.game, self.event(pygame.FINGERDOWN, 5, 0.2, 0.8)
        )
        self.assertEqual(self.game.touch_points, {})


if __name__ == "__main__":
    unittest.main()
