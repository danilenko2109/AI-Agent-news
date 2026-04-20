"""
Async database layer using aiosqlite.
To migrate to PostgreSQL: replace aiosqlite with asyncpg and rewrite
get_connection() to return an asyncpg pool. All query methods stay the same.
"""

import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import aiosqlite

from db.models import CREATE_TABLES_SQL

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./data/newsagent.db")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", 3))


@asynccontextmanager
async def get_connection():
    """Context manager that yields a database connection."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


async def init_db():
    """Initialize database schema."""
    async with get_connection() as db:
        for sql in CREATE_TABLES_SQL:
            await db.execute(sql)
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


# ─── Users ────────────────────────────────────────────────────────────────────

async def get_or_create_user(telegram_id: int, username: str | None = None) -> dict:
    trial_ends = (datetime.utcnow() + timedelta(days=TRIAL_DAYS)).isoformat()
    async with get_connection() as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, username, subscription_status, trial_ends_at)
            VALUES (?, ?, 'trial', ?)
            ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username
            """,
            (telegram_id, username, trial_ends),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row)


async def is_user_active(telegram_id: int) -> bool:
    """Return True if the user has an active subscription or a valid trial."""
    async with get_connection() as db:
        cursor = await db.execute(
            "SELECT subscription_status, trial_ends_at FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False
        if row["subscription_status"] == "active":
            return True
        if row["subscription_status"] == "trial" and row["trial_ends_at"]:
            ends = datetime.fromisoformat(row["trial_ends_at"])
            return datetime.utcnow() < ends
        return False


async def get_all_users() -> list[dict]:
    async with get_connection() as db:
        cursor = await db.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ─── Channels ─────────────────────────────────────────────────────────────────

async def add_channel(
    owner_telegram_id: int,
    bot_token: str,
    target_channel_id: str,
    prompt_style: str = "default",
) -> int:
    async with get_connection() as db:
        cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (owner_telegram_id,)
        )
        user = await cursor.fetchone()
        if not user:
            raise ValueError("User not found")
        cursor = await db.execute(
            """
            INSERT INTO channels (owner_id, bot_token, target_channel_id, prompt_style)
            VALUES (?, ?, ?, ?)
            """,
            (user["id"], bot_token, target_channel_id, prompt_style),
        )
        await db.commit()
        return cursor.lastrowid


async def get_user_channels(telegram_id: int) -> list[dict]:
    async with get_connection() as db:
        cursor = await db.execute(
            """
            SELECT c.* FROM channels c
            JOIN users u ON c.owner_id = u.id
            WHERE u.telegram_id = ? AND c.is_active = 1
            """,
            (telegram_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_active_channels() -> list[dict]:
    async with get_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM channels WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ─── Sources ──────────────────────────────────────────────────────────────────

async def add_source(channel_id: int, source_tg_link: str) -> int:
    async with get_connection() as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO sources (channel_id, source_tg_link)
            VALUES (?, ?)
            """,
            (channel_id, source_tg_link.strip()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_sources_for_channel(channel_id: int) -> list[dict]:
    async with get_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM sources WHERE channel_id = ?", (channel_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_sources() -> list[dict]:
    """Return all sources joined with channel info for the listener."""
    async with get_connection() as db:
        cursor = await db.execute(
            """
            SELECT s.*, c.bot_token, c.target_channel_id, c.prompt_style
            FROM sources s
            JOIN channels c ON s.channel_id = c.id
            WHERE c.is_active = 1
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ─── Processed Posts ──────────────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def is_duplicate(source_post_id: str, channel_id: int, text: str) -> bool:
    h = _content_hash(text)
    async with get_connection() as db:
        cursor = await db.execute(
            """
            SELECT id FROM processed_posts
            WHERE (source_post_id = ? AND channel_id = ?) OR content_hash = ?
            """,
            (source_post_id, channel_id, h),
        )
        return await cursor.fetchone() is not None


async def mark_as_processed(source_post_id: str, channel_id: int, text: str):
    h = _content_hash(text)
    async with get_connection() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO processed_posts (source_post_id, content_hash, channel_id)
            VALUES (?, ?, ?)
            """,
            (source_post_id, h, channel_id),
        )
        await db.commit()


async def get_stats() -> dict:
    async with get_connection() as db:
        users_cur = await db.execute("SELECT COUNT(*) as cnt FROM users")
        channels_cur = await db.execute("SELECT COUNT(*) as cnt FROM channels WHERE is_active=1")
        sources_cur = await db.execute("SELECT COUNT(*) as cnt FROM sources")
        posts_cur = await db.execute("SELECT COUNT(*) as cnt FROM processed_posts")
        return {
            "users": (await users_cur.fetchone())["cnt"],
            "channels": (await channels_cur.fetchone())["cnt"],
            "sources": (await sources_cur.fetchone())["cnt"],
            "posts_published": (await posts_cur.fetchone())["cnt"],
        }
