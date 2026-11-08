"""Simple read/write functions for each table (no business rules here)."""
from typing import Optional

from app.database.db import Database

# ----------------------------------------------------------------- users


async def upsert_user(db: Database, tg_user) -> tuple:
    """Create the customer on first contact, keep their name up to date.

    Returns (user_dict, created_bool).
    """
    full_name = (tg_user.full_name or "")[:100]
    username = tg_user.username
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (tg_user.id,)
        )
        row = await cur.fetchone()
        created = row is None
        if created:
            language = "km" if (tg_user.language_code or "").startswith("km") else "en"
            await conn.execute(
                "INSERT INTO users (telegram_id, username, full_name, language) "
                "VALUES (?, ?, ?, ?)",
                (tg_user.id, username, full_name, language),
            )
        elif row["username"] != username or row["full_name"] != full_name:
            await conn.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE telegram_id = ?",
                (username, full_name, tg_user.id),
            )
        cur = await conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (tg_user.id,)
        )
        user = dict(await cur.fetchone())
    return user, created


async def set_language(db: Database, telegram_id: int, language: str) -> None:
    if language not in ("en", "km"):
        raise ValueError("unsupported language")
    await db.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?", (language, telegram_id)
    )


async def count_users(db: Database) -> int:
    row = await db.fetchone("SELECT COUNT(*) AS n FROM users")
    return row["n"]


async def list_users(db: Database, limit: int, offset: int) -> list:
    return await db.fetchall(
        "SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    )


# ----------------------------------------------------------------- games


async def list_games(db: Database) -> list:
    return await db.fetchall("SELECT * FROM games ORDER BY sort_order, name")


async def get_game(db: Database, code: str) -> Optional[dict]:
    return await db.fetchone("SELECT * FROM games WHERE code = ?", (code,))


# -------------------------------------------------------------- products


async def list_products(db: Database, game_code: str, only_active: bool) -> list:
    sql = "SELECT * FROM products WHERE game_code = ?"
    if only_active:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order, id"
    return await db.fetchall(sql, (game_code,))


async def get_product(db: Database, product_id: int) -> Optional[dict]:
    return await db.fetchone(
        "SELECT p.*, g.name AS game_name, g.needs_server_id "
        "FROM products p JOIN games g ON g.code = p.game_code WHERE p.id = ?",
        (product_id,),
    )


async def add_product(db: Database, game_code: str, name: str, price_cents: int) -> int:
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM products WHERE game_code = ?",
            (game_code,),
        )
        next_order = (await cur.fetchone())["n"]
        cur = await conn.execute(
            "INSERT INTO products (game_code, name, price_cents, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (game_code, name, price_cents, next_order),
        )
        return cur.lastrowid


async def update_product_price(db: Database, product_id: int, price_cents: int) -> bool:
    return await db.execute(
        "UPDATE products SET price_cents = ? WHERE id = ?", (price_cents, product_id)
    ) == 1


async def update_product_name(db: Database, product_id: int, name: str) -> bool:
    return await db.execute(
        "UPDATE products SET name = ? WHERE id = ?", (name, product_id)
    ) == 1


async def set_supplier_mapping(
    db: Database, product_id: int, supplier_game: Optional[str], supplier_code: Optional[str]
) -> bool:
    return await db.execute(
        "UPDATE products SET supplier_game = ?, supplier_code = ? WHERE id = ?",
        (supplier_game, supplier_code, product_id),
    ) == 1


async def set_product_margin(db: Database, product_id: int, margin_cents: Optional[int]) -> bool:
    return await db.execute(
        "UPDATE products SET margin_cents = ? WHERE id = ?", (margin_cents, product_id)) == 1


async def list_all_products(db: Database) -> list:
    return await db.fetchall(
        "SELECT p.*, g.name AS game_name FROM products p JOIN games g ON g.code = p.game_code "
        "ORDER BY g.sort_order, p.game_code, p.sort_order, p.id"
    )


async def toggle_product(db: Database, product_id: int) -> bool:
    return await db.execute(
        "UPDATE products SET is_active = 1 - is_active WHERE id = ?", (product_id,)
    ) == 1


# ---------------------------------------------------------------- orders

_ORDER_SELECT = (
    "SELECT o.*, u.telegram_id AS user_telegram_id, u.full_name AS user_name, "
    "u.username AS user_username, u.language AS user_language, g.name AS game_name "
    "FROM orders o JOIN users u ON u.id = o.user_id "
    "JOIN games g ON g.code = o.game_code "
)


async def list_user_orders(db: Database, user_id: int, limit: int = 10) -> list:
    return await db.fetchall(
        _ORDER_SELECT + "WHERE o.user_id = ? ORDER BY o.id DESC LIMIT ?",
        (user_id, limit),
    )


async def get_order(db: Database, order_id: int) -> Optional[dict]:
    return await db.fetchone(_ORDER_SELECT + "WHERE o.id = ?", (order_id,))


async def list_orders(db: Database, status: Optional[str], limit: int, offset: int) -> list:
    if status:
        return await db.fetchall(
            _ORDER_SELECT + "WHERE o.status = ? ORDER BY o.id DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    return await db.fetchall(
        _ORDER_SELECT + "ORDER BY o.id DESC LIMIT ? OFFSET ?", (limit, offset)
    )


async def count_orders(db: Database, status: Optional[str]) -> int:
    if status:
        row = await db.fetchone("SELECT COUNT(*) AS n FROM orders WHERE status = ?", (status,))
    else:
        row = await db.fetchone("SELECT COUNT(*) AS n FROM orders")
    return row["n"]


# ---------------------------------------------------------- transactions


async def list_user_transactions(db: Database, user_id: int, limit: int = 15) -> list:
    return await db.fetchall(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )


# -------------------------------------------------------------- deposits


async def list_pending_deposits(db: Database, limit: int = 10) -> list:
    return await db.fetchall(
        "SELECT d.*, u.full_name AS user_name, u.username AS user_username, "
        "u.telegram_id AS user_telegram_id "
        "FROM deposit_requests d JOIN users u ON u.id = d.user_id "
        "WHERE d.status = 'pending' AND d.provider = 'manual' ORDER BY d.id LIMIT ?",
        (limit,),
    )


# -------------------------------------------------------------- settings


async def get_setting(db: Database, key: str) -> Optional[str]:
    row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else None


async def set_setting(db: Database, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


async def get_pending_deposit(db: Database, user_id: int) -> Optional[dict]:
    return await db.fetchone(
        "SELECT * FROM deposit_requests WHERE user_id = ? AND status = 'pending'",
        (user_id,),
    )
