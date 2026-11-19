"""Точка входа."""
import asyncio
import logging

from game import Game

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(Game().run())
    except Exception:
        logging.getLogger("neuro_game").exception("Критическая ошибка игры")
        raise

