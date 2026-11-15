"""/app - opens the shop Mini App (only works when WEBAPP_URL is set in Railway)."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

router = Router(name="webapp")


@router.message(Command("app"))
async def cmd_app(message: Message, webapp_url: str = ""):
    if not webapp_url:
        await message.answer("🛍 The shop app is not ready yet.\nហាង app មិនទាន់ត្រៀមរួចទេ។")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍 Open shop / បើកហាង", web_app=WebAppInfo(url=webapp_url)),
    ]])
    await message.answer("💎 <b>Diamond ZS</b>", reply_markup=keyboard)
