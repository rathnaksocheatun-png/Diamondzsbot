"""Basic sales numbers for the admin panel."""
from app.database.db import Database


async def sales_report(db: Database) -> dict:
    customers = await db.fetchone("SELECT COUNT(*) AS n FROM users")
    by_status = await db.fetchall(
        "SELECT status, COUNT(*) AS n, COALESCE(SUM(price_cents), 0) AS total "
        "FROM orders GROUP BY status"
    )
    today = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(price_cents), 0) AS total FROM orders "
        "WHERE status = 'completed' AND date(updated_at) = date('now')"
    )
    deposits = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total "
        "FROM deposit_requests WHERE status = 'approved'"
    )
    pending_deposits = await db.fetchone(
        "SELECT COUNT(*) AS n FROM deposit_requests WHERE status = 'pending'"
    )
    wallets = await db.fetchone(
        "SELECT COALESCE(SUM(balance_cents), 0) AS total FROM users"
    )
    # Money the admin added / took by hand (/addbalance, /subbalance). Kept apart from
    # deposits and sales on purpose: it is not a customer payment or a purchase.
    manual_added = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total FROM transactions "
        "WHERE note LIKE '[manual]%' AND amount_cents > 0"
    )
    manual_deducted = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(-SUM(amount_cents), 0) AS total FROM transactions "
        "WHERE note LIKE '[manual]%' AND amount_cents < 0"
    )
    referral = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total FROM transactions "
        "WHERE note LIKE '[referral]%'"
    )
    level_bonus = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total FROM transactions "
        "WHERE note LIKE '[level]%'"
    )
    per_game = await db.fetchall(
        "SELECT g.name AS name, COUNT(o.id) AS n, COALESCE(SUM(o.price_cents), 0) AS total "
        "FROM games g LEFT JOIN orders o ON o.game_code = g.code AND o.status = 'completed' "
        "GROUP BY g.code ORDER BY g.sort_order"
    )
    return {
        "customers": customers["n"],
        "by_status": {r["status"]: r for r in by_status},
        "today": today,
        "deposits": deposits,
        "pending_deposits": pending_deposits["n"],
        "wallets_total": wallets["total"],
        "manual_added": manual_added,
        "manual_deducted": manual_deducted,
        "referral": referral,
        "level_bonus": level_bonus,
        "per_game": per_game,
    }
