"""
Database schema definitions.
Swap aiosqlite for asyncpg + SQLAlchemy to migrate to PostgreSQL.
"""

CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username    TEXT,
        subscription_status TEXT NOT NULL DEFAULT 'trial',
        trial_ends_at       TEXT,
        created_at          TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channels (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        bot_token         TEXT NOT NULL,
        target_channel_id TEXT NOT NULL,
        prompt_style      TEXT DEFAULT 'default',
        is_active         INTEGER DEFAULT 1,
        created_at        TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id     INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
        source_tg_link TEXT NOT NULL,
        created_at     TEXT DEFAULT (datetime('now')),
        UNIQUE(channel_id, source_tg_link)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processed_posts (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        source_post_id TEXT NOT NULL,
        content_hash   TEXT NOT NULL,
        channel_id     INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
        published_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(source_post_id, channel_id)
    )
    """,
]
