from __future__ import annotations

import asyncio

from app.bot.main_bot import run_admin_bot
from app.core.deduplicator import Deduplicator
from app.core.processor import PostProcessor
from app.database import Database
from app.listeners.telethon_listener import TelethonListener
from app.logger import logger, setup_logger
from app.services.gemini_service import GeminiService
from app.services.image_service import ImageService
from app.services.telegram_publisher import TelegramPublisher
from app.utils import setup_signals


async def main() -> None:
    setup_logger()

    db = Database()
    await db.init()

    processor = PostProcessor(
        gemini=GeminiService(),
        image_service=ImageService(),
        deduplicator=Deduplicator(db),
        publisher=TelegramPublisher(),
    )
    listener = TelethonListener(db=db, processor=processor)

    tasks = [
        asyncio.create_task(run_admin_bot(db), name="admin_bot"),
        asyncio.create_task(listener.start(), name="telethon_listener"),
    ]

    def stop_callback() -> None:
        logger.info("Shutting down services...")
        for task in tasks:
            if not task.done():
                task.cancel()

    setup_signals(asyncio.get_running_loop(), stop_callback)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down services...")
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await listener.stop()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
