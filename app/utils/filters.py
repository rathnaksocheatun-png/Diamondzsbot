"""Custom filters. IsAdmin is the only gate to every admin feature."""
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.config import Settings


class IsAdmin(BaseFilter):
    """Passes only if the sender's Telegram ID is listed in ADMIN_IDS (.env)."""

    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        sender = getattr(event, "from_user", None)
        return sender is not None and sender.id in settings.admin_ids
