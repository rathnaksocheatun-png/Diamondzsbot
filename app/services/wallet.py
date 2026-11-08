"""Wallet rules: deposit requests that an admin approves by hand.

There is NO automatic payment check. Money is only added to a wallet when an
admin presses Approve after confirming the payment themselves.
"""
import sqlite3
from typing import Optional

from app.database.db import Database
from app.services.errors import DuplicateDeposit, NotFoundOrAlreadyHandled


async def create_deposit_request(db: Database, telegram_id: int, amount_cents: int) -> int:
    try:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cur.fetchone()
            cur = await conn.execute(
                "SELECT * FROM deposit_requests WHERE user_id = ? AND status = 'pending'",
                (user["id"],),
            )
            existing = await cur.fetchone()
            if existing is not None:
                raise DuplicateDeposit(dict(existing))
            cur = await conn.execute(
                "INSERT INTO deposit_requests (user_id, amount_cents) VALUES (?, ?)",
                (user["id"], amount_cents),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise DuplicateDeposit({"id": 0, "amount_cents": amount_cents})


async def get_deposit(db: Database, deposit_id: int) -> Optional[dict]:
    return await db.fetchone(
        "SELECT d.*, u.telegram_id AS user_telegram_id, u.language AS user_language "
        "FROM deposit_requests d JOIN users u ON u.id = d.user_id WHERE d.id = ?",
        (deposit_id,),
    )


async def approve_deposit(db: Database, deposit_id: int) -> int:
    """Credit the wallet once. Returns the customer's new balance (cents)."""
    async with db.transaction() as conn:
        cur = await conn.execute(
            "UPDATE deposit_requests SET status = 'approved', decided_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            (deposit_id,),
        )
        if cur.rowcount != 1:
            raise NotFoundOrAlreadyHandled()
        cur = await conn.execute(
            "SELECT * FROM deposit_requests WHERE id = ?", (deposit_id,)
        )
        deposit = await cur.fetchone()
        cur = await conn.execute(
            "SELECT balance_cents FROM users WHERE id = ?", (deposit["user_id"],)
        )
        balance = (await cur.fetchone())["balance_cents"] + deposit["amount_cents"]
        await conn.execute(
            "UPDATE users SET balance_cents = ? WHERE id = ?",
            (balance, deposit["user_id"]),
        )
        await conn.execute(
            "INSERT INTO transactions (user_id, type, amount_cents, "
            "balance_after_cents, note) VALUES (?, 'deposit', ?, ?, ?)",
            (deposit["user_id"], deposit["amount_cents"], balance,
             f"Deposit #{deposit_id}"),
        )
        return balance


async def reject_deposit(db: Database, deposit_id: int) -> None:
    changed = await db.execute(
        "UPDATE deposit_requests SET status = 'rejected', decided_at = datetime('now') "
        "WHERE id = ? AND status = 'pending'",
        (deposit_id,),
    )
    if changed != 1:
        raise NotFoundOrAlreadyHandled()
