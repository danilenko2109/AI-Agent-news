from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.bot.keyboards import main_keyboard
from app.database import Database

router = Router()


class SetupStates(StatesGroup):
    waiting_bot_token = State()
    waiting_target_channel = State()
    waiting_source = State()


def register_handlers(db: Database) -> Router:
    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await db.upsert_user(message.from_user.id)
        await state.clear()
        await message.answer("Привіт! Налаштуємо AI News Agent.", reply_markup=main_keyboard())

    @router.message(F.text == "Добавить канал")
    async def add_channel_begin(message: Message, state: FSMContext) -> None:
        await state.set_state(SetupStates.waiting_bot_token)
        await message.answer("Пришлите bot token канала клиента")

    @router.message(SetupStates.waiting_bot_token)
    async def receive_bot_token(message: Message, state: FSMContext) -> None:
        await state.update_data(bot_token=message.text.strip())
        await state.set_state(SetupStates.waiting_target_channel)
        await message.answer("Теперь ID/username канала назначения (например @my_channel)")

    @router.message(SetupStates.waiting_target_channel)
    async def receive_channel_target(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        bot_token = data["bot_token"]
        channel_id = await db.create_or_update_channel(
            user_id=message.from_user.id,
            bot_token=bot_token,
            target_channel_id=message.text.strip(),
        )
        trial_until = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat()
        await db.set_trial(channel_id, trial_until)
        await state.clear()
        await message.answer("Канал сохранен. Триал активирован на 7 дней.", reply_markup=main_keyboard())

    @router.message(F.text == "Добавить доноры")
    async def add_source_begin(message: Message, state: FSMContext) -> None:
        user_channel = await db.get_user_channel(message.from_user.id)
        if not user_channel:
            await message.answer("Сначала добавьте канал клиента")
            return
        await state.set_state(SetupStates.waiting_source)
        await message.answer("Пришлите source link: @channel или числовой chat_id")

    @router.message(SetupStates.waiting_source)
    async def receive_source(message: Message, state: FSMContext) -> None:
        user_channel = await db.get_user_channel(message.from_user.id)
        if not user_channel:
            await message.answer("Канал не найден")
            return
        await db.add_source(user_channel.id, message.text.strip())
        await state.clear()
        await message.answer("Источник добавлен", reply_markup=main_keyboard())

    @router.message(F.text == "Включить/выключить автопилот")
    async def toggle_autopilot(message: Message) -> None:
        try:
            enabled = await db.toggle_channel(message.from_user.id)
            await message.answer("Автопилот включен" if enabled else "Автопилот выключен")
        except ValueError:
            await message.answer("Сначала добавьте канал")

    @router.message(F.text == "Проверка триала")
    async def check_trial(message: Message) -> None:
        channel = await db.get_user_channel(message.from_user.id)
        if not channel or not channel.trial_until:
            await message.answer("Триал еще не активирован")
            return
        active = channel.trial_until > datetime.now(timezone.utc)
        status = "активен" if active else "истёк"
        await message.answer(f"Триал {status} до {channel.trial_until.isoformat()}")

    return router
