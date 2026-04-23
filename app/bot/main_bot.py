from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.config import settings
from app.database import Database
from app.bot.handlers import register_handlers
from app.logger import logger


async def run_admin_bot(db: Database) -> None:
    if not settings.admin_bot_token:
        logger.warning("ADMIN_BOT_TOKEN not set. Admin bot is disabled.")
        return

    bot = Bot(settings.admin_bot_token)
    dp = Dispatcher()
    dp.include_router(register_handlers(db))

    logger.info("Admin bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
