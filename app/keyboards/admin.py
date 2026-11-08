"""Buttons that only admins see."""
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

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


def home_row() -> list:
    return [_btn("🏠 Admin menu", "adm:home")]


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("👥 Customers", "adm:cust:0"), _btn("📦 Orders", "adm:orders:pending:0")],
        [_btn("🛍 Products", "adm:products"), _btn("💰 Deposits", "adm:deposits")],
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


def games_admin_kb(games: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for g in games:
        builder.button(text=f"{g['emoji']} {g['name']}", callback_data=f"adm:pg:{g['code']}")
    builder.adjust(1)
    builder.row(*home_row())
    return builder.as_markup()


def products_admin_kb(products: list, game_code: str) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        icon = "✅" if p["is_active"] else "🚫"
        rows.append([_btn(f"{icon} {p['name']} — {money(p['price_cents'])}", f"adm:p:{p['id']}")])
    rows.append([_btn("➕ Add product", f"adm:padd:{game_code}")])
    rows.append([_btn("⬅️ Games", "adm:products")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(product: dict) -> InlineKeyboardMarkup:
    pid = product["id"]
    toggle = "🚫 Disable" if product["is_active"] else "✅ Enable"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💲 Edit price", f"adm:pprice:{pid}"), _btn("✏️ Edit name", f"adm:pname:{pid}")],
        [_btn(toggle, f"adm:ptoggle:{pid}")],
        [_btn("⬅️ Products", f"adm:pg:{product['game_code']}")],
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
