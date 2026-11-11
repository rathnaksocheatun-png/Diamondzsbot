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


async def list_games(db: Database, only_active: bool = False) -> list:
    sql = "SELECT * FROM games"
    if only_active:
        sql += " WHERE is_active = 1"
    return await db.fetchall(sql + " ORDER BY sort_order, name")


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
        "SELECT p.*, g.name AS game_name, g.needs_server_id, g.is_active AS game_active "
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


async def update_game_name(db: Database, code: str, name: str) -> bool:
    return await db.execute("UPDATE games SET name = ? WHERE code = ?", (name, code)) == 1


async def update_game_emoji(db: Database, code: str, emoji: str, emoji_id: Optional[str]) -> bool:
    return await db.execute(
        "UPDATE games SET emoji = ?, emoji_id = ? WHERE code = ?", (emoji, emoji_id, code)) == 1


async def update_product_emoji(
    db: Database, product_id: int, emoji: Optional[str], emoji_id: Optional[str]
) -> bool:
    return await db.execute(
        "UPDATE products SET emoji = ?, emoji_id = ? WHERE id = ?",
        (emoji, emoji_id, product_id)) == 1


async def update_game_products_emoji(
    db: Database, code: str, emoji: Optional[str], emoji_id: Optional[str]
) -> int:
    """Give every package of a game the same icon. Returns how many were changed."""
    return await db.execute(
        "UPDATE products SET emoji = ?, emoji_id = ? WHERE game_code = ?",
        (emoji, emoji_id, code))


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


# ------------------------------------------------- premium emoji (admin-edited)


async def list_custom_emojis(db: Database) -> list:
    return await db.fetchall("SELECT emoji, emoji_id FROM custom_emojis ORDER BY rowid")


async def set_custom_emoji(db: Database, emoji: str, emoji_id: str) -> None:
    await db.execute(
        "INSERT INTO custom_emojis (emoji, emoji_id) VALUES (?, ?) "
        "ON CONFLICT(emoji) DO UPDATE SET emoji_id = excluded.emoji_id, "
        "updated_at = datetime('now')",
        (emoji, emoji_id),
    )


async def delete_custom_emoji(db: Database, emoji: str) -> bool:
    return await db.execute("DELETE FROM custom_emojis WHERE emoji = ?", (emoji,)) >= 1


async def clear_custom_emojis(db: Database) -> int:
    return await db.execute("DELETE FROM custom_emojis")


# ------------------------------------------------- message texts (admin-edited)


async def list_custom_texts(db: Database) -> list:
    return await db.fetchall("SELECT lang, key, value FROM custom_texts")


async def set_custom_text(db: Database, lang: str, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO custom_texts (lang, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(lang, key) DO UPDATE SET value = excluded.value, "
        "updated_at = datetime('now')",
        (lang, key, value),
    )


async def delete_custom_text(db: Database, key: str, lang: Optional[str] = None) -> int:
    """Remove the edit (back to the original text). lang=None -> both languages."""
    if lang:
        return await db.execute(
            "DELETE FROM custom_texts WHERE key = ? AND lang = ?", (key, lang))
    return await db.execute("DELETE FROM custom_texts WHERE key = ?", (key,))


# ------------------------------------------- admin: change a customer's balance


class InsufficientBalance(Exception):
    """The deduction is bigger than what the customer has."""


async def find_user_by_ref(db: Database, ref: str) -> Optional[dict]:
    """Find a customer by Telegram ID (digits) or @username."""
    ref = (ref or "").strip()
    if ref.startswith("@"):
        return await db.fetchone(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (ref[1:],))
    if ref.isdigit():
        return await db.fetchone("SELECT * FROM users WHERE telegram_id = ?", (int(ref),))
    return None


async def adjust_balance(db: Database, user_id: int, delta_cents: int, note: str) -> int:
    """Add (delta > 0) or take (delta < 0) money. Returns the new balance in cents.

    Everything happens in ONE database transaction: the balance and the history line
    are saved together or not at all. The balance can never go below zero."""
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT balance_cents FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            raise LookupError("user not found")
        new_balance = row["balance_cents"] + delta_cents
        if new_balance < 0:
            raise InsufficientBalance()
        await conn.execute("UPDATE users SET balance_cents = ? WHERE id = ?",
                           (new_balance, user_id))
        # The transactions table only accepts deposit / purchase / refund, so a credit
        # is saved as 'deposit' and a deduction as 'purchase'; the note says it was manual.
        await conn.execute(
            "INSERT INTO transactions (user_id, type, amount_cents, balance_after_cents, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, "deposit" if delta_cents > 0 else "purchase",
             delta_cents, new_balance, note[:250]),
        )
    return new_balance


async def list_manual_adjustments(db: Database, user_id: Optional[int] = None,
                                  limit: int = 15) -> list:
    """Latest balance changes made by an admin (newest first), optionally for one customer."""
    sql = (
        "SELECT tr.created_at, tr.amount_cents, tr.balance_after_cents, tr.note, "
        "u.telegram_id, u.full_name, u.username "
        "FROM transactions tr JOIN users u ON u.id = tr.user_id "
        "WHERE tr.note LIKE '[manual]%'"
    )
    params: tuple = ()
    if user_id is not None:
        sql += " AND tr.user_id = ?"
        params = (user_id,)
    sql += " ORDER BY tr.id DESC LIMIT ?"
    return await db.fetchall(sql, params + (limit,))
