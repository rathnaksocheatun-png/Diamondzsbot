"""Admin commands to connect your packages to Bay2Game (admins only)."""
from typing import Optional

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.config import Settings
from app.database import repositories as repo
from app.database.db import Database
from app.services import fulfilment, pricing
from app.services.bay2game import Bay2GameClient, Bay2GameError
from app.utils.filters import IsAdmin
from app.utils.formatting import esc, money
from app.utils.validators import parse_money, to_int

router = Router(name="supplier")
router.message.filter(IsAdmin())

MAX_CHARS = 3500

HELP = (
    "🔌 <b>Bay2Game (automatic delivery)</b>\n\n"
    "📥 <b>Automatic games &amp; packages</b>\n"
    "/b2g_import - pull ALL games and packages from Bay2Game into your shop\n"
    "(or use Admin → 🔌 Bay2Game). Delete what you do not want in Admin → 🛍 Products.\n\n"
    "/b2g_games - supplier games and their codes\n"
    "/b2g_products &lt;game_code&gt; - supplier packages and their cost\n"
    "/b2g_ours - your packages (with IDs) and what is connected\n"
    "/b2g_map &lt;your_package_id&gt; &lt;game_code&gt; &lt;product_code&gt; - connect a package\n"
    "/b2g_unmap &lt;your_package_id&gt; - disconnect (back to manual delivery)\n"
    "/b2g_check &lt;order_id&gt; - ask Bay2Game about a stuck order\n\n"
    "💲 <b>Automatic prices (cost + fixed profit)</b>\n"
    "/b2g_margin - show margins\n"
    "/b2g_margin 0.20 - default profit for ALL connected packages\n"
    "/b2g_margin 3 0.50 - profit for package #3 only\n"
    "/b2g_margin 3 default - package #3 uses the default again\n"
    "/b2g_margin off - turn the default off\n"
    "/b2g_sync - update prices now (also runs every 10 minutes)\n\n"
    "Example: <code>/b2g_map 3 freefire_sgmy FF_100</code>\n"
    "Packages that are not connected are still delivered by hand, as before."
)


async def _reply_lines(message: Message, header: str, lines: list) -> None:
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 1 > MAX_CHARS:
            await message.answer(chunk)
            chunk = ""
        chunk += ("\n" if chunk else "") + line
    await message.answer(chunk or header)


async def _client_or_explain(message: Message, b2g: Optional[Bay2GameClient]) -> bool:
    if b2g is None:
        await message.answer(
            "Bay2Game is OFF. Add the variable <code>BAY2GAME_API_KEY</code> on your host "
            "and restart the bot.")
        return False
    return True


@router.message(Command("b2g"))
async def cmd_b2g(message: Message, settings: Settings, b2g: Optional[Bay2GameClient] = None):
    if not await _client_or_explain(message, b2g):
        return
    try:
        balance = await b2g.balance_cents()
        extra = f"\n\n💰 Bay2Game balance: <b>{money(balance)}</b>"
        if balance < settings.bay2game_low_balance_cents:
            extra += "\n⚠️ Low balance - top up soon."
    except Bay2GameError as exc:
        extra = f"\n\n⚠️ Could not read the balance: {esc(exc)}"
    await message.answer(HELP + extra)


@router.message(Command("b2g_games"))
async def cmd_games(message: Message, b2g: Optional[Bay2GameClient] = None):
    if not await _client_or_explain(message, b2g):
        return
    try:
        cats = await b2g.categories()
    except Bay2GameError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    lines = [
        f"<code>{esc(c.get('game_code'))}</code> - {esc(c.get('name'))} "
        f"(needs: {esc(', '.join(c.get('game_fields') or []))})"
        for c in cats
    ]
    await _reply_lines(message, f"🎮 <b>Supplier games ({len(cats)})</b>", lines)


@router.message(Command("b2g_products"))
async def cmd_products(message: Message, command: CommandObject,
                       b2g: Optional[Bay2GameClient] = None):
    if not await _client_or_explain(message, b2g):
        return
    game = (command.args or "").strip().split(" ")[0]
    if not game:
        await message.answer("Usage: <code>/b2g_products freefire_sgmy</code>")
        return
    try:
        items = await b2g.products(game, max_age=0)
    except Bay2GameError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    lines = [
        f"<code>{esc(p.code)}</code> - {esc(p.name)} - cost <b>{money(p.price_cents)}</b>"
        + ("" if p.active else " (inactive)")
        for p in items
    ]
    await _reply_lines(message, f"📦 <b>{esc(game)} ({len(items)})</b>", lines)


@router.message(Command("b2g_ours"))
async def cmd_ours(message: Message, db: Database):
    products = await repo.list_all_products(db)
    lines = []
    for p in products:
        link = (f"→ {esc(p['supplier_game'])}/{esc(p['supplier_code'])}"
                if p["supplier_code"] else "→ manual")
        off = "" if p["is_active"] else " (hidden)"
        lines.append(f"<b>#{p['id']}</b> {esc(p['game_name'])} - {esc(p['name'])} "
                     f"- {money(p['price_cents'])}{off} {link}")
    await _reply_lines(message, "🛍 <b>Your packages</b>", lines or ["(none)"])


