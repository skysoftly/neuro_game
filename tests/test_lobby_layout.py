"""Regression tests for non-overlapping multiplayer lobby controls."""
import unittest

import pygame

from config import (
    H,
    LOBBY_HOST_ACTION_RECT,
    LOBBY_CLIENT_STATUS_RECT,
    LOBBY_CLIENT_ACTION_RECT,
)


class LobbyLayoutTests(unittest.TestCase):
    def test_client_status_and_ready_button_are_side_by_side(self):
        status = pygame.Rect(*LOBBY_CLIENT_STATUS_RECT)
        action = pygame.Rect(*LOBBY_CLIENT_ACTION_RECT)

        self.assertFalse(status.colliderect(action))
        self.assertLess(status.right, action.left)
        self.assertEqual(status.top, action.top)
        self.assertEqual(status.bottom, action.bottom)

    def test_lobby_actions_leave_space_for_back_button(self):
        back = pygame.Rect(1280 // 2 - 150, H - 66, 300, 42)
        host_action = pygame.Rect(*LOBBY_HOST_ACTION_RECT)
        client_action = pygame.Rect(*LOBBY_CLIENT_ACTION_RECT)
        status = pygame.Rect(*LOBBY_CLIENT_STATUS_RECT)

        self.assertFalse(host_action.colliderect(back))
        self.assertFalse(client_action.colliderect(back))
        self.assertFalse(status.colliderect(back))

    def test_host_action_remains_centered(self):
        action = pygame.Rect(*LOBBY_HOST_ACTION_RECT)
        self.assertEqual(action.centerx, 1280 // 2)


if __name__ == "__main__":
    unittest.main()
