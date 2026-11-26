"""Automatic selling prices: supplier cost + your fixed profit (in dollars).

For every package connected to Bay2Game that has a margin (its own, or the default
one), the selling price is kept equal to  supplier cost + margin.  When Bay2Game
changes its cost, the price follows by itself and the admins are told.

Auto-hide: a package that Bay2Game no longer sells (missing or inactive) is HIDDEN from
customers, and shown again by itself when Bay2Game sells it again. Only packages hidden by
this robot are re-shown - a package you hid by hand always stays hidden.

Safety: nothing changes if Bay2Game cannot be reached or sends an EMPTY list for a game (so
a supplier outage can never hide the whole shop); a price is never set below the cost;
orders already placed keep the price the customer agreed to.
"""
import asyncio
import json
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
AUTO_HIDDEN_KEY = "auto_hidden_ids"   # ids of packages hidden by this robot


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


async def _load_auto_hidden(db: Database) -> set:
    try:
        return {int(x) for x in json.loads(await repo.get_setting(db, AUTO_HIDDEN_KEY) or "[]")}
    except (ValueError, TypeError):
        return set()


async def sync_prices(db: Database, client: Bay2GameClient,
                      only_product: Optional[int] = None,
                      report: Optional[dict] = None) -> tuple:
    """Update prices and hide / re-show packages. Returns (changes, problems).

    If `report` (a dict) is given it is filled with report["hidden"] and report["restored"]
    (lists of (id, name)). Never raises on supplier errors."""
    default = await get_default_margin(db)
    rows = await db.fetchall(
        "SELECT * FROM products WHERE supplier_code IS NOT NULL AND supplier_game IS NOT NULL")
    auto = await _load_auto_hidden(db)
    auto_before = set(auto)
    auto &= {r["id"] for r in rows}                    # forget packages that were deleted
    changes, problems, hidden, restored = [], [], [], []
    games: dict = {}                                   # supplier game -> list | Exception
    for row in rows:
        if only_product is not None and row["id"] != only_product:
            continue
        sg = row["supplier_game"]
        if sg not in games:
            try:
                games[sg] = await client.products(sg)
            except Bay2GameError as exc:
                games[sg] = exc
                problems.append(f"{sg}: could not read the supplier ({exc}) - nothing changed")
            else:
                if not games[sg]:
                    problems.append(f"{sg}: Bay2Game sent no packages - nothing hidden")
        items = games[sg]
        if isinstance(items, Exception) or not items:
            continue                                   # supplier problem: never hide because of it
        sp = next((p for p in items if p.code == row["supplier_code"]), None)

        if sp is None or not sp.active:                # Bay2Game does not sell it now
            if row["is_active"]:
                done = await db.execute(
                    "UPDATE products SET is_active = 0 WHERE id = ? AND is_active = 1", (row["id"],))
                if done:
                    auto.add(row["id"])
                    hidden.append((row["id"], row["name"]))
            continue

        if row["id"] in auto:                          # it is sold again: show it again
            auto.discard(row["id"])
            if not row["is_active"]:
                done = await db.execute(
                    "UPDATE products SET is_active = 1 WHERE id = ? AND is_active = 0", (row["id"],))
                if done:
                    restored.append((row["id"], row["name"]))

        margin = effective_margin(row, default)
        if margin is None or margin < 0:
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
    if auto != auto_before:
        await repo.set_setting(db, AUTO_HIDDEN_KEY, json.dumps(sorted(auto)))
    if report is not None:
        report["hidden"], report["restored"] = hidden, restored
    return changes, problems


def describe_visibility(hidden: list, restored: list, limit: int = 2000) -> str:
    """HTML text about packages that were hidden / shown again (cut to a safe length)."""
    lines = []
    if hidden:
        lines.append(f"🙈 <b>លាក់ {len(hidden)} កញ្ចប់</b> (Bay2Game លែងលក់) - អតិថិជនលែងឃើញ")
        lines += [f"• #{i} {esc(n)}" for i, n in hidden]
    if restored:
        lines.append(f"♻️ <b>បង្ហាញវិញ {len(restored)} កញ្ចប់</b> (Bay2Game លក់វិញ)")
        lines += [f"• #{i} {esc(n)}" for i, n in restored]
    out, size = [], 0
    for k, line in enumerate(lines):
        if size + len(line) + 1 > limit:
            out.append(f"… និង {len(lines) - k} បន្ទាត់ទៀត")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


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
            report: dict = {}
            changes, _ = await sync_prices(db, client, report=report)
            if changes:
                await notify_admins(bot, settings,
                                    "💲 <b>Prices updated automatically</b>\n" + describe(changes))
            if report.get("hidden") or report.get("restored"):
                await notify_admins(bot, settings, describe_visibility(
                    report.get("hidden", []), report.get("restored", [])))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Price sync error")
        await asyncio.sleep(SYNC_INTERVAL)
