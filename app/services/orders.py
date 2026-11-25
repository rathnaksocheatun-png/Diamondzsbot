"""Order rules: create, complete, cancel (with refund)."""
import logging
import sqlite3

from app.database.db import Database
from app.services import coins as coin_service
from app.services.errors import (
    DuplicateOrder,
    InsufficientBalance,
    NotFoundOrAlreadyHandled,
    ProductUnavailable,
)


log = logging.getLogger("diamond_zs.orders")


async def create_order(
    db: Database, telegram_id: int, product_id: int, player_id: str, server_id: str
) -> int:
    """Take the money from the wallet and create a PENDING order, atomically.

    Nothing is delivered automatically: an admin completes the order by hand.
    Raises ProductUnavailable, InsufficientBalance or DuplicateOrder.
    """
    try:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cur.fetchone()
            cur = await conn.execute(
                "SELECT p.*, g.needs_server_id FROM products p "
                "JOIN games g ON g.code = p.game_code "
                "WHERE p.id = ? AND p.is_active = 1 AND g.is_active = 1",
                (product_id,),
            )
            product = await cur.fetchone()
            if user is None or product is None:
                raise ProductUnavailable()

            if product["needs_server_id"] and not server_id:
                raise ProductUnavailable()
            if not product["needs_server_id"]:
                server_id = ""

            cur = await conn.execute(
                "SELECT 1 FROM orders WHERE user_id = ? AND product_id = ? "
                "AND player_id = ? AND server_id = ? AND status = 'pending'",
                (user["id"], product_id, player_id, server_id),
            )
            if await cur.fetchone() is not None:
                raise DuplicateOrder()

            price = product["price_cents"]
            if user["balance_cents"] < price:
                raise InsufficientBalance(price, user["balance_cents"])

            new_balance = user["balance_cents"] - price
            await conn.execute(
                "UPDATE users SET balance_cents = ? WHERE id = ?",
                (new_balance, user["id"]),
            )
            cur = await conn.execute(
                "INSERT INTO orders (user_id, product_id, game_code, product_name, "
                "player_id, server_id, price_cents) VALUES (?,?,?,?,?,?,?)",
                (user["id"], product_id, product["game_code"], product["name"],
                 player_id, server_id, price),
            )
            order_id = cur.lastrowid
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount_cents, "
                "balance_after_cents, order_id, note) VALUES (?, 'purchase', ?, ?, ?, ?)",
                (user["id"], -price, new_balance, order_id, product["name"]),
            )
            return order_id
    except sqlite3.IntegrityError:
        # Two taps at the same moment: the unique index stops the second one.
        raise DuplicateOrder()


async def complete_order(db: Database, order_id: int) -> int:
    """Mark an order completed. Returns the free coins the customer earned (0 = none)."""
    tiers = await coin_service.get_rewards(db)        # read BEFORE the transaction
    async with db.transaction() as conn:
        cur = await conn.execute(
            "UPDATE orders SET status = 'completed', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'", (order_id,))
        if cur.rowcount != 1:
            raise NotFoundOrAlreadyHandled()
        cur = await conn.execute(
            "SELECT user_id, price_cents FROM orders WHERE id = ?", (order_id,))
        order = await cur.fetchone()
        coins = coin_service.reward_for(order["price_cents"], tiers)
        if coins:
            await conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?",
                               (coins, order["user_id"]))
    coin_service.notify_reward(db, order_id, coins)    # after the commit
    # Friend referral bonus. It must NEVER stop an order from being completed.
    try:
        from app.services import loyalty
        await loyalty.reward_for_order(db, order_id)
    except Exception:
        log.exception("Referral reward failed for order %s (the order itself is completed)", order_id)
    return coins


async def cancel_order(db: Database, order_id: int) -> None:
    """Cancel a pending order and refund the customer's wallet (only once)."""
    async with db.transaction() as conn:
        cur = await conn.execute(
            "UPDATE orders SET status = 'cancelled', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            (order_id,),
        )
        if cur.rowcount != 1:
            raise NotFoundOrAlreadyHandled()
        cur = await conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        order = await cur.fetchone()
        cur = await conn.execute(
            "SELECT balance_cents FROM users WHERE id = ?", (order["user_id"],)
        )
        balance = (await cur.fetchone())["balance_cents"] + order["price_cents"]
        await conn.execute(
            "UPDATE users SET balance_cents = ? WHERE id = ?",
            (balance, order["user_id"]),
        )
        await conn.execute(
            "INSERT INTO transactions (user_id, type, amount_cents, "
            "balance_after_cents, order_id, note) VALUES (?, 'refund', ?, ?, ?, ?)",
            (order["user_id"], order["price_cents"], balance, order_id,
             order["product_name"]),
        )
