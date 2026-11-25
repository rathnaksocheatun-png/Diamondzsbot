"""Admin only: add money to / take money from a customer's wallet.

  /addbalance <id or @username> <amount> [note]
  /subbalance <id or @username> <amount> [note]

Examples:   /addbalance 123456789 5
            /subbalance @sokdara 2.50 wrong top-up

The bot first shows a summary with Confirm / Cancel buttons (a wrong ID or an extra
zero would be expensive), then changes the balance, saves a history line, and tells the
customer. The balance can never go below zero.
"""
import logging
import re
import secrets
import time
from decimal import Decimal

from aiogram import F, Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database import repositories as repo
from app.database.db import Database
from app.texts import t
from app.utils.filters import IsAdmin
from app.utils.formatting import esc, money, short_date
from app.utils.telegram import notify_user

log = logging.getLogger("diamond_zs.wallet_admin")

router = Router(name="wallet_admin")
router.message.filter(IsAdmin())

MAX_CENTS = 1_000_000          # $10,000 per change
PENDING_SECONDS = 600          # a confirmation button works for 10 minutes
_AMOUNT_RE = re.compile(r"^\$?(\d{1,5})(?:\.(\d{1,2}))?$")
_pending: dict = {}            # token -> details of a change waiting for Confirm


def parse_amount(text: str):
    """'5' -> 500, '2.5' -> 250, '$0.30' -> 30. Returns cents, or None if invalid."""
    m = _AMOUNT_RE.match((text or "").strip())
    if not m:
        return None
    cents = int(Decimal(m.group(1)) * 100) + int((m.group(2) or "0").ljust(2, "0"))
    return cents if 0 < cents <= MAX_CENTS else None


def _purge() -> None:
    now = time.time()
    for token in [k for k, v in _pending.items() if v["expires"] < now]:
        _pending.pop(token, None)


def _who(user: dict) -> str:
    handle = f" @{esc(user['username'])}" if user.get("username") else ""
    return f"{esc(user['full_name'] or '-')}{handle} (<code>{user['telegram_id']}</code>)"


async def _start(message: Message, command: CommandObject, db: Database, sign: int) -> None:
    name = "addbalance" if sign > 0 else "subbalance"
    parts = (command.args or "").split(None, 2)
    if len(parts) < 2:
        await message.answer(
            f"{'➕' if sign > 0 else '➖'} <b>{'Add to' if sign > 0 else 'Deduct from'} a "
            f"customer's wallet</b>\n\n"
            f"<code>/{name} ID_or_@username amount [note]</code>\n"
            f"Example: <code>/{name} 123456789 5</code>\n"
            f"Amount is in dollars (up to 2 decimals, max ${MAX_CENTS // 100:,}). "
            "The customer's ID is shown in Admin → Customers (tap it to copy).")
        return
    ref, amount_text = parts[0], parts[1]
    note = parts[2].strip() if len(parts) > 2 else ""
    cents = parse_amount(amount_text)
    if cents is None:
        await message.answer(
            f"⚠️ Amount <code>{esc(amount_text)}</code> is not valid. Use a number such as "
            f"<code>5</code> or <code>2.50</code> (between 0.01 and {MAX_CENTS // 100:,}).")
        return
    user = await repo.find_user_by_ref(db, ref)
    if user is None:
        await message.answer(
            f"⚠️ No customer found for <code>{esc(ref)}</code>. Use the Telegram ID from "
            "Admin → Customers, or @username. The customer must have started the bot.")
        return
    delta = sign * cents
    new_balance = user["balance_cents"] + delta
    if new_balance < 0:
        await message.answer(
            f"⚠️ Not possible: {_who(user)} only has {money(user['balance_cents'])}, "
            f"you cannot deduct {money(cents)}.")
        return
    _purge()
    token = secrets.token_urlsafe(6)
    _pending[token] = {
        "admin": message.from_user.id, "user_id": user["id"],
        "telegram_id": user["telegram_id"], "delta": delta, "note": note,
        "expires": time.time() + PENDING_SECONDS,
    }
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm", callback_data=f"wadj:ok:{token}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"wadj:no:{token}"),
    ]])
    await message.answer(
        f"{'➕ <b>Add money</b>' if sign > 0 else '➖ <b>Deduct money</b>'}\n\n"
        f"Customer: {_who(user)}\n"
        f"Amount: <b>{'+' if sign > 0 else '-'}{money(cents)}</b>\n"
        f"Balance: {money(user['balance_cents'])} → <b>{money(new_balance)}</b>\n"
        + (f"Note: {esc(note)}\n" if note else "")
        + "\nPlease check the customer and amount, then confirm.",
        reply_markup=keyboard)


@router.message(Command("addbalance"))
async def cmd_addbalance(message: Message, command: CommandObject, db: Database):
    await _start(message, command, db, +1)


