"""/start, /menu, /cancel, language choice and the global Cancel button."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo,
)

from app.database import repositories as repo
from app.database.db import Database
from app.keyboards.user import language_kb, main_menu
from app.texts import t
from app.utils.formatting import esc
from app.utils.telegram import edit_or_send

router = Router(name="start")

SHOP_BUTTON_TEXT = {"km": "🛍 ហាង App", "en": "🛍 Open Shop"}


def with_shop(kb, webapp_url: str, lang: str):
    """Put a one-tap Mini App button on top of the existing main menu.

    Does nothing when WEBAPP_URL is not set, so the bot behaves exactly as before.
    """
    if not webapp_url or kb is None:
        return kb
    text = SHOP_BUTTON_TEXT.get(lang, SHOP_BUTTON_TEXT["en"])
    web_app = WebAppInfo(url=webapp_url)
    if isinstance(kb, ReplyKeyboardMarkup):
        row = [KeyboardButton(text=text, web_app=web_app)]
        return kb.model_copy(update={"keyboard": [row, *kb.keyboard]})
    if isinstance(kb, InlineKeyboardMarkup):
        row = [InlineKeyboardButton(text=text, web_app=web_app)]
        return kb.model_copy(update={"inline_keyboard": [row, *kb.inline_keyboard]})
    return kb


async def send_welcome(target: Message, lang: str, full_name: str, webapp_url: str = "") -> None:
    await target.answer(
        t(lang, "welcome", name=esc(full_name or "friend")),
        reply_markup=with_shop(main_menu(lang), webapp_url, lang),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: dict, is_new: bool, webapp_url: str = ""):
    await state.clear()
    if is_new:
        await message.answer(t("en", "choose_language"), reply_markup=language_kb())
        return
    await send_welcome(message, user["language"], user["full_name"], webapp_url)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, user: dict, webapp_url: str = ""):
    await state.clear()
    await message.answer(t(user["language"], "menu_hint"),
                         reply_markup=with_shop(main_menu(user["language"]), webapp_url, user["language"]))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, user: dict, webapp_url: str = ""):
    await state.clear()
    await message.answer(t(user["language"], "flow_cancelled"),
                         reply_markup=with_shop(main_menu(user["language"]), webapp_url, user["language"]))


@router.callback_query(F.data.startswith("lang:"))
async def on_language(cb: CallbackQuery, db: Database, user: dict, webapp_url: str = ""):
    code = (cb.data or "").split(":", 1)[1]
    if code not in ("en", "km"):
        await cb.answer()
        return
    await repo.set_language(db, cb.from_user.id, code)
    await cb.answer()
    if isinstance(cb.message, Message):
        try:
            await cb.message.delete()
        except Exception:  # message too old to delete - not a problem
            pass
        await cb.message.answer(t(code, "language_changed"))
        await send_welcome(cb.message, code, user["full_name"], webapp_url)


@router.callback_query(F.data == "flow:cancel")
async def on_flow_cancel(cb: CallbackQuery, state: FSMContext, user: dict):
    await state.clear()
    await cb.answer()
    await edit_or_send(cb, t(user["language"], "flow_cancelled"))
