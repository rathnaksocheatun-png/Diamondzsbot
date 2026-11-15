"""/app - opens the shop Mini App (only works when WEBAPP_URL is set in Railway)."""
import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.database import repositories as repo
from app.database.db import Database
from app.utils.filters import IsAdmin

router = Router(name="webapp")
admin = Router(name="webapp_admin")
admin.message.filter(IsAdmin())
router.include_router(admin)


@router.message(Command("app"))
async def cmd_app(message: Message, webapp_url: str = ""):
    if not webapp_url:
        await message.answer("🛍 The shop app is not ready yet.\nហាង app មិនទាន់ត្រៀមរួចទេ។")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍 Open shop / បើកហាង", web_app=WebAppInfo(url=webapp_url)),
    ]])
    await message.answer("💎 <b>Diamond ZS</b>", reply_markup=keyboard)


@admin.message(Command("banner"))
async def cmd_banner(message: Message, db: Database):
    """/banner your text   (shown on the Mini App home page)   |   /banner off"""
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        await message.answer("Use: /banner your text   or   /banner off")
        return
    await repo.set_setting(db, "webapp_banner", "" if text.lower() == "off" else text[:200])
    await message.answer("✅ Banner updated (visible within ~10 seconds).")


@admin.message(F.photo, F.caption.startswith("/gameimg"))
async def cmd_gameimg(message: Message, db: Database):
    """Send a photo with the caption  /gameimg <game_code>  to set that game's picture."""
    code = (message.caption or "").partition(" ")[2].strip()
    if not code or not await repo.get_game(db, code):
        await message.answer("Use: send a photo with caption  /gameimg <game_code>")
        return
    imgs = json.loads(await repo.get_setting(db, "webapp_imgs") or "{}")
    imgs[code] = message.photo[-1].file_id
    await repo.set_setting(db, "webapp_imgs", json.dumps(imgs))
    await message.answer(f"✅ Picture set for {code}.")


@admin.message(Command("gameimg"))
async def cmd_gameimg_off(message: Message, db: Database):
    """/gameimg off <game_code>  removes a picture."""
    parts = (message.text or "").split()
    if len(parts) == 3 and parts[1] == "off":
        imgs = json.loads(await repo.get_setting(db, "webapp_imgs") or "{}")
        imgs.pop(parts[2], None)
        await repo.set_setting(db, "webapp_imgs", json.dumps(imgs))
        await message.answer("✅ Picture removed.")
    else:
        await message.answer("Use: photo + caption /gameimg <code>   or   /gameimg off <code>")
