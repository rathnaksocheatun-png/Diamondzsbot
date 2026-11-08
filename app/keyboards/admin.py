"""Buttons that only admins see."""
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.formatting import money

STATUS_ICON = {"pending": "⏳", "completed": "✅", "cancelled": "❌"}


def _btn(text: str, data: str, style: Optional[str] = None) -> InlineKeyboardButton:
    """Admin button. style: "primary" (blue), "success" (green) or "danger" (red)."""
    if style is None:
        if "✅" in text or text.startswith("Approve"):
            style = "success"
        elif "❌" in text or "🚫" in text:
            style = "danger"
        else:
            style = "primary"
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


button = _btn      # public name for other modules


def home_row() -> list:
    return [_btn("🏠 Admin menu", "adm:home")]


PAGE_SIZE = 12     # buttons per page in admin lists (Telegram allows 100 per message)


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("👥 Customers", "adm:cust:0"), _btn("📦 Orders", "adm:orders:pending:0")],
        [_btn("🛍 Products", "adm:products"), _btn("💰 Deposits", "adm:deposits")],
        [_btn("🔌 Bay2Game (auto games & packages)", "adm:b2g")],
        [_btn("📊 Sales report", "adm:reports"), _btn("🎁 Promotions text", "adm:promo")],
        [_btn("✖️ Close", "adm:close")],
    ])


def pagination_row(prefix: str, page: int, has_next: bool) -> list:
    row = []
    if page > 0:
        row.append(_btn("⬅️ Prev", f"{prefix}:{page - 1}"))
    if has_next:
        row.append(_btn("Next ➡️", f"{prefix}:{page + 1}"))
    return row


