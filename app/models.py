from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ChannelConfig:
    id: int
    user_id: int
    bot_token: str
    target_channel_id: str
    enabled: bool
    trial_until: datetime | None


@dataclass(slots=True)
class Source:
    id: int
    channel_id: int
    source_link: str
