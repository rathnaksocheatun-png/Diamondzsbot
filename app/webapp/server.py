"""Mini App web server. It runs inside the bot (same process, same database).

Phase 1: customers can browse games, packages and prices. Nothing here changes
data or touches money.
"""
import logging
import time
from pathlib import Path

from aiohttp import web

from app.database import repositories as repo
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
    games = []
    for game in await repo.list_games(db, only_active=True):
        products = await repo.list_products(db, game["code"], only_active=True)
        if not products:
            continue
        games.append({
            "code": game["code"],
            "name": game["name"],
            "emoji": game.get("emoji") or "🎮",
            "products": [
                {"id": p["id"], "name": p["name"], "price_cents": p["price_cents"],
                 "emoji": p.get("emoji") or "💎"}
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
    if user is not None:
        row = await request.app["db"].fetchone(
            "SELECT language FROM users WHERE telegram_id = ?", (user["id"],))
        if row and row["language"] in ("en", "km"):
            lang = row["language"]
        else:
            lang = "km" if str(user.get("language_code", "")).startswith("km") else "en"
    else:
        lang = "km"
    return _json({"lang": lang, "games": await _games(request.app),
                  "bot": request.app["bot_username"], "signed_in": user is not None})


async def start_webapp(db, bot_token: str, port: int, bot_username: str = "") -> web.AppRunner:
    app = web.Application(middlewares=[_headers])
    app["db"] = db
    app["bot_token"] = bot_token
    app["bot_username"] = bot_username
    app["cache"] = {"games": None, "at": 0.0}
    app.add_routes([
        web.get("/", _page),
        web.get("/logo.png", _logo),
        web.get("/health", _health),
        web.get("/api/catalog", _catalog),
    ])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Mini App web server is listening on port %d", port)
    return runner
