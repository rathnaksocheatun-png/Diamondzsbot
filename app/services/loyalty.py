"""Membership levels and friend referral (the "invite friends" bonus).

LEVELS   - computed from what the customer has spent on COMPLETED orders. A badge only (no money),
           so it costs nothing. Admin can change the steps with /levels.
REFERRAL - every customer has a personal link  https://t.me/<bot>?start=ref_<their telegram id>.
           A new customer who opens the bot with that link is remembered as "invited by".
           When that friend's first big-enough order is COMPLETED, the inviter gets a wallet
           credit (once per friend). Admin controls it with /referral.

Safety rules (all enforced here, in the database layer, not in the app):
 * only a brand-new customer (no orders yet) can be linked to an inviter, never yourself;
 * the reward is paid after the order is completed (not at sign-up), exactly once per friend
   (UNIQUE friend_id), only if the order is at least the minimum, and only up to a monthly cap;
 * the credit is saved in the history as type 'deposit' with the note '[referral] ...', so it
   never counts as a customer deposit or as a sale (reports show it on its own line).
"""
import asyncio
import json
import logging
from typing import Optional

from app.database import repositories as repo
from app.database.db import Database

log = logging.getLogger("diamond_zs.loyalty")

# name, from how many cents spent. Icons are given by position.
DEFAULT_LEVELS = [("Bronze", 0), ("Silver", 2000), ("Gold", 5000), ("Diamond", 10000)]
LEVEL_ICONS = ["🥉", "🥈", "🥇", "💎", "👑", "🏆"]
MAX_LEVELS = len(LEVEL_ICONS)

DEFAULT_MIN_ORDER_CENTS = 100      # a friend's order must be at least $1.00 to count
DEFAULT_MONTHLY_CAP = 20           # at most 20 rewards per inviter per calendar month


# --------------------------------------------------------------------------- levels


async def get_levels(db: Database) -> list:
    """[(name, from_cents), ...] sorted, first one always from 0. Falls back to the defaults."""
    raw = await repo.get_setting(db, "levels")
    try:
        data = json.loads(raw) if raw else None
        levels = [(str(n)[:16], int(c)) for n, c in data]
        levels.sort(key=lambda x: x[1])
        if 2 <= len(levels) <= MAX_LEVELS and levels[0][1] == 0:
            return levels
    except (ValueError, TypeError):
        pass
    return list(DEFAULT_LEVELS)


async def get_level_bonuses(db: Database, levels: list) -> dict:
    """{level index: bonus cents} - a one-time wallet credit when the customer first reaches that level."""
    try:
        raw = json.loads(await repo.get_setting(db, "level_bonus") or "{}")
        by_name = {str(k).lower(): int(v) for k, v in raw.items()}
    except (ValueError, TypeError, AttributeError):
        by_name = {}
    return {i: by_name[n.lower()] for i, (n, _) in enumerate(levels)
            if i >= 1 and by_name.get(n.lower(), 0) > 0}


async def sync_level_seen(db: Database) -> int:
    """Mark every customer as 'already reached' the level they have NOW. Called when the admin
    sets a bonus, so bonuses are only paid for levels reached AFTER that moment (no surprise
    pay-out to customers who crossed a level long ago). Returns how many customers changed."""
    levels = await get_levels(db)
    rows = await db.fetchall(
        "SELECT u.id, u.level_seen, COALESCE(SUM(o.price_cents), 0) AS s FROM users u "
        "LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'completed' GROUP BY u.id")
    changed = 0
    for r in rows:
        idx = level_info(levels, r["s"])["index"]
        if idx > r["level_seen"]:
            await db.execute("UPDATE users SET level_seen = ? WHERE id = ?", (idx, r["id"]))
            changed += 1
    return changed


def level_info(levels: list, spent_cents: int) -> dict:
    """Where the customer is now and how far the next level is."""
    idx = 0
    for i, (_, need) in enumerate(levels):
        if spent_cents >= need:
            idx = i
    name, start = levels[idx]
    info = {"name": name, "icon": LEVEL_ICONS[idx], "index": idx, "spent_cents": spent_cents,
            "next_name": None, "next_icon": None, "next_cents": None,
            "remaining_cents": 0, "progress": 100}
    if idx + 1 < len(levels):
        nname, need = levels[idx + 1]
        span = max(need - start, 1)
        info.update(next_name=nname, next_icon=LEVEL_ICONS[idx + 1], next_cents=need,
                    remaining_cents=max(need - spent_cents, 0),
                    progress=max(0, min(100, int((spent_cents - start) * 100 / span))))
    return info


async def spent_cents(db: Database, user_id: int) -> int:
    row = await db.fetchone(
        "SELECT COALESCE(SUM(price_cents), 0) AS s FROM orders "
        "WHERE user_id = ? AND status = 'completed'", (user_id,))
    return row["s"]


