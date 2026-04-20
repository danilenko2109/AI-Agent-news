"""
Telethon listener: monitors all configured source channels in real time
and triggers the AI processing pipeline for each new message.
"""

import asyncio
import logging
import os
import re

from telethon import TelegramClient, events
from telethon.utils import get_peer_id

from core.processor import rewrite_post, build_image_url, format_telegram_message
from core.publisher import publish_post
from db import get_all_sources, get_duplicate_reason, mark_as_processed

logger = logging.getLogger(__name__)

API_ID = int(os.getenv("TELEGRAM_API_ID", 0))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE = os.getenv("TELEGRAM_PHONE", "")

MIN_TEXT_LENGTH = 80  # Ignore very short messages (captions, stickers, etc.)
SOURCES_REFRESH_SECONDS = int(os.getenv("SOURCES_REFRESH_SECONDS", 60))
BOT_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
TARGET_CHANNEL_RE = re.compile(r"^(?:@[A-Za-z][A-Za-z0-9_]{4,}|-100\d{6,})$")


def _extract_username(link: str) -> str:
    """Extract @username or t.me/username from a source link."""
    link = link.strip()
    link = re.sub(r"https?://(t\.me|telegram\.me)/", "", link)
    link = link.lstrip("@").split("/")[0]
    return link


def _normalize_chat_id(value: int | None) -> int | None:
    """Normalize Telegram IDs to Telethon peer-id format (-100... for channels)."""
    if value is None:
        return None
    value_str = str(value)
    if value_str.startswith("-100"):
        return value
    if value < 0:
        return value
    return int(f"-100{value}")


async def _process_message(
    message_text: str,
    source_post_id: str,
    channel_id: int,
    bot_token: str,
    target_channel_id: str,
    prompt_style: str,
):
    """Full pipeline: deduplicate → rewrite → publish."""
    logger.info(
        "received | source_post_id=%s channel_id=%s target=%s",
        source_post_id,
        channel_id,
        target_channel_id,
    )
    reason, is_dup = await get_duplicate_reason(source_post_id, channel_id, message_text)
    if is_dup:
        logger.info(
            "dedupe_skip | source_post_id=%s channel_id=%s reason=%s",
            source_post_id,
            channel_id,
            reason,
        )
        return

    result = await rewrite_post(message_text, prompt_style)
    if not result:
        logger.warning(
            "rewrite_failed | source_post_id=%s channel_id=%s",
            source_post_id,
            channel_id,
        )
        return
    logger.info(
        "rewritten | source_post_id=%s channel_id=%s title=%s",
        source_post_id,
        channel_id,
        result["title"][:80],
    )

    image_url = build_image_url(result["image_prompt"])
    html_message = format_telegram_message(result["title"], result["text"])

    success = await publish_post(bot_token, target_channel_id, html_message, image_url)
    if success:
        await mark_as_processed(source_post_id, channel_id, message_text)
        logger.info(
            "publish_success | source_post_id=%s channel_id=%s target=%s",
            source_post_id,
            channel_id,
            target_channel_id,
        )
    else:
        logger.error(
            "publish_failed | source_post_id=%s channel_id=%s target=%s",
            source_post_id,
            channel_id,
            target_channel_id,
        )


def _is_valid_source_link(source_link: str) -> bool:
    normalized = source_link.strip()
    return normalized.startswith("@") or "t.me/" in normalized


def _is_valid_target_channel(target_channel_id: str) -> bool:
    return bool(TARGET_CHANNEL_RE.match(target_channel_id.strip()))


def _is_valid_bot_token(token: str) -> bool:
    return bool(BOT_TOKEN_RE.match(token.strip()))


async def _build_watched_entities(
    client: TelegramClient,
) -> dict[int, list[dict]]:
    sources = await get_all_sources()
    source_map: dict[str, list[dict]] = {}

    for src in sources:
        source_link = src["source_tg_link"]
        if not _is_valid_source_link(source_link):
            logger.warning(
                "Skipping invalid source link for channel_id=%s: %s",
                src["channel_id"],
                source_link,
            )
            continue
        if not _is_valid_bot_token(src["bot_token"]):
            logger.warning(
                "Skipping source due to invalid bot token format | channel_id=%s",
                src["channel_id"],
            )
            continue
        if not _is_valid_target_channel(src["target_channel_id"]):
            logger.warning(
                "Skipping source due to invalid target channel format | channel_id=%s target=%s",
                src["channel_id"],
                src["target_channel_id"],
            )
            continue
        username = _extract_username(source_link)
        source_map.setdefault(username, []).append(src)

    watched_entities: dict[int, list[dict]] = {}
    for username, configs in source_map.items():
        try:
            entity = await client.get_entity(username)
            peer_id = _normalize_chat_id(get_peer_id(entity))
            watched_entities[peer_id] = configs
            logger.info(
                "watching_source | source=@%s entity_id=%s peer_id=%s routes=%d",
                username,
                entity.id,
                peer_id,
                len(configs),
            )
        except Exception as e:
            logger.error("Cannot resolve @%s: %s", username, e)
    return watched_entities


async def start_listener():
    """
    Build the Telethon client, subscribe to all source channels from the DB,
    and listen for new messages indefinitely.
    """
    client = TelegramClient("session/parser_session", API_ID, API_HASH)
    await client.start(phone=PHONE)
    logger.info("Telethon client started.")

    watched_entities: dict[int, list[dict]] = await _build_watched_entities(client)
    watched_lock = asyncio.Lock()
    if not watched_entities:
        logger.warning("No valid sources configured yet. Listener will keep refreshing.")

    async def refresh_sources_loop():
        while True:
            await asyncio.sleep(max(10, SOURCES_REFRESH_SECONDS))
            try:
                updated = await _build_watched_entities(client)
                async with watched_lock:
                    watched_entities.clear()
                    watched_entities.update(updated)
                logger.info("sources_refreshed | watched_entities=%d", len(updated))
            except Exception as e:
                logger.exception("sources_refresh_failed: %s", e)

    refresh_task = asyncio.create_task(refresh_sources_loop())

    @client.on(events.NewMessage())
    async def handler(event):
        sender_id = _normalize_chat_id(event.chat_id)
        async with watched_lock:
            configs = watched_entities.get(sender_id, [])
        if not configs:
            return

        # Extract text (message or photo caption)
        text = event.message.text or event.message.message or ""
        if len(text) < MIN_TEXT_LENGTH:
            logger.info(
                "Skipped short message from %s (length=%d, min=%d).",
                sender_id,
                len(text),
                MIN_TEXT_LENGTH,
            )
            return

        source_post_id = f"{sender_id}_{event.message.id}"
        logger.info(
            "incoming_message | source=%s source_post_id=%s routes=%d",
            sender_id,
            source_post_id,
            len(configs),
        )

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
