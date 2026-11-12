"""Admin only: look after the PayWay payment link and test it safely.

  /payway_link                 show the link in use
  /payway_link <https://link.payway.com.kh/ABAPAY...>   change it (saved, active at once)
  /payway_test                 makes a real $0.01 KHQR (NO wallet is touched) and watches it for
                               3 minutes, so you can pay it yourself and see "approved" is detected
  /payway_deposit <id>         show one deposit and ask PayWay what it says about it
"""
import asyncio
import logging
from typing import Optional

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.database import repositories as repo
from app.database.db import Database
from app.services import online_payments
from app.services.khpay import KhpayError
from app.services.payway import LINK_RE, PaywayClient
from app.utils.filters import IsAdmin
from app.utils.formatting import esc, money

log = logging.getLogger("diamond_zs.payway_admin")

router = Router(name="payway_admin")
router.message.filter(IsAdmin())

SETTING_KEY = "payway_link"
TEST_SECONDS = 180
TEST_INTERVAL = 10
_tasks: set = set()
_testing = False

NOT_ON = ("⚠️ Automatic PayWay deposits are OFF because no link is set.\n"
          "Send <code>/payway_link https://link.payway.com.kh/ABAPAY...</code> and then "
          "redeploy / restart the bot once.")


@router.message(Command("payway_link"))
async def cmd_link(message: Message, command: CommandObject, db: Database,
                   khpay: Optional[PaywayClient] = None):
    arg = (command.args or "").strip()
    if not arg:
        current = khpay.link if khpay is not None else \
            (await repo.get_setting(db, SETTING_KEY) or "")
        if current:
            await message.answer(
                f"💳 <b>PayWay link in use</b>\n{esc(current)}\n\n"
                f"Automatic deposits: <b>{'ON' if khpay is not None else 'OFF (restart needed)'}</b>\n"
                "Change: <code>/payway_link https://link.payway.com.kh/ABAPAY...</code>\n"
                "Test: /payway_test")
        else:
            await message.answer(NOT_ON)
        return
    if not LINK_RE.match(arg):
        await message.answer("⚠️ That is not a PayWay payment link. It must look like "
                             "<code>https://link.payway.com.kh/ABAPAYxxxxxxx</code>")
        return
    await repo.set_setting(db, SETTING_KEY, arg)
    if khpay is None:
        await message.answer("✅ Link saved. Restart / redeploy the bot once to turn on "
                             "automatic deposits, then run /payway_test.")
        return
    khpay.set_link(arg)
    await message.answer("✅ Link changed and active now. Run /payway_test to check it.")


@router.message(Command("payway_test"))
async def cmd_test(message: Message, bot: Bot, khpay: Optional[PaywayClient] = None):
    global _testing
    if khpay is None:
        await message.answer(NOT_ON)
        return
    if _testing:
        await message.answer("A test is already running. Please wait for it to finish.")
        return
    await message.answer("⏳ Contacting PayWay…")
    try:
        merchant = await khpay.self_test()
        qr = await khpay.generate_qr(1, "Admin test", {}, "payway-test")
    except KhpayError as exc:
        await message.answer(
            f"❌ PayWay test failed:\n<code>{esc(str(exc))}</code>\n\n"
            + ("Too many page loads. Wait a minute and try again." if exc.code == "429"
               else "ABA refused this server (403). It is blocking the bot's server address, "
                    "not a mistake in your link. Look at the Railway logs for the line "
                    "starting with [PayWay]." if exc.code == "403"
               else "Check the link with /payway_link and the Railway logs."))
        return
    photo = online_payments.qr_photo(qr)
    caption = (f"✅ PayWay works.\nAccount name: <b>{esc(merchant)}</b>\n"
               f"This is a TEST KHQR for <b>$0.01</b> (Tran <code>{esc(qr.transaction_id)}</code>).\n"
               "Pay it with ABA Mobile and I will tell you when I see the payment. "
               "Your wallet and customers are not touched. Watching for 3 minutes.")
    if photo is not None:
        await message.answer_photo(photo, caption=caption)
    else:
        await message.answer(caption)
    _testing = True
    task = asyncio.create_task(_watch_test(bot, message.chat.id, khpay, qr.transaction_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _watch_test(bot: Bot, chat_id: int, client: PaywayClient, tran_id: str) -> None:
    global _testing
    seen, deadline = set(), asyncio.get_running_loop().time() + TEST_SECONDS
    try:
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(TEST_INTERVAL)
            try:
                status = await client.check(tran_id)
            except KhpayError as exc:
                log.warning("payway test check failed: %s", exc)
                continue
            if status.paid:
                await bot.send_message(
                    chat_id, "✅ <b>Payment detected: approved.</b> Automatic deposits will work. "
                             "(Test only - no wallet was credited.)")
                return
            if status.action not in seen and status.action != "request_qr":
                seen.add(status.action)
                await bot.send_message(chat_id, f"👀 Status: <b>{esc(status.action)}</b>")
        await bot.send_message(chat_id, "⌛ Test finished: no payment was detected "
                                        "(that is normal if you did not pay).")
    except Exception:
        log.exception("payway test crashed")
    finally:
        _testing = False


@router.message(Command("payway_deposit"))
async def cmd_deposit(message: Message, command: CommandObject, db: Database,
                      khpay: Optional[PaywayClient] = None):
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Usage: <code>/payway_deposit 12</code> (the deposit number)")
        return
    dep = await online_payments.get_deposit(db, int(arg))
    if dep is None:
        await message.answer("No deposit with that number.")
        return
    lines = [
        f"💳 <b>Deposit #{dep['id']}</b>",
        f"Customer: {esc(dep['user_name'] or '-')} (<code>{dep['user_telegram_id']}</code>)",
        f"Amount: <b>{money(dep['amount_cents'])}</b>",
        f"Status: <b>{esc(dep['status'])}</b> • provider: {esc(dep['provider'])}",
        f"Tran ID: <code>{esc(dep['external_id'] or '-')}</code>",
        f"Created: {esc(dep['created_at'])}",
    ]
    if khpay is not None and dep["external_id"] and dep["provider"] == online_payments.PROVIDER:
        try:
            status = await khpay.check(dep["external_id"])
            lines.append(f"PayWay says: <b>{esc(status.action)}</b>")
        except KhpayError as exc:
            lines.append(f"PayWay check failed: {esc(str(exc))}")
    await message.answer("\n".join(lines))
