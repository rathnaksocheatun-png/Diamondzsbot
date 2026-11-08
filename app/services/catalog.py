"""Pull games and packages from Bay2Game automatically - and remove them again later.

Import rules (what keeps this safe):
  * Every imported package is connected to its Bay2Game package, so it is delivered
    automatically, and its price follows the supplier cost:  price = cost + profit.
    The profit is your default profit (/b2g_margin); the import REFUSES to run until
    one is set, so nothing is ever put on sale at a guessed price.
  * Importing is idempotent: running it again only adds what is new.
  * Anything you delete is written to a "removed" list and is never imported again
    (until you press "Restore removed").
  * Games that need information we cannot send to Bay2Game (anything besides a
    Player ID and a Zone/Server ID) are skipped and reported.

Deleting is safe for the books: a package or game that already has orders cannot be
erased without breaking order history and reports, so it is HIDDEN instead.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from aiogram import Bot

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.services import pricing
from app.services.bay2game import Bay2GameClient, Bay2GameError
from app.utils.formatting import esc, money
from app.utils.telegram import notify_admins
from app.utils.validators import valid_price

log = logging.getLogger(__name__)

AUTO_IMPORT_KEY = "auto_import"
WATCH_INTERVAL = 6 * 3600.0       # look for new games/packages every 6 hours
FETCH_PARALLEL = 3                # supplier requests at the same time
NAME_MAX = 40

_import_lock = asyncio.Lock()


class MarginNotSet(Exception):
    """The default profit is not set, so a selling price cannot be calculated."""


@dataclass
class ImportReport:
    games_added: int = 0
    products_added: int = 0
    per_game: list = field(default_factory=list)       # (game name, new packages, new game?)
    skipped_games: list = field(default_factory=list)  # "Name (reason)"
    blocked: int = 0                                   # skipped: you deleted them before
    stale: int = 0                                     # yours, but gone/inactive at Bay2Game
    problems: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.games_added or self.products_added)


# ------------------------------------------------------------------- helpers

_ID_WORDS = ("user", "id", "uid", "player")
_ZONE_WORDS = ("zone", "server")

_EMOJI_BY_NAME = (
    ("free fire", "🔥"), ("freefire", "🔥"), ("mobile legends", "⚔️"), ("mlbb", "⚔️"),
    ("pubg", "🎯"), ("honor of kings", "👑"), ("genshin", "✨"), ("roblox", "🧱"),
    ("valorant", "🔫"), ("call of duty", "🔫"), ("blood strike", "🔫"),
)


def _field_name(f) -> str:
    if isinstance(f, dict):
        f = f.get("name") or f.get("key") or f.get("field") or ""
    return str(f).strip().lower()


def classify_fields(fields) -> tuple:
    """-> (supported, needs_zone). Supported = only a Player ID and maybe a Zone ID."""
    names = [_field_name(f) for f in (fields or [])]
    zone = [n for n in names if any(w in n for w in _ZONE_WORDS)]
    ids = [n for n in names if n not in zone and any(w in n for w in _ID_WORDS)]
    unknown = [n for n in names if n not in zone and n not in ids]
    supported = not unknown and len(zone) <= 1 and len(ids) <= 1
    return supported, bool(zone)


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _emoji_for(name: str) -> str:
    low = name.lower()
    for word, emoji in _EMOJI_BY_NAME:
        if word in low:
            return emoji
    return "🎮"


def _slug(supplier_code: str) -> str:
    return ("b2g_" + re.sub(r"[^a-z0-9_]", "_", supplier_code.lower()))[:40]


# --------------------------------------------------------------- settings/stats


async def auto_import_enabled(db: Database) -> bool:
    return (await repo.get_setting(db, AUTO_IMPORT_KEY)) == "1"


async def set_auto_import(db: Database, on: bool) -> None:
    await repo.set_setting(db, AUTO_IMPORT_KEY, "1" if on else "0")


async def store_stats(db: Database) -> dict:
    g = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(is_active), 0) AS shown FROM games")
    p = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(is_active), 0) AS shown, "
        "COALESCE(SUM(supplier_code IS NOT NULL), 0) AS linked FROM products")
    r = await db.fetchone("SELECT COUNT(*) AS n FROM supplier_removed")
    return {"games": g["n"], "games_shown": g["shown"], "products": p["n"],
            "products_shown": p["shown"], "linked": p["linked"], "removed": r["n"]}


# --------------------------------------------------------------------- import


async def _fetch_products(client: Bay2GameClient, cats: list, max_age: float) -> dict:
    """{game_code: (products | None, error | None)} - a few requests at a time."""
    sem = asyncio.Semaphore(FETCH_PARALLEL)

    async def one(code: str):
        async with sem:
            try:
                return code, (await client.products(code, max_age=max_age), None)
            except Bay2GameError as exc:
                return code, (None, str(exc))

    return dict(await asyncio.gather(*(one(c) for c in cats)))


async def import_catalog(db: Database, client: Bay2GameClient,
                         only_game: Optional[str] = None) -> ImportReport:
    """Add every game/package from Bay2Game that you do not have yet.

    only_game: import just this supplier game (an explicit choice, so it also
    overrides an earlier deletion of that game).
    Raises MarginNotSet, or Bay2GameError if the game list cannot be read.
    """
    margin = await pricing.get_default_margin(db)
    if margin is None or margin < 0:
        raise MarginNotSet()

    async with _import_lock:
        cats = await client.categories()
        if only_game is not None:
            cats = [c for c in cats if str(c.get("game_code") or "").strip() == only_game]
            async with db.transaction() as conn:
                await conn.execute(
                    "DELETE FROM supplier_removed WHERE supplier_game = ?", (only_game,))
        report = ImportReport()

        wanted = []
        removed = {(r["supplier_game"], r["supplier_code"]) for r in
                   await db.fetchall("SELECT supplier_game, supplier_code FROM supplier_removed")}
        for cat in cats:
            code = str(cat.get("game_code") or "").strip()
            name = _clip(cat.get("name") or code, 60) or code
            if not code:
                continue
            supported, _ = classify_fields(cat.get("game_fields"))
            if not supported:
                fields = ", ".join(_field_name(f) for f in cat.get("game_fields") or [])
                report.skipped_games.append(f"{name} (needs: {fields})")
            elif (code, "") in removed:
                report.blocked += 1
            else:
                wanted.append(cat)

        fetched = await _fetch_products(
            client, [str(c["game_code"]).strip() for c in wanted],
            max_age=0 if only_game else 60.0)

        for cat in wanted:
            code = str(cat["game_code"]).strip()
            name = _clip(cat.get("name") or code, 60) or code
            _, needs_zone = classify_fields(cat.get("game_fields"))
            items, error = fetched.get(code, (None, "no answer"))
            if items is None:
                report.problems.append(f"{name}: {error}")
                continue
            await _import_game(db, report, code, name, needs_zone, items, margin)
        return report


async def _import_game(db: Database, report: ImportReport, supplier_game: str, name: str,
                       needs_zone: bool, items: list, margin: int) -> None:
    sellable = sorted((p for p in items if p.active), key=lambda p: (p.price_cents, p.code))

    async with db.transaction() as conn:
        # Re-read inside the transaction: a deletion may have happened a moment ago.
        cur = await conn.execute(
            "SELECT 1 FROM supplier_removed WHERE supplier_game = ? AND supplier_code = ''",
            (supplier_game,))
        if await cur.fetchone() is not None:
            report.blocked += 1
            return
        cur = await conn.execute(
            "SELECT supplier_code FROM supplier_removed WHERE supplier_game = ? "
            "AND supplier_code != ''", (supplier_game,))
        gone = {r["supplier_code"] for r in await cur.fetchall()}
        cur = await conn.execute(
            "SELECT supplier_code FROM products WHERE supplier_game = ?", (supplier_game,))
        have = {r["supplier_code"] for r in await cur.fetchall()}
        report.stale += len(have - {p.code for p in sellable})

        fresh = []
        for p in sellable:
            if p.code in have:
                continue
            if p.code in gone:
                report.blocked += 1
                continue
            price = p.price_cents + margin
            if not valid_price(price):
                report.problems.append(f"{name} / {p.code}: price {money(price)} not allowed")
                continue
            fresh.append((p, price))
        if not fresh:
            return

        # Which of our games holds this supplier game?
        cur = await conn.execute("SELECT code FROM games WHERE supplier_game = ?", (supplier_game,))
        row = await cur.fetchone()
        if row is None:
            # A game you made by hand whose packages are already connected to it.
            cur = await conn.execute(
                "SELECT game_code AS code FROM products WHERE supplier_game = ? LIMIT 1",
                (supplier_game,))
            row = await cur.fetchone()
        new_game = row is None
        if new_game:
            game_code, n = _slug(supplier_game), 2
            while True:
                cur = await conn.execute("SELECT 1 FROM games WHERE code = ?", (game_code,))
                if await cur.fetchone() is None:
                    break
                game_code = f"{_slug(supplier_game)[:36]}_{n}"
                n += 1
            cur = await conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM games")
            order = (await cur.fetchone())["n"]
            await conn.execute(
                "INSERT INTO games (code, name, emoji, needs_server_id, sort_order, supplier_game) "
                "VALUES (?,?,?,?,?,?)",
                (game_code, name, _emoji_for(name), 1 if needs_zone else 0, order, supplier_game))
            report.games_added += 1
        else:
            game_code = row["code"]

        cur = await conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS n FROM products WHERE game_code = ?",
            (game_code,))
        order = (await cur.fetchone())["n"]
        for p, price in fresh:
            order += 1
            await conn.execute(
                "INSERT INTO products (game_code, name, price_cents, sort_order, "
                "supplier_game, supplier_code) VALUES (?,?,?,?,?,?)",
                (game_code, _clip(p.name or p.code, NAME_MAX) or p.code, price, order,
                 supplier_game, p.code))
        report.products_added += len(fresh)
        report.per_game.append((name, len(fresh), new_game))


def describe(report: ImportReport, limit: int = 3400) -> str:
    """HTML summary for the admin (kept under Telegram's message size)."""
    lines = []
    if report.changed:
        lines.append(f"✅ Added <b>{report.games_added}</b> new game(s) and "
                     f"<b>{report.products_added}</b> package(s).")
        for name, count, is_new in report.per_game:
            lines.append(f"• {esc(name)}: +{count}" + (" 🆕" if is_new else ""))
    else:
        lines.append("✅ Nothing new - your shop already has everything from Bay2Game "
                     "(except what you deleted).")
    if report.blocked:
        lines.append(f"\n🗑 Skipped {report.blocked} item(s) you deleted earlier.")
    if report.skipped_games:
        lines.append("\n⏭ Skipped games that need extra details we cannot send:")
        lines += [f"• {esc(x)}" for x in report.skipped_games]
    if report.stale:
        lines.append(f"\n⚠️ {report.stale} of your package(s) are no longer sold by Bay2Game "
                     "(missing or inactive). Check them in Products.")
    if report.problems:
        lines.append("\n⚠️ Problems:")
        lines += [f"• {esc(x)}" for x in report.problems]
    out, size = [], 0
    for i, line in enumerate(lines):
        if size + len(line) + 1 > limit:
            out.append(f"… and {len(lines) - i} more line(s)")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


# --------------------------------------------------------------------- remove


async def delete_product(db: Database, product_id: int) -> str:
    """-> 'deleted' | 'hidden' (it has orders, so it is kept hidden) | 'missing'."""
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = await cur.fetchone()
        if product is None:
            return "missing"
        if product["supplier_game"] and product["supplier_code"]:
            await conn.execute(
                "INSERT OR IGNORE INTO supplier_removed (supplier_game, supplier_code) "
                "VALUES (?, ?)", (product["supplier_game"], product["supplier_code"]))
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE product_id = ?", (product_id,))
        if (await cur.fetchone())["n"]:
            await conn.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
            return "hidden"
        await conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return "deleted"


async def delete_game(db: Database, game_code: str) -> str:
    """Delete a game with all its packages. -> 'deleted' | 'hidden' | 'missing'."""
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM games WHERE code = ?", (game_code,))
        game = await cur.fetchone()
        if game is None:
            return "missing"
        cur = await conn.execute(
            "SELECT DISTINCT supplier_game FROM products "
            "WHERE game_code = ? AND supplier_game IS NOT NULL", (game_code,))
        suppliers = {r["supplier_game"] for r in await cur.fetchall()}
        if game["supplier_game"]:
            suppliers.add(game["supplier_game"])
        for sg in suppliers:
            await conn.execute(
                "INSERT OR IGNORE INTO supplier_removed (supplier_game, supplier_code) "
                "VALUES (?, '')", (sg,))
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE game_code = ?", (game_code,))
        if (await cur.fetchone())["n"]:
            await conn.execute("UPDATE games SET is_active = 0 WHERE code = ?", (game_code,))
            return "hidden"
        await conn.execute("DELETE FROM products WHERE game_code = ?", (game_code,))
        await conn.execute("DELETE FROM games WHERE code = ?", (game_code,))
        return "deleted"


async def toggle_game(db: Database, game_code: str) -> bool:
    return await db.execute(
        "UPDATE games SET is_active = 1 - is_active WHERE code = ?", (game_code,)) == 1


async def restore_removed(db: Database) -> int:
    """Forget the deleted list, so the next import can bring those items back."""
    return await db.execute("DELETE FROM supplier_removed")


# ------------------------------------------------------------------ background


async def watch_catalog(bot: Bot, db: Database, client: Bay2GameClient,
                        settings: Settings) -> None:
    """Add new games/packages by itself (only while 'auto-add' is ON)."""
    await asyncio.sleep(120)         # let the start-up checks finish first
    while True:
        try:
            if await auto_import_enabled(db):
                report = await import_catalog(db, client)
                if report.changed:
                    await notify_admins(
                        bot, settings,
                        "🆕 <b>New from Bay2Game - added to your shop automatically</b>\n"
                        + describe(report, limit=3000)
                        + "\n\nDon't want something? Admin → 🛍 Products → open it → 🗑 Delete. "
                          "Deleted items never come back by themselves.")
        except asyncio.CancelledError:
            raise
        except MarginNotSet:
            log.info("Auto-add is ON but no default profit is set - nothing imported")
        except Bay2GameError as exc:
            log.warning("Catalog sync: %s", exc)
        except Exception:
            log.exception("Catalog sync error")
        await asyncio.sleep(WATCH_INTERVAL)
