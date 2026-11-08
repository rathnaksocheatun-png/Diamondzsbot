"""Admin: Bay2Game panel (import games & packages) and the delete / hide buttons."""
import time
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.handlers.states import AdminFlow
from app.keyboards import admin as kb
from app.services import catalog, pricing
from app.services.bay2game import Bay2GameClient, Bay2GameError
from app.utils.filters import IsAdmin
from app.utils.formatting import esc, money
from app.utils.telegram import edit_or_send
from app.utils.validators import parse_money

router = Router(name="catalog")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_CODE = r"[A-Za-z0-9_.\-]{1,45}"
_cats_cache: tuple = (0.0, [])          # (time, categories) - keeps the game picker fast

OFF_TEXT = ("🔌 <b>Bay2Game is OFF</b>\nAdd the variable <code>BAY2GAME_API_KEY</code> on your "
            "host (Railway → Variables) and restart the bot.")


def _data(cb: CallbackQuery) -> list:
    return (cb.data or "").split(":")


def _int(text: Optional[str]) -> int:
    return int(text) if text is not None and text.isdigit() and len(text) < 8 else 0


async def _panel_text(db: Database, b2g: Bay2GameClient, settings: Settings) -> str:
    margin = await pricing.get_default_margin(db)
    stats = await catalog.store_stats(db)
    auto = await catalog.auto_import_enabled(db)
    try:
        balance = await b2g.balance_cents()
        bal = f"💰 Bay2Game balance: <b>{money(balance)}</b>" + (
            "  ⚠️ low" if balance < settings.bay2game_low_balance_cents else "")
    except Bay2GameError as exc:
        bal = f"⚠️ Could not read the balance: {esc(exc)}"
    profit = (f"<b>{money(margin)}</b> per sale" if margin is not None
              else "<b>NOT SET</b> - set it first, then import")
    return (
        "🔌 <b>Bay2Game — games & packages</b>\n\n"
        f"{bal}\n"
        f"💲 Your profit: {profit}\n"
        f"🤖 Auto-add new games/packages: <b>{'ON' if auto else 'OFF'}</b> (checked every 6 hours)\n\n"
        f"🛍 Your shop: <b>{stats['games_shown']}</b> game(s) and <b>{stats['products_shown']}</b> "
        f"package(s) visible ({stats['linked']} connected to Bay2Game)\n"
        f"🗑 Deleted items that will not come back: {stats['removed']}\n\n"
        "Selling price = Bay2Game cost + your profit, kept up to date automatically. "
        "Delete what you do not want in 🛍 Products - deleted items are never added again."
    )


async def _show_panel(cb: CallbackQuery, db: Database, b2g: Optional[Bay2GameClient],
                      settings: Settings) -> None:
    if b2g is None:
        await edit_or_send(cb, OFF_TEXT, kb.simple_home_kb())
        return
    stats = await catalog.store_stats(db)
    await edit_or_send(
        cb, await _panel_text(db, b2g, settings),
        kb.b2g_panel_kb(await catalog.auto_import_enabled(db), stats["removed"] > 0))


@router.callback_query(F.data == "adm:b2g")
async def cb_panel(cb: CallbackQuery, db: Database, settings: Settings,
                   state: FSMContext, b2g: Optional[Bay2GameClient] = None):
    await state.clear()
    await cb.answer()
    await _show_panel(cb, db, b2g, settings)


# ----------------------------------------------------------------- import


async def _run_import(db: Database, b2g: Bay2GameClient, only_game: Optional[str]) -> str:
    """Run the import and return the text to show. Never raises."""
    try:
        report = await catalog.import_catalog(db, b2g, only_game=only_game)
    except catalog.MarginNotSet:
        return ("💲 <b>Set your profit first.</b>\nThe bot needs it to calculate selling prices "
                "(cost + profit). Tap “Set profit per sale” (example: 0.01).")
    except Bay2GameError as exc:
        return f"⚠️ Could not read the Bay2Game catalog: {esc(exc)}"
    text = catalog.describe(report)
    if only_game is None and await repo.get_setting(db, catalog.AUTO_IMPORT_KEY) is None:
        await catalog.set_auto_import(db, True)
        text += ("\n\n🤖 Auto-add is now <b>ON</b>: new games/packages from Bay2Game are added "
                 "by themselves. You can turn it off in the Bay2Game panel.")
    return text


@router.callback_query(F.data == "adm:b2g:import")
async def cb_import(cb: CallbackQuery, db: Database, b2g: Optional[Bay2GameClient] = None):
    if b2g is None:
        await cb.answer()
        await edit_or_send(cb, OFF_TEXT, kb.simple_home_kb())
        return
    if catalog._import_lock.locked():
        await cb.answer("An import is already running. Please wait.", show_alert=True)
        return
    await cb.answer()
    await edit_or_send(cb, "⏳ Reading Bay2Game and adding games & packages…\n"
                           "This can take up to a minute.")
    await edit_or_send(cb, await _run_import(db, b2g, None), kb.b2g_back_kb())


