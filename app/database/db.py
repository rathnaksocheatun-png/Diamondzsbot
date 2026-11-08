"""SQLite database: connection, tables and starting data.

All access goes through one connection protected by a lock, so two users
tapping buttons at the same moment can never corrupt each other's data.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL UNIQUE,
    username      TEXT,
    full_name     TEXT NOT NULL DEFAULT '',
    language      TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'km')),
    balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS games (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    emoji           TEXT NOT NULL DEFAULT '🎮',
    needs_server_id INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_code   TEXT NOT NULL REFERENCES games(code),
    name        TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    game_code   TEXT NOT NULL,
    product_name TEXT NOT NULL,
    player_id   TEXT NOT NULL,
    server_id   TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'completed', 'cancelled')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Duplicate protection: the database itself refuses two identical pending orders.
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_pending_duplicate
    ON orders(user_id, product_id, player_id, server_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS transactions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(id),
    type               TEXT NOT NULL CHECK (type IN ('deposit', 'purchase', 'refund')),
    amount_cents       INTEGER NOT NULL,
    balance_after_cents INTEGER NOT NULL,
    order_id           INTEGER,
    note               TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deposit_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at   TEXT,
    provider     TEXT NOT NULL DEFAULT 'manual',
    external_id  TEXT,
    expires_at   TEXT
);

-- Only one pending deposit request per customer at a time.
CREATE UNIQUE INDEX IF NOT EXISTS ux_deposit_one_pending
    ON deposit_requests(user_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Things the admin deleted. The automatic import never brings them back.
-- supplier_code = '' means "the whole supplier game".
CREATE TABLE IF NOT EXISTS supplier_removed (
    supplier_game TEXT NOT NULL,
    supplier_code TEXT NOT NULL DEFAULT '',
    removed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (supplier_game, supplier_code)
);
"""

GAMES = [
    ("free_fire", "Free Fire", "🔥", 0, 1),
    ("mlbb", "Mobile Legends: Bang Bang", "⚔️", 1, 2),
    ("pubg", "PUBG Mobile", "🎯", 0, 3),
    ("hok", "Honor of Kings", "👑", 0, 4),
]

# SAMPLE PRICES in cents. They are NOT real prices - change them in the
# admin panel (Products -> Free Fire -> pick a package -> Edit price).
FREE_FIRE_PACKAGES = [
    ("100 Diamonds", 100),
    ("310 Diamonds", 300),
    ("520 Diamonds", 500),
    ("1060 Diamonds", 1000),
    ("2180 Diamonds", 2000),
    ("Weekly Pass", 150),
    ("Weekly Lite", 50),
    ("Monthly Pass", 700),
]


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> we control transactions ourselves.
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._seed()

    async def _add_columns(self, table: str, columns: tuple) -> None:
        cur = await self._conn.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in await cur.fetchall()}
        await cur.close()
        for column, ddl in columns:
            if column not in existing:
                await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    async def _migrate(self) -> None:
        """Upgrade databases created by older versions of the bot (adds columns)."""
        await self._add_columns("deposit_requests", (
            ("provider", "TEXT NOT NULL DEFAULT 'manual'"),
            ("external_id", "TEXT"),
            ("expires_at", "TEXT"),
        ))
        # Bay2Game auto-delivery: which supplier package a product maps to,
        # and the automatic-delivery state of each order.
        await self._add_columns("products", (
            ("supplier_game", "TEXT"),
            ("supplier_code", "TEXT"),
            ("margin_cents", "INTEGER"),   # NULL = use the default margin
        ))
        # Games pulled from Bay2Game automatically; a game can be hidden from customers.
        await self._add_columns("games", (
            ("supplier_game", "TEXT"),   # NULL = a game you created yourself
            ("is_active", "INTEGER NOT NULL DEFAULT 1"),
            ("emoji_id", "TEXT"),        # Telegram Premium (animated) emoji, optional
        ))
        await self._add_columns("products", (
            ("emoji", "TEXT"),           # NULL = the default 💎
            ("emoji_id", "TEXT"),        # Telegram Premium (animated) emoji, optional
        ))
        await self._add_columns("orders", (
            ("auto_state", "TEXT"),      # NULL | submitting | done | review
            ("supplier_ref", "TEXT"),
            ("supplier_note", "TEXT"),
        ))
        # One gateway transaction can never be credited to two deposit requests.
        await self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_deposit_external "
            "ON deposit_requests(provider, external_id) WHERE external_id IS NOT NULL"
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _seed(self) -> None:
        """Insert the 4 games and sample Free Fire packages (first run only).

        Only on the first run: if an admin deletes one of these games, it must not
        come back the next time the bot restarts.
        """
        async with self.transaction() as conn:
            cur = await conn.execute("SELECT 1 FROM settings WHERE key = 'seeded_v1'")
            if await cur.fetchone() is None:
                for game in GAMES:
                    await conn.execute(
                        "INSERT OR IGNORE INTO games "
                        "(code, name, emoji, needs_server_id, sort_order) VALUES (?,?,?,?,?)",
                        game,
                    )
                for order, (name, price) in enumerate(FREE_FIRE_PACKAGES, start=1):
                    await conn.execute(
                        "INSERT INTO products (game_code, name, price_cents, sort_order) "
                        "VALUES ('free_fire', ?, ?, ?)",
                        (name, price, order),
                    )
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('seeded_v1', '1')"
                )

    # ---- helpers used by the rest of the bot -------------------------------

    async def fetchone(self, sql: str, params: tuple = ()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
        return [dict(r) for r in rows]

    async def execute(self, sql: str, params: tuple = ()) -> int:
        """Run one write statement. Returns the number of changed rows."""
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            changed = cur.rowcount
            await cur.close()
        return changed

    @asynccontextmanager
    async def transaction(self):
        """All-or-nothing group of changes (e.g. take money AND create order)."""
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                await self._conn.execute("ROLLBACK")
                raise
            else:
                await self._conn.execute("COMMIT")
