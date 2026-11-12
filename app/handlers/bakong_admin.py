"""Admin only: look after the Bakong connection.

  /bakong                 show the account and token status
  /bakong_token <token>   save a new Bakong token (active at once; your message is deleted)
  /bakong_test            (in payway_admin.py) makes a real $0.01 KHQR and watches it

The account id, name and city come from Railway Variables (BAKONG_ACCOUNT_ID,
BAKONG_MERCHANT_NAME, BAKONG_MERCHANT_CITY). The token can be changed here at any time.
"""
import logging
import re
from typing import Optional

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.database import repositories as repo
from app.database.db import Database
from app.services.bakong import TOKEN_SETTING, BakongClient
from app.utils.filters import IsAdmin
from app.utils.formatting import esc

log = logging.getLogger("diamond_zs.bakong_admin")

router = Router(name="bakong_admin")
router.message.filter(IsAdmin())

_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")

NOT_ON = ("⚠️ Automatic deposits through Bakong are OFF.\n"
          "In Railway → Variables add <code>BAKONG_ACCOUNT_ID</code> (like yourname@aba) and "
          "<code>BAKONG_TOKEN</code>, then redeploy.")


@router.message(Command("bakong"))
async def cmd_bakong(message: Message, khpay=None):
    if not isinstance(khpay, BakongClient):
        await message.answer(NOT_ON)
        return
    token = khpay._token
    await message.answer(
        "🏦 <b>Bakong connection</b>\n\n"
        f"Account: <code>{esc(khpay.account_id)}</code>\n"
        f"Name on QR: {esc(khpay.merchant_name)} • {esc(khpay.merchant_city)}\n"
        f"Token: {'set (…' + esc(token[-6:]) + ')' if token else 'NOT set'}\n"
        f"Auto-renew by email: {'yes' if khpay._email else 'no'}\n\n"
        "Test: /bakong_test\nNew token: <code>/bakong_token PASTE_TOKEN</code>")


@router.message(Command("bakong_token"))
async def cmd_token(message: Message, command: CommandObject, db: Database, khpay=None):
    token = (command.args or "").strip()
    if not _JWT_RE.match(token):
        await message.answer("Usage: <code>/bakong_token PASTE_THE_WHOLE_TOKEN</code>\n"
                             "The token is a long text with two dots, usually starting with eyJ.")
        return
    await repo.set_setting(db, TOKEN_SETTING, token)
    try:                                   # do not leave the secret sitting in the chat
        await message.delete()
    except TelegramAPIError:
        pass
    if isinstance(khpay, BakongClient):
        khpay.set_token(token)
        await message.answer("✅ Token saved and active now. I deleted your message. "
                             "Run /bakong_test to check it.")
    else:
        await message.answer("✅ Token saved, and I deleted your message. " + NOT_ON)
