"""A tutorial video for the customer's "How to Use" button.

Admin (admins only):
  /howtovideo km      -> the bot asks for a video; send it and it is saved for Khmer
  /howtovideo en      -> same, for English
  /howtovideo         -> shows which videos are set
  /howtovideo_del km | en | all   -> remove

Customers: when they tap "How to Use" (or /howto) they first receive the video for their
language (the other language's video if theirs is missing), followed by the normal text.
If no video is set, nothing changes - they just get the text as before.

The video is saved as a Telegram file_id in the existing `settings` table, so it survives
deploys (the database is on the Railway volume) and needs no new table.
"""
import logging
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.database import repositories as repo
from app.database.db import Database
from app.utils.filters import IsAdmin

log = logging.getLogger("diamond_zs.howto_video")

router = Router(name="howto_video")
router.message.filter(IsAdmin())

LANGS = ("km", "en")
LANG_NAMES = {"km": "Khmer 🇰🇭", "en": "English 🇬🇧"}


class HowtoFlow(StatesGroup):
    video = State()


def _key(lang: str) -> str:
    return f"howto_video_{lang}"


async def get_video_id(db: Database, lang: str) -> Optional[str]:
    """The saved video for this language, or the other language's video, or None."""
    other = "en" if lang == "km" else "km"
    for code in (lang, other):
        value = await repo.get_setting(db, _key(code))
        if value:
            return value
    return None


async def send_howto_video(message: Message, db: Database, lang: str) -> bool:
    """Customer side: send the tutorial video if there is one. Never raises - if the video
    cannot be sent the customer still gets the written text. Returns True if it was sent."""
    file_id = await get_video_id(db, lang)
    if not file_id:
        return False
    try:
        await message.answer_video(file_id)
        return True
    except Exception:  # bad file_id, user blocked, network... the text still follows
        log.exception("could not send the how-to video")
        return False


# ------------------------------------------------------------------ admin side


@router.message(Command("howtovideo"))
async def cmd_howtovideo(message: Message, command: CommandObject, state: FSMContext,
                         db: Database):
    arg = (command.args or "").strip().lower()
    if arg not in LANGS:
        lines = ["🎬 <b>How-to video</b>\n"]
        for lang in LANGS:
            has = await repo.get_setting(db, _key(lang))
            lines.append(f"{LANG_NAMES[lang]}: {'✅ set' if has else '— not set'}")
        lines.append(
            "\nSet or replace: <code>/howtovideo km</code> or <code>/howtovideo en</code>, "
            "then send the video.\nRemove: <code>/howtovideo_del km</code> "
            "(or <code>en</code> / <code>all</code>).")
        await message.answer("\n".join(lines))
        return
    await state.clear()
    await state.set_state(HowtoFlow.video)
    await state.update_data(howto_lang=arg)
    await message.answer(
        f"🎬 Send the tutorial video for <b>{LANG_NAMES[arg]}</b> now.\n"
        "Send it as a normal video (not as a file). /cancel to stop.")


@router.message(HowtoFlow.video, F.video)
async def got_video(message: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    lang = data.get("howto_lang")
    if lang not in LANGS:
        await state.clear()
        await message.answer("Something went wrong. Send /howtovideo km (or en) again.")
        return
    await repo.set_setting(db, _key(lang), message.video.file_id)
    await state.clear()
    await message.answer(f"✅ How-to video saved for <b>{LANG_NAMES[lang]}</b>. "
                         "Customers see it now when they tap “How to Use”.")


@router.message(HowtoFlow.video)
async def not_a_video(message: Message):
    await message.answer("⚠️ That is not a video. Send the tutorial as a video, or /cancel to stop.")


@router.message(Command("howtovideo_del"))
async def cmd_howtovideo_del(message: Message, command: CommandObject, db: Database):
    arg = (command.args or "").strip().lower()
    if arg not in LANGS and arg != "all":
        await message.answer("Usage: <code>/howtovideo_del km</code>, <code>en</code> or <code>all</code>")
        return
    for lang in (LANGS if arg == "all" else (arg,)):
        await repo.set_setting(db, _key(lang), "")   # empty = no video
    await message.answer("🗑 Removed. Customers now get only the text.")
