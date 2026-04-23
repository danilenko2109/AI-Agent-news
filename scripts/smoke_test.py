from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.deduplicator import Deduplicator
from app.core.processor import PostProcessor
from app.database import Database
from app.services.gemini_service import GeminiService
from app.services.image_service import ImageService


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    async def publish(self, bot_token: str, channel_id: str, text: str, image_path=None) -> None:  # noqa: ANN001
        self.calls.append((bot_token, channel_id, image_path is not None))
        print("PUBLISH_OK", channel_id, text[:40], "image=", bool(image_path))


async def main() -> None:
    db = Database("/tmp/newsagent_smoke.db")
    await db.init()
    await db.upsert_user(1)
    channel_id = await db.create_or_update_channel(1, "demo-bot-token", "@demo_target")
    await db.set_trial(channel_id, (datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
    await db.add_source(channel_id, "@demo_source")

    publisher = FakePublisher()
    processor = PostProcessor(
        gemini=GeminiService(api_key=""),
        image_service=ImageService(),
        deduplicator=Deduplicator(db),
        publisher=publisher,
    )

    channels = await db.get_enabled_channels()
    success = await processor.process_and_publish(channels[0], "Київ запускає нову міську ініціативу для безпеки")
    assert success is True
    assert len(publisher.calls) == 1

    duplicate = await processor.process_and_publish(channels[0], "Київ запускає нову міську ініціативу для безпеки")
    assert duplicate is False

    print("SMOKE_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
