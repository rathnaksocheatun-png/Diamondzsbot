"""Admin panel. Every handler in this file is locked to ADMIN_IDS (.env)."""
from aiogram import F, Bot, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database import repositories as repo
from app.database.db import Database
from app.handlers.states import AdminFlow
from app.keyboards import admin as kb
from app.services import orders as order_service
from app.services import reports
from app.services import wallet as wallet_service
from app.services.errors import NotFoundOrAlreadyHandled
from app.texts import t
from app.utils.filters import IsAdmin
from app.utils.formatting import esc, money, short_date
from app.utils.telegram import edit_or_send, notify_user
from app.utils.validators import (
    parse_money, to_int, valid_price, valid_product_name, valid_promo_text,
)

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

CUSTOMERS_PER_PAGE = 10
ORDERS_PER_PAGE = 8
PANEL_TEXT = "👑 <b>DIAMOND ZS — Admin Panel</b>\nChoose an option:"


def _data(cb: CallbackQuery) -> list:
    return (cb.data or "").split(":")


# ------------------------------------------------ premium emoji ID finder


@router.message(
    StateFilter(None),
    F.entities.func(lambda ents: any(e.type == "custom_emoji" for e in ents)),
)
async def cmd_emoji_ids(message: Message):
    """Admin sends a premium emoji -> the bot replies with its ID for custom_emoji.json."""
    found = {}
    for entity in message.entities or []:
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            found[entity.extract_from(message.text or "")] = entity.custom_emoji_id
    if not found:
        return
    lines = [f"{char} → <code>{emoji_id}</code>" for char, emoji_id in found.items()]
    snippet = ", ".join(f'"{char}": "{emoji_id}"' for char, emoji_id in found.items())
    await message.answer(
        "✨ <b>Premium emoji IDs</b>\n" + "\n".join(lines)
        + "\n\nAdd this to <code>custom_emoji.json</code>:\n<code>{" + esc(snippet) + "}</code>"
    )


# ------------------------------------------------------------------ home


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(PANEL_TEXT, reply_markup=kb.admin_menu_kb())


@router.callback_query(F.data == "adm:home")
async def cb_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await edit_or_send(cb, PANEL_TEXT, kb.admin_menu_kb())


@router.callback_query(F.data == "adm:close")
async def cb_close(cb: CallbackQuery):
    await cb.answer()
    if isinstance(cb.message, Message):
        try:
            await cb.message.delete()
        except Exception:
            pass


# ------------------------------------------------------------- customers


@router.callback_query(F.data.regexp(r"^adm:cust:\d+$"))
async def cb_customers(cb: CallbackQuery, db: Database):
    page = to_int(_data(cb)[2]) or 0
    total = await repo.count_users(db)
    users = await repo.list_users(db, CUSTOMERS_PER_PAGE, page * CUSTOMERS_PER_PAGE)
    lines = [f"👥 <b>Customers</b> ({total})", ""]
    if not users:
        lines.append("No customers yet.")
    for u in users:
        handle = f" @{esc(u['username'])}" if u["username"] else ""
        lines.append(
            f"• <code>{u['telegram_id']}</code> {esc(u['full_name'])}{handle}\n"
            f"   Wallet: {money(u['balance_cents'])} • Joined: {short_date(u['created_at'])}"
        )
    has_next = (page + 1) * CUSTOMERS_PER_PAGE < total
    await cb.answer()
    await edit_or_send(cb, "\n".join(lines), kb.customers_kb(page, has_next))


# ---------------------------------------------------------------- orders


def _auto_line(o: dict) -> str:
    state = o.get("auto_state")
    if not state:
        return ""
    labels = {"submitting": "🔄 being sent to Bay2Game", "done": "🤖 handled by Bay2Game",
              "review": "⚠️ needs your decision"}
    note = f"\n<i>{esc(o['supplier_note'])}</i>" if o.get("supplier_note") else ""
    return f"\nAuto-delivery: {labels.get(state, esc(state))}{note}"


def _order_text(o: dict) -> str:
    who = esc(o["user_name"]) + (f" (@{esc(o['user_username'])})" if o["user_username"] else "")
    zone = f"\nZone ID: <code>{esc(o['server_id'])}</code>" if o["server_id"] else ""
    return (
        f"📦 <b>Order #{o['id']}</b> — {kb.STATUS_ICON.get(o['status'], '')} {o['status']}\n\n"
        f"Customer: {who}\nTelegram ID: <code>{o['user_telegram_id']}</code>\n"
        f"Game: {esc(o['game_name'])}\nPackage: {esc(o['product_name'])}\n"
        f"Player ID: <code>{esc(o['player_id'])}</code>{zone}\n"
        f"Price: <b>{money(o['price_cents'])}</b>\n"
        f"Created: {short_date(o['created_at'])}\nUpdated: {short_date(o['updated_at'])}"
        + _auto_line(o)
    )


