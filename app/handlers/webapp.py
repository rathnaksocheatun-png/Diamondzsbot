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


@admin.message(Command("gamecodes"))
async def cmd_gamecodes(message: Message, db: Database):
    """/gamecodes  (all games)   |   /gamecodes pool  (search by name or code)"""
    q = (message.text or "").partition(" ")[2].strip().lower()
    games = await repo.list_games(db, only_active=False)
    lines = [f"{g.get('emoji') or '🎮'} {g['name']} → <code>{g['code']}</code>" for g in games
             if not q or q in g["name"].lower() or q in g["code"].lower()]
    if not lines:
        await message.answer("No game found." if q else "No games yet.")
        return
    chunk = ""
    for line in lines:                      # Telegram limits one message, so send in parts
        if len(chunk) + len(line) + 1 > 3500:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.answer(chunk)


@admin.message(Command("pkgs"))
async def cmd_pkgs(message: Message, db: Database):
    """/pkgs <game_code> - list the packages of a game with their numbers."""
    code = (message.text or "").partition(" ")[2].strip()
    products = await repo.list_products(db, code, only_active=False) if code else []
    if not products:
        await message.answer("Use: /pkgs <game_code>   (see /gamecodes)")
        return
    await message.answer("\n".join(f"<code>{p['id']}</code> → {p['name']}" for p in products)[:4000])


@admin.message(F.photo, F.caption.startswith("/pkgimg"))
async def cmd_pkgimg(message: Message, db: Database):
    """Send a photo with the caption  /pkgimg <package_number>  to set that package's picture."""
    pid = (message.caption or "").partition(" ")[2].strip()
    if not pid.isdigit() or not await repo.get_product(db, int(pid)):
        await message.answer("Use: photo + caption /pkgimg <package_number>   (numbers: /pkgs <game_code>)")
        return
    imgs = json.loads(await repo.get_setting(db, "webapp_pimgs") or "{}")
    imgs[pid] = message.photo[-1].file_id
    await repo.set_setting(db, "webapp_pimgs", json.dumps(imgs))
    await message.answer(f"✅ Picture set for package {pid}.")


@admin.message(Command("pkgimg"))
async def cmd_pkgimg_off(message: Message, db: Database):
    """/pkgimg off <package_number>  removes a picture."""
    parts = (message.text or "").split()
    if len(parts) == 3 and parts[1] == "off":
        imgs = json.loads(await repo.get_setting(db, "webapp_pimgs") or "{}")
        imgs.pop(parts[2], None)
        await repo.set_setting(db, "webapp_pimgs", json.dumps(imgs))
        await message.answer("✅ Picture removed.")
    else:
        await message.answer("Use: photo + caption /pkgimg <number>   or   /pkgimg off <number>")


@admin.message(Command("hot"))
async def cmd_hot(message: Message, db: Database):
    """/hot  |  /hot add 15 26  |  /hot remove 15  |  /hot clear   (Hot Packages on the Mini App home)"""
    parts = (message.text or "").split()[1:]
    ids = json.loads(await repo.get_setting(db, "webapp_hot") or "[]")
    if parts and parts[0] == "clear":
        ids = []
    elif len(parts) > 1 and parts[0] in ("add", "remove"):
        nums = [int(x) for x in parts[1:] if x.isdigit()]
        if parts[0] == "add":
            for n in nums:
                if n not in ids and await repo.get_product(db, n):
                    ids.append(n)
        else:
            ids = [i for i in ids if i not in nums]
    await repo.set_setting(db, "webapp_hot", json.dumps(ids[:8]))
    lines = []
    for i in ids[:8]:
        p = await repo.get_product(db, i)
        lines.append(f"<code>{i}</code> → {p.get('name', '?') if p else '?'}")
    await message.answer("🔥 Hot packages (max 8):\n" + ("\n".join(lines) or "none (automatic)")
                         + "\n\n/hot add 15 26   |   /hot remove 15   |   /hot clear\nNumbers: /pkgs <game_code>")
