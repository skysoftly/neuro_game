"""Regression tests for the split Game mixins and stable public entry point."""
import unittest

from game import Game
from rendering import RenderingMixin
from networking import NetworkingMixin
from controls import ControlsMixin
from simulation import SimulationMixin


class GameModuleLayoutTests(unittest.TestCase):
    def test_game_keeps_all_feature_mixins(self):
        self.assertTrue(issubclass(Game, RenderingMixin))
        self.assertTrue(issubclass(Game, NetworkingMixin))
        self.assertTrue(issubclass(Game, ControlsMixin))
        self.assertTrue(issubclass(Game, SimulationMixin))

    def test_public_game_methods_remain_available(self):
        for name in (
            "run", "render", "draw_hud", "handle_events", "start_host",
            "join_server", "host_update", "update_waves", "build_snapshot",
            "set_display_mode", "toggle_borderless_fullscreen",
        ):
            with self.subTest(method=name):
                self.assertTrue(callable(getattr(Game, name, None)))


if __name__ == "__main__":
    unittest.main()
