"""Premium (animated) custom emoji.

How it works
------------
You list the emoji you want upgraded in `custom_emoji.json`, e.g.

    {"💎": "5368324170671202286", "✅": "5206607081334906820"}

Every outgoing message/caption/button then has those plain emoji swapped for the
premium version automatically. Customers without Telegram Premium still see the
normal emoji. If the file is empty (`{}`) nothing changes.

Telegram only lets a bot use custom emoji when the bot OWNER has Telegram Premium.
If Telegram ever refuses a message because of them, the bot automatically
re-sends it with plain emoji, so customers never see an error.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest

from app.utils import icons

log = logging.getLogger(__name__)

_VS16 = "️"
_TAG_SPLIT = re.compile(r"(<[^>]*>)")
_ID = re.compile(r"^\d{5,25}$")


def load_mapping(path: str) -> dict:
    """Read custom_emoji.json -> {emoji: id}. Bad entries are ignored with a warning."""
    file = Path(path)
    if not file.exists():
        return {}
    try:
        raw = json.loads(file.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        log.warning("custom_emoji.json could not be read (%s) - premium emoji are OFF", exc)
        return {}
    if not isinstance(raw, dict):
        log.warning("custom_emoji.json must be a JSON object like {\"💎\": \"123\"}")
        return {}
    mapping = {}
    for emoji, emoji_id in raw.items():
        key = str(emoji).replace(_VS16, "").strip()
        if key and _ID.match(str(emoji_id)):
            mapping[key] = str(emoji_id)
        else:
            log.warning("Ignoring invalid custom emoji entry: %r", emoji)
    return mapping


def _pattern(mapping: dict) -> Optional[re.Pattern]:
    if not mapping:
        return None
    keys = sorted(mapping, key=len, reverse=True)
    return re.compile("(" + "|".join(re.escape(k) for k in keys) + ")" + _VS16 + "?")


def apply_to_text(text: str, mapping: dict) -> str:
    """Swap mapped emoji for <tg-emoji> tags in an HTML message (tags are left alone)."""
    pattern = _pattern(mapping)
    if not text or pattern is None:
        return text
    out, inside_emoji_tag = [], False
    for part in _TAG_SPLIT.split(text):
        if part.startswith("<") and part.endswith(">"):
            low = part.lower()
            if low.startswith("<tg-emoji"):
                inside_emoji_tag = True
            elif low.startswith("</tg-emoji"):
                inside_emoji_tag = False
            out.append(part)
        elif inside_emoji_tag:
            out.append(part)
        else:
            out.append(pattern.sub(
                lambda m: f'<tg-emoji emoji-id="{mapping[m.group(1)]}">{m.group(0)}</tg-emoji>',
                part,
            ))
    return "".join(out)


def _leading_emoji(text: str, mapping: dict):
    """If a button text starts with a mapped emoji -> (id, rest of text)."""
    for key in sorted(mapping, key=len, reverse=True):
        if text.startswith(key):
            rest = text[len(key):].lstrip(_VS16).lstrip()
            if rest:                      # never leave a button with an empty label
                return mapping[key], rest
    return None


def apply_to_markup(markup, mapping: dict):
    """Give INLINE buttons a premium icon. (Reply-keyboard text must stay unchanged,
    because Telegram sends the button text back to us when it is tapped.)"""
    rows = getattr(markup, "inline_keyboard", None)
    if not rows or not mapping:
        return markup
    new_rows = []
    for row in rows:
        new_row = []
        for button in row:
            found = None if getattr(button, "icon_custom_emoji_id", None) else \
                _leading_emoji(button.text, mapping)
            if found:
                new_row.append(button.model_copy(
                    update={"icon_custom_emoji_id": found[0], "text": found[1]}))
            else:
                new_row.append(button)
        new_rows.append(new_row)
    return markup.model_copy(update={"inline_keyboard": new_rows})


def strip_icons(markup):
    """Turn every premium button icon back into a plain emoji in the text."""
    rows = getattr(markup, "inline_keyboard", None)
    if not rows:
        return markup
    new_rows = []
    for row in rows:
        new_row = []
        for button in row:
            icon = getattr(button, "icon_custom_emoji_id", None)
            if icon:
                new_row.append(button.model_copy(update={
                    "icon_custom_emoji_id": None,
                    "text": f"{icons.fallback_for(icon)} {button.text}"}))
            else:
                new_row.append(button)
        new_rows.append(new_row)
    return markup.model_copy(update={"inline_keyboard": new_rows})


class CustomEmojiMiddleware(BaseRequestMiddleware):
    """Applies the emoji upgrade to every outgoing request, with a safe fallback."""

    def __init__(self, mapping: dict):
        self.mapping = mapping

    async def __call__(self, make_request, bot, method):
        original = {}
        for field in ("text", "caption"):
            value = getattr(method, field, None)
            if isinstance(value, str) and value:
                original[field] = value
                setattr(method, field, apply_to_text(value, self.mapping))
        markup = getattr(method, "reply_markup", None)
        if markup is not None and hasattr(markup, "inline_keyboard"):
            original["reply_markup"] = markup
            setattr(method, "reply_markup", apply_to_markup(markup, self.mapping))
        if not original:
            return await make_request(bot, method)
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            msg = str(exc).lower()
            if "emoji" not in msg and "entit" not in msg and "icon" not in msg:
                raise
            log.warning("Telegram refused premium emoji (%s) - re-sending with plain emoji", exc)
            for field, value in original.items():
                setattr(method, field, strip_icons(value) if field == "reply_markup" else value)
            return await make_request(bot, method)
