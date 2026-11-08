"""Emoji for a game or a package: a normal emoji, or a Telegram Premium (animated) one.

A Premium emoji is stored as its ID plus a normal "fallback" emoji. Customers without
Premium (and any case where Telegram refuses the Premium emoji) see the fallback.
Pure Python - no Telegram imports - so it is easy to test.
"""
import re
from typing import Optional

_ID = re.compile(r"^\d{5,25}$")
_MAX_LEN = 8
_FALLBACK: dict = {}          # premium emoji id -> plain emoji, filled as buttons are built


def clean_plain_emoji(text: Optional[str]) -> Optional[str]:
    """One normal emoji typed by the admin, or None if it looks like ordinary text."""
    value = (text or "").strip()
    if not value or len(value) > _MAX_LEN:
        return None
    if any(ch.isalnum() or ch.isspace() or ch in "<>&" for ch in value):
        return None
    return value


def valid_id(emoji_id: Optional[str]) -> bool:
    return bool(emoji_id) and bool(_ID.match(str(emoji_id)))


def remember(emoji_id: str, char: str) -> None:
    _FALLBACK[emoji_id] = char


def fallback_for(emoji_id: str) -> str:
    return _FALLBACK.get(emoji_id, "🎮")


def button_icon(emoji: Optional[str], emoji_id: Optional[str], default: str = "") -> tuple:
    """-> (text prefix, premium icon id or None) for an inline button."""
    char = emoji or default
    if valid_id(emoji_id):
        remember(str(emoji_id), char or "🎮")
        return "", str(emoji_id)
    return (f"{char} " if char else ""), None


def html_icon(emoji: Optional[str], emoji_id: Optional[str], default: str = "") -> str:
    """The emoji for use inside an HTML message."""
    char = emoji or default
    if valid_id(emoji_id):
        return f'<tg-emoji emoji-id="{emoji_id}">{char or "🎮"}</tg-emoji>'
    return char