def customers_kb(page: int, has_next: bool) -> InlineKeyboardMarkup:
    rows = []
    nav = pagination_row("adm:cust", page, has_next)
    if nav:
        rows.append(nav)
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def orders_kb(orders: list, status: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    filters = [
        _btn(("• " if status == s else "") + s.capitalize(), f"adm:orders:{s}:0")
        for s in ("pending", "completed", "cancelled", "all")
    ]
    rows = [filters[:2], filters[2:]]
    for o in orders:
        icon = STATUS_ICON.get(o["status"], "")
        rows.append([_btn(f"{icon} #{o['id']} {o['product_name']} • {money(o['price_cents'])}",
                          f"adm:order:{o['id']}")])
    nav = pagination_row(f"adm:orders:{status}", page, has_next)
    if nav:
        rows.append(nav)
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_detail_kb(order: dict) -> InlineKeyboardMarkup:
    rows = []
    if order["status"] == "pending":
        rows.append([
            _btn("✅ Mark completed", f"adm:ostat:{order['id']}:completed"),
            _btn("❌ Cancel + refund", f"adm:ostat:{order['id']}:cancelled"),
        ])
    rows.append([_btn("⬅️ Orders", f"adm:orders:{order['status']}:0")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def games_admin_kb(games: list, page: int = 0) -> InlineKeyboardMarkup:
    """One page of games (PAGE_SIZE). `games` is the full list."""
    rows = []
    for g in games[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        hidden = "" if g.get("is_active", 1) else "🚫 "
        rows.append([_btn(f"{hidden}{g['emoji']} {g['name']}", f"adm:pg:{g['code']}",
                          style="primary")])
    nav = pagination_row("adm:products", page, (page + 1) * PAGE_SIZE < len(games))
    if nav:
        rows.append(nav)
    rows.append([_btn("🔌 Import from Bay2Game", "adm:b2g")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_admin_kb(products: list, game: dict, page: int = 0) -> InlineKeyboardMarkup:
    """One page of a game's packages, plus the game-level buttons."""
    code = game["code"]
    rows = []
    for p in products[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        icon = "✅" if p["is_active"] else "🚫"
        rows.append([_btn(f"{icon} {p['name']} — {money(p['price_cents'])}", f"adm:p:{p['id']}")])
    nav = pagination_row(f"adm:pg:{code}", page, (page + 1) * PAGE_SIZE < len(products))
    if nav:
        rows.append(nav)
    rows.append([_btn("➕ Add product", f"adm:padd:{code}")])
    rows.append([_btn("✏️ Rename game", f"adm:gname:{code}", style="primary"),
                 _btn("😀 Game emoji", f"adm:gemoji:{code}", style="primary")])
    rows.append([_btn("💎 Emoji for ALL its packages", f"adm:gpemoji:{code}", style="primary")])
    shown = game.get("is_active", 1)
    rows.append([
        _btn("🙈 Hide game" if shown else "👁 Show game", f"adm:gtoggle:{code}", style="primary"),
        _btn("🗑 Delete game", f"adm:gdel:{code}", style="danger"),
    ])
    rows.append([_btn("⬅️ Games", "adm:products")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(product: dict) -> InlineKeyboardMarkup:
    pid = product["id"]
    toggle = "🚫 Disable" if product["is_active"] else "✅ Enable"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💲 Edit price", f"adm:pprice:{pid}"), _btn("✏️ Edit name", f"adm:pname:{pid}")],
        [_btn("😀 Edit emoji", f"adm:pemoji:{pid}", style="primary"), _btn(toggle, f"adm:ptoggle:{pid}")],
        [_btn("🗑 Delete", f"adm:pdel:{pid}", style="danger")],
        [_btn("⬅️ Products", f"adm:pg:{product['game_code']}")],
        home_row(),
    ])


def confirm_delete_kb(yes_data: str, back_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 Yes, delete", yes_data, style="danger"), _btn("⬅️ No, keep it", back_data,
                                                              style="primary")],
    ])


def b2g_panel_kb(auto_on: bool, has_removed: bool) -> InlineKeyboardMarkup:
    rows = [
        [_btn("📥 Import ALL games & packages", "adm:b2g:import", style="success")],
        [_btn("🎮 Choose games to import", "adm:b2g:pick:0")],
        [_btn("💲 Set profit per sale", "adm:b2g:margin"), _btn("🔄 Update prices", "adm:b2g:sync")],
        [_btn("🤖 Auto-add new: ON ✅ (tap to turn off)" if auto_on
              else "🤖 Auto-add new: OFF (tap to turn on)", "adm:b2g:auto", style="primary")],
    ]
    if has_removed:
        rows.append([_btn("♻️ Restore deleted items", "adm:b2g:restore", style="primary")])
    rows.append([_btn("🛍 Manage products (delete / hide)", "adm:products", style="primary")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def b2g_pick_kb(entries: list, page: int) -> InlineKeyboardMarkup:
    """entries: [(label, supplier_game_code)] - one page is shown."""
    rows = [[_btn(label, f"adm:b2g:one:{code}", style="primary")]
            for label, code in entries[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    nav = pagination_row("adm:b2g:pick", page, (page + 1) * PAGE_SIZE < len(entries))
    if nav:
        rows.append(nav)
    rows.append([_btn("⬅️ Bay2Game", "adm:b2g")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def b2g_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🛍 Products", "adm:products", style="primary"), _btn("⬅️ Bay2Game", "adm:b2g")],
        home_row(),
    ])


def deposits_kb(deposits: list) -> InlineKeyboardMarkup:
    rows = []
    for d in deposits:
        amount = money(d["amount_cents"])
        rows.append([
            _btn(f"✅ Approve #{d['id']} ({amount})", f"adm:dep:ok:{d['id']}"),
            _btn(f"❌ Reject #{d['id']}", f"adm:dep:no:{d['id']}"),
        ])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deposit_review_kb(deposit_id: int, amount_cents: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn(f"✅ Approve ({money(amount_cents)})", f"adm:dep:ok:{deposit_id}"),
        _btn("❌ Reject", f"adm:dep:no:{deposit_id}"),
    ]])


def view_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(f"📦 Open order #{order_id}", f"adm:order:{order_id}")]])


def simple_home_kb(extra: Optional[list] = None) -> InlineKeyboardMarkup:
    rows = [extra] if extra else []
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)
