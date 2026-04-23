from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.config import settings
from app.models import ChannelConfig, Source


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or str(settings.database_path)

    async def close(self) -> None:
        return

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    bot_token TEXT NOT NULL,
                    target_channel_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    trial_until TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    source_link TEXT NOT NULL,
                    UNIQUE(channel_id, source_link),
                    FOREIGN KEY(channel_id) REFERENCES channels(id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def upsert_user(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users(id, created_at) VALUES (?, ?)",
                (user_id, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def create_or_update_channel(self, user_id: int, bot_token: str, target_channel_id: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT id FROM channels WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row:
                channel_id = int(row[0])
                await db.execute(
                    "UPDATE channels SET bot_token = ?, target_channel_id = ? WHERE id = ?",
                    (bot_token, target_channel_id, channel_id),
                )
            else:
                trial_until = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                cursor = await db.execute(
                    "INSERT INTO channels(user_id, bot_token, target_channel_id, trial_until) VALUES (?, ?, ?, ?)",
                    (user_id, bot_token, target_channel_id, trial_until),
                )
                channel_id = int(cursor.lastrowid)
            await db.commit()
            return channel_id

    async def set_trial(self, channel_id: int, trial_until: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE channels SET trial_until=? WHERE id=?", (trial_until, channel_id))
            await db.commit()

    async def add_source(self, channel_id: int, source_link: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO sources(channel_id, source_link) VALUES (?, ?)",
                (channel_id, source_link),
            )
            await db.commit()

    async def toggle_channel(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT id, enabled FROM channels WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                raise ValueError("Channel not configured")
            enabled = not bool(row[1])
            await db.execute("UPDATE channels SET enabled = ? WHERE id = ?", (int(enabled), int(row[0])))
            await db.commit()
            return enabled

    async def get_user_channel(self, user_id: int) -> ChannelConfig | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT id, user_id, bot_token, target_channel_id, enabled, trial_until FROM channels WHERE user_id=?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            trial_until = datetime.fromisoformat(row[5]) if row[5] else None
            return ChannelConfig(int(row[0]), int(row[1]), str(row[2]), str(row[3]), bool(row[4]), trial_until)

    async def get_enabled_channels(self) -> list[ChannelConfig]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT id, user_id, bot_token, target_channel_id, enabled, trial_until FROM channels WHERE enabled = 1"
            )
            rows = await cursor.fetchall()
            channels: list[ChannelConfig] = []
            for row in rows:
                trial_until = datetime.fromisoformat(row[5]) if row[5] else None
                channels.append(ChannelConfig(int(row[0]), int(row[1]), str(row[2]), str(row[3]), bool(row[4]), trial_until))
            return channels

    async def get_sources_for_channel(self, channel_id: int) -> list[Source]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT id, channel_id, source_link FROM sources WHERE channel_id = ?", (channel_id,))
            rows = await cursor.fetchall()
            return [Source(int(row[0]), int(row[1]), str(row[2])) for row in rows]

    async def get_sources_map(self) -> dict[str, list[ChannelConfig]]:
        channels = await self.get_enabled_channels()
        source_map: dict[str, list[ChannelConfig]] = {}
        for channel in channels:
            for source in await self.get_sources_for_channel(channel.id):
                source_map.setdefault(source.source_link, []).append(channel)
        return source_map

    async def has_post_hash(self, digest: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT id FROM posts WHERE hash = ?", (digest,))
            return await cursor.fetchone() is not None

    async def insert_post_hash(self, digest: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO posts(hash, created_at) VALUES (?, ?)",
                (digest, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()


async def healthcheck(db: Database) -> dict[str, Any]:
    await db.init()
    return {"database": "ok", "path": db.path}
