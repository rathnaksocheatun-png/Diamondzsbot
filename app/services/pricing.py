"""Automatic selling prices: supplier cost + your fixed profit (in dollars).

For every package connected to Bay2Game that has a margin (its own, or the default
one), the selling price is kept equal to  supplier cost + margin.  When Bay2Game
changes its cost, the price follows by itself and the admins are told.

Safety: nothing changes if the supplier package is missing/inactive or Bay2Game
cannot be reached; a price is never set below the cost; orders already placed keep
the price the customer agreed to.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.services.bay2game import Bay2GameClient, Bay2GameError
from app.utils.formatting import esc, money
from app.utils.telegram import notify_admins
from app.utils.validators import valid_price

log = logging.getLogger(__name__)

DEFAULT_MARGIN_KEY = "default_margin_cents"
SYNC_INTERVAL = 600.0     # 10 minutes


@dataclass
class PriceChange:
    product_id: int
    name: str
    old_cents: int
    new_cents: int
    cost_cents: int
    margin_cents: int


async def get_default_margin(db: Database) -> Optional[int]:
    raw = await repo.get_setting(db, DEFAULT_MARGIN_KEY)
    try:
        return int(raw) if raw not in (None, "") else None
    except ValueError:
        return None


async def set_default_margin(db: Database, cents: Optional[int]) -> None:
    await repo.set_setting(db, DEFAULT_MARGIN_KEY, "" if cents is None else str(cents))


def effective_margin(row, default: Optional[int]) -> Optional[int]:
    m = row["margin_cents"]
    return m if m is not None else default


async def sync_prices(db: Database, client: Bay2GameClient,
                      only_product: Optional[int] = None) -> tuple:
    """Returns (changes, problems). Never raises on supplier errors."""
    default = await get_default_margin(db)
    rows = await db.fetchall(
        "SELECT * FROM products WHERE supplier_code IS NOT NULL AND supplier_game IS NOT NULL")
    changes, problems = [], []
    for row in rows:
        if only_product is not None and row["id"] != only_product:
            continue
        margin = effective_margin(row, default)
        if margin is None or margin < 0:
            continue
        try:
            sp = await client.find_product(row["supplier_game"], row["supplier_code"])
        except Bay2GameError as exc:
            problems.append(f"{row['name']}: could not read supplier price ({exc})")
            continue
        if sp is None or not sp.active:
            problems.append(f"{row['name']}: supplier package missing or inactive - price kept")
            continue
        new_price = sp.price_cents + margin
        if not valid_price(new_price):
            problems.append(f"{row['name']}: calculated price {money(new_price)} is not allowed")
            continue
        if new_price != row["price_cents"]:
            await db.execute(
                "UPDATE products SET price_cents = ? WHERE id = ? AND price_cents = ?",
                (new_price, row["id"], row["price_cents"]))
            changes.append(PriceChange(row["id"], row["name"], row["price_cents"],
                                       new_price, sp.price_cents, margin))
    return changes, problems


def describe(changes: list, limit: int = 2800) -> str:
    """HTML list of price changes. It is cut short (whole lines only, so no HTML tag is ever
    broken) because Telegram refuses messages longer than 4096 characters."""
    lines = [f"• <b>#{c.product_id}</b> {esc(c.name)}: {money(c.old_cents)} → "
             f"<b>{money(c.new_cents)}</b> (cost {money(c.cost_cents)} + profit {money(c.margin_cents)})"
             for c in changes]
    out, size = [], 0
    for i, line in enumerate(lines):
        if size + len(line) + 1 > limit:
            out.append(f"… និង {len(lines) - i} កញ្ចប់ទៀត (តម្លៃត្រូវបានកែរួចហើយ)")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


async def watch_prices(bot: Bot, db: Database, client: Bay2GameClient,
                       settings: Settings) -> None:
    while True:
        try:
            changes, _ = await sync_prices(db, client)
            if changes:
                await notify_admins(bot, settings,
                                    "💲 <b>Prices updated automatically</b>\n" + describe(changes))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Price sync error")
        await asyncio.sleep(SYNC_INTERVAL)