# ------------------------------------------------------------------------- referral


async def get_referral_config(db: Database) -> dict:
    def num(raw, default):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    on = (await repo.get_setting(db, "ref_on")) == "1"
    return {
        "on": on,
        "reward_cents": num(await repo.get_setting(db, "ref_reward_cents"), 0),
        "min_cents": num(await repo.get_setting(db, "ref_min_cents"), DEFAULT_MIN_ORDER_CENTS),
        "cap_month": num(await repo.get_setting(db, "ref_cap_month"), DEFAULT_MONTHLY_CAP),
    }


def referral_active(cfg: dict) -> bool:
    return bool(cfg["on"] and cfg["reward_cents"] > 0)


async def record_referrer(db: Database, new_user: dict, referrer_telegram_id: int) -> bool:
    """Remember who invited a brand-new customer. True only if it was saved.

    Refused for: yourself, an unknown inviter, a customer who already has an inviter or
    already ordered something (so old customers can't be 'invited' afterwards)."""
    if referrer_telegram_id == new_user["telegram_id"]:
        return False
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT id FROM users WHERE telegram_id = ?",
                                 (referrer_telegram_id,))
        ref = await cur.fetchone()
        await cur.close()
        if ref is None or ref["id"] == new_user["id"]:
            return False
        cur = await conn.execute(
            "UPDATE users SET referred_by = ? WHERE id = ? AND referred_by IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",
            (ref["id"], new_user["id"]))
        changed = cur.rowcount
        await cur.close()
        return changed == 1


async def reward_for_order(db: Database, order_id: int) -> Optional[dict]:
    """Called right after an order was completed. Pays the inviter if all rules are met.

    Returns {"referrer_id", "friend_id", "amount_cents"} when money was paid, else None."""
    cfg = await get_referral_config(db)
    if not referral_active(cfg):
        return None
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT o.user_id, o.price_cents, o.status, u.referred_by FROM orders o "
            "JOIN users u ON u.id = o.user_id WHERE o.id = ?", (order_id,))
        o = await cur.fetchone()
        await cur.close()
        if (o is None or o["status"] != "completed" or not o["referred_by"]
                or o["price_cents"] < cfg["min_cents"] or o["referred_by"] == o["user_id"]):
            return None
        friend_id, referrer_id, reward = o["user_id"], o["referred_by"], cfg["reward_cents"]
        cur = await conn.execute("SELECT 1 FROM referral_rewards WHERE friend_id = ?", (friend_id,))
        paid_before = await cur.fetchone()
        await cur.close()
        if paid_before is not None:
            return None
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM referral_rewards WHERE referrer_id = ? "
            "AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')", (referrer_id,))
        this_month = (await cur.fetchone())["n"]
        await cur.close()
        if this_month >= cfg["cap_month"]:
            return None
        cur = await conn.execute("SELECT balance_cents FROM users WHERE id = ?", (referrer_id,))
        ref = await cur.fetchone()
        await cur.close()
        if ref is None:
            return None
        new_balance = ref["balance_cents"] + reward
        await conn.execute("UPDATE users SET balance_cents = ? WHERE id = ?",
                           (new_balance, referrer_id))
        await conn.execute(
            "INSERT INTO transactions (user_id, type, amount_cents, balance_after_cents, note) "
            "VALUES (?, 'deposit', ?, ?, ?)",
            (referrer_id, reward, new_balance, f"[referral] friend {friend_id} order #{order_id}"))
        await conn.execute(
            "INSERT INTO referral_rewards (referrer_id, friend_id, order_id, amount_cents) "
            "VALUES (?, ?, ?, ?)", (referrer_id, friend_id, order_id, reward))
    return {"referrer_id": referrer_id, "friend_id": friend_id, "amount_cents": reward}


