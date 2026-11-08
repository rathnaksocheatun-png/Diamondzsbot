"""Buying: choose game -> package -> Player ID (-> Zone ID) -> confirm."""
import asyncio
from typing import Optional

from aiogram import F, Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.handlers.states import OrderFlow
from app.keyboards.admin import view_order_kb
from app.keyboards.user import (
    back_to_games_kb, cancel_kb, confirm_kb, games_kb, products_kb,
)
from app.services import fulfilment
from app.services import orders as order_service
from app.services.bay2game import Bay2GameClient
from app.services.errors import DuplicateOrder, InsufficientBalance, ProductUnavailable
from app.texts import t
from app.utils.formatting import esc, money, short_date
from app.utils.telegram import edit_or_send, notify_admins
from app.utils.validators import to_int, valid_player_id, valid_server_id

router = Router(name="shop")
_background: set = set()      # keeps running delivery jobs alive until they finish


async def show_games(target: Message, db: Database, lang: str) -> None:
    games = await repo.list_games(db)
    await target.answer(t(lang, "choose_game"), reply_markup=games_kb(games))


async def show_orders(target: Message, db: Database, user: dict) -> None:
    lang = user["language"]
    orders = await repo.list_user_orders(db, user["id"], 10)
    if not orders:
        await target.answer(t(lang, "orders_empty"))
        return
    lines = [t(lang, "orders_title"), ""]
    for o in orders:
        lines.append(t(
            lang, "order_line",
            id=o["id"], product=esc(o["product_name"]), price=money(o["price_cents"]),
            status=t(lang, f"status_{o['status']}"),
            player_id=esc(o["player_id"]), date=short_date(o["created_at"]),
        ))
    await target.answer(lines[0] + "\n\n" + "\n\n".join(lines[2:]))


@router.callback_query(F.data == "buy:back")
async def on_back_to_games(cb: CallbackQuery, db: Database, user: dict):
    await cb.answer()
    games = await repo.list_games(db)
    await edit_or_send(cb, t(user["language"], "choose_game"), games_kb(games))


@router.callback_query(F.data.startswith("game:"))
async def on_game(cb: CallbackQuery, db: Database, user: dict):
    lang = user["language"]
    code = (cb.data or "").split(":", 1)[1]
    game = await repo.get_game(db, code)
    if game is None:
        await cb.answer(t(lang, "product_unavailable"), show_alert=True)
        return
    await cb.answer()
    products = await repo.list_products(db, code, only_active=True)
    if not products:
        await edit_or_send(cb, t(lang, "no_products"), back_to_games_kb(lang))
        return
    await edit_or_send(
        cb,
        t(lang, "choose_package", game=f"{game['emoji']} <b>{esc(game['name'])}</b>"),
        products_kb(products, lang),
    )


@router.callback_query(F.data.startswith("pkg:"))
async def on_package(cb: CallbackQuery, state: FSMContext, db: Database, user: dict):
    lang = user["language"]
    product_id = to_int((cb.data or "").split(":", 1)[1])
    product = await repo.get_product(db, product_id) if product_id else None
    if product is None or not product["is_active"]:
        await cb.answer(t(lang, "product_unavailable"), show_alert=True)
        return
    await state.clear()
    await state.set_state(OrderFlow.player_id)
    await state.update_data(product_id=product["id"])
    await cb.answer()
    await edit_or_send(
        cb,
        t(lang, "ask_player_id", product=esc(product["name"]),
          price=money(product["price_cents"]), game=esc(product["game_name"])),
        cancel_kb(lang),
    )


async def _show_summary(target: Message, state: FSMContext, db: Database, user: dict) -> bool:
    lang = user["language"]
    data = await state.get_data()
    product = await repo.get_product(db, data.get("product_id") or 0)
    if product is None or not product["is_active"] or not data.get("player_id"):
        await state.clear()
        await target.answer(t(lang, "product_unavailable"))
        return False
    server_id = data.get("server_id") or ""
    server_line = t(lang, "server_line", server_id=esc(server_id)) if server_id else ""
    await state.set_state(OrderFlow.confirm)
    await target.answer(
        t(lang, "order_summary",
          game=esc(product["game_name"]), product=esc(product["name"]),
          player_id=esc(data["player_id"]), server_line=server_line,
          price=money(product["price_cents"]), balance=money(user["balance_cents"])),
        reply_markup=confirm_kb(lang),
    )
    return True


