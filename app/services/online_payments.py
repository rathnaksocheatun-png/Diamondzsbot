"""Automatic deposits through KHPAY.

Safety rules built into this file:
  * A wallet is credited ONLY after KHPAY itself says "paid" when WE ask it
    (we never trust a redirect, a screenshot or a user message).
  * The amount KHPAY reports must equal the amount we asked for.
  * Crediting reuses wallet.approve_deposit, which flips the deposit from
    'pending' to 'approved' atomically - so the same payment can never be
    credited twice, even if the watcher and a button press race each other.
  * If anything is unclear (gateway down, wrong amount) the wallet is NOT
    credited and an admin is told.
"""
import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.config import Settings
from app.database.db import Database
from app.services import wallet as wallet_service
from app.services.errors import DuplicateDeposit, NotFoundOrAlreadyHandled
from app.services.khpay import KhpayClient, KhpayError, QrPayment, cents_to_amount
from app.texts import t
from app.utils.formatting import esc, money
from app.utils.telegram import notify_admins, notify_user

log = logging.getLogger(__name__)

PROVIDER = "khpay"
# KHPAY QR codes live ~180 s. We keep checking a little longer than that so a
# payment made in the last second is never missed.
GRACE_SECONDS = 120
WATCH_INTERVAL = 4.0
MAX_PARALLEL_CHECKS = 8


@dataclass
class Outcome:
    kind: str                 # credited | pending | expired | failed | mismatch | already | error
    balance_cents: int = 0
    detail: str = ""


# --------------------------------------------------------------- start / cancel


async def start_online_deposit(
    db: Database, client: KhpayClient, telegram_id: int, amount_cents: int
) -> tuple:
    """Create the deposit row, then ask KHPAY for a QR. Returns (deposit_id, QrPayment)."""
    try:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cur.fetchone()
            # Forget our own stale online requests so they cannot block a new one.
            await conn.execute(
                "UPDATE deposit_requests SET status = 'rejected', decided_at = datetime('now') "
                "WHERE user_id = ? AND status = 'pending' AND provider = ? AND "
                "((expires_at IS NOT NULL AND expires_at < datetime('now')) OR "
                " (external_id IS NULL AND created_at < datetime('now', '-3 minutes')))",
                (user["id"], PROVIDER),
            )
            cur = await conn.execute(
                "SELECT * FROM deposit_requests WHERE user_id = ? AND status = 'pending'",
                (user["id"],),
            )
            existing = await cur.fetchone()
            if existing is not None:
                raise DuplicateDeposit(dict(existing))
            cur = await conn.execute(
                "INSERT INTO deposit_requests (user_id, amount_cents, provider) "
                "VALUES (?, ?, ?)",
                (user["id"], amount_cents, PROVIDER),
            )
            deposit_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise DuplicateDeposit({"id": 0, "amount_cents": amount_cents})

    try:
        qr = await client.generate_qr(
            amount_cents,
            note=f"Deposit #{deposit_id}",
            metadata={"deposit_id": str(deposit_id)},
            idempotency_key=f"diamondzs-dep-{deposit_id}",
        )
    except KhpayError:
        await _mark_rejected(db, deposit_id)
        raise
    await db.execute(
        "UPDATE deposit_requests SET external_id = ?, "
        "expires_at = datetime('now', ?) WHERE id = ?",
        (qr.transaction_id, f"+{qr.expires_in + GRACE_SECONDS} seconds", deposit_id),
    )
    return deposit_id, qr


async def cancel_online_deposit(
    db: Database, client: KhpayClient, telegram_id: int, deposit_id: int
) -> Outcome:
    """Customer pressed Cancel. If they actually already paid, credit instead."""
    dep = await _get(db, deposit_id)
    if dep is None or dep["user_telegram_id"] != telegram_id or dep["provider"] != PROVIDER:
        return Outcome("already")
    outcome = await settle_deposit(db, client, deposit_id)
    if outcome.kind != "pending":
        return outcome
    if await _mark_rejected(db, deposit_id) and dep["external_id"]:
        await client.expire(dep["external_id"])
    return Outcome("expired", detail="cancelled")


# ------------------------------------------------------------------- settling


async def _get(db: Database, deposit_id: int) -> Optional[dict]:
    return await db.fetchone(
        "SELECT d.*, u.telegram_id AS user_telegram_id, u.language AS user_language, "
        "u.full_name AS user_name, u.username AS user_username, "
        "(d.expires_at IS NOT NULL AND d.expires_at < datetime('now')) AS is_late, "
        "(d.created_at < datetime('now', '-3 minutes')) AS is_old "
        "FROM deposit_requests d JOIN users u ON u.id = d.user_id WHERE d.id = ?",
        (deposit_id,),
    )


get_deposit = _get


async def _mark_rejected(db: Database, deposit_id: int) -> bool:
    changed = await db.execute(
        "UPDATE deposit_requests SET status = 'rejected', decided_at = datetime('now') "
        "WHERE id = ? AND status = 'pending'",
        (deposit_id,),
    )
    return changed == 1


