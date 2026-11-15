"""Mini App web server. It runs inside the bot (same process, same database).

Phase 1: customers can browse games, packages and prices. Nothing here changes
data or touches money.
"""
import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import web

from app.database import repositories as repo
from app.keyboards.admin import view_order_kb
from app.services import fulfilment
from app.services import online_payments as op
from app.services import orders as order_service
from app.services.khpay import KhpayError
from app.services.errors import (
    DuplicateDeposit, DuplicateOrder, InsufficientBalance, ProductUnavailable,
)
from app.texts import t
from app.utils.formatting import esc, money
from app.utils.telegram import notify_admins, notify_group, notify_user
from app.utils.validators import valid_player_id, valid_server_id
from app.webapp.auth import validate_init_data

log = logging.getLogger("diamond_zs")
HERE = Path(__file__).resolve().parent

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    ),
}


@web.middleware
async def _headers(request: web.Request, handler):
    response = await handler(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


async def _page(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


async def _logo(request: web.Request) -> web.StreamResponse:
    path = HERE / "mini_logo.png"
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


CACHE_SECONDS = 10      # the shop list is rebuilt at most once every 10 seconds


async def _games(app: web.Application) -> list:
    """Games and packages that customers can see (same rules as the bot's shop)."""
    cache = app["cache"]
    if cache["games"] is not None and time.monotonic() - cache["at"] < CACHE_SECONDS:
        return cache["games"]
    db = app["db"]
    try:
        imgs = json.loads(await repo.get_setting(db, "webapp_imgs") or "{}")
    except ValueError:
        imgs = {}
    cache["imgs"] = imgs
    try:
        pimgs = json.loads(await repo.get_setting(db, "webapp_pimgs") or "{}")
    except ValueError:
        pimgs = {}
    cache["pimgs"] = pimgs
    cache["banner"] = (await repo.get_setting(db, "webapp_banner")) or ""
    games = []
    for game in await repo.list_games(db, only_active=True):
        products = await repo.list_products(db, game["code"], only_active=True)
        if not products:
            continue
        games.append({
            "code": game["code"],
            "name": game["name"],
            "emoji": game.get("emoji") or "🎮",
            "needs_server": bool(game.get("needs_server_id")),
            "img": game["code"] in imgs,
            "products": [
                {"id": p["id"], "name": p["name"], "price_cents": p["price_cents"],
                 "emoji": p.get("emoji") or "💎", "img": str(p["id"]) in pimgs}
                for p in products
            ],
        })
    cache["games"], cache["at"] = games, time.monotonic()
    return games


async def _catalog(request: web.Request) -> web.Response:
    """The shop list. Anyone can browse it (it is read-only and the prices are public);
    when the page is opened inside Telegram the customer's own language is used."""
    init = request.headers.get("X-Init-Data", "")
    user = None
    if init:                                   # a signed request must be genuine
        user = validate_init_data(init, request.app["bot_token"])
        if user is None:
            return _json({"error": "unauthorized"}, 401)
    balance = None
    if user is not None:
        row = await request.app["db"].fetchone(
            "SELECT language, balance_cents FROM users WHERE telegram_id = ?", (user["id"],))
        if row:
            balance = row["balance_cents"]
        if row and row["language"] in ("en", "km"):
            lang = row["language"]
        else:
            lang = "km" if str(user.get("language_code", "")).startswith("km") else "en"
    else:
        lang = "km"
    return _json({"lang": lang, "games": await _games(request.app),
                  "bot": request.app["bot_username"], "signed_in": user is not None,
                  "balance_cents": balance, "banner": request.app["cache"].get("banner", ""),
                  "pay": request.app["pay"] is not None})


async def _account(request: web.Request) -> web.Response:
    """The signed-in customer's own wallet history, orders and totals (read-only)."""
    user = validate_init_data(request.headers.get("X-Init-Data", ""), request.app["bot_token"])
    if user is None:
        return _json({"error": "unauthorized"}, 401)
    db = request.app["db"]
    row = await db.fetchone("SELECT * FROM users WHERE telegram_id = ?", (user["id"],))
    name = (user.get("first_name") or "") + (" " + user["last_name"] if user.get("last_name") else "")
    if row is None:
        return _json({"registered": False, "name": name, "tg_id": user["id"]})
    orders = await repo.list_user_orders(db, row["id"], 30)
    txs = await db.fetchall(
        "SELECT type, amount_cents, created_at FROM transactions WHERE user_id = ? "
        "ORDER BY id DESC LIMIT 30", (row["id"],))
    stats = await db.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(price_cents), 0) AS spent FROM orders "
        "WHERE user_id = ? AND status != 'cancelled'", (row["id"],))
    return _json({
        "registered": True, "tg_id": user["id"], "name": row["full_name"] or name,
        "username": row["username"] or "", "balance_cents": row["balance_cents"],
        "total_orders": stats["n"], "total_spent_cents": stats["spent"],
        "orders": [{"id": o["id"], "name": o["product_name"], "game": o["game_name"],
                    "price_cents": o["price_cents"], "status": o["status"],
                    "created_at": o["created_at"]} for o in orders],
        "transactions": [{"type": x["type"], "amount_cents": x["amount_cents"],
                          "created_at": x["created_at"]} for x in txs],
    })


