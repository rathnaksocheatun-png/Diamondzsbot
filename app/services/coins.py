"""Coins for the lucky wheel.

* Coin packs (what a customer pays for coins) - admin edits them with /coinprice.
* Free-coin rewards for completed orders       - admin edits them with /coinreward.
Both are saved in the `settings` table, so changes are live without a restart.
"""
import asyncio
import json
import logging

from app.database import repositories as repo
from app.texts import t

log = logging.getLogger("diamond_zs.coins")

BOT = None                     # set once in main.py (used to tell the customer about free coins)
_tasks: set = set()

PACKS_KEY = "coin_packs"
PACKS_DEFAULT = [(1, 10), (5, 45), (10, 80)]          # (coins, price in cents)

REWARD_KEY = "coin_rewards"
REWARD_DEFAULT = [(500, 1), (1000, 3)]                 # (min order price in cents, coins)


# ------------------------------------------------------------------ coin packs


async def get_packs(db) -> list:
    try:
        raw = json.loads(await repo.get_setting(db, PACKS_KEY) or "null")
        packs = [(int(c), int(p)) for c, p in raw]
        if 1 <= len(packs) <= 6 and all(0 < c <= 1000 and 0 < p <= 100000 for c, p in packs):
            return packs
    except (ValueError, TypeError):
        pass
    return list(PACKS_DEFAULT)


async def set_packs(db, packs) -> None:
    """None = back to the default packs."""
    await repo.set_setting(db, PACKS_KEY, json.dumps(packs) if packs else "")


# ----------------------------------------------------------- order rewards


async def get_rewards(db) -> list:
    raw = await repo.get_setting(db, REWARD_KEY)
    if not raw:
        return list(REWARD_DEFAULT)
    try:
        tiers = [(int(m), int(c)) for m, c in json.loads(raw)]
        if len(tiers) <= 6 and all(m > 0 and 0 < c <= 100 for m, c in tiers):
            return tiers
    except (ValueError, TypeError):
        pass
    return list(REWARD_DEFAULT)


async def set_rewards(db, tiers) -> None:
    """None = back to default, [] = reward turned off."""
    await repo.set_setting(db, REWARD_KEY, "" if tiers is None else json.dumps(tiers))


def reward_for(price_cents: int, tiers: list) -> int:
    return max([c for m, c in tiers if price_cents >= m], default=0)


def notify_reward(db, order_id: int, coins: int) -> None:
    """Tell the customer (a moment later, after the 'order completed' message)."""
    if BOT is None or not coins:
        return
    task = asyncio.create_task(_notify(db, order_id, coins))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _notify(db, order_id: int, coins: int) -> None:
    try:
        await asyncio.sleep(2)
        row = await db.fetchone(
            "SELECT u.telegram_id, u.language FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.id = ?", (order_id,))
        if row:
            from app.utils.telegram import notify_user      # local import: no import loops
            await notify_user(BOT, row["telegram_id"],
                              t(row["language"], "coin_reward_user", coins=coins))
    except Exception:
        log.exception("Could not send the free-coin message for order #%s", order_id)
