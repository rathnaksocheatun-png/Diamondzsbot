"""Every main-menu button. This router is included FIRST so that tapping a
menu button always works, even in the middle of another conversation.

Each handler answers the keyboard button AND the same-named slash command
(/buy, /orders ...) so the Telegram "Menu" list works too -
that list is defined in app/utils/commands.py."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.config import Settings
from app.database.db import Database
from app.handlers import howto_video, info, shop, wallet
from app.keyboards.user import language_kb
from app.texts import menu_labels, t

router = Router(name="menu")


@router.message(Command("buy"))
@router.message(F.text.in_(menu_labels("buy")))
async def menu_buy(message: Message, state: FSMContext, db: Database, user: dict):
    await state.clear()
    await shop.show_games(message, db, user["language"])


@router.message(Command("orders"))
@router.message(F.text.in_(menu_labels("orders")))
async def menu_orders(message: Message, state: FSMContext, db: Database, user: dict):
    await state.clear()
    await shop.show_orders(message, db, user)


@router.message(Command("wallet"))
@router.message(F.text.in_(menu_labels("wallet")))
async def menu_wallet(message: Message, state: FSMContext, user: dict):
    await state.clear()
    await wallet.show_wallet(message, user)


@router.message(Command("deposit"))
@router.message(F.text.in_(menu_labels("deposit")))
async def menu_deposit(message: Message, state: FSMContext, db: Database, user: dict, khpay=None):
    await wallet.start_deposit(message, state, db, user, auto=khpay is not None)


@router.message(Command("promos"))
@router.message(F.text.in_(menu_labels("promos")))
async def menu_promos(message: Message, state: FSMContext, db: Database, user: dict):
    await state.clear()
    await info.show_promos(message, db, user["language"])


@router.message(Command("support"))
@router.message(F.text.in_(menu_labels("support")))
async def menu_support(message: Message, state: FSMContext, settings: Settings, user: dict):
    await state.clear()
    await info.show_support(message, settings, user["language"])


@router.message(Command("history"))
@router.message(F.text.in_(menu_labels("history")))
async def menu_history(message: Message, state: FSMContext, db: Database, user: dict):
    await state.clear()
    await wallet.show_history(message, db, user)


@router.message(Command("howto"))
@router.message(F.text.in_(menu_labels("howto")))
async def menu_howto(message: Message, state: FSMContext, db: Database, user: dict):
    await state.clear()
    # Tutorial video first (only if an admin set one with /howtovideo), then the text.
    await howto_video.send_howto_video(message, db, user["language"])
    await info.show_howto(message, user["language"])


@router.message(Command("language"))
@router.message(F.text.in_(menu_labels("language")))
async def menu_language(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(t("en", "choose_language"), reply_markup=language_kb())