async def settle_deposit(db: Database, client: KhpayClient, deposit_id: int) -> Outcome:
    """Ask KHPAY about one pending online deposit and act on the answer."""
    dep = await _get(db, deposit_id)
    if dep is None or dep["status"] != "pending" or dep["provider"] != PROVIDER:
        return Outcome("already")

    if not dep["external_id"]:
        # We created the row but never got a QR back (crash / gateway error).
        if dep["is_old"]:
            await _mark_rejected(db, deposit_id)
            return Outcome("expired")
        return Outcome("pending")

    try:
        status = await client.check(dep["external_id"])
    except KhpayError as exc:
        log.warning("KHPAY check failed for deposit #%s: %s", deposit_id, exc)
        return Outcome("error", detail=str(exc))

    if status.paid:
        wrong_amount = (
            status.amount_cents is not None and status.amount_cents != dep["amount_cents"]
        )
        wrong_currency = bool(status.currency) and status.currency != "USD"
        if wrong_amount or wrong_currency:
            await _mark_rejected(db, deposit_id)
            return Outcome(
                "mismatch",
                detail=(
                    f"expected {cents_to_amount(dep['amount_cents'])} USD, gateway says "
                    f"{status.amount_cents} cents {status.currency} (txn {dep['external_id']})"
                ),
            )
        try:
            balance = await wallet_service.approve_deposit(db, deposit_id)
        except NotFoundOrAlreadyHandled:
            return Outcome("already")
        return Outcome("credited", balance_cents=balance)

    if status.status in ("expired", "failed"):
        await _mark_rejected(db, deposit_id)
        return Outcome(status.status)

    if dep["is_late"]:
        # Past expiry + grace and still unpaid: give up on it.
        if await _mark_rejected(db, deposit_id):
            await client.expire(dep["external_id"])
        return Outcome("expired")
    return Outcome("pending")


# ---------------------------------------------------------------- notifications


async def announce_outcome(
    bot: Bot, settings: Settings, dep: dict, outcome: Outcome
) -> None:
    """Tell the customer (and admins when useful). Safe to call for any outcome."""
    lang = dep["user_language"]
    chat_id = dep["user_telegram_id"]
    amount = money(dep["amount_cents"])
    if outcome.kind == "credited":
        await notify_user(bot, chat_id, t(
            lang, "deposit_paid_user", id=dep["id"], amount=amount,
            balance=money(outcome.balance_cents),
        ))
        who = esc(dep["user_name"]) + (f" (@{esc(dep['user_username'])})" if dep["user_username"] else "")
        await notify_admins(
            bot, settings,
            f"✅ Auto deposit #{dep['id']} credited: <b>{amount}</b> to {who} "
            f"(ID <code>{chat_id}</code>).",
        )
    elif outcome.kind in ("expired", "failed"):
        key = "deposit_cancelled_user" if outcome.detail == "cancelled" else "deposit_expired_user"
        await notify_user(bot, chat_id, t(lang, key, id=dep["id"], amount=amount))
    elif outcome.kind == "mismatch":
        await notify_user(bot, chat_id, t(
            lang, "deposit_mismatch_user", id=dep["id"],
            support=esc(settings.support_username or "support"),
        ))
        await notify_admins(
            bot, settings,
            f"⚠️ <b>Deposit #{dep['id']} NOT credited - amount mismatch.</b>\n"
            f"{esc(outcome.detail)}\nCheck your KHPAY dashboard and handle it manually.",
        )


# ------------------------------------------------------------------- background


async def watch_payments(
    bot: Bot, db: Database, client: KhpayClient, settings: Settings
) -> None:
    """Runs forever: checks every pending online deposit every few seconds.

    It reads pending deposits from the database, so it also resumes correctly
    after the bot is restarted or redeployed.
    """
    gate = asyncio.Semaphore(MAX_PARALLEL_CHECKS)

    async def handle(deposit_id: int) -> None:
        async with gate:
            try:
                outcome = await settle_deposit(db, client, deposit_id)
                if outcome.kind in ("credited", "expired", "failed", "mismatch"):
                    dep = await _get(db, deposit_id)
                    if dep is not None:
                        await announce_outcome(bot, settings, dep, outcome)
            except Exception:
                log.exception("Unexpected error while settling deposit #%s", deposit_id)

    while True:
        try:
            rows = await db.fetchall(
                "SELECT id FROM deposit_requests WHERE status = 'pending' "
                "AND provider = ? ORDER BY id LIMIT 100",
                (PROVIDER,),
            )
            if rows:
                await asyncio.gather(*(handle(r["id"]) for r in rows))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Payment watcher loop error")
        await asyncio.sleep(WATCH_INTERVAL)


def qr_photo(qr: QrPayment) -> Optional[BufferedInputFile]:
    """Turn KHPAY's 'data:image/png;base64,...' string into a Telegram photo."""
    import base64
    if not qr.qr_image.startswith("data:image/") or "," not in qr.qr_image:
        return None
    try:
        raw = base64.b64decode(qr.qr_image.split(",", 1)[1], validate=False)
    except ValueError:
        return None
    return BufferedInputFile(raw, filename="khqr.png") if raw else None
