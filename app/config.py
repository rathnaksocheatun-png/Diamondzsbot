"""Loads settings from the .env file. Secrets never live in source code."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """Raised when the .env file is missing or contains wrong values."""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset
    database_path: str
    support_username: str
    khpay_api_key: str = ""          # empty = automatic payments OFF (manual approval)
    khpay_base_url: str = "https://khpay.site/api/v1"
    khpay_test_mode: bool = False
    bay2game_api_key: str = ""       # empty = diamonds are delivered by an admin by hand
    bay2game_base_url: str = "https://api.bay2game.xyz/api"
    bay2game_method: str = "POST"
    bay2game_ref_prefix: str = "DZS"
    bay2game_low_balance_cents: int = 1000
    orders_chat_id: int = 0          # 0 = no orders group; else notices are posted there
    payments_chat_id: int = 0        # 0 = no payments group


def _parse_admin_ids(raw: str) -> frozenset:
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError(
                f"ADMIN_IDS must contain only numbers separated by commas. Got: {part!r}"
            )
        ids.add(int(part))
    return frozenset(ids)


def _parse_chat_id(name: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number like -1001234567890. Got: {raw!r}")


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token.startswith("PASTE_") or ":" not in token:
        raise ConfigError(
            "BOT_TOKEN is missing or still the example value. "
            "Open your .env file and paste the token from @BotFather."
        )

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    if not admin_ids:
        raise ConfigError(
            "ADMIN_IDS is missing. Open your .env file and add your numeric "
            "Telegram ID (get it from @userinfobot)."
        )

    db_path = os.getenv("DATABASE_PATH", "data/diamond_zs.db").strip()
    path = Path(db_path)
    if not path.is_absolute():
        path = BASE_DIR / path

    support = os.getenv("SUPPORT_USERNAME", "").strip()
    if support.startswith("@your_support"):
        support = ""

    khpay_key = os.getenv("KHPAY_API_KEY", "").strip()
    if khpay_key.startswith("PASTE_"):
        khpay_key = ""
    base_url = os.getenv("KHPAY_BASE_URL", "https://khpay.site/api/v1").strip()
    if khpay_key and not base_url.lower().startswith("https://"):
        raise ConfigError("KHPAY_BASE_URL must start with https://")

    b2g_key = os.getenv("BAY2GAME_API_KEY", "").strip()
    if b2g_key.startswith("PASTE_"):
        b2g_key = ""
    b2g_url = os.getenv("BAY2GAME_BASE_URL", "https://api.bay2game.xyz/api").strip()
    if b2g_key and not b2g_url.lower().startswith("https://"):
        raise ConfigError("BAY2GAME_BASE_URL must start with https://")
    try:
        low_balance = int(round(float(os.getenv("BAY2GAME_LOW_BALANCE", "10") or 10) * 100))
    except ValueError:
        raise ConfigError("BAY2GAME_LOW_BALANCE must be a number, e.g. 10")

    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        database_path=str(path),
        support_username=support,
        khpay_api_key=khpay_key,
        khpay_base_url=base_url,
        khpay_test_mode=os.getenv("KHPAY_TEST_MODE", "").strip().lower() in ("1", "true", "yes"),
        bay2game_api_key=b2g_key,
        bay2game_base_url=b2g_url,
        bay2game_method="GET" if os.getenv("BAY2GAME_METHOD", "").strip().upper() == "GET" else "POST",
        bay2game_ref_prefix=("".join(c for c in os.getenv("BAY2GAME_REF_PREFIX", "DZS") if c.isalnum()) or "DZS")[:12],
        bay2game_low_balance_cents=low_balance,
        orders_chat_id=_parse_chat_id("ORDERS_CHAT_ID"),
        payments_chat_id=_parse_chat_id("PAYMENTS_CHAT_ID"),
    )
