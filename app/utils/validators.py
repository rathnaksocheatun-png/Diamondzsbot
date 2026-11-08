"""Input validation. Every piece of text typed by a user passes through here."""
import re
from typing import Optional

_PLAYER_ID = re.compile(r"^\d{5,15}$")
_SERVER_ID = re.compile(r"^\d{1,6}$")
_AMOUNT = re.compile(r"^\d{1,6}(\.\d{1,2})?$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

MIN_DEPOSIT_CENTS = 50          # $0.50
MAX_DEPOSIT_CENTS = 100_000     # $1000.00
MAX_PRICE_CENTS = 1_000_000     # $10000.00


def clean_text(text: Optional[str]) -> str:
    return (text or "").strip()


def valid_player_id(text: Optional[str]) -> Optional[str]:
    value = clean_text(text)
    return value if _PLAYER_ID.match(value) else None


def valid_server_id(text: Optional[str]) -> Optional[str]:
    value = clean_text(text)
    return value if _SERVER_ID.match(value) else None


def parse_money(text: Optional[str]) -> Optional[int]:
    """'5' -> 500, '10.5' -> 1050. Returns cents, or None if invalid."""
    value = clean_text(text).lstrip("$")
    if not _AMOUNT.match(value):
        return None
    whole, _, frac = value.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def valid_deposit(cents: Optional[int]) -> bool:
    return cents is not None and MIN_DEPOSIT_CENTS <= cents <= MAX_DEPOSIT_CENTS


def valid_price(cents: Optional[int]) -> bool:
    return cents is not None and 0 < cents <= MAX_PRICE_CENTS


def valid_product_name(text: Optional[str]) -> Optional[str]:
    value = clean_text(text)
    if not 2 <= len(value) <= 40 or _CONTROL_CHARS.search(value):
        return None
    return value


def valid_promo_text(text: Optional[str]) -> Optional[str]:
    value = clean_text(text)
    if not 1 <= len(value) <= 1500:
        return None
    return value


def to_int(text: Optional[str]) -> Optional[int]:
    """Safely convert callback data pieces to int."""
    if text is not None and text.isdigit() and len(text) < 12:
        return int(text)
    return None