async def check_level_up(db: Database, order_id: int) -> Optional[dict]:
    """Called right after an order was completed. If the customer's total spending just crossed
    into a higher level, remember it (once per level) so the congratulation message is sent."""
    levels = await get_levels(db)
    bonuses = await get_level_bonuses(db, levels)
    bonus = 0
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT o.user_id, u.level_seen FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.id = ? AND o.status = 'completed'", (order_id,))
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            return None
        cur = await conn.execute(
            "SELECT COALESCE(SUM(price_cents), 0) AS s FROM orders "
            "WHERE user_id = ? AND status = 'completed'", (row["user_id"],))
        spent = (await cur.fetchone())["s"]
        await cur.close()
        idx = level_info(levels, spent)["index"]
        if idx <= row["level_seen"]:
            return None
        await conn.execute("UPDATE users SET level_seen = ? WHERE id = ?", (idx, row["user_id"]))
        if idx >= 1:                                  # the first level (from $0) is not worth a message
            # Every level crossed pays its bonus, so one big purchase pays the same total as
            # climbing step by step (nobody is better off by splitting purchases).
            crossed = range(row["level_seen"] + 1, idx + 1)
            bonus = sum(bonuses.get(i, 0) for i in crossed)
            if bonus > 0:
                cur = await conn.execute("SELECT balance_cents FROM users WHERE id = ?", (row["user_id"],))
                new_balance = (await cur.fetchone())["balance_cents"] + bonus
                await cur.close()
                await conn.execute("UPDATE users SET balance_cents = ? WHERE id = ?",
                                   (new_balance, row["user_id"]))
                await conn.execute(
                    "INSERT INTO transactions (user_id, type, amount_cents, balance_after_cents, note) "
                    "VALUES (?, 'deposit', ?, ?, ?)",
                    (row["user_id"], bonus, new_balance, f"[level] {levels[idx][0]} bonus"))
            await conn.execute(
                "INSERT INTO level_ups (user_id, level_idx, level_name, bonus_cents) VALUES (?, ?, ?, ?)",
                (row["user_id"], idx, levels[idx][0], bonus))
    return {"user_id": row["user_id"], "level_idx": idx, "level_name": levels[idx][0], "bonus_cents": bonus}


async def account_extras(db: Database, user: dict, bot_username: str) -> dict:
    """Level + referral numbers for the Mini App profile tab."""
    levels = await get_levels(db)
    cfg = await get_referral_config(db)
    info = level_info(levels, await spent_cents(db, user["id"]))
    info["next_bonus_cents"] = (await get_level_bonuses(db, levels)).get(info["index"] + 1, 0)
    invited = await db.fetchone("SELECT COUNT(*) AS n FROM users WHERE referred_by = ?", (user["id"],))
    bought = await db.fetchone(
        "SELECT COUNT(DISTINCT o.user_id) AS n FROM orders o JOIN users u ON u.id = o.user_id "
        "WHERE u.referred_by = ? AND o.status = 'completed'", (user["id"],))
    earned = await db.fetchone(
        "SELECT COALESCE(SUM(amount_cents), 0) AS s FROM referral_rewards WHERE referrer_id = ?",
        (user["id"],))
    link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}" if bot_username else ""
    return {
        "level": info,
        "referral": {"active": referral_active(cfg), "reward_cents": cfg["reward_cents"],
                     "min_cents": cfg["min_cents"], "link": link, "invited": invited["n"],
                     "bought": bought["n"], "earned_cents": earned["s"]},
    }


async def referral_admin_stats(db: Database) -> dict:
    invited = await db.fetchone("SELECT COUNT(*) AS n FROM users WHERE referred_by IS NOT NULL")
    paid = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS s FROM referral_rewards")
    return {"invited": invited["n"], "paid_n": paid["n"], "paid_cents": paid["s"]}


# ------------------------------------------------------------- tell the inviter


async def watch_referral_rewards(bot, db: Database) -> None:
    """Background loop: thank-you message to inviters whose reward was paid, and a
    congratulation message to customers who reached a new membership level."""
    from app.texts import t
    from app.utils.formatting import esc, money
    from app.utils.telegram import notify_user
    while True:
        try:
            rows = await db.fetchall(
                "SELECT r.id, r.amount_cents, f.full_name AS friend, u.telegram_id, u.language "
                "FROM referral_rewards r JOIN users u ON u.id = r.referrer_id "
                "JOIN users f ON f.id = r.friend_id WHERE r.notified = 0 ORDER BY r.id LIMIT 20")
            for r in rows:
                await notify_user(bot, r["telegram_id"], t(
                    r["language"], "referral_reward_user",
                    friend=esc(r["friend"] or "-"), amount=money(r["amount_cents"])))
                await db.execute("UPDATE referral_rewards SET notified = 1 WHERE id = ?", (r["id"],))
            ups = await db.fetchall(
                "SELECT l.id, l.level_idx, l.level_name, l.bonus_cents, u.telegram_id, u.language "
                "FROM level_ups l JOIN users u ON u.id = l.user_id WHERE l.notified = 0 "
                "ORDER BY l.id LIMIT 20")
            for r in ups:
                await notify_user(bot, r["telegram_id"], t(
                    r["language"], "level_up_bonus_user" if r["bonus_cents"] > 0 else "level_up_user",
                    icon=LEVEL_ICONS[min(r["level_idx"], MAX_LEVELS - 1)], level=esc(r["level_name"]),
                    amount=money(r["bonus_cents"])))
                await db.execute("UPDATE level_ups SET notified = 1 WHERE id = ?", (r["id"],))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Could not send referral / level-up notifications")
        await asyncio.sleep(20)
