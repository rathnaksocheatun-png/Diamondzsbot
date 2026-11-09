"""Automatic diamond delivery through Bay2Game.

Money-safety rules built into this file:
  * One order is sent to the supplier AT MOST ONCE: it is "claimed" with an atomic
    database update first, and the supplier reference (DZS<order id, 6 digits>) is
    unique, so even a repeated request cannot buy twice.
  * We never buy at a loss: if the supplier price is higher than our selling price
    the order is NOT sent; an admin is asked to decide.
  * A clear refusal from the supplier (e.g. invalid Player ID) refunds the customer's
    wallet. A supplier-side problem (no balance, maintenance...) or any UNCLEAR
    answer (timeout, broken reply) never refunds and never retries blindly: the
    order is marked "review" and an admin is told. Orders stuck mid-delivery are
    re-checked with the supplier's check_order by reference.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.keyboards.admin import view_order_kb
from app.services import orders as order_service
from app.services.bay2game import (
    Bay2GameClient, Bay2GameError, Bay2GameFailed, OrderNotFound, OrderResult,
)
from app.services.errors import NotFoundOrAlreadyHandled
from app.texts import t
from app.utils.formatting import esc, money
from app.utils.telegram import notify_admins, notify_user

log = logging.getLogger(__name__)

# A refusal containing one of these words is a SUPPLIER-side problem, not the
# customer's fault, so we keep the order for an admin instead of refunding.
SUPPLIER_SIDE_HINTS = (
    "insufficient", "balance", "maintenance", "unavailable", "disabled", "temporar",
    "try again", "rate limit", "too many", "not active", "inactive", "api key",
    "permission", "suspended", "stock",
)
STUCK_AFTER_MINUTES = 2
SWEEP_INTERVAL = 60.0


@dataclass
class Outcome:
    kind: str                 # delivered | refunded | review | manual | skipped | pending
    detail: str = ""
    supplier_balance_cents: Optional[int] = None


def reference_for(prefix: str, order_id: int) -> str:
    """Bay2Game wants 6-64 characters, letters and/or numbers only (no '-' or '_').

    Order 4 with prefix 'DZS' -> 'DZS000004'.
    """
    clean = "".join(ch for ch in str(prefix) if ch.isalnum()) or "DZS"
    return f"{clean}{order_id:06d}"


# ----------------------------------------------------------------- state helpers


async def _set_state(db: Database, order_id: int, state: Optional[str], note: str = "") -> None:
    await db.execute(
        "UPDATE orders SET auto_state = ?, supplier_note = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (state, note[:300], order_id),
    )


async def _review(db: Database, order_id: int, note: str) -> Outcome:
    await _set_state(db, order_id, "review", note)
    return Outcome("review", note)


async def _deliver(db: Database, order_id: int, result: Optional[OrderResult],
                   price_cents: int) -> Outcome:
    note = "delivered by Bay2Game"
    if result is not None and result.amount_cents is not None and result.amount_cents > price_cents:
        note += f" (supplier charged {money(result.amount_cents)}, more than the selling price!)"
    try:
        await order_service.complete_order(db, order_id)
    except NotFoundOrAlreadyHandled:
        # Delivered at the supplier, but the order was already closed here.
        return await _review(
            db, order_id,
            "Supplier DELIVERED this order, but it was already completed/cancelled in the "
            "bot. If it was cancelled and refunded, you have paid twice - check the wallet.",
        )
    await _set_state(db, order_id, "done", note)
    balance = result.balance_after_cents if result else None
    return Outcome("delivered", note, balance)


async def _refund(db: Database, order_id: int, reason: str) -> Outcome:
    try:
        await order_service.cancel_order(db, order_id)   # refunds the wallet, only once
    except NotFoundOrAlreadyHandled:
        return await _review(db, order_id, f"Refund needed but order already handled ({reason})")
    await _set_state(db, order_id, "done", f"refunded: {reason}")
    return Outcome("refunded", reason)


# --------------------------------------------------------------------- delivering


async def fulfil_order(db: Database, client: Bay2GameClient, order_id: int,
                       ref_prefix: str) -> Outcome:
    """Send ONE pending order to Bay2Game (if its product is mapped)."""
    claimed = await db.execute(
        "UPDATE orders SET auto_state = 'submitting', updated_at = datetime('now') "
        "WHERE id = ? AND status = 'pending' AND auto_state IS NULL",
        (order_id,),
    )
    if claimed != 1:
        return Outcome("skipped")
    row = await db.fetchone(
        "SELECT o.*, p.supplier_game, p.supplier_code FROM orders o "
        "JOIN products p ON p.id = o.product_id WHERE o.id = ?",
        (order_id,),
    )
    if row is None or not row["supplier_code"] or not row["supplier_game"]:
        await db.execute("UPDATE orders SET auto_state = NULL WHERE id = ?", (order_id,))
        return Outcome("manual")

    # Never buy at a loss.
    try:
        supplier_product = await client.find_product(row["supplier_game"], row["supplier_code"])
    except Bay2GameError as exc:
        return await _review(db, order_id, f"Could not check the supplier price: {exc}")
    if supplier_product is None or not supplier_product.active:
        return await _review(
            db, order_id,
            f"Supplier package {row['supplier_code']} is missing or inactive.")
    if supplier_product.price_cents > row["price_cents"]:
        return await _review(
            db, order_id,
            f"Supplier price {money(supplier_product.price_cents)} is higher than your "
            f"selling price {money(row['price_cents'])} - not sent.")

    reference = reference_for(ref_prefix, order_id)
    await db.execute("UPDATE orders SET supplier_ref = ? WHERE id = ?", (reference, order_id))
    try:
        result = await client.create_order(
            row["supplier_code"], row["player_id"], row["server_id"], reference)
    except Bay2GameFailed as exc:
        message = str(exc)
        if any(hint in message.lower() for hint in SUPPLIER_SIDE_HINTS):
            return await _review(db, order_id, f"Supplier problem: {message}")
        return await _refund(db, order_id, message or "order failed")
    except Bay2GameError as exc:
        # Unclear answer: ask the supplier what really happened (by our reference).
        log.warning("Unclear Bay2Game answer for order #%s: %s", order_id, exc)
        return await resolve_by_check(db, client, order_id, ref_prefix, after_unclear=True)
    return await _deliver(db, order_id, result, row["price_cents"])


async def resolve_by_check(db: Database, client: Bay2GameClient, order_id: int,
                           ref_prefix: str, after_unclear: bool = False) -> Outcome:
    """Find out from Bay2Game what happened to an order and finish it."""
    row = await db.fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if row is None or row["status"] != "pending":
        return Outcome("skipped")
    reference = row["supplier_ref"]
    if not reference:
        return await _review(db, order_id, "Interrupted before it was sent to the supplier.")
    try:
        status = await client.check_order(reference)
    except OrderNotFound:
        return await _review(
            db, order_id,
            "Bay2Game has no record of this order (it was probably not placed). "
            "Verify in the Bay2Game dashboard, then complete or cancel it here.")
    except Bay2GameError as exc:
        return await _review(db, order_id, f"Could not confirm with Bay2Game: {exc}")
    if status.status == "success":
        return await _deliver(db, order_id, None, row["price_cents"])
    if status.status == "failed":
        return await _refund(db, order_id, "supplier reported the order as failed")
    return await _review(db, order_id, "Bay2Game still shows this order as processing.")


# ------------------------------------------------------------------ notifications


async def announce(bot: Bot, settings: Settings, order: dict, outcome: Outcome) -> None:
    lang = order["user_language"]
    chat = order["user_telegram_id"]
    oid = order["id"]
    product = esc(order["product_name"])
    if outcome.kind == "delivered":
        await notify_user(bot, chat, t(lang, "order_completed_user", id=oid, product=product))
        text = f"✅ Auto-delivered order #{oid} ({product}) to ID <code>{esc(order['player_id'])}</code>."
        bal = outcome.supplier_balance_cents
        if bal is not None:
            text += f"\nBay2Game balance: <b>{money(bal)}</b>"
            if bal < settings.bay2game_low_balance_cents:
                text += "\n⚠️ <b>Low balance - top up Bay2Game soon, or orders will stop.</b>"
        await notify_admins(bot, settings, text)
    elif outcome.kind == "refunded":
        await notify_user(bot, chat, t(
            lang, "order_cancelled_user", id=oid, product=product,
            price=money(order["price_cents"])))
        await notify_admins(
            bot, settings,
            f"↩️ Order #{oid} ({product}) was refunded automatically.\nReason: {esc(outcome.detail)}")
    elif outcome.kind == "review":
        await notify_user(bot, chat, t(lang, "order_review_user", id=oid, product=product))
        await notify_admins(
            bot, settings,
            f"⚠️ <b>Order #{oid} needs your attention.</b>\n{esc(outcome.detail)}\n\n"
            "The customer's money is still held. Check it, then complete or cancel the order.",
            reply_markup=view_order_kb(oid),
        )


async def run_fulfilment(bot: Bot, db: Database, client: Bay2GameClient,
                         settings: Settings, order_id: int) -> None:
    """Background job started after a customer's order is created."""
    try:
        outcome = await fulfil_order(db, client, order_id, settings.bay2game_ref_prefix)
        order = await repo.get_order(db, order_id)
        if order is None:
            return
        if outcome.kind in ("delivered", "refunded", "review"):
            await announce(bot, settings, order, outcome)
        elif outcome.kind == "manual":
            await notify_admins(
                bot, settings,
                f"🆕 <b>New order #{order_id}</b> needs manual delivery.\n"
                f"{esc(order['game_name'])} - {esc(order['product_name'])}\n"
                f"Player ID: <code>{esc(order['player_id'])}</code>",
                reply_markup=view_order_kb(order_id))
    except Exception:
        log.exception("Unexpected error while delivering order #%s", order_id)
        try:
            await _set_state(db, order_id, "review", "Unexpected bot error - check the logs.")
            await notify_admins(bot, settings, f"⚠️ Order #{order_id}: unexpected error during "
                                "automatic delivery. Please check it manually.",
                                reply_markup=view_order_kb(order_id))
        except Exception:
            log.exception("Could not even report the failure for order #%s", order_id)


async def watch_stuck_orders(bot: Bot, db: Database, client: Bay2GameClient,
                             settings: Settings) -> None:
    """Every minute: finish orders that got stuck 'submitting' (e.g. the bot restarted)."""
    while True:
        try:
            rows = await db.fetchall(
                "SELECT id FROM orders WHERE status = 'pending' AND auto_state = 'submitting' "
                "AND updated_at < datetime('now', ?) ORDER BY id LIMIT 20",
                (f"-{STUCK_AFTER_MINUTES} minutes",),
            )
            for r in rows:
                outcome = await resolve_by_check(
                    db, client, r["id"], settings.bay2game_ref_prefix)
                order = await repo.get_order(db, r["id"])
                if order is not None and outcome.kind in ("delivered", "refunded", "review"):
                    await announce(bot, settings, order, outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Stuck-order sweeper error")
        await asyncio.sleep(SWEEP_INTERVAL)
