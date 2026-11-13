"""Helpers for sending/editing Telegram messages without crashing on errors."""
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.config import Settings

log = logging.getLogger(__name__)


async def edit_or_send(
    cb: CallbackQuery, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None
) -> None:
    """Replace the message that holds the tapped button (or send a new one)."""
    msg = cb.message
    if not isinstance(msg, Message):
        return
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        try:
            await msg.answer(text, reply_markup=reply_markup)
        except TelegramAPIError:
            log.warning("Could not send message", exc_info=True)


async def notify_user(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except TelegramAPIError:
        log.warning("Could not notify user %s (they may have blocked the bot)", chat_id)


async def notify_admins(
    bot: Bot, settings: Settings, text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except TelegramAPIError:
            log.warning("Could not notify admin %s", admin_id)


async def notify_group(
    bot: Bot, settings: Settings, kind: str, text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Post to the orders or payments group. kind = "orders" or "payments".

    Does nothing if that group is not configured, and never raises, so a
    problem with the group can never break an order or a deposit.
    """
    chat_id = settings.orders_chat_id if kind == "orders" else settings.payments_chat_id
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except TelegramAPIError:
        log.warning("Could not post to the %s group (%s)", kind, chat_id)
