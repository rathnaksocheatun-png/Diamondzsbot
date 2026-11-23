"""Wallet, transaction history and the deposit-request flow."""
import logging
from typing import Optional

from aiogram import F, Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.handlers.states import DepositFlow
from app.keyboards.admin import deposit_review_kb
from app.keyboards.user import cancel_kb, deposit_qr_kb, wallet_kb
from app.services import online_payments
from app.services import wallet as wallet_service
from app.services.errors import DuplicateDeposit
from app.services.khpay import KhpayClient, KhpayError
from app.texts import t
from app.utils.formatting import esc, money, short_date
from app.utils.telegram import notify_admins
from app.utils.validators import parse_money, to_int, valid_deposit

router = Router(name="wallet")
log = logging.getLogger(__name__)


async def show_wallet(target: Message, user: dict) -> None:
    lang = user["language"]
    await target.answer(
        t(lang, "wallet", balance=money(user["balance_cents"])),
        reply_markup=wallet_kb(lang),
    )


async def show_history(target: Message, db: Database, user: dict) -> None:
    lang = user["language"]
    rows = await repo.list_user_transactions(db, user["id"], 15)
    if not rows:
        await target.answer(t(lang, "history_empty"))
        return
    lines = [t(lang, "history_title"), ""]
    for r in rows:
        lines.append(t(
            lang, "tx_line",
            date=short_date(r["created_at"]),
            type=t(lang, "tx_referral" if (r.get("note") or "").startswith("[referral]")
                   else "tx_level" if (r.get("note") or "").startswith("[level]")
                   else f"tx_{r['type']}"),
            amount=money(r["amount_cents"]),
            balance=money(r["balance_after_cents"]),
        ))
    await target.answer("\n".join(lines))


async def start_deposit(
    target: Message, state: FSMContext, db: Database, user: dict, auto: bool = False
) -> None:
    lang = user["language"]
    await state.clear()
    pending = await repo.get_pending_deposit(db, user["id"])
    if pending:
        await target.answer(t(
            lang, "deposit_pending_exists",
            amount=money(pending["amount_cents"]), id=pending["id"],
        ))
        return
    await state.set_state(DepositFlow.amount)
    intro = "deposit_intro_auto" if auto else "deposit_intro"
    await target.answer(t(lang, intro), reply_markup=cancel_kb(lang))


@router.callback_query(F.data == "wallet:deposit")
async def cb_deposit(
    cb: CallbackQuery, state: FSMContext, db: Database, user: dict,
    khpay: Optional[KhpayClient] = None,
):
    await cb.answer()
    if isinstance(cb.message, Message):
        await start_deposit(cb.message, state, db, user, auto=khpay is not None)


@router.callback_query(F.data == "wallet:history")
async def cb_history(cb: CallbackQuery, db: Database, user: dict):
    await cb.answer()
    if isinstance(cb.message, Message):
        await show_history(cb.message, db, user)


@router.message(DepositFlow.amount)
async def on_deposit_amount(
    message: Message, state: FSMContext, db: Database, user: dict,
    bot: Bot, settings: Settings, khpay: Optional[KhpayClient] = None,
):
    lang = user["language"]
    cents = parse_money(message.text)
    if not valid_deposit(cents):
        await message.answer(t(lang, "invalid_amount"), reply_markup=cancel_kb(lang))
        return
    if khpay is not None:
        await _auto_deposit(message, state, db, user, settings, khpay, cents)
        return
    try:
        deposit_id = await wallet_service.create_deposit_request(db, message.from_user.id, cents)
    except DuplicateDeposit as exc:
        await state.clear()
        await message.answer(t(
            lang, "deposit_pending_exists",
            amount=money(exc.deposit["amount_cents"]), id=exc.deposit["id"],
        ))
        return
    await state.clear()
    await message.answer(t(
        lang, "deposit_created",
        id=deposit_id, amount=money(cents),
        support=esc(settings.support_username or "our support team"),
    ))
    who = esc(user["full_name"]) + (f" (@{esc(user['username'])})" if user["username"] else "")
    await notify_admins(
        bot, settings,
        f"💰 <b>New deposit request #{deposit_id}</b>\n"
        f"Customer: {who}\nTelegram ID: <code>{user['telegram_id']}</code>\n"
        f"Amount: <b>{money(cents)}</b>\n\n"
        "Only approve after you have received the money yourself.",
        reply_markup=deposit_review_kb(deposit_id, cents),
    )


