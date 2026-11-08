"""Buttons that customers see."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import t
from app.utils.formatting import money

_MENU_ROWS = [
    ["buy", "orders"],
    ["wallet", "deposit"],
    ["promos", "support"],
    ["history", "howto"],
    ["language"],
]


# Button colours (Telegram: "primary" = blue, "success" = green, "danger" = red).
_MENU_STYLE = {
    "buy": "success", "deposit": "success",
    "orders": "primary", "wallet": "primary", "promos": "primary",
    "support": "primary", "history": "primary", "howto": "primary",
}


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, f"menu_{key}"), style=_MENU_STYLE.get(key))
             for key in row]
            for row in _MENU_ROWS
        ],
        resize_keyboard=True,
        input_field_placeholder="DIAMOND ZS 👑",
    )


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        InlineKeyboardButton(text="🇰🇭 ខ្មែរ", callback_data="lang:km"),
    ]])


def games_kb(games: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for game in games:
        builder.button(text=f"{game['emoji']} {game['name']}", callback_data=f"game:{game['code']}", style="primary")
    builder.adjust(1)
    return builder.as_markup()


def products_kb(products: list, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in products:
        builder.button(text=f"💎 {p['name']} — {money(p['price_cents'])}", callback_data=f"pkg:{p['id']}", style="success")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="buy:back"))
    return builder.as_markup()


def back_to_games_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="buy:back")
    ]])


def confirm_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_confirm"), callback_data="order:confirm", style="success"),
        InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="flow:cancel", style="danger"),
    ]])


def cancel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="flow:cancel", style="danger")
    ]])


def wallet_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_deposit"), callback_data="wallet:deposit", style="success"),
        InlineKeyboardButton(text=t(lang, "btn_history"), callback_data="wallet:history", style="primary"),
    ]])


def deposit_qr_kb(lang: str, deposit_id: int, payment_url: str) -> InlineKeyboardMarkup:
    rows = []
    if payment_url.startswith("https://"):
        rows.append([InlineKeyboardButton(text=t(lang, "btn_pay_page"), url=payment_url, style="success")])
    rows.append([
        InlineKeyboardButton(text=t(lang, "btn_check_payment"), callback_data=f"dep:chk:{deposit_id}", style="primary"),
        InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data=f"dep:cancel:{deposit_id}", style="danger"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
