"""Admin only: send an announcement (text, photo or video) to every customer who started the bot.

  /broadcast   -> the bot asks for the message. Send it exactly as you want customers to see
                  it (text, or a photo / video with a caption). Formatting and premium emoji
                  are kept, because the bot COPIES your message to each customer.
               -> you get a preview, see how many people will receive it, and choose
                  All / Khmer only / English only / Cancel.

Sending runs in the background, slowly enough for Telegram's limits (about 16 per second),
and you get a summary at the end. Customers who blocked the bot are skipped and counted.
Nothing is sent until you press a Send button.
"""
import asyncio
import logging
from typing import Awaitable, Callable, Optional

from aiogram import F, Bot, Router
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.db import Database
from app.utils.filters import IsAdmin

log = logging.getLogger("diamond_zs.broadcast")

router = Router(name="broadcast")
router.message.filter(IsAdmin())

DELAY = 0.06                 # seconds between messages (~16 per second, under Telegram's limit)
PROGRESS_EVERY = 100         # update the status message every N customers
_running = False             # only one broadcast at a time
_tasks: set = set()          # keeps the background task alive


class BroadcastFlow(StatesGroup):
    content = State()


async def count_targets(db: Database) -> dict:
    rows = await db.fetchall("SELECT language, COUNT(*) AS n FROM users GROUP BY language")
    counts = {r["language"]: r["n"] for r in rows}
    return {"all": sum(counts.values()), "km": counts.get("km", 0), "en": counts.get("en", 0)}


async def target_ids(db: Database, audience: str) -> list:
    if audience in ("km", "en"):
        rows = await db.fetchall(
            "SELECT telegram_id FROM users WHERE language = ? ORDER BY id", (audience,))
    else:
        rows = await db.fetchall("SELECT telegram_id FROM users ORDER BY id")
    return [r["telegram_id"] for r in rows]


async def deliver(bot: Bot, targets: list, from_chat: int, message_id: int,
                  progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
                  delay: float = DELAY) -> dict:
    """Copy one message to every target. Returns {'sent', 'blocked', 'failed'}."""
    stats = {"sent": 0, "blocked": 0, "failed": 0}
    for index, chat_id in enumerate(targets, start=1):
        for attempt in (1, 2):
            try:
                await bot.copy_message(chat_id, from_chat, message_id)
                stats["sent"] += 1
            except TelegramRetryAfter as exc:
                if attempt == 1:                       # Telegram asked us to slow down
                    await asyncio.sleep(exc.retry_after + 1)
                    continue
                stats["failed"] += 1
            except TelegramForbiddenError:             # customer blocked the bot / deleted account
                stats["blocked"] += 1
            except TelegramBadRequest as exc:
                log.warning("broadcast to %s failed: %s", chat_id, exc)
                stats["failed"] += 1
            except Exception:                          # never let one customer stop the rest
                log.exception("broadcast to %s failed", chat_id)
                stats["failed"] += 1
            break
        if progress and index % PROGRESS_EVERY == 0:
            await progress(index, len(targets))
        await asyncio.sleep(delay)
    return stats


# ------------------------------------------------------------------ the flow


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, db: Database):
    counts = await count_targets(db)
    await state.clear()
    await state.set_state(BroadcastFlow.content)
    await message.answer(
        "📢 <b>New announcement</b>\n\n"
        f"It can reach up to <b>{counts['all']}</b> customers who started the bot.\n\n"
        "Now send the message exactly as customers should see it:\n"
        "• text, or\n• a photo or video with a caption\n"
        "Bold/italic and premium emoji are kept. Send ONE message (not an album).\n\n"
        "Nothing is sent yet — you will see a preview first. /cancel to stop.")


@router.message(BroadcastFlow.content)
async def got_content(message: Message, state: FSMContext, bot: Bot, db: Database):
    if message.text and message.text.startswith("/"):
        await message.answer("Send the announcement itself, or /cancel to stop.")
        return
    if message.media_group_id:
        await message.answer("⚠️ Albums are not supported. Send ONE photo or video.")
        return
    if not (message.text or message.photo or message.video or message.animation):
        await message.answer("⚠️ Please send text, a photo, or a video (with a caption if you like).")
        return
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    counts = await count_targets(db)
    await message.answer("👆 This is the announcement. Preview of what customers will receive:")
    try:
        await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    except TelegramBadRequest as exc:
        await state.clear()
        await message.answer(f"⚠️ Telegram cannot send this message: {exc}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Send to ALL ({counts['all']})", callback_data="bc:go:all")],
        [InlineKeyboardButton(text=f"🇰🇭 Khmer only ({counts['km']})", callback_data="bc:go:km"),
         InlineKeyboardButton(text=f"🇬🇧 English only ({counts['en']})", callback_data="bc:go:en")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="bc:no")],
    ])
    await message.answer(
        "Above is exactly what they will get. Choose who receives it.\n"
        "<i>Customers who blocked the bot will be skipped.</i>", reply_markup=keyboard)


@router.callback_query(F.data == "bc:no")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "bc_msg" not in data:
        await cb.answer("This request expired.", show_alert=True)
        return
    await state.clear()
    await cb.answer("Cancelled")
    await _edit(cb, "❌ Cancelled. Nothing was sent.")


@router.callback_query(F.data.regexp(r"^bc:go:(all|km|en)$"))
async def cb_send(cb: CallbackQuery, state: FSMContext, bot: Bot, db: Database):
    global _running
    data = await state.get_data()
    if "bc_msg" not in data:                       # also blocks anyone who is not the admin who started it
        await cb.answer("This request expired. Send /broadcast again.", show_alert=True)
        return
    if _running:
        await cb.answer("Another broadcast is still sending. Please wait.", show_alert=True)
        return
    audience = cb.data.split(":")[2]
    targets = await target_ids(db, audience)
    await state.clear()                            # one press = one broadcast (no double send)
    if not targets:
        await cb.answer("Nobody to send to.", show_alert=True)
        return
    await cb.answer("Sending started")
    await _edit(cb, f"⏳ Sending to <b>{len(targets)}</b> customers… "
                    "you will get a summary here when it is done.")
    status = cb.message
    _running = True
    task = asyncio.create_task(_run(bot, status, targets, data["bc_chat"], data["bc_msg"]))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(bot: Bot, status: Message, targets: list, from_chat: int, message_id: int) -> None:
    global _running
    try:
        async def progress(done: int, total: int) -> None:
            try:
                await status.edit_text(f"⏳ Sending… {done}/{total}")
            except TelegramBadRequest:
                pass

        stats = await deliver(bot, targets, from_chat, message_id, progress)
        log.info("broadcast finished: %s of %s", stats, len(targets))
        await bot.send_message(
            from_chat,
            "📢 <b>Broadcast finished</b>\n\n"
            f"✅ Delivered: <b>{stats['sent']}</b>\n"
            f"🚫 Blocked the bot / unreachable: {stats['blocked']}\n"
            f"⚠️ Failed: {stats['failed']}\n"
            f"👥 Total tried: {len(targets)}")
    except Exception:
        log.exception("broadcast crashed")
        try:
            await bot.send_message(from_chat, "⚠️ The broadcast stopped because of an error. "
                                              "Check the Railway logs; some customers may not have received it.")
        except Exception:
            pass
    finally:
        _running = False


async def _edit(cb: CallbackQuery, text: str) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=None)
    except TelegramBadRequest:
        await cb.message.answer(text)