# ------------------------------------------------- automatic payments (PayWay)


def _qr_kb_no_link(lang: str, deposit_id: int) -> InlineKeyboardMarkup:
    """Check payment + Cancel (same buttons as before, without the 'open page' link)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_check_payment"), callback_data=f"dep:chk:{deposit_id}"),
        InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data=f"dep:cancel:{deposit_id}"),
    ]])


async def _auto_deposit(
    message: Message, state: FSMContext, db: Database, user: dict,
    settings: Settings, khpay: KhpayClient, cents: int,
) -> None:
    lang = user["language"]
    support = esc(settings.support_username or "our support team")
    try:
        deposit_id, qr = await online_payments.start_online_deposit(
            db, khpay, message.from_user.id, cents
        )
    except DuplicateDeposit as exc:
        await state.clear()
        await message.answer(t(
            lang, "deposit_pending_exists",
            amount=money(exc.deposit["amount_cents"]), id=exc.deposit["id"],
        ))
        return
    except KhpayError as exc:
        log.warning("Could not create PayWay payment: %s (code=%s)", exc, exc.code)
        await state.clear()
        await message.answer(t(lang, "deposit_gateway_error", support=support))
        return
    await state.clear()
    caption = t(lang, "deposit_qr_caption", id=deposit_id, amount=money(cents),
                seconds=qr.expires_in)
    markup = (deposit_qr_kb(lang, deposit_id, qr.payment_url) if qr.payment_url
              else _qr_kb_no_link(lang, deposit_id))   # PayWay has no web page to open
    photo = online_payments.qr_photo(qr)
    sent = None
    try:
        if photo is not None:
            sent = await message.answer_photo(photo, caption=caption, reply_markup=markup)
    except TelegramAPIError:
        log.warning("Could not send QR photo", exc_info=True)
    if sent is None:
        sent = await message.answer(caption, reply_markup=markup)
    # So the bot can delete this QR automatically when the deposit is paid / expired / cancelled.
    await online_payments.remember_qr_message(db, deposit_id, sent.chat.id, sent.message_id)


@router.callback_query(F.data.regexp(r"^dep:(chk|cancel):\d+$"))
async def cb_deposit_action(
    cb: CallbackQuery, db: Database, bot: Bot, settings: Settings,
    khpay: Optional[KhpayClient] = None,
):
    _, action, id_text = cb.data.split(":")
    deposit_id = to_int(id_text)
    if khpay is None or deposit_id is None:
        await cb.answer()
        return
    dep = await online_payments.get_deposit(db, deposit_id)
    if dep is None or dep["user_telegram_id"] != cb.from_user.id:
        await cb.answer()
        return
    lang = dep["user_language"]
    if action == "chk":
        outcome = await online_payments.settle_deposit(db, khpay, deposit_id)
    else:
        outcome = await online_payments.cancel_online_deposit(
            db, khpay, cb.from_user.id, deposit_id
        )
    if outcome.kind == "pending":
        await cb.answer(t(lang, "deposit_check_wait"), show_alert=True)
        return
    if outcome.kind == "error":
        await cb.answer(t(lang, "deposit_gateway_error", support=esc(settings.support_username or "support")),
                        show_alert=True)
        return
    await cb.answer()
    if isinstance(cb.message, Message):
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    if outcome.kind != "already":
        await online_payments.announce_outcome(bot, settings, dep, outcome, db)
