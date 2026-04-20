"""
Publisher: sends a rewritten post (text + image) to a target Telegram channel
using the channel's own bot token via aiogram Bot.
"""

import asyncio
import logging
import os

import aiohttp
from aiogram import Bot
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)

POST_DELAY = int(os.getenv("POST_DELAY", 5))


async def _download_image(url: str, timeout: int = 10) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logger.warning("Image download failed: %s", e)
    return None


async def publish_post(
    bot_token: str,
    target_channel_id: str,
    message_html: str,
    image_url: str | None = None,
) -> bool:
    """
    Publish a post to a Telegram channel.
    Returns True on success, False on failure.
    """
    bot = Bot(token=bot_token)
    try:
        if image_url:
            image_bytes = await _download_image(image_url)
            if image_bytes:
                from aiogram.types import BufferedInputFile
                photo = BufferedInputFile(image_bytes, filename="news.jpg")
                await bot.send_photo(
                    chat_id=target_channel_id,
                    photo=photo,
                    caption=message_html,
                    parse_mode=ParseMode.HTML,
                )
                await asyncio.sleep(POST_DELAY)
                return True

        # Fallback: text-only post
        await bot.send_message(
            chat_id=target_channel_id,
            text=message_html,
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(POST_DELAY)
        return True

    except Exception as e:
        logger.error("Publish error to %s: %s", target_channel_id, e)
        return False
    finally:
        await bot.session.close()
