"""Catches anything nobody else handled. Must be included LAST."""
from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from app.keyboards.user import main_menu
from app.texts import t

router = Router(name="fallback")


@router.message(StateFilter(None))
async def unknown_message(message: Message, user: dict):
    lang = user["language"]
    await message.answer(t(lang, "menu_hint"), reply_markup=main_menu(lang))


@router.callback_query()
async def unknown_callback(cb: CallbackQuery, user: dict):
    # e.g. a button from an old message, or a double tap on Confirm
    await cb.answer(t(user["language"], "session_expired"), show_alert=True)
