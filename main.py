"""Точка входа."""
import logging
import os
import sys

from game import Game

if __name__ == "__main__":
    # CI smoke test: initialize the real game without entering the endless loop.
    # SDL dummy drivers let Windows CI verify the packaged runtime without a monitor/audio device.
    if "--smoke-test" in sys.argv:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        import pygame
        Game()
        pygame.quit()
        raise SystemExit(0)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        Game().run()
    except Exception:
        logging.getLogger("neuro_game").exception("Критическая ошибка игры")
        raise

