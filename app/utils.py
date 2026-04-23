from __future__ import annotations

import hashlib
import signal
import sys
from datetime import datetime, timezone
from typing import Callable


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_signals(loop, stop_callback: Callable[[], None]) -> None:
    if sys.platform == "win32":
        return

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_callback)
