"""The Telegram "Menu" button (the list that opens next to the text box).

 - Every customer sees USER_COMMANDS.
 - Each admin (ADMIN_IDS in .env) sees ADMIN_COMMANDS + USER_COMMANDS, but only
   inside their own chat - customers never see the admin items.

To add, remove or rename a menu item: edit the two lists below and restart the
bot. Descriptions are bilingual (English / Khmer), same style as the
"Language / ភាសា" button. A new command also needs a handler that answers it
(see app/handlers/menu.py for the customer ones).
"""
import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

if TYPE_CHECKING:
    from app.config import Settings

log = logging.getLogger("diamond_zs")

# Same items as the buttons under the keyboard (see app/keyboards/user.py).
USER_COMMANDS = [
    BotCommand(command="start", description="🚀 Start / ចាប់ផ្តើម"),
    BotCommand(command="buy", description="💎 Buy / ទិញពេជ្រ"),
    BotCommand(command="orders", description="📦 Orders / ការបញ្ជាទិញ"),
    BotCommand(command="wallet", description="👛 Wallet / កាបូប"),
    BotCommand(command="deposit", description="➕ Deposit / ដាក់ប្រាក់"),
    BotCommand(command="promos", description="🎁 Promos / ប្រូម៉ូសិន"),
    BotCommand(command="history", description="🧾 History / ប្រវត្តិ"),
    BotCommand(command="support", description="💬 Support / ជំនួយ"),
    BotCommand(command="howto", description="ℹ️ How to use / របៀបប្រើ"),
    BotCommand(command="language", description="🌐 Language / ភាសា"),
]

# Admin-only extras. Commands that need an argument (/b2g_map, /b2g_check ...)
# are left out - open /b2g to see them all.
ADMIN_COMMANDS = [
    BotCommand(command="admin", description="👑 Admin panel"),
    BotCommand(command="backup", description="💾 Backup database"),
    BotCommand(command="b2g", description="🔌 Bay2Game help + balance"),
    BotCommand(command="b2g_games", description="🎮 Supplier games"),
    BotCommand(command="b2g_ours", description="📋 Our packages"),
    BotCommand(command="b2g_margin", description="💲 Profit margins"),
    BotCommand(command="b2g_sync", description="🔄 Sync prices now"),
    BotCommand(command="emoji", description="😀 Set premium emoji"),
    BotCommand(command="emoji_list", description="📃 Premium emoji list"),
    BotCommand(command="texts", description="📝 Editable messages"),
    BotCommand(command="settext", description="✏️ Edit a message"),
    BotCommand(command="addbalance", description="➕ Add money to a customer"),
    BotCommand(command="subbalance", description="➖ Deduct money from a customer"),
    BotCommand(command="balancelog", description="🧾 Manual balance history"),
    BotCommand(command="broadcast", description="📢 Send announcement to customers"),
    BotCommand(command="howtovideo", description="🎬 Set the how-to video"),
    BotCommand(command="bakong", description="🏦 Bakong payment status"),
    BotCommand(command="bakong_test", description="🧪 Test payment ($0.01)"),
]


async def _set(bot: Bot, commands: list, scope, who: str) -> None:
    try:
        await bot.set_my_commands(commands, scope=scope)
    except TelegramAPIError as exc:
        # Never stop the bot because of a menu problem.
        log.warning("Could not set the Menu for %s: %s", who, exc)


async def setup_commands(bot: Bot, settings: "Settings") -> None:
    """Call once at start-up. Safe to run on every restart."""
    await _set(bot, USER_COMMANDS, BotCommandScopeDefault(), "customers")
    for admin_id in settings.admin_ids:
        # "chat not found" here just means this admin has not pressed /start yet.
        await _set(bot, ADMIN_COMMANDS + USER_COMMANDS,
                   BotCommandScopeChat(chat_id=admin_id), f"admin {admin_id}")
    try:  # make sure the button beside the text box opens the command list
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except TelegramAPIError as exc:
        log.warning("Could not set the Menu button: %s", exc)
