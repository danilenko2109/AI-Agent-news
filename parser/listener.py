"""
Telethon listener: monitors all configured source channels in real time
and triggers the AI processing pipeline for each new message.
"""

import asyncio
import logging
import os
import re
from collections import defaultdict

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
DEBUG_TEXT_LIMIT = 180
LAST_LISTENER_EVENT: dict = {}
LISTENER_SOURCE_SNAPSHOT: list[dict] = []


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


def _normalize_username(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    normalized = re.sub(r"^https?://(t\.me|telegram\.me)/", "", normalized)
    normalized = normalized.lstrip("@").split("/")[0].strip().lower()
    if not normalized:
        return None
    return normalized


def normalize_source_key(value) -> str | None:
    """Return unified comparable source key for username/entity/id values."""
    if value is None:
        return None

    if isinstance(value, str):
        username = _normalize_username(value)
        if username:
            return f"username:{username}"
        try:
            value = int(value.strip())
        except Exception:
            return None

    if isinstance(value, int):
        peer_id = _normalize_chat_id(value)
        return f"peer:{peer_id}" if peer_id is not None else None

    username = _normalize_username(getattr(value, "username", None))
    if username:
        return f"username:{username}"

    entity_id = getattr(value, "id", None)
    if entity_id is not None:
        return f"id:{int(entity_id)}"

    try:
        peer_id = _normalize_chat_id(get_peer_id(value))
        if peer_id is not None:
            return f"peer:{peer_id}"
    except Exception:
        return None
    return None


def _build_source_keys(raw_source_link: str, entity=None) -> set[str]:
    keys: set[str] = set()
    source_key = normalize_source_key(raw_source_link)
    if source_key:
        keys.add(source_key)

    username = _normalize_username(raw_source_link)
    if username:
        keys.add(f"username:{username}")

    if entity is not None:
        username_key = normalize_source_key(getattr(entity, "username", None))
        if username_key:
            keys.add(username_key)
        entity_id = getattr(entity, "id", None)
        if entity_id is not None:
            keys.add(f"id:{int(entity_id)}")
            peer_from_entity_id = _normalize_chat_id(int(entity_id))
            if peer_from_entity_id is not None:
                keys.add(f"peer:{peer_from_entity_id}")
        try:
            entity_peer_id = _normalize_chat_id(get_peer_id(entity))
            if entity_peer_id is not None:
                keys.add(f"peer:{entity_peer_id}")
        except Exception:
            pass
    return keys


def get_listener_debug_snapshot() -> dict:
    """Expose listener runtime state for /diagnose."""
    return {
        "last_event": dict(LAST_LISTENER_EVENT),
        "known_sources": [dict(item) for item in LISTENER_SOURCE_SNAPSHOT],
    }


def _truncate_text(text: str, limit: int = DEBUG_TEXT_LIMIT) -> str:
    cleaned = (text or "").replace("\n", " ").strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}..."


def _extract_event_keys(event) -> tuple[set[str], int | None]:
    keys: set[str] = set()

    event_chat_id = _normalize_chat_id(getattr(event, "chat_id", None))
    if event_chat_id is not None:
        keys.add(f"peer:{event_chat_id}")
        keys.add(f"id:{abs(int(event_chat_id))}")

    sender_id = _normalize_chat_id(getattr(event, "sender_id", None))
    if sender_id is not None:
        keys.add(f"peer:{sender_id}")
        keys.add(f"id:{abs(int(sender_id))}")

    peer = getattr(getattr(event, "message", None), "peer_id", None)
    if peer is not None:
        try:
            peer_id = _normalize_chat_id(get_peer_id(peer))
            if peer_id is not None:
                keys.add(f"peer:{peer_id}")
                keys.add(f"id:{abs(int(peer_id))}")
        except Exception:
            pass

    chat = getattr(event, "chat", None)
    chat_username = _normalize_username(getattr(chat, "username", None))
    if chat_username:
        keys.add(f"username:{chat_username}")

    return keys, event_chat_id


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
) -> tuple[dict[str, list[dict]], list[dict]]:
    sources = await get_all_sources()
    watched_entities: dict[str, list[dict]] = defaultdict(list)
    source_snapshot: list[dict] = []

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
        try:
            username = _extract_username(source_link)
            entity = await client.get_entity(username)
            source_keys = _build_source_keys(source_link, entity)
            for key in source_keys:
                watched_entities[key].append(src)
            resolved_peer = _normalize_chat_id(get_peer_id(entity))
            resolved_username = _normalize_username(getattr(entity, "username", None))
            resolved_id = getattr(entity, "id", None)
            source_snapshot.append(
                {
                    "channel_id": src["channel_id"],
                    "source_tg_link": source_link,
                    "source_username": _normalize_username(source_link),
                    "resolved_peer_id": resolved_peer,
                    "source_keys": sorted(source_keys),
                    "resolved_id": resolved_id,
                    "resolved_username": resolved_username,
                }
            )
            logger.info(
                "watching_source | source=@%s entity_id=%s peer_id=%s keys=%s",
                username,
                resolved_id,
                resolved_peer,
                sorted(source_keys),
            )
        except Exception as e:
            logger.error("Cannot resolve %s: %s", source_link, e)
    return dict(watched_entities), source_snapshot


