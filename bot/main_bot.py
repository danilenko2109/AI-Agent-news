"""
Admin bot (aiogram 3.x) — manages users, channels and sources.

Commands:
  /start        — Register or show status
  /add_channel  — Add a new output channel (with bot token)
  /add_source   — Add a source channel to scrape
  /my_channels  — List your channels with their sources
  /stats        — Global platform statistics (admin only)
"""

import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from db import (
    get_or_create_user,
    is_user_active,
    add_channel,
    add_source,
    get_user_channels,
    get_sources_for_channel,
    get_stats,
)

logger = logging.getLogger(__name__)

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", 0))  # Your personal Telegram ID

router = Router()


# ─── FSM States ───────────────────────────────────────────────────────────────

class AddChannelStates(StatesGroup):
    waiting_bot_token = State()
    waiting_target_channel = State()
    waiting_prompt_style = State()


class AddSourceStates(StatesGroup):
    waiting_channel_select = State()
    waiting_source_link = State()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _trial_or_active_badge(user: dict) -> str:
    from datetime import datetime
    status = user["subscription_status"]
    if status == "active":
        return "✅ Активна підписка"
    if status == "trial" and user.get("trial_ends_at"):
        ends = datetime.fromisoformat(user["trial_ends_at"])
        delta = ends - datetime.utcnow()
        days = max(0, delta.days)
        return f"🕐 Пробний період: {days} дн. залишилось"
    return "❌ Підписка закінчилась"


# ─── Handlers ─────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    badge = _trial_or_active_badge(user)
    await message.answer(
        f"👋 Привіт, <b>{message.from_user.first_name}</b>!\n\n"
        f"🤖 <b>AI News Agent</b> — автоматизація ваших Telegram-каналів.\n\n"
        f"📊 Статус: {badge}\n\n"
        f"Команди:\n"
        f"  /add_channel — Додати вихідний канал\n"
        f"  /add_source  — Додати канал-донор\n"
        f"  /my_channels — Мої канали\n",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("my_channels"))
async def cmd_my_channels(message: Message):
    channels = await get_user_channels(message.from_user.id)
    if not channels:
        await message.answer("У вас ще немає каналів. Використайте /add_channel.")
        return
    lines = []
    for ch in channels:
        sources = await get_sources_for_channel(ch["id"])
        src_list = "\n".join(f"    • {s['source_tg_link']}" for s in sources) or "    (немає джерел)"
        lines.append(
            f"📢 <code>{ch['target_channel_id']}</code>\n"
            f"  Стиль: {ch['prompt_style']}\n"
            f"  Джерела:\n{src_list}"
        )
    await message.answer("\n\n".join(lines), parse_mode=ParseMode.HTML)


# ── Add Channel Flow ──────────────────────────────────────────────────────────

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, state: FSMContext):
    if not await is_user_active(message.from_user.id):
        await message.answer("❌ Ваш пробний період закінчився. Зверніться до адміна.")
        return
    await state.set_state(AddChannelStates.waiting_bot_token)
    await message.answer(
        "📋 <b>Крок 1/3</b>\n\n"
        "Надішліть <b>Bot Token</b> вашого бота, від імені якого публікуватимуться пости.\n"
        "(Отримайте у @BotFather → /newbot)",
        parse_mode=ParseMode.HTML,
    )


@router.message(AddChannelStates.waiting_bot_token)
async def process_bot_token(message: Message, state: FSMContext):
    token = message.text.strip()
    if ":" not in token or len(token) < 20:
        await message.answer("❌ Невірний формат токена. Спробуйте ще раз.")
        return
    await state.update_data(bot_token=token)
    await state.set_state(AddChannelStates.waiting_target_channel)
    await message.answer(
        "📋 <b>Крок 2/3</b>\n\n"
        "Надішліть <b>ID або @username</b> вашого Telegram-каналу.\n"
        "Приклад: <code>@my_news_channel</code> або <code>-1001234567890</code>",
        parse_mode=ParseMode.HTML,
    )


