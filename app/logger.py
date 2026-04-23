from __future__ import annotations

import logging
import sys

from app.config import settings

try:
    from loguru import logger as _loguru_logger
except ModuleNotFoundError:  # pragma: no cover
    _loguru_logger = None


class _StdLoggerAdapter:
    def __init__(self) -> None:
        self._logger = logging.getLogger("ai-news-agent")

    def remove(self) -> None:
        self._logger.handlers.clear()

    def add(self, sink, level: str, format: str, **_: object) -> None:  # noqa: A002
        handler = logging.StreamHandler(sink)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        self._logger.setLevel(level)
        self._logger.addHandler(handler)

    def info(self, message: str, *args: object) -> None:
        self._logger.info(message.format(*args))

    def error(self, message: str, *args: object) -> None:
        self._logger.error(message.format(*args))

    def debug(self, message: str, *args: object) -> None:
        self._logger.debug(message.format(*args))

    def warning(self, message: str, *args: object) -> None:
        self._logger.warning(message.format(*args))


logger = _loguru_logger or _StdLoggerAdapter()


def setup_logger() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {name}:{function}:{line} - {message}",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


__all__ = ["logger", "setup_logger"]
