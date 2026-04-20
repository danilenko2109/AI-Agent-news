"""
Telethon listener: monitors all configured source channels in real time
and triggers the AI processing pipeline for each new message.
"""

import asyncio
import logging
import os
import re

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from core.processor import rewrite_post, build_image_url, format_telegram_message
from core.publisher import publish_post
from db import get_all_sources, is_duplicate, mark_as_processed

logger = logging.getLogger(__name__)

API_ID = int(os.getenv("TELEGRAM_API_ID", 0))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE = os.getenv("TELEGRAM_PHONE", "")

MIN_TEXT_LENGTH = 80  # Ignore very short messages (captions, stickers, etc.)


def _extract_username(link: str) -> str:
    """Extract @username or t.me/username from a source link."""
    link = link.strip()
    link = re.sub(r"https?://(t\.me|telegram\.me)/", "", link)
    link = link.lstrip("@").split("/")[0]
    return link


async def _process_message(
    message_text: str,
    source_post_id: str,
    channel_id: int,
    bot_token: str,
    target_channel_id: str,
    prompt_style: str,
):
    """Full pipeline: deduplicate → rewrite → publish."""
    if await is_duplicate(source_post_id, channel_id, message_text):
        logger.debug("Duplicate detected, skipping: %s", source_post_id)
        return

    result = await rewrite_post(message_text, prompt_style)
    if not result:
        return

    image_url = build_image_url(result["image_prompt"])
    html_message = format_telegram_message(result["title"], result["text"])

    success = await publish_post(bot_token, target_channel_id, html_message, image_url)
    if success:
        await mark_as_processed(source_post_id, channel_id, message_text)
        logger.info("✅ Published to %s | %s", target_channel_id, result["title"])


async def start_listener():
    """
    Build the Telethon client, subscribe to all source channels from the DB,
    and listen for new messages indefinitely.
    """
    client = TelegramClient("session/parser_session", API_ID, API_HASH)
    await client.start(phone=PHONE)
    logger.info("Telethon client started.")

    # Load sources from DB and map username → list of channel configs
    sources = await get_all_sources()
    if not sources:
        logger.warning("No sources configured. Add sources via the admin bot.")
        return client

    # Group by source link for efficient handler dispatch
    source_map: dict[str, list[dict]] = {}
    for src in sources:
        username = _extract_username(src["source_tg_link"])
        source_map.setdefault(username, []).append(src)

    logger.info("Listening to %d source channels.", len(source_map))

    # Resolve entity IDs for all sources
    watched_entities: dict[int, list[dict]] = {}
    for username, configs in source_map.items():
        try:
            entity = await client.get_entity(username)
            watched_entities[entity.id] = configs
            logger.info("Subscribed to: @%s (id=%d)", username, entity.id)
        except Exception as e:
            logger.error("Cannot resolve @%s: %s", username, e)

    @client.on(events.NewMessage())
    async def handler(event):
        sender_id = event.chat_id
        configs = watched_entities.get(sender_id)
        if not configs:
            return

        # Extract text (message or photo caption)
        text = event.message.text or event.message.message or ""
        if len(text) < MIN_TEXT_LENGTH:
            return

        source_post_id = f"{sender_id}_{event.message.id}"

        for cfg in configs:
            asyncio.create_task(
                _process_message(
                    message_text=text,
                    source_post_id=source_post_id,
                    channel_id=cfg["channel_id"],
                    bot_token=cfg["bot_token"],
                    target_channel_id=cfg["target_channel_id"],
                    prompt_style=cfg["prompt_style"],
                )
            )

    return client
