"""Runs before every handler: registers the customer and blocks group chats."""
from aiogram import BaseMiddleware
from aiogram.types import Message

from app.database import repositories as repo


class UserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # The shop only works in private chats with the bot.
        if isinstance(event, Message) and event.chat.type != "private":
            return None

        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None

        user, created = await repo.upsert_user(data["db"], tg_user)
        data["user"] = user
        data["is_new"] = created
        return await handler(event, data)
