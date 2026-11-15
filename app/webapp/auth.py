"""Check that a Mini App request really comes from Telegram.

Telegram gives the page a signed string (initData). We re-compute the signature
with the bot token; if it matches, the user id inside can be trusted. Nobody can
fake it without the bot token.
"""
import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

MAX_AGE_SECONDS = 24 * 3600     # an old copy of initData stops working after a day


def _signature(pairs: dict, secret: bytes) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str, bot_token: str,
                       max_age: int = MAX_AGE_SECONDS) -> Optional[dict]:
    """Return the Telegram user (dict with 'id' ...) or None if the data is not valid."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = pairs.pop("hash", None)
    if not received:
        return None
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    ok = hmac.compare_digest(_signature(pairs, secret), received)
    if not ok and "signature" in pairs:       # newer Telegram versions add this extra field
        trimmed = {k: v for k, v in pairs.items() if k != "signature"}
        ok = hmac.compare_digest(_signature(trimmed, secret), received)
    if not ok:
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(pairs.get("user", ""))
    except (ValueError, TypeError):
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    return user
