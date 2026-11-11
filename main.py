"""DIAMOND ZS - Telegram game top-up bot. Start it with:  python main.py"""
import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from app.config import ConfigError, load_settings
from app.database.db import Database
from app.handlers import admin, fallback, menu, shop, start, wallet
from app.handlers import appearance, catalog as catalog_handlers
from app.handlers import supplier
from app.handlers import live_edit
from app.handlers import wallet_admin
from app.services.bay2game import Bay2GameClient, Bay2GameError
from app.services.catalog import watch_catalog
from app.services.fulfilment import watch_stuck_orders
from app.services.pricing import watch_prices
from app.services.khpay import KhpayClient, KhpayError
from app.utils.commands import setup_commands
from app.utils.custom_emoji import CustomEmojiMiddleware, load_mapping
from app.utils.emoji_store import EmojiStore, LiveEmojiMiddleware
from app.services.online_payments import watch_payments
from app.utils.telegram import notify_admins
from app.utils.middleware import UserMiddleware

log = logging.getLogger("diamond_zs")


async def on_error(event: ErrorEvent) -> bool:
    """Log unexpected problems instead of crashing the whole bot."""
    log.error("Unhandled error while processing an update", exc_info=event.exception)
    return True


async def _check_khpay(bot: Bot, settings, khpay: KhpayClient) -> None:
    """Warn the admins at start-up if KHPAY is not ready (the bot keeps running)."""
    try:
        info = await khpay.account_info()
    except KhpayError as exc:
        log.error("KHPAY check failed: %s", exc)
        await notify_admins(bot, settings, "⚠️ KHPAY key check failed - automatic deposits "
                            "will not work until this is fixed. Check KHPAY_API_KEY.")
        return
    if not (info.get("payway_link_set") and info.get("aba_available")):
        log.error("KHPAY account is not ready: %s", info)
        await notify_admins(bot, settings, "⚠️ KHPAY says your ABA PayWay link is not set up "
                            "yet. Automatic deposits will fail until you connect it in the "
                            "KHPAY dashboard.")


async def _check_bay2game(bot: Bot, settings, b2g: Bay2GameClient) -> None:
    """Tell the admins at start-up if the Bay2Game key works and the balance is healthy."""
    try:
        balance = await b2g.balance_cents()
    except Bay2GameError as exc:
        log.error("Bay2Game check failed: %s", exc)
        await notify_admins(bot, settings, "⚠️ Bay2Game key check failed - automatic delivery "
                            f"will not work until fixed.\n{exc}")
        return
    from app.utils.formatting import money
    text = f"🔌 Bay2Game is connected. Balance: <b>{money(balance)}</b>. Send /b2g for commands."
    if balance < settings.bay2game_low_balance_cents:
        text += "\n⚠️ Low balance - top up soon."
    await notify_admins(bot, settings, text)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"\n❌ Configuration problem:\n   {exc}\n")
        sys.exit(1)

    db = Database(settings.database_path)
    await db.connect()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Premium (animated) emoji from custom_emoji.json - does nothing when the file is empty.
    emoji_map = load_mapping(os.getenv("CUSTOM_EMOJI_FILE", str(Path(__file__).parent / "custom_emoji.json")))
    if emoji_map:
        bot.session.middleware(CustomEmojiMiddleware(emoji_map))
        log.info("Premium emoji ON for %d emoji", len(emoji_map))

    # Premium emoji + message texts that admins edit from inside the bot (/emoji, /settext).
    # Saved in the database, applied live - no restart needed. Works next to the file above.
    emoji_store = EmojiStore()
    await emoji_store.load(db)
    bot.session.middleware(LiveEmojiMiddleware(emoji_store))
    n_texts = await live_edit.load_text_overrides(db)
    log.info("Admin-edited: %d premium emoji, %d message text(s)", len(emoji_store), n_texts)

    # Objects that handlers can receive just by naming them as parameters.
    dp["db"] = db
    dp["emoji_store"] = emoji_store
    dp["settings"] = settings
    # Automatic payments are ON only when KHPAY_API_KEY is set.
    khpay = (
        KhpayClient(settings.khpay_api_key, settings.khpay_base_url, settings.khpay_test_mode)
        if settings.khpay_api_key else None
    )
    dp["khpay"] = khpay
    # Automatic diamond delivery is ON only when BAY2GAME_API_KEY is set.
    b2g = (
        Bay2GameClient(settings.bay2game_api_key, settings.bay2game_base_url,
                       settings.bay2game_method)
        if settings.bay2game_api_key else None
    )
    dp["b2g"] = b2g

    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    dp.errors.register(on_error)

    # ORDER MATTERS: earlier routers get the first chance to handle a message.
    dp.include_router(start.router)     # /start, /menu, /cancel, language
    dp.include_router(live_edit.router)  # admin only: /emoji, /texts, /settext (works in any state)
    dp.include_router(wallet_admin.router)  # admin only: /addbalance, /subbalance
    dp.include_router(menu.router)      # all main-menu buttons
    dp.include_router(admin.router)     # admin only
    dp.include_router(supplier.router)  # admin only: Bay2Game commands
    dp.include_router(catalog_handlers.router)  # admin only: import games/packages, delete
    dp.include_router(appearance.router)  # admin only: rename games, emoji
    dp.include_router(wallet.router)    # deposit flow
    dp.include_router(shop.router)      # ordering flow
    dp.include_router(fallback.router)  # anything else (must be last)

    watcher = None
    sweeper = None
    pricer = None
    importer = None
    try:
        me = await bot.get_me()
        log.info("Bot started as @%s - press Ctrl+C to stop", me.username)
        await bot.delete_webhook(drop_pending_updates=True)
        await setup_commands(bot, settings)  # Telegram "Menu" list (customers + admins)
        if khpay is not None:
            await _check_khpay(bot, settings, khpay)
            watcher = asyncio.create_task(watch_payments(bot, db, khpay, settings))
            log.info("Automatic payments (KHPAY) are ON%s",
                     " - TEST MODE" if settings.khpay_test_mode else "")
        else:
            log.info("Automatic payments are OFF - deposits are approved by an admin")
        if b2g is not None:
            await _check_bay2game(bot, settings, b2g)
            sweeper = asyncio.create_task(watch_stuck_orders(bot, db, b2g, settings))
            pricer = asyncio.create_task(watch_prices(bot, db, b2g, settings))
            importer = asyncio.create_task(watch_catalog(bot, db, b2g, settings))
            log.info("Automatic delivery (Bay2Game) is ON")
        else:
            log.info("Automatic delivery is OFF - admins deliver orders by hand")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except TelegramUnauthorizedError:
        print("\n❌ Telegram rejected your BOT_TOKEN. Check the token in your .env file.\n")
        sys.exit(1)
    finally:
        for task in (watcher, sweeper, pricer, importer):
            if task is not None:
                task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
