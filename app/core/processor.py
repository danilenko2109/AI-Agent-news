from __future__ import annotations

from app.core.deduplicator import Deduplicator
from app.logger import logger
from app.models import ChannelConfig
from app.services.gemini_service import GeminiService
from app.services.image_service import ImageService
from app.services.telegram_publisher import TelegramPublisher


class PostProcessor:
    def __init__(
        self,
        gemini: GeminiService,
        image_service: ImageService,
        deduplicator: Deduplicator,
        publisher: TelegramPublisher,
    ) -> None:
        self.gemini = gemini
        self.image_service = image_service
        self.deduplicator = deduplicator
        self.publisher = publisher

    async def process_and_publish(self, channel: ChannelConfig, source_message: str) -> bool:
        text = source_message.strip()
        if not text:
            logger.debug("Empty message skipped")
            return False

        if await self.deduplicator.is_duplicate(text):
            logger.info("Duplicate skipped")
            return False

        rewritten = await self.gemini.rewrite(text)
        prompt = await self.gemini.generate_image_prompt(rewritten)

        image_path = None
        try:
            image_path = await self.image_service.generate(prompt)
        except Exception as exc:
            logger.error("Image generation failed completely: {}", exc)

        try:
            await self.publisher.publish(
                bot_token=channel.bot_token,
                channel_id=channel.target_channel_id,
                text=rewritten,
                image_path=image_path,
            )
        except Exception:
            if image_path is not None:
                await self.publisher.publish(
                    bot_token=channel.bot_token,
                    channel_id=channel.target_channel_id,
                    text=rewritten,
                    image_path=None,
                )
            else:
                raise

        await self.deduplicator.remember(text)
        return True
