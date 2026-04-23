from __future__ import annotations

import asyncio
import signal

from app.bot.main_bot import run_admin_bot
from app.core.deduplicator import Deduplicator
from app.core.processor import PostProcessor
from app.database import Database
from app.listeners.telethon_listener import TelethonListener
from app.logger import setup_logger
from app.services.gemini_service import GeminiService
from app.services.image_service import ImageService
from app.services.telegram_publisher import TelegramPublisher


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

    listener_task = asyncio.create_task(listener.start())
    bot_task = asyncio.create_task(run_admin_bot(db))

    stop_event = asyncio.Event()

    def _stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    await stop_event.wait()
    await listener.stop()
    listener_task.cancel()
    bot_task.cancel()
    await asyncio.gather(listener_task, bot_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
