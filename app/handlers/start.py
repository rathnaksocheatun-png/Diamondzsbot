"""/start, /menu, /cancel, language choice and the global Cancel button."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo,
)

from app.database import repositories as repo
from app.database.db import Database
from app.keyboards.user import SHOP_BUTTON_TEXTS, language_kb, main_menu
from app.texts import t
from app.utils.formatting import esc
from app.utils.telegram import edit_or_send

router = Router(name="start")


async def send_welcome(target: Message, lang: str, full_name: str) -> None:
    await target.answer(
        t(lang, "welcome", name=esc(full_name or "friend")),
        reply_markup=main_menu(lang),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: dict, is_new: bool):
    await state.clear()
    if is_new:
        await message.answer(t("en", "choose_language"), reply_markup=language_kb())
        return
    await send_welcome(message, user["language"], user["full_name"])


@router.message(F.text.in_(SHOP_BUTTON_TEXTS))
async def on_shop_button(message: Message, webapp_url: str = ""):
    """The "🛍 ហាង App" menu button: answer exactly like /app (inline Open-shop button)."""
    if not webapp_url:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍 Open shop / បើកហាង", web_app=WebAppInfo(url=webapp_url),
                             style="success"),
    ]])
    await message.answer("💎 <b>Diamond ZS</b>", reply_markup=kb)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, user: dict):
    await state.clear()
    await message.answer(t(user["language"], "menu_hint"), reply_markup=main_menu(user["language"]))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, user: dict):
    await state.clear()
    await message.answer(t(user["language"], "flow_cancelled"), reply_markup=main_menu(user["language"]))


@router.callback_query(F.data.startswith("lang:"))
async def on_language(cb: CallbackQuery, db: Database, user: dict):
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
        await send_welcome(cb.message, code, user["full_name"])


@router.callback_query(F.data == "flow:cancel")
async def on_flow_cancel(cb: CallbackQuery, state: FSMContext, user: dict):
    await state.clear()
    await cb.answer()
    await edit_or_send(cb, t(user["language"], "flow_cancelled"))