@router.message(Command("b2g_import"))
async def cmd_import(message: Message, db: Database, b2g: Optional[Bay2GameClient] = None):
    if b2g is None:
        await message.answer(OFF_TEXT)
        return
    if catalog._import_lock.locked():
        await message.answer("An import is already running. Please wait.")
        return
    await message.answer("⏳ Reading Bay2Game and adding games & packages…")
    await message.answer(await _run_import(db, b2g, None), reply_markup=kb.b2g_back_kb())


async def _categories(b2g: Bay2GameClient) -> list:
    global _cats_cache
    if time.monotonic() - _cats_cache[0] > 60:
        _cats_cache = (time.monotonic(), await b2g.categories())
    return _cats_cache[1]


@router.callback_query(F.data.regexp(r"^adm:b2g:pick:\d+$"))
async def cb_pick(cb: CallbackQuery, db: Database, b2g: Optional[Bay2GameClient] = None):
    if b2g is None:
        await cb.answer()
        await edit_or_send(cb, OFF_TEXT, kb.simple_home_kb())
        return
    await cb.answer()
    try:
        cats = await _categories(b2g)
    except Bay2GameError as exc:
        await edit_or_send(cb, f"⚠️ {esc(exc)}", kb.b2g_back_kb())
        return
    have = {g["supplier_game"] for g in await repo.list_games(db) if g.get("supplier_game")}
    removed = {r["supplier_game"] for r in await db.fetchall(
        "SELECT supplier_game FROM supplier_removed WHERE supplier_code = ''")}
    entries = []
    for c in cats:
        code = str(c.get("game_code") or "").strip()
        supported, _ = catalog.classify_fields(c.get("game_fields"))
        if not code or not supported or len(code) > 45 or not all(
                ch.isalnum() or ch in "_.-" for ch in code):
            continue
        mark = "✅ " if code in have else ("🗑 " if code in removed else "")
        entries.append((f"{mark}{c.get('name') or code}", code))
    page = _int(_data(cb)[3])
    await edit_or_send(
        cb, f"🎮 <b>Choose a game to import</b> ({len(entries)})\n"
            "✅ = already in your shop, 🗑 = you deleted it (tap to bring it back).",
        kb.b2g_pick_kb(entries, page))


@router.callback_query(F.data.regexp(rf"^adm:b2g:one:{_CODE}$"))
async def cb_import_one(cb: CallbackQuery, db: Database, b2g: Optional[Bay2GameClient] = None):
    if b2g is None:
        await cb.answer()
        return
    if catalog._import_lock.locked():
        await cb.answer("An import is already running. Please wait.", show_alert=True)
        return
    await cb.answer()
    code = _data(cb)[3]
    await edit_or_send(cb, "⏳ Importing…")
    await edit_or_send(cb, await _run_import(db, b2g, code), kb.b2g_back_kb())


# --------------------------------------------------- profit, sync, auto, restore


@router.callback_query(F.data == "adm:b2g:margin")
async def cb_margin_start(cb: CallbackQuery, state: FSMContext, db: Database):
    current = await pricing.get_default_margin(db)
    await state.clear()
    await state.set_state(AdminFlow.b2g_margin)
    await cb.answer()
    await edit_or_send(
        cb,
        f"💲 Current profit per sale: <b>{money(current) if current is not None else 'not set'}</b>\n\n"
        "Send the profit in dollars you want on EVERY package (example: <code>0.01</code> or "
        "<code>0.20</code>).\nSelling price = Bay2Game cost + this profit.\n"
        "Send /cancel to stop.")


@router.message(AdminFlow.b2g_margin)
async def on_margin(message: Message, state: FSMContext, db: Database,
                    b2g: Optional[Bay2GameClient] = None):
    cents = parse_money(message.text)
    if cents is None:
        await message.answer("⚠️ Send a number like 0.01 or 0.20")
        return
    await state.clear()
    await pricing.set_default_margin(db, cents)
    text = f"✅ Profit = <b>{money(cents)}</b> per sale."
    if b2g is not None:
        changes, problems = await pricing.sync_prices(db, b2g)
        text += f"\n💲 {len(changes)} price(s) updated now."
        if problems:
            text += "\n⚠️ " + "\n⚠️ ".join(esc(x) for x in problems[:5])
    await message.answer(text, reply_markup=kb.b2g_back_kb())


@router.callback_query(F.data == "adm:b2g:sync")
async def cb_sync(cb: CallbackQuery, db: Database, b2g: Optional[Bay2GameClient] = None):
    if b2g is None:
        await cb.answer()
        return
    await cb.answer("Updating prices…")
    changes, problems = await pricing.sync_prices(db, b2g)
    text = ("💲 <b>Prices updated</b>\n" + pricing.describe(changes)[:3000]) if changes \
        else "✅ All prices are already correct."
    if problems:
        text += "\n\n⚠️ " + "\n⚠️ ".join(esc(x) for x in problems[:8])
    await edit_or_send(cb, text, kb.b2g_back_kb())


