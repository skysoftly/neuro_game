"""Точка входа для desktop и WebAssembly."""
import asyncio
import logging

from game import Game


async def main():
    try:
        await Game().run()
    except Exception:
        logging.getLogger("neuro_game").exception("Критическая ошибка игры")
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(main())
