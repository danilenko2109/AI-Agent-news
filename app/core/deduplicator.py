from __future__ import annotations

from app.database import Database
from app.utils import sha256_text


class Deduplicator:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def is_duplicate(self, text: str) -> bool:
        digest = sha256_text(text)
        return await self.db.has_post_hash(digest)

    async def remember(self, text: str) -> None:
        digest = sha256_text(text)
        await self.db.insert_post_hash(digest)