@router.callback_query(F.data == "adm:b2g:auto")
async def cb_auto(cb: CallbackQuery, db: Database, settings: Settings,
                  b2g: Optional[Bay2GameClient] = None):
    await catalog.set_auto_import(db, not await catalog.auto_import_enabled(db))
    await cb.answer("Updated ✅")
    await _show_panel(cb, db, b2g, settings)


@router.callback_query(F.data == "adm:b2g:restore")
async def cb_restore(cb: CallbackQuery, db: Database, settings: Settings,
                     b2g: Optional[Bay2GameClient] = None):
    n = await catalog.restore_removed(db)
    await cb.answer(f"{n} deleted item(s) can be imported again.", show_alert=True)
    await _show_panel(cb, db, b2g, settings)


# ------------------------------------------------------- delete / hide buttons


@router.callback_query(F.data.regexp(r"^adm:pdel:\d+$"))
async def cb_product_delete_ask(cb: CallbackQuery, db: Database):
    pid = _int(_data(cb)[2])
    product = await repo.get_product(db, pid)
    if product is None:
        await cb.answer("Product not found.", show_alert=True)
        return
    await cb.answer()
    await edit_or_send(
        cb, f"🗑 Delete <b>{esc(product['name'])}</b> ({esc(product['game_name'])})?\n"
            "Customers will no longer see it, and the automatic import will not add it back.",
        kb.confirm_delete_kb(f"adm:pdel:{pid}:y", f"adm:p:{pid}"))


@router.callback_query(F.data.regexp(r"^adm:pdel:\d+:y$"))
async def cb_product_delete(cb: CallbackQuery, db: Database):
    pid = _int(_data(cb)[2])
    product = await repo.get_product(db, pid)
    result = await catalog.delete_product(db, pid)
    await cb.answer("Done ✅" if result != "missing" else "Already gone.")
    back = kb.simple_home_kb([kb.button("⬅️ Games", "adm:products")])
    if product is not None:
        back = kb.simple_home_kb([kb.button("⬅️ Packages", f"adm:pg:{product['game_code']}")])
    if result == "hidden":
        text = ("🙈 This package already has orders, so it cannot be erased without breaking "
                "your order history. It is now <b>hidden</b> from customers and will not be "
                "added back.")
    elif result == "deleted":
        text = "✅ Package deleted."
    else:
        text = "That package was already deleted."
    await edit_or_send(cb, text, back)


@router.callback_query(F.data.regexp(r"^adm:gdel:[a-z0-9_]+$"))
async def cb_game_delete_ask(cb: CallbackQuery, db: Database):
    code = _data(cb)[2]
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer("Game not found.", show_alert=True)
        return
    n = len(await repo.list_products(db, code, only_active=False))
    await cb.answer()
    await edit_or_send(
        cb, f"🗑 Delete the game <b>{esc(game['name'])}</b> and its {n} package(s)?\n"
            "Customers will no longer see it, and the automatic import will not add it back.",
        kb.confirm_delete_kb(f"adm:gdel:{code}:y", f"adm:pg:{code}"))


@router.callback_query(F.data.regexp(r"^adm:gdel:[a-z0-9_]+:y$"))
async def cb_game_delete(cb: CallbackQuery, db: Database):
    code = _data(cb)[2]
    result = await catalog.delete_game(db, code)
    await cb.answer("Done ✅" if result != "missing" else "Already gone.")
    if result == "hidden":
        text = ("🙈 This game already has orders, so it cannot be erased without breaking your "
                "order history and sales report. It is now <b>hidden</b> from customers and "
                "will not be added back.")
    elif result == "deleted":
        text = "✅ Game deleted."
    else:
        text = "That game was already deleted."
    await edit_or_send(cb, text, kb.simple_home_kb([kb.button("⬅️ Games", "adm:products")]))


@router.callback_query(F.data.regexp(r"^adm:gtoggle:[a-z0-9_]+$"))
async def cb_game_toggle(cb: CallbackQuery, db: Database):
    code = _data(cb)[2]
    if not await catalog.toggle_game(db, code):
        await cb.answer("Game not found.", show_alert=True)
        return
    game = await repo.get_game(db, code)
    products = await repo.list_products(db, code, only_active=False)
    await cb.answer("Hidden 🙈" if not game["is_active"] else "Visible 👁")
    state = "" if game["is_active"] else "\n🚫 This game is HIDDEN from customers."
    await edit_or_send(
        cb, f"🛍 <b>{esc(game['name'])}</b> — {len(products)} product(s){state}\n"
            "✅ = active, 🚫 = disabled",
        kb.products_admin_kb(products, game, 0))