async def _show_order(cb: CallbackQuery, db: Database, order_id: int) -> None:
    order = await repo.get_order(db, order_id)
    if order is None:
        await edit_or_send(cb, "Order not found.", kb.simple_home_kb())
        return
    await edit_or_send(cb, _order_text(order), kb.order_detail_kb(order))


@router.callback_query(F.data.regexp(r"^adm:orders:(pending|completed|cancelled|all):\d+$"))
async def cb_orders(cb: CallbackQuery, db: Database):
    _, _, status, page_text = _data(cb)
    page = to_int(page_text) or 0
    db_status = None if status == "all" else status
    total = await repo.count_orders(db, db_status)
    orders = await repo.list_orders(db, db_status, ORDERS_PER_PAGE, page * ORDERS_PER_PAGE)
    text = f"📦 <b>Orders: {status}</b> ({total})"
    if not orders:
        text += "\n\nNo orders here."
    has_next = (page + 1) * ORDERS_PER_PAGE < total
    await cb.answer()
    await edit_or_send(cb, text, kb.orders_kb(orders, status, page, has_next))


@router.callback_query(F.data.regexp(r"^adm:order:\d+$"))
async def cb_order(cb: CallbackQuery, db: Database):
    await cb.answer()
    await _show_order(cb, db, to_int(_data(cb)[2]) or 0)


@router.callback_query(F.data.regexp(r"^adm:ostat:\d+:(completed|cancelled)$"))
async def cb_order_status(cb: CallbackQuery, db: Database, bot: Bot):
    order_id = to_int(_data(cb)[2]) or 0
    new_status = _data(cb)[3]
    order = await repo.get_order(db, order_id)
    if order is None:
        await cb.answer("Order not found.", show_alert=True)
        return
    if order.get("auto_state") == "submitting":
        await cb.answer("This order is being delivered automatically right now. "
                        "Wait a minute, then check it again.", show_alert=True)
        return
    try:
        if new_status == "completed":
            await order_service.complete_order(db, order_id)
        else:
            await order_service.cancel_order(db, order_id)  # also refunds the wallet
    except NotFoundOrAlreadyHandled:
        await cb.answer("This order was already handled.", show_alert=True)
        await _show_order(cb, db, order_id)
        return

    await cb.answer("Done ✅")
    lang = order["user_language"]
    if new_status == "completed":
        message = t(lang, "order_completed_user", id=order_id, product=esc(order["product_name"]))
    else:
        message = t(lang, "order_cancelled_user", id=order_id,
                    product=esc(order["product_name"]), price=money(order["price_cents"]))
    await notify_user(bot, order["user_telegram_id"], message)
    await _show_order(cb, db, order_id)


# -------------------------------------------------------------- products


def _product_text(p: dict) -> str:
    state = "✅ Active (customers can buy it)" if p["is_active"] else "🚫 Disabled (hidden from customers)"
    return (
        f"🛍 <b>{esc(p['name'])}</b>\nGame: {esc(p['game_name'])}\n"
        f"Price: <b>{money(p['price_cents'])}</b>\nStatus: {state}\nProduct ID: {p['id']}"
    )


async def _show_product(target, db: Database, product_id: int) -> None:
    """target can be a CallbackQuery (edit) or a Message (send new)."""
    product = await repo.get_product(db, product_id)
    if product is None:
        text, markup = "Product not found.", kb.simple_home_kb()
    else:
        text, markup = _product_text(product), kb.product_detail_kb(product)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^adm:products(:\d+)?$"))
async def cb_products(cb: CallbackQuery, db: Database):
    parts = _data(cb)
    page = to_int(parts[2]) or 0 if len(parts) > 2 else 0
    games = await repo.list_games(db)
    await cb.answer()
    await edit_or_send(
        cb, f"🛍 <b>Products</b> — {len(games)} game(s)\nChoose a game (🚫 = hidden from customers):",
        kb.games_admin_kb(games, page))


@router.callback_query(F.data.regexp(r"^adm:pg:[a-z0-9_]+(:\d+)?$"))
async def cb_game_products(cb: CallbackQuery, db: Database):
    parts = _data(cb)
    code = parts[2]
    page = to_int(parts[3]) or 0 if len(parts) > 3 else 0
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer("Game not found.", show_alert=True)
        return
    products = await repo.list_products(db, code, only_active=False)
    state = "" if game["is_active"] else "\n🚫 This game is HIDDEN from customers."
    text = (f"🛍 <b>{esc(game['name'])}</b> — {len(products)} product(s){state}\n"
            "✅ = active, 🚫 = disabled")
    await cb.answer()
    await edit_or_send(cb, text, kb.products_admin_kb(products, game, page))


