from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить канал"), KeyboardButton(text="Добавить доноры")],
            [KeyboardButton(text="Включить/выключить автопилот"), KeyboardButton(text="Проверка триала")],
        ],
        resize_keyboard=True,
    )