@router.message(OrderFlow.player_id)
async def on_player_id(message: Message, state: FSMContext, db: Database, user: dict):
    lang = user["language"]
    player_id = valid_player_id(message.text)
    if player_id is None:
        await message.answer(t(lang, "invalid_player_id"), reply_markup=cancel_kb(lang))
        return
    data = await state.get_data()
    product = await repo.get_product(db, data.get("product_id") or 0)
    if product is None or not product["is_active"]:
        await state.clear()
        await message.answer(t(lang, "product_unavailable"))
        return
    await state.update_data(player_id=player_id, server_id="")
    if product["needs_server_id"]:
        await state.set_state(OrderFlow.server_id)
        await message.answer(t(lang, "ask_server_id"), reply_markup=cancel_kb(lang))
    else:
        await _show_summary(message, state, db, user)


@router.message(OrderFlow.server_id)
async def on_server_id(message: Message, state: FSMContext, db: Database, user: dict):
    lang = user["language"]
    server_id = valid_server_id(message.text)
    if server_id is None:
        await message.answer(t(lang, "invalid_server_id"), reply_markup=cancel_kb(lang))
        return
    await state.update_data(server_id=server_id)
    await _show_summary(message, state, db, user)


@router.callback_query(OrderFlow.confirm, F.data == "order:confirm")
async def on_confirm(
    cb: CallbackQuery, state: FSMContext, db: Database, user: dict,
    bot: Bot, settings: Settings, b2g: Optional[Bay2GameClient] = None,
):
    lang = user["language"]
    data = await state.get_data()
    product_id, player_id = data.get("product_id"), data.get("player_id")
    if not product_id or not player_id:
        await state.clear()
        await cb.answer(t(lang, "session_expired"), show_alert=True)
        return

    # Clear the state FIRST: a second tap on Confirm then finds nothing to confirm.
    await state.clear()
    await cb.answer()
    try:
        order_id = await order_service.create_order(
            db, cb.from_user.id, product_id, player_id, data.get("server_id") or ""
        )
    except InsufficientBalance as exc:
        await edit_or_send(cb, t(
            lang, "insufficient",
            price=money(exc.price_cents), balance=money(exc.balance_cents)))
        return
    except DuplicateOrder:
        await edit_or_send(cb, t(lang, "duplicate_order"))
        return
    except ProductUnavailable:
        await edit_or_send(cb, t(lang, "product_unavailable"))
        return

    order = await repo.get_order(db, order_id)
    auto = False
    if b2g is not None:
        row = await db.fetchone(
            "SELECT supplier_code FROM products WHERE id = ?", (order["product_id"],))
        auto = bool(row and row["supplier_code"])
    await edit_or_send(cb, t(
        lang, "order_created_auto" if auto else "order_created",
        id=order_id, price=money(order["price_cents"])))
    if auto:
        # Deliver in the background; the admin is told only if something needs a human.
        task = asyncio.create_task(
            fulfilment.run_fulfilment(bot, db, b2g, settings, order_id))
        _background.add(task)
        task.add_done_callback(_background.discard)
        return

    who = esc(user["full_name"]) + (f" (@{esc(user['username'])})" if user["username"] else "")
    zone = f"\nZone ID: <code>{esc(order['server_id'])}</code>" if order["server_id"] else ""
    await notify_admins(
        bot, settings,
        f"🆕 <b>New order #{order_id}</b>\nCustomer: {who}\n"
        f"Game: {esc(order['game_name'])}\nPackage: {esc(order['product_name'])}\n"
        f"Player ID: <code>{esc(order['player_id'])}</code>{zone}\n"
        f"Paid from wallet: <b>{money(order['price_cents'])}</b>",
        reply_markup=view_order_kb(order_id),
    )