@router.callback_query(F.data.regexp(r"^adm:p:\d+$"))
async def cb_product(cb: CallbackQuery, db: Database):
    await cb.answer()
    await _show_product(cb, db, to_int(_data(cb)[2]) or 0)


@router.callback_query(F.data.regexp(r"^adm:ptoggle:\d+$"))
async def cb_product_toggle(cb: CallbackQuery, db: Database):
    product_id = to_int(_data(cb)[2]) or 0
    if not await repo.toggle_product(db, product_id):
        await cb.answer("Product not found.", show_alert=True)
        return
    await cb.answer("Updated ✅")
    await _show_product(cb, db, product_id)


@router.callback_query(F.data.regexp(r"^adm:pprice:\d+$"))
async def cb_price_start(cb: CallbackQuery, state: FSMContext, db: Database):
    product_id = to_int(_data(cb)[2]) or 0
    product = await repo.get_product(db, product_id)
    if product is None:
        await cb.answer("Product not found.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.edit_price)
    await state.update_data(product_id=product_id)
    await cb.answer()
    await edit_or_send(
        cb,
        f"💲 Current price of <b>{esc(product['name'])}</b>: {money(product['price_cents'])}\n\n"
        "Send the NEW price in dollars (example: <code>2.50</code>).\nSend /cancel to stop.",
    )


@router.message(AdminFlow.edit_price)
async def on_new_price(message: Message, state: FSMContext, db: Database):
    cents = parse_money(message.text)
    if not valid_price(cents):
        await message.answer("⚠️ Invalid price. Send a number like 2.50 (more than 0).")
        return
    product_id = (await state.get_data()).get("product_id") or 0
    await state.clear()
    if not await repo.update_product_price(db, product_id, cents):
        await message.answer("Product not found.")
        return
    await message.answer("✅ Price updated.")
    await _show_product(message, db, product_id)


@router.callback_query(F.data.regexp(r"^adm:pname:\d+$"))
async def cb_name_start(cb: CallbackQuery, state: FSMContext, db: Database):
    product_id = to_int(_data(cb)[2]) or 0
    product = await repo.get_product(db, product_id)
    if product is None:
        await cb.answer("Product not found.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.edit_name)
    await state.update_data(product_id=product_id)
    await cb.answer()
    await edit_or_send(
        cb,
        f"✏️ Current name: <b>{esc(product['name'])}</b>\n\n"
        "Send the NEW name (2–40 characters).\nSend /cancel to stop.",
    )


@router.message(AdminFlow.edit_name)
async def on_new_name(message: Message, state: FSMContext, db: Database):
    name = valid_product_name(message.text)
    if name is None:
        await message.answer("⚠️ Name must be 2–40 characters of plain text.")
        return
    product_id = (await state.get_data()).get("product_id") or 0
    await state.clear()
    if not await repo.update_product_name(db, product_id, name):
        await message.answer("Product not found.")
        return
    await message.answer("✅ Name updated.")
    await _show_product(message, db, product_id)


@router.callback_query(F.data.regexp(r"^adm:padd:[a-z0-9_]+$"))
async def cb_add_start(cb: CallbackQuery, state: FSMContext, db: Database):
    code = _data(cb)[2]
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer("Game not found.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.add_name)
    await state.update_data(game_code=code)
    await cb.answer()
    await edit_or_send(
        cb,
        f"➕ New product for <b>{esc(game['name'])}</b>\n\n"
        "Send the product name (example: <code>310 Diamonds</code>).\nSend /cancel to stop.",
    )


@router.message(AdminFlow.add_name)
async def on_add_name(message: Message, state: FSMContext):
    name = valid_product_name(message.text)
    if name is None:
        await message.answer("⚠️ Name must be 2–40 characters of plain text.")
        return
    await state.update_data(name=name)
    await state.set_state(AdminFlow.add_price)
    await message.answer(
        f"Name: <b>{esc(name)}</b>\nNow send the price in dollars (example: <code>3.00</code>)."
    )


@router.message(AdminFlow.add_price)
async def on_add_price(message: Message, state: FSMContext, db: Database):
    cents = parse_money(message.text)
    if not valid_price(cents):
        await message.answer("⚠️ Invalid price. Send a number like 3.00 (more than 0).")
        return
    data = await state.get_data()
    await state.clear()
    if not data.get("game_code") or not data.get("name"):
        await message.answer("Session expired. Open /admin and try again.")
        return
    product_id = await repo.add_product(db, data["game_code"], data["name"], cents)
    await message.answer("✅ Product added.")
    await _show_product(message, db, product_id)


# -------------------------------------------------------------- deposits


async def _show_deposits(cb: CallbackQuery, db: Database) -> None:
    deposits = await repo.list_pending_deposits(db, 10)
    if not deposits:
        await edit_or_send(cb, "💰 <b>Deposits</b>\n\nNo pending deposit requests.", kb.simple_home_kb())
        return
    lines = ["💰 <b>Pending deposit requests</b>",
             "Approve only after you have received the money yourself.", ""]
    for d in deposits:
        handle = f" @{esc(d['user_username'])}" if d["user_username"] else ""
        lines.append(
            f"#{d['id']} • <b>{money(d['amount_cents'])}</b> • {esc(d['user_name'])}{handle}\n"
            f"   ID <code>{d['user_telegram_id']}</code> • {short_date(d['created_at'])}"
        )
    await edit_or_send(cb, "\n".join(lines), kb.deposits_kb(deposits))


@router.callback_query(F.data == "adm:deposits")
async def cb_deposits(cb: CallbackQuery, db: Database):
    await cb.answer()
    await _show_deposits(cb, db)


@router.callback_query(F.data.regexp(r"^adm:dep:(ok|no):\d+$"))
async def cb_deposit_decision(cb: CallbackQuery, db: Database, bot: Bot):
    _, _, action, id_text = _data(cb)
    deposit_id = to_int(id_text) or 0
    deposit = await wallet_service.get_deposit(db, deposit_id)
    if deposit is None:
        await cb.answer("Deposit not found.", show_alert=True)
        return
    lang = deposit["user_language"]
    try:
        if action == "ok":
            new_balance = await wallet_service.approve_deposit(db, deposit_id)
            message = t(lang, "deposit_approved_user", id=deposit_id,
                        amount=money(deposit["amount_cents"]), balance=money(new_balance))
        else:
            await wallet_service.reject_deposit(db, deposit_id)
            message = t(lang, "deposit_rejected_user", id=deposit_id,
                        amount=money(deposit["amount_cents"]))
    except NotFoundOrAlreadyHandled:
        await cb.answer("This request was already handled.", show_alert=True)
        await _show_deposits(cb, db)
        return
    await cb.answer("Done ✅")
    await notify_user(bot, deposit["user_telegram_id"], message)
    await _show_deposits(cb, db)


# --------------------------------------------------------------- reports


@router.callback_query(F.data == "adm:reports")
async def cb_reports(cb: CallbackQuery, db: Database):
    r = await reports.sales_report(db)
    status = r["by_status"]

    def row(name: str) -> str:
        item = status.get(name)
        return f"{item['n']} order(s) • {money(item['total'])}" if item else "0 order(s) • $0.00"

    lines = [
        "📊 <b>Sales report</b>", "",
        f"👥 Customers: <b>{r['customers']}</b>", "",
        "<b>Orders</b>",
        f"⏳ Pending: {row('pending')}",
        f"✅ Completed: {row('completed')}",
        f"❌ Cancelled: {row('cancelled')}", "",
        f"📅 Completed today: {r['today']['n']} order(s) • <b>{money(r['today']['total'])}</b>", "",
        "<b>Money</b>",
        f"💰 Approved deposits: {r['deposits']['n']} • {money(r['deposits']['total'])}",
        f"⏳ Pending deposit requests: {r['pending_deposits']}",
        f"👛 Total in customer wallets: {money(r['wallets_total'])}", "",
        "<b>Completed sales by game</b>",
    ]
    for g in r["per_game"]:
        lines.append(f"• {esc(g['name'])}: {g['n']} • {money(g['total'])}")
    await cb.answer()
    await edit_or_send(cb, "\n".join(lines), kb.simple_home_kb())


# ------------------------------------------------------------- promotions


@router.callback_query(F.data == "adm:promo")
async def cb_promo_start(cb: CallbackQuery, state: FSMContext, db: Database):
    current = await repo.get_setting(db, "promo_text")
    await state.clear()
    await state.set_state(AdminFlow.promo)
    await cb.answer()
    await edit_or_send(
        cb,
        "🎁 <b>Promotions text</b>\n\n"
        f"Current:\n{esc(current) if current else '(empty)'}\n\n"
        "Send the new text (max 1500 characters). Send <code>-</code> to clear it.\n"
        "Send /cancel to stop.",
    )


@router.message(AdminFlow.promo)
async def on_promo_text(message: Message, state: FSMContext, db: Database):
    text = valid_promo_text(message.text)
    if text is None:
        await message.answer("⚠️ Send text between 1 and 1500 characters.")
        return
    await state.clear()
    await repo.set_setting(db, "promo_text", "" if text == "-" else text)
    await message.answer("✅ Promotions updated." if text != "-" else "✅ Promotions cleared.",
                         reply_markup=kb.simple_home_kb())
