"""Premium (animated) emoji that admins manage from inside the bot (/emoji ...).

How it works
- The emoji -> premium-id list lives in the database (table custom_emojis) and in
  memory. Changing it with /emoji takes effect immediately: no restart, no GitHub push.
- LiveEmojiMiddleware looks at every message the bot sends:
    * in the TEXT (HTML mode) a mapped emoji becomes <tg-emoji emoji-id="...">
      (Telegram only shows it animated if the bot has a Fragment username;
       otherwise the normal emoji is shown - nothing breaks)
    * on INLINE buttons a mapped emoji at the start of the label becomes the
      button icon (works when the bot owner has Telegram Premium)
- The big menu (reply keyboard) is NOT touched, because the bot recognises those
  buttons by their exact text.
- This runs IN ADDITION to the old custom_emoji.json system; it does not replace it.
"""
import logging
import re
from typing import Optional

from aiogram.client.default import Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database import repositories as repo
from app.database.db import Database

log = logging.getLogger("diamond_zs.emoji")

VS16 = "\ufe0f"  # the invisible "show as emoji" marker, some emoji have it, some don't
_TAG_RE = re.compile(r"(<[^<>]*>)")
_SKIP_TAGS = ("tg-emoji", "code", "pre")
_BUTTON_HAS_ICON = "icon_custom_emoji_id" in InlineKeyboardButton.model_fields


def norm(emoji: str) -> str:
    """Compare emoji with and without the invisible VS16 marker as the same thing."""
    return (emoji or "").replace(VS16, "")


class EmojiStore:
    def __init__(self) -> None:
        self.mapping: dict = {}      # normalised emoji -> premium id
        self._shown: dict = {}       # normalised emoji -> emoji as the admin sent it
        self._regex: Optional[re.Pattern] = None

    def __len__(self) -> int:
        return len(self.mapping)

    def _rebuild(self) -> None:
        keys = sorted(self.mapping, key=len, reverse=True)
        self._regex = (
            re.compile("(" + "|".join(re.escape(k) for k in keys) + ")" + VS16 + "?")
            if keys else None
        )

    def replace_all(self, rows: list) -> None:
        self.mapping = {norm(r["emoji"]): str(r["emoji_id"]) for r in rows}
        self._shown = {norm(r["emoji"]): r["emoji"] for r in rows}
        self._rebuild()

    def items(self) -> list:
        return [(self._shown[k], v) for k, v in self.mapping.items()]

    async def load(self, db: Database) -> None:
        self.replace_all(await repo.list_custom_emojis(db))

    async def set(self, db: Database, emoji: str, emoji_id: str) -> None:
        await repo.set_custom_emoji(db, emoji, emoji_id)
        await self.load(db)

    async def delete(self, db: Database, emoji: str) -> bool:
        removed = await repo.delete_custom_emoji(db, emoji)
        if not removed and norm(emoji) != emoji:       # stored with the marker
            removed = await repo.delete_custom_emoji(db, norm(emoji))
        if not removed:                                # stored without the marker
            removed = await repo.delete_custom_emoji(db, norm(emoji) + VS16)
        await self.load(db)
        return removed

    async def clear(self, db: Database) -> int:
        n = await repo.clear_custom_emojis(db)
        await self.load(db)
        return n

    # ------------------------------------------------------------ rewriting

    def html(self, text: str) -> str:
        """Wrap mapped emoji of an HTML text in <tg-emoji>, never inside tags/code."""
        if not text or self._regex is None:
            return text
        out, depth = [], {name: 0 for name in _SKIP_TAGS}
        for part in _TAG_RE.split(text):
            if part.startswith("<") and part.endswith(">"):
                m = re.match(r"</?\s*([A-Za-z0-9-]+)", part)
                name = m.group(1).lower() if m else ""
                if name in depth:
                    depth[name] += -1 if part.startswith("</") else 1
                    depth[name] = max(depth[name], 0)
                out.append(part)
            elif any(depth.values()):
                out.append(part)
            else:
                out.append(self._regex.sub(
                    lambda m: f'<tg-emoji emoji-id="{self.mapping[norm(m.group(1))]}">'
                              f'{m.group(0)}</tg-emoji>', part))
        return "".join(out)

    def button(self, button: InlineKeyboardButton) -> InlineKeyboardButton:
        """Use a premium emoji as the icon of an inline button (label starts with it)."""
        if not _BUTTON_HAS_ICON or self._regex is None:
            return button
        if getattr(button, "icon_custom_emoji_id", None) or not button.text:
            return button
        m = self._regex.match(button.text.lstrip())
        if not m:
            return button
        rest = button.text.lstrip()[m.end():].strip()
        if not rest:
            return button
        return button.model_copy(update={
            "text": rest, "icon_custom_emoji_id": self.mapping[norm(m.group(1))]})

    def markup(self, markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
        rows = [[self.button(b) for b in row] for row in markup.inline_keyboard]
        return markup.model_copy(update={"inline_keyboard": rows})


class LiveEmojiMiddleware(BaseRequestMiddleware):
    """Rewrites every outgoing request using the current EmojiStore."""

    def __init__(self, store: EmojiStore) -> None:
        self.store = store

    async def __call__(self, make_request, bot, method):
        if len(self.store):
            try:
                method = self._rewrite(bot, method)
            except Exception:  # never let a cosmetic feature stop a message
                log.exception("premium emoji rewrite failed - sending normal emoji")
        return await make_request(bot, method)

    def _rewrite(self, bot, method):
        updates: dict = {}
        parse_mode = getattr(method, "parse_mode", None)
        if isinstance(parse_mode, Default):
            parse_mode = getattr(bot.default, parse_mode.name, None)
        if str(getattr(parse_mode, "value", parse_mode) or "").upper() == "HTML":
            for field in ("text", "caption"):
                value = getattr(method, field, None)
                if isinstance(value, str) and not getattr(method, "entities", None):
                    new = self.store.html(value)
                    if new != value:
                        updates[field] = new
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            updates["reply_markup"] = self.store.markup(markup)
        return method.model_copy(update=updates) if updates else method
