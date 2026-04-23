from __future__ import annotations

import asyncio

from telethon import TelegramClient, events

from app.config import settings
from app.core.processor import PostProcessor
from app.database import Database
from app.logger import logger


class TelethonListener:
    def __init__(self, db: Database, processor: PostProcessor) -> None:
        self.db = db
        self.processor = processor
        self.client = TelegramClient(settings.session_path, settings.tg_api_id, settings.tg_api_hash)
        self._sources_map: dict[str, list] = {}
        self._refresh_task: asyncio.Task[None] | None = None

    async def _refresh_sources_loop(self) -> None:
        while True:
            self._sources_map = await self.db.get_sources_map()
            logger.debug("Loaded {} source channels", len(self._sources_map))
            await asyncio.sleep(30)

    async def start(self) -> None:
        await self.client.connect()

        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event: events.NewMessage.Event) -> None:
            message = event.message
            if not message or not message.raw_text or message.forward:
                return

            source_key = None
            if event.chat and getattr(event.chat, "username", None):
                source_key = f"@{event.chat.username}"
            elif event.chat_id:
                source_key = str(event.chat_id)

            if not source_key or source_key not in self._sources_map:
                return

            for channel in self._sources_map[source_key]:
                try:
                    await self.processor.process_and_publish(channel, message.raw_text)
                except Exception as exc:
                    logger.error("Processor error: {}", exc)

        self._refresh_task = asyncio.create_task(self._refresh_sources_loop())
        logger.info("Telethon listener started")

        while True:
            try:
                await self.client.run_until_disconnected()
            except asyncio.CancelledError:
                logger.info("Listener stopped")
                raise
            except Exception as exc:
                logger.error("Telethon disconnected: {}. Reconnecting...", exc)
                await asyncio.sleep(3)
                await self.client.connect()

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
        await self.client.disconnect()
        logger.info("Listener stopped")
