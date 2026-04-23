from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class Settings:
    gemini_key: str = os.getenv("GEMINI_KEY", "")
    tg_api_id: int = int(os.getenv("TG_API_ID", "0") or "0")
    tg_api_hash: str = os.getenv("TG_API_HASH", "")
    admin_bot_token: str = os.getenv("ADMIN_BOT_TOKEN", "")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/newsagent.db"))
    session_path: str = os.getenv("TELETHON_SESSION", "session/newsagent")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