@router.message(AddChannelStates.waiting_target_channel)
async def process_target_channel(message: Message, state: FSMContext):
    await state.update_data(target_channel_id=message.text.strip())
    await state.set_state(AddChannelStates.waiting_prompt_style)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="default"), KeyboardButton(text="breaking")],
            [KeyboardButton(text="analytical")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "📋 <b>Крок 3/3</b>\n\nОберіть стиль постів:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


@router.message(AddChannelStates.waiting_prompt_style)
async def process_prompt_style(message: Message, state: FSMContext):
    style = message.text.strip().lower()
    if style not in ("default", "breaking", "analytical"):
        style = "default"
    data = await state.get_data()
    try:
        channel_id = await add_channel(
            owner_telegram_id=message.from_user.id,
            bot_token=data["bot_token"],
            target_channel_id=data["target_channel_id"],
            prompt_style=style,
        )
        await state.clear()
        await message.answer(
            f"✅ Канал <code>{data['target_channel_id']}</code> додано (ID: {channel_id}).\n\n"
            f"Тепер додайте канали-донори через /add_source.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("add_channel error: %s", e)
        await state.clear()
        await message.answer("❌ Помилка при додаванні каналу.", reply_markup=ReplyKeyboardRemove())


# ── Add Source Flow ───────────────────────────────────────────────────────────

@router.message(Command("add_source"))
async def cmd_add_source(message: Message, state: FSMContext):
    channels = await get_user_channels(message.from_user.id)
    if not channels:
        await message.answer("Спочатку додайте канал через /add_channel.")
        return
    await state.update_data(channels=channels)
    await state.set_state(AddSourceStates.waiting_channel_select)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=ch["target_channel_id"])] for ch in channels],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Оберіть канал, до якого додати джерело:", reply_markup=kb)


@router.message(AddSourceStates.waiting_channel_select)
async def process_channel_select(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = message.text.strip()
    channel = next((c for c in data["channels"] if c["target_channel_id"] == selected), None)
    if not channel:
        await message.answer("❌ Канал не знайдено. Спробуйте знову.")
        return
    await state.update_data(selected_channel=channel)
    await state.set_state(AddSourceStates.waiting_source_link)
    await message.answer(
        "Надішліть посилання або @username каналу-донора:\n"
        "Приклад: <code>@unian_ua</code> або <code>https://t.me/unian_ua</code>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML,
    )


@router.message(AddSourceStates.waiting_source_link)
async def process_source_link(message: Message, state: FSMContext):
    data = await state.get_data()
    channel = data["selected_channel"]
    source_link = message.text.strip()
    try:
        await add_source(channel["id"], source_link)
        await state.clear()
        await message.answer(
            f"✅ Джерело <code>{source_link}</code> додано до каналу "
            f"<code>{channel['target_channel_id']}</code>.\n\n"
            "⚠️ Перезапустіть listener для застосування змін.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("add_source error: %s", e)
        await state.clear()
        await message.answer("❌ Помилка при додаванні джерела.")


# ── Stats (admin only) ────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if ADMIN_TG_ID and message.from_user.id != ADMIN_TG_ID:
        await message.answer("⛔ Тільки для адміна.")
        return
    stats = await get_stats()
    await message.answer(
        f"📊 <b>Статистика платформи</b>\n\n"
        f"👥 Користувачів: <b>{stats['users']}</b>\n"
        f"📢 Активних каналів: <b>{stats['channels']}</b>\n"
        f"📡 Джерел: <b>{stats['sources']}</b>\n"
        f"📰 Опублікованих постів: <b>{stats['posts_published']}</b>",
        parse_mode=ParseMode.HTML,
    )


# ─── Bot Factory ──────────────────────────────────────────────────────────────

def create_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=ADMIN_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return bot, dp