MIN_DEPOSIT_CENTS, MAX_DEPOSIT_CENTS = 50, 50000     # $0.50 .. $500 (change here if needed)


async def _image(request: web.Request) -> web.Response:
    """Game picture set by the admin with /gameimg (Telegram file, cached in memory)."""
    await _games(request.app)
    return await _send_file(request.app, request.app["cache"].get("imgs", {}).get(request.match_info["code"]))


async def _pimage(request: web.Request) -> web.Response:
    """Package picture set by the admin with /pkgimg."""
    await _games(request.app)
    return await _send_file(request.app, request.app["cache"].get("pimgs", {}).get(request.match_info["pid"]))


async def _send_file(app, file_id) -> web.Response:
    if not file_id:
        raise web.HTTPNotFound()
    if file_id not in app["imgbytes"]:
        try:
            app["imgbytes"][file_id] = (await app["bot"].download(file_id)).read()
        except Exception:
            raise web.HTTPNotFound()
    return web.Response(body=app["imgbytes"][file_id], content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=3600"})


def _gate(app, request, key: str):
    """Common checks for money endpoints. Returns (user, error_response)."""
    user = validate_init_data(request.headers.get("X-Init-Data", ""), app["bot_token"])
    if user is None:
        return None, _fail("unauthorized", 401)
    if app["pay"] is None:
        return None, _fail("no_pay")
    now = time.monotonic()
    k = (key, user["id"])
    recent = [x for x in app["attempts"].get(k, []) if now - x < 60]
    if len(recent) >= ORDERS_PER_MINUTE:
        return None, _fail("rate_limited", 429)
    app["attempts"][k] = recent + [now]
    return user, None


async def _deposit(request: web.Request) -> web.Response:
    """Start a KHQR deposit; the existing payment watcher credits the wallet when paid."""
    app = request.app
    user, bad = _gate(app, request, "dep")
    if bad:
        return bad
    try:
        cents = (await request.json())["amount_cents"]
        if not isinstance(cents, int) or isinstance(cents, bool):
            raise ValueError
    except Exception:
        return _fail("bad_request", 400)
    if not MIN_DEPOSIT_CENTS <= cents <= MAX_DEPOSIT_CENTS:
        return _fail("bad_amount", min_cents=MIN_DEPOSIT_CENTS, max_cents=MAX_DEPOSIT_CENTS)
    try:
        dep_id, qr = await op.start_online_deposit(app["db"], app["pay"], user["id"], cents)
    except DuplicateDeposit:
        return _fail("deposit_pending")
    except KhpayError:
        return _fail("pay_error")
    except Exception:
        log.exception("Mini App deposit failed")
        return _fail("error")
    return _json({"ok": True, "id": dep_id, "qr": qr.qr_image, "expires_in": qr.expires_in})


async def _deposit_status(request: web.Request) -> web.Response:
    app = request.app
    user = validate_init_data(request.headers.get("X-Init-Data", ""), app["bot_token"])
    if user is None:
        return _fail("unauthorized", 401)
    try:
        dep_id = int(request.query.get("id", ""))
    except ValueError:
        return _fail("bad_request", 400)
    row = await app["db"].fetchone(
        "SELECT d.status, u.balance_cents FROM deposit_requests d JOIN users u ON u.id = d.user_id "
        "WHERE d.id = ? AND u.telegram_id = ?", (dep_id, user["id"]))
    if row is None:
        return _fail("not_found", 404)
    return _json({"ok": True, "status": row["status"], "balance_cents": row["balance_cents"]})


async def _deposit_cancel(request: web.Request) -> web.Response:
    app = request.app
    user, bad = _gate(app, request, "depc")
    if bad:
        return bad
    try:
        dep_id = int((await request.json())["id"])
    except Exception:
        return _fail("bad_request", 400)
    db = app["db"]
    dep = await op._get(db, dep_id)
    outcome = await op.cancel_online_deposit(db, app["pay"], user["id"], dep_id)
    if outcome.kind == "credited" and dep:          # they had paid after all
        await op.announce_outcome(app["bot"], app["settings"], dep, outcome, db)
    return _json({"ok": True, "kind": outcome.kind})


ORDERS_PER_MINUTE = 6


def _fail(error: str, status: int = 200, **extra) -> web.Response:
    return _json({"ok": False, "error": error, **extra}, status)


async def _order(request: web.Request) -> web.Response:
    """Buy a package with the wallet balance (same rules as the bot's shop)."""
    app = request.app
    user = validate_init_data(request.headers.get("X-Init-Data", ""), app["bot_token"])
    if user is None:
        return _fail("unauthorized", 401)
    uid = user["id"]
    now = time.monotonic()
    if len(app["attempts"]) > 5000:
        app["attempts"].clear()
    recent = [x for x in app["attempts"].get(uid, []) if now - x < 60]
    if len(recent) >= ORDERS_PER_MINUTE:
        return _fail("rate_limited", 429)
    app["attempts"][uid] = recent + [now]
    if uid in app["busy"]:
        return _fail("busy", 409)
    try:
        body = await request.json()
        product_id = body["product_id"]
        if not isinstance(product_id, int) or isinstance(product_id, bool):
            raise ValueError
    except Exception:
        return _fail("bad_request", 400)
    app["busy"].add(uid)
    try:
        return await _place_order(app, uid, product_id, body)
    except Exception:
        log.exception("Mini App order failed")
        return _fail("error")
    finally:
        app["busy"].discard(uid)


async def _place_order(app, uid: int, product_id: int, body: dict) -> web.Response:
    db, bot, settings, b2g = app["db"], app["bot"], app["settings"], app["b2g"]
    user = await db.fetchone("SELECT * FROM users WHERE telegram_id = ?", (uid,))
    if user is None:
        return _fail("no_user")
    product = await repo.get_product(db, product_id)
    if product is None or not product["is_active"] or not product["game_active"]:
        return _fail("unavailable")
    player_id = valid_player_id(str(body.get("player_id", "")))
    if player_id is None:
        return _fail("invalid_player_id")
    server_id = ""
    if product["needs_server_id"]:
        server_id = valid_server_id(str(body.get("server_id", "")))
        if server_id is None:
            return _fail("invalid_server_id")
    try:
        order_id = await order_service.create_order(db, uid, product_id, player_id, server_id)
    except InsufficientBalance as exc:
        return _fail("insufficient", price_cents=exc.price_cents, balance_cents=exc.balance_cents)
    except DuplicateOrder:
        return _fail("duplicate")
    except ProductUnavailable:
        return _fail("unavailable")

    # The money is taken: from here on the customer must always get "ok".
    try:
        order = await repo.get_order(db, order_id)
        auto = False
        if b2g is not None:
            row = await db.fetchone("SELECT supplier_code FROM products WHERE id = ?",
                                    (order["product_id"],))
            auto = bool(row and row["supplier_code"])
        await notify_user(bot, uid, t(user["language"],
                                      "order_created_auto" if auto else "order_created",
                                      id=order_id, price=money(order["price_cents"])))
        if auto:
            task = asyncio.create_task(
                fulfilment.run_fulfilment(bot, db, b2g, settings, order_id))
            app["tasks"].add(task)
            task.add_done_callback(app["tasks"].discard)
        else:
            who = esc(user["full_name"]) + (f" (@{esc(user['username'])})" if user["username"] else "")
            zone = f"\nZone ID: <code>{esc(order['server_id'])}</code>" if order["server_id"] else ""
            detail = (f"Game: {esc(order['game_name'])}\nPackage: {esc(order['product_name'])}\n"
                      f"Player ID: <code>{esc(order['player_id'])}</code>{zone}")
            await notify_admins(bot, settings,
                                f"🆕 <b>New order #{order_id}</b> (Mini App)\nCustomer: {who}\n{detail}\n"
                                f"Paid from wallet: <b>{money(order['price_cents'])}</b>",
                                reply_markup=view_order_kb(order_id))
            await notify_group(bot, settings, "orders",
                               f"🆕 <b>New order #{order_id}</b> - manual delivery needed\n{detail}")
    except Exception:
        log.exception("Order #%s was created but a notification failed", order_id)
    row = await db.fetchone("SELECT balance_cents FROM users WHERE telegram_id = ?", (uid,))
    return _json({"ok": True, "order_id": order_id,
                  "balance_cents": row["balance_cents"] if row else None})


async def start_webapp(db, bot_token: str, port: int, bot_username: str = "",
                       bot=None, settings=None, b2g=None, pay=None) -> web.AppRunner:
    app = web.Application(middlewares=[_headers], client_max_size=8192)
    app["bot"], app["settings"], app["b2g"], app["pay"] = bot, settings, b2g, pay
    app["imgbytes"] = {}
    app["attempts"], app["busy"], app["tasks"] = {}, set(), set()
    app["db"] = db
    app["bot_token"] = bot_token
    app["bot_username"] = bot_username
    app["cache"] = {"games": None, "at": 0.0}
    app.add_routes([
        web.get("/", _page),
        web.get("/logo.png", _logo),
        web.get("/health", _health),
        web.get("/api/catalog", _catalog),
        web.post("/api/order", _order),
        web.post("/api/deposit", _deposit),
        web.get("/api/deposit_status", _deposit_status),
        web.post("/api/deposit_cancel", _deposit_cancel),
        web.get("/img/{code}", _image),
        web.get("/pimg/{pid}", _pimage),
        web.get("/api/account", _account),
    ])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Mini App web server is listening on port %d", port)
    return runner