async def start_listener():
    """
    Build the Telethon client, subscribe to all source channels from the DB,
    and listen for new messages indefinitely.
    """
    client = TelegramClient("session/parser_session", API_ID, API_HASH)
    await client.start(phone=PHONE)
    logger.info("Telethon client started.")

    watched_entities, source_snapshot = await _build_watched_entities(client)
    watched_lock = asyncio.Lock()
    LISTENER_SOURCE_SNAPSHOT.clear()
    LISTENER_SOURCE_SNAPSHOT.extend(source_snapshot)
    if not watched_entities:
        logger.warning("No valid sources configured yet. Listener will keep refreshing.")

    async def refresh_sources_loop():
        while True:
            await asyncio.sleep(max(10, SOURCES_REFRESH_SECONDS))
            try:
                updated, updated_snapshot = await _build_watched_entities(client)
                async with watched_lock:
                    watched_entities.clear()
                    watched_entities.update(updated)
                    LISTENER_SOURCE_SNAPSHOT.clear()
                    LISTENER_SOURCE_SNAPSHOT.extend(updated_snapshot)
                logger.info("sources_refreshed | watched_entities=%d", len(updated))
            except Exception as e:
                logger.exception("sources_refresh_failed: %s", e)

    refresh_task = asyncio.create_task(refresh_sources_loop())

    @client.on(events.NewMessage())
    async def handler(event):
        text = event.message.text or event.message.message or ""
        chat = None
        with_chat_error = None
        try:
            chat = event.chat or await event.get_chat()
        except Exception as e:
            with_chat_error = str(e)

        event_keys, event_chat_id = _extract_event_keys(event)
        message_peer_id = None
        try:
            message_peer_id = _normalize_chat_id(get_peer_id(event.message.peer_id))
        except Exception:
            pass
        fwd_chat_id = None
        try:
            fwd_from = getattr(event.message, "fwd_from", None)
            if fwd_from and getattr(fwd_from, "from_id", None):
                fwd_chat_id = _normalize_chat_id(get_peer_id(fwd_from.from_id))
        except Exception:
            pass

        event_debug_payload = {
            "event_type": event.__class__.__name__,
            "event_chat_id": event_chat_id,
            "event_sender_id": _normalize_chat_id(getattr(event, "sender_id", None)),
            "event_peer_id": message_peer_id,
            "event_keys": sorted(event_keys),
            "chat_username": _normalize_username(getattr(chat, "username", None)),
            "chat_title": getattr(chat, "title", None),
            "is_media": bool(getattr(event.message, "media", None)),
            "is_reply": bool(getattr(event.message, "reply_to", None)),
            "is_forwarded": bool(getattr(event.message, "fwd_from", None)),
            "fwd_chat_id": fwd_chat_id,
            "text_preview": _truncate_text(text),
        }
        LAST_LISTENER_EVENT.clear()
        LAST_LISTENER_EVENT.update(event_debug_payload)
        logger.info(
            "event_received_raw | type=%s chat_id=%s sender_id=%s peer_id=%s keys=%s "
            "chat_username=%s chat_title=%s media=%s forwarded=%s fwd_chat_id=%s text=%r chat_err=%s",
            event_debug_payload["event_type"],
            event_debug_payload["event_chat_id"],
            event_debug_payload["event_sender_id"],
            event_debug_payload["event_peer_id"],
            event_debug_payload["event_keys"],
            event_debug_payload["chat_username"],
            event_debug_payload["chat_title"],
            event_debug_payload["is_media"],
            event_debug_payload["is_forwarded"],
            event_debug_payload["fwd_chat_id"],
            event_debug_payload["text_preview"],
            with_chat_error,
        )

        async with watched_lock:
            matched_configs: list[dict] = []
            for key in event_keys:
                matched_configs.extend(watched_entities.get(key, []))
            known_sources = sorted(watched_entities.keys())

        unique_configs_map: dict[int, dict] = {}
        for cfg in matched_configs:
            unique_configs_map[cfg["channel_id"]] = cfg
        configs = list(unique_configs_map.values())

        if not configs:
            logger.info(
                "source_not_matched | event_chat_id=%s event_keys=%s known_sources=%s",
                event_chat_id,
                sorted(event_keys),
                known_sources,
            )
            return

        if len(text) < MIN_TEXT_LENGTH:
            logger.info(
                "min_text_skip | source=%s length=%d min=%d text=%r",
                event_chat_id,
                len(text),
                MIN_TEXT_LENGTH,
                _truncate_text(text),
            )
            return

        source_post_id = f"{event_chat_id}_{event.message.id}"
        logger.info(
            "incoming_message | source=%s source_post_id=%s routes=%d event_keys=%s",
            event_chat_id,
            source_post_id,
            len(configs),
            sorted(event_keys),
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
