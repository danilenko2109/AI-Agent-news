from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ModuleNotFoundError:  # pragma: no cover
    def retry(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

from app.logger import logger


class TelegramPublisher:
    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3), reraise=True)
    async def publish(self, bot_token: str, channel_id: str, text: str, image_path: Path | None = None) -> None:
        bot = Bot(token=bot_token)
        try:
            if image_path and image_path.exists():
                photo = FSInputFile(str(image_path))
                await bot.send_photo(chat_id=channel_id, photo=photo, caption=text)
            else:
                await bot.send_message(chat_id=channel_id, text=text)
            logger.info("Published post to {}", channel_id)
        except Exception as exc:
            logger.error("Publish failed: {}", exc)
            raise
        finally:
            await bot.session.close()
