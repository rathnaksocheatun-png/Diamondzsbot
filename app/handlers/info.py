"""Promotions, Contact Support, How to Use (read-only information)."""
from aiogram.types import Message

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.texts import t
from app.utils.formatting import esc


async def show_promos(target: Message, db: Database, lang: str) -> None:
    text = await repo.get_setting(db, "promo_text")
    if text:
        await target.answer(t(lang, "promos_title", text=esc(text)))
    else:
        await target.answer(t(lang, "promos_empty"))


async def show_support(target: Message, settings: Settings, lang: str) -> None:
    if settings.support_username:
        await target.answer(t(lang, "support", support=esc(settings.support_username)))
    else:
        await target.answer(t(lang, "support_missing"))


async def show_howto(target: Message, lang: str) -> None:
    await target.answer(t(lang, "howto"))