@router.message(Command("b2g_map"))
async def cmd_map(message: Message, command: CommandObject, db: Database,
                  b2g: Optional[Bay2GameClient] = None):
    if not await _client_or_explain(message, b2g):
        return
    parts = (command.args or "").split()
    product_id = to_int(parts[0]) if len(parts) == 3 else None
    if product_id is None:
        await message.answer("Usage: <code>/b2g_map 3 freefire_sgmy FF_100</code>")
        return
    game_code, product_code = parts[1][:60], parts[2][:60]
    ours = await repo.get_product(db, product_id)
    if ours is None:
        await message.answer("❌ You have no package with that ID. See /b2g_ours")
        return
    try:
        theirs = await b2g.find_product(game_code, product_code)
    except Bay2GameError as exc:
        await message.answer(f"⚠️ Could not check with Bay2Game: {esc(exc)}")
        return
    if theirs is None:
        await message.answer("❌ Bay2Game has no such package. See /b2g_products "
                             f"{esc(game_code)}")
        return
    await repo.set_supplier_mapping(db, product_id, game_code, product_code)
    profit = ours["price_cents"] - theirs.price_cents
    text = (f"✅ Connected <b>{esc(ours['name'])}</b> (you sell {money(ours['price_cents'])}) "
            f"→ <code>{esc(product_code)}</code> (cost {money(theirs.price_cents)}).\n")
    if profit < 0:
        text += (f"⚠️ You would LOSE {money(-profit)} per sale. Orders will NOT be sent "
                 "automatically until your price is at least the cost.")
    else:
        text += f"Profit per sale: <b>{money(profit)}</b>."
    await message.answer(text)


@router.message(Command("b2g_unmap"))
async def cmd_unmap(message: Message, command: CommandObject, db: Database):
    product_id = to_int((command.args or "").strip())
    if product_id is None or not await repo.set_supplier_mapping(db, product_id, None, None):
        await message.answer("Usage: <code>/b2g_unmap 3</code> (see /b2g_ours)")
        return
    await message.answer("✅ Disconnected. That package is delivered by hand again.")


@router.message(Command("b2g_check"))
async def cmd_check(message: Message, command: CommandObject, db: Database, bot,
                    settings: Settings, b2g: Optional[Bay2GameClient] = None):
    if not await _client_or_explain(message, b2g):
        return
    order_id = to_int((command.args or "").strip())
    if order_id is None:
        await message.answer("Usage: <code>/b2g_check 15</code>")
        return
    order = await repo.get_order(db, order_id)
    if order is None or order["status"] != "pending":
        await message.answer("That order was not found or is already completed/cancelled.")
        return
    outcome = await fulfilment.resolve_by_check(
        db, b2g, order_id, settings.bay2game_ref_prefix)
    order = await repo.get_order(db, order_id)
    if outcome.kind in ("delivered", "refunded"):
        await fulfilment.announce(bot, settings, order, outcome)
    await message.answer(f"Result: <b>{esc(outcome.kind)}</b>\n{esc(outcome.detail)}")


def _fmt_margin(cents) -> str:
    return "none" if cents is None else money(cents)


@router.message(Command("b2g_margin"))
async def cmd_margin(message: Message, command: CommandObject, db: Database,
                     b2g: Optional[Bay2GameClient] = None):
    parts = (command.args or "").split()
    default = await pricing.get_default_margin(db)

    if not parts:
        rows = [p for p in await repo.list_all_products(db) if p["supplier_code"]]
        lines = []
        for p in rows:
            eff = pricing.effective_margin(p, default)
            own = "" if p["margin_cents"] is None else " (own)"
            lines.append(f"<b>#{p['id']}</b> {esc(p['name'])} - price {money(p['price_cents'])} "
                         f"- profit {_fmt_margin(eff)}{own}")
        await _reply_lines(
            message, f"💲 <b>Default profit: {_fmt_margin(default)}</b>",
            lines or ["(no package is connected to Bay2Game yet)"])
        return

    if len(parts) == 1:
        if parts[0].lower() == "off":
            await pricing.set_default_margin(db, None)
            await message.answer("✅ Default profit turned off. Prices without their own "
                                 "profit stay as they are.")
            return
        cents = parse_money(parts[0])
        if cents is None:
            await message.answer("Usage: <code>/b2g_margin 0.20</code>")
            return
        await pricing.set_default_margin(db, cents)
        await message.answer(f"✅ Default profit = <b>{money(cents)}</b> per sale. "
                             "Use /b2g_sync to apply now.")
        return

    product_id = to_int(parts[0])
    if product_id is None or len(parts) != 2 or await repo.get_product(db, product_id) is None:
        await message.answer("Usage: <code>/b2g_margin 3 0.50</code> (see /b2g_ours)")
        return
    if parts[1].lower() in ("default", "off"):
        await repo.set_product_margin(db, product_id, None)
        await message.answer(f"✅ Package #{product_id} uses the default profit again.")
        return
    cents = parse_money(parts[1])
    if cents is None:
        await message.answer("Usage: <code>/b2g_margin 3 0.50</code>")
        return
    await repo.set_product_margin(db, product_id, cents)
    await message.answer(f"✅ Package #{product_id}: profit = <b>{money(cents)}</b>. "
                         "Use /b2g_sync to apply now.")


@router.message(Command("b2g_sync"))
async def cmd_sync(message: Message, db: Database, b2g: Optional[Bay2GameClient] = None):
    if not await _client_or_explain(message, b2g):
        return
    changes, problems = await pricing.sync_prices(db, b2g)
    text = ("💲 <b>Prices updated</b>\n" + pricing.describe(changes)) if changes \
        else "✅ All prices are already correct."
    if problems:
        text += "\n\n⚠️ " + "\n⚠️ ".join(esc(x) for x in problems)
    await message.answer(text)