@router.message(Command("subbalance"))
async def cmd_subbalance(message: Message, command: CommandObject, db: Database):
    await _start(message, command, db, -1)


@router.callback_query(F.data.regexp(r"^wadj:(ok|no):[\w-]+$"))
async def cb_decision(cb: CallbackQuery, db: Database, bot: Bot):
    _, action, token = cb.data.split(":", 2)
    _purge()
    job = _pending.get(token)
    # Only the admin who asked can press the button (the token is also unguessable).
    if job is None or job["admin"] != cb.from_user.id:
        await cb.answer("This request expired. Send the command again.", show_alert=True)
        return
    _pending.pop(token, None)                      # one use only: no double-tap twice
    if action == "no":
        await cb.answer("Cancelled")
        await _edit(cb, "❌ Cancelled. Nothing was changed.")
        return
    try:
        new_balance = await repo.adjust_balance(
            db, job["user_id"], job["delta"],
            f"[manual] Admin {job['admin']}" + (f": {job['note']}" if job["note"] else ""))
    except repo.InsufficientBalance:
        await cb.answer("The customer no longer has enough money.", show_alert=True)
        await _edit(cb, "⚠️ Not done: the balance is now too low for this deduction.")
        return
    except LookupError:
        await cb.answer("Customer not found.", show_alert=True)
        return
    log.info("admin %s changed balance of user %s by %s cents (now %s)",
             job["admin"], job["telegram_id"], job["delta"], new_balance)
    await cb.answer("Done ✅")
    await _edit(cb, f"✅ Done. New balance: <b>{money(new_balance)}</b> "
                    f"({'+' if job['delta'] > 0 else '-'}{money(abs(job['delta']))}).")
    user = await db.fetchone("SELECT language FROM users WHERE id = ?", (job["user_id"],))
    key = "balance_added_user" if job["delta"] > 0 else "balance_deducted_user"
    await notify_user(bot, job["telegram_id"], t(
        (user or {}).get("language", "en"), key,
        amount=money(abs(job["delta"])), balance=money(new_balance)))


async def _edit(cb: CallbackQuery, text: str) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=None)
    except TelegramBadRequest:
        await cb.message.answer(text)


@router.message(Command("balancelog"))
async def cmd_balancelog(message: Message, command: CommandObject, db: Database):
    """/balancelog  -> last 15 manual changes;  /balancelog <id or @username> -> one customer."""
    arg = (command.args or "").strip()
    user_id = None
    title = "🧾 <b>Manual balance changes</b> (latest 15)"
    if arg:
        user = await repo.find_user_by_ref(db, arg.split()[0])
        if user is None:
            await message.answer(f"⚠️ No customer found for <code>{esc(arg)}</code>.")
            return
        user_id = user["id"]
        title = f"🧾 <b>Manual balance changes</b> — {_who(user)}"
    rows = await repo.list_manual_adjustments(db, user_id)
    if not rows:
        await message.answer(title + "\n\nNothing yet.")
        return
    lines = [title, ""]
    for r in rows:
        sign = "+" if r["amount_cents"] > 0 else "-"
        detail = r["note"].replace("[manual]", "", 1).strip()
        who = "" if user_id is not None else f" {esc(r['full_name'] or '-')} (<code>{r['telegram_id']}</code>)"
        lines.append(
            f"{short_date(r['created_at'])} • <b>{sign}{money(abs(r['amount_cents']))}</b>{who}\n"
            f"   → {money(r['balance_after_cents'])} • {esc(detail)}")
    await message.answer("\n".join(lines))


@router.message(Command("addcoin"))
async def cmd_addcoin(message: Message, command: CommandObject, db: Database, bot: Bot):
    """/addcoin <id or @username> <n>   (use a negative n to take coins back)"""
    parts = (command.args or "").split()
    n = int(parts[1]) if len(parts) == 2 and parts[1].lstrip("-").isdigit() else None
    if n is None or n == 0 or abs(n) > 1000:
        await message.answer("Use: <code>/addcoin ID_or_@username 3</code> (ដកកាក់: <code>-1</code>)")
        return
    user = await repo.find_user_by_ref(db, parts[0])
    if user is None:
        await message.answer("⚠️ រកអតិថិជនមិនឃើញ។")
        return
    await db.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE id = ?", (n, user["id"]))
    row = await db.fetchone("SELECT coins FROM users WHERE id = ?", (user["id"],))
    await message.answer(f"✅ កាក់របស់ {esc(user['full_name'])}: <b>{row['coins']}</b>")
    if n > 0:
        await notify_user(bot, user["telegram_id"],
                          f"🪙 អ្នកទទួលបាន {n} ដុំកាក់! បង្វិលកង់សំណាងក្នុង Mini App ➜ Profile។")
