"""Admin: rename games, and give games / packages an emoji (normal or Telegram Premium)."""
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database import repositories as repo
from app.database.db import Database
from app.handlers.states import AdminFlow
from app.keyboards import admin as kb
from app.utils import icons
from app.utils.filters import IsAdmin
from app.utils.formatting import esc
from app.utils.telegram import edit_or_send
from app.utils.validators import to_int, valid_product_name

router = Router(name="appearance")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

EMOJI_HELP = (
    "Send ONE emoji.\n"
    "• A normal emoji, e.g. 🔥\n"
    "• Or a ✨ Telegram Premium animated emoji (you need Telegram Premium to send it, and "
    "your bot's owner needs it for customers to see it animated)\n"
    "• Send <code>-</code> to go back to the default.\n"
    "Send /cancel to stop."
)


def _data(cb: CallbackQuery) -> list:
    return (cb.data or "").split(":")


def parse_emoji(message: Message) -> Optional[tuple]:
    """-> (emoji, premium_id) | (None, None) for "reset" | None if it is not one emoji."""
    text = (message.text or "").strip()
    if text == "-":
        return None, None
    custom = [e for e in (message.entities or []) if e.type == "custom_emoji"]
    if custom:
        if len(custom) != 1:
            return None
        char = custom[0].extract_from(message.text or "").strip()
        if char != text or not icons.valid_id(custom[0].custom_emoji_id):
            return None
        return char, str(custom[0].custom_emoji_id)
    char = icons.clean_plain_emoji(text)
    return (char, None) if char else None


def _show(emoji: Optional[str], emoji_id: Optional[str], default: str) -> str:
    return icons.html_icon(emoji, emoji_id, default)


# ------------------------------------------------------------------ rename game


@router.callback_query(F.data.regexp(r"^adm:gname:[a-z0-9_]+$"))
async def cb_game_name_start(cb: CallbackQuery, state: FSMContext, db: Database):
    code = _data(cb)[2]
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer("Game not found.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.game_name)
    await state.update_data(game_code=code)
    await cb.answer()
    await edit_or_send(
        cb, f"✏️ Current name: <b>{esc(game['name'])}</b>\n\n"
            "Send the NEW name (2–40 characters, Khmer is fine).\nSend /cancel to stop.")


@router.message(AdminFlow.game_name)
async def on_game_name(message: Message, state: FSMContext, db: Database):
    name = valid_product_name(message.text)
    if name is None:
        await message.answer("⚠️ Name must be 2–40 characters of plain text.")
        return
    code = (await state.get_data()).get("game_code") or ""
    await state.clear()
    if not await repo.update_game_name(db, code, name):
        await message.answer("Game not found.")
        return
    await message.answer(f"✅ Game renamed to <b>{esc(name)}</b>.",
                         reply_markup=kb.simple_home_kb([kb.button("⬅️ Game", f"adm:pg:{code}")]))


# ------------------------------------------------------------------- emoji flows


async def _start_emoji(cb: CallbackQuery, state: FSMContext, new_state, **data) -> None:
    await state.clear()
    await state.set_state(new_state)
    await state.update_data(**data)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:gemoji:[a-z0-9_]+$"))
async def cb_game_emoji_start(cb: CallbackQuery, state: FSMContext, db: Database):
    code = _data(cb)[2]
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer("Game not found.", show_alert=True)
        return
    await _start_emoji(cb, state, AdminFlow.game_emoji, game_code=code)
    await edit_or_send(
        cb, f"😀 Emoji for <b>{esc(game['name'])}</b> — now: "
            f"{_show(game['emoji'], game.get('emoji_id'), '🎮')}\n\n{EMOJI_HELP}")


@router.message(AdminFlow.game_emoji)
async def on_game_emoji(message: Message, state: FSMContext, db: Database):
    parsed = parse_emoji(message)
    if parsed is None:
        await message.answer("⚠️ Please send exactly ONE emoji (or <code>-</code> for default).")
        return
    emoji, emoji_id = parsed
    code = (await state.get_data()).get("game_code") or ""
    await state.clear()
    if not await repo.update_game_emoji(db, code, emoji or "🎮", emoji_id):
        await message.answer("Game not found.")
        return
    await message.answer(
        f"✅ Game emoji is now {_show(emoji, emoji_id, '🎮')}",
        reply_markup=kb.simple_home_kb([kb.button("⬅️ Game", f"adm:pg:{code}")]))


@router.callback_query(F.data.regexp(r"^adm:pemoji:\d+$"))
async def cb_product_emoji_start(cb: CallbackQuery, state: FSMContext, db: Database):
    pid = to_int(_data(cb)[2]) or 0
    product = await repo.get_product(db, pid)
    if product is None:
        await cb.answer("Product not found.", show_alert=True)
        return
    await _start_emoji(cb, state, AdminFlow.product_emoji, product_id=pid)
    await edit_or_send(
        cb, f"😀 Emoji for <b>{esc(product['name'])}</b> — now: "
            f"{_show(product['emoji'], product.get('emoji_id'), '💎')}\n\n{EMOJI_HELP}")


@router.message(AdminFlow.product_emoji)
async def on_product_emoji(message: Message, state: FSMContext, db: Database):
    parsed = parse_emoji(message)
    if parsed is None:
        await message.answer("⚠️ Please send exactly ONE emoji (or <code>-</code> for default).")
        return
    emoji, emoji_id = parsed
    pid = (await state.get_data()).get("product_id") or 0
    await state.clear()
    if not await repo.update_product_emoji(db, pid, emoji, emoji_id):
        await message.answer("Product not found.")
        return
    await message.answer(
        f"✅ Package emoji is now {_show(emoji, emoji_id, '💎')}",
        reply_markup=kb.simple_home_kb([kb.button("⬅️ Package", f"adm:p:{pid}")]))


@router.callback_query(F.data.regexp(r"^adm:gpemoji:[a-z0-9_]+$"))
async def cb_game_pkg_emoji_start(cb: CallbackQuery, state: FSMContext, db: Database):
    code = _data(cb)[2]
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer("Game not found.", show_alert=True)
        return
    n = len(await repo.list_products(db, code, only_active=False))
    await _start_emoji(cb, state, AdminFlow.game_pkg_emoji, game_code=code)
    await edit_or_send(
        cb, f"💎 Emoji for ALL {n} package(s) of <b>{esc(game['name'])}</b>\n\n{EMOJI_HELP}")


@router.message(AdminFlow.game_pkg_emoji)
async def on_game_pkg_emoji(message: Message, state: FSMContext, db: Database):
    parsed = parse_emoji(message)
    if parsed is None:
        await message.answer("⚠️ Please send exactly ONE emoji (or <code>-</code> for default).")
        return
    emoji, emoji_id = parsed
    code = (await state.get_data()).get("game_code") or ""
    await state.clear()
    n = await repo.update_game_products_emoji(db, code, emoji, emoji_id)
    await message.answer(
        f"✅ {n} package(s) now use {_show(emoji, emoji_id, '💎')}",
        reply_markup=kb.simple_home_kb([kb.button("⬅️ Game", f"adm:pg:{code}")]))
