"""
Entry point: starts both the Telethon listener and the aiogram admin bot
concurrently using asyncio.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    # 1. Init DB
    from db import init_db
    await init_db()

    # 2. Start Telethon listener (returns client after login)
    from parser.listener import start_listener
    telethon_client = await start_listener()

    # 3. Start aiogram admin bot
    from bot.main_bot import create_bot_and_dispatcher
    bot, dp = create_bot_and_dispatcher()

    logger.info("🚀 AI News Agent started.")

    # Run both concurrently
    await asyncio.gather(
        telethon_client.run_until_disconnected(),
        dp.start_polling(bot, handle_signals=False),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
