"""Client for the Bay2Game reseller API (https://api.bay2game.xyz/api).

Endpoints used (from the official docs): /profile, /categories, /products,
/create_order, /check_order. Standard library only (urllib in a worker thread).

The API key is never logged and never appears in error messages. Orders are sent
with POST (JSON body) so the key stays out of URLs; the read-only endpoints are
documented as GET with `api_key` as a query parameter.
"""
import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Optional

log = logging.getLogger(__name__)


class Bay2GameError(Exception):
    """Base error. `uncertain` = we do NOT know whether Bay2Game processed the request."""

    def __init__(self, message: str, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class Bay2GameFailed(Bay2GameError):
    """Bay2Game answered clearly that the request did not succeed."""

    def __init__(self, message: str):
        super().__init__(message, uncertain=False)


class OrderNotFound(Bay2GameError):
    pass


def usd_to_cents_ceil(value) -> Optional[int]:
    """12.5 -> 1250. Rounds UP so a cost is never under-estimated."""
    try:
        d = Decimal(str(value)) * 100
    except (InvalidOperation, ValueError):
        return None
    return int(d.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class SupplierProduct:
    code: str
    name: str
    price_cents: int
    active: bool


@dataclass(frozen=True)
class OrderResult:
    reference: str
    amount_cents: Optional[int]
    balance_after_cents: Optional[int]
    message: str


@dataclass(frozen=True)
class OrderStatus:
    reference: str
    status: str            # success | failed | other (still processing)
    amount_cents: Optional[int]


def _ok(data: dict) -> bool:
    """Bay2Game says SUCCESS; accept any letter case so 'success' works too."""
    return str(data.get("status") or "").strip().upper() == "SUCCESS"


def _why(data: dict, default: str) -> str:
    """Readable reason for a refused request (never contains the API key)."""
    msg = str(data.get("message") or data.get("error") or "").strip()
    status = str(data.get("status") or "").strip()
    parts = [msg or default, f"HTTP {data.get('_http')}"]
    if status and status.upper() != "SUCCESS":
        parts.append(f"status={status[:30]}")
    keys = ",".join(sorted(k for k in data if k != "_http"))[:80]
    if not msg:
        parts.append(f"reply keys: {keys or 'none'}")
    return " | ".join(parts)


class Bay2GameClient:
    def __init__(self, api_key: str, base_url: str = "https://api.bay2game.xyz/api",
                 method: str = "POST", timeout: int = 20):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._post = method.upper() != "GET"
        self._timeout = timeout
        self._products_cache: dict = {}

    # ---- low level -----------------------------------------------------------

    def _call_sync(self, path: str, params: dict, post: bool) -> dict:
        params = {**params, "api_key": self._api_key}
        headers = {"Accept": "application/json", "User-Agent": "diamond-zs-bot/1.0"}
        if post:
            req = urllib.request.Request(
                self._base_url + path, data=json.dumps(params).encode(),
                headers={**headers, "Content-Type": "application/json"}, method="POST")
        else:
            req = urllib.request.Request(
                self._base_url + path + "?" + urllib.parse.urlencode(params),
                headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw, status = resp.read(), resp.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read(), exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Message deliberately contains no URL (it would contain the API key on GET).
            raise Bay2GameError(f"cannot reach Bay2Game ({type(exc).__name__})",
                                uncertain=True) from None
        try:
            payload = json.loads(raw.decode() or "{}")
        except ValueError:
            raise Bay2GameError(f"Bay2Game sent an unreadable answer (HTTP {status})",
                                uncertain=True) from None
        if not isinstance(payload, dict):
            raise Bay2GameError("Bay2Game sent an unexpected answer", uncertain=True)
        if status >= 500:
            raise Bay2GameError(f"Bay2Game server error (HTTP {status})", uncertain=True)
        payload["_http"] = status
        return payload

    async def _call(self, path: str, params: dict, post: bool = False) -> dict:
        return await asyncio.to_thread(self._call_sync, path, params, post)

    # ---- read-only endpoints ---------------------------------------------------

    async def balance_cents(self) -> int:
        data = await self._call("/profile", {})
        if not _ok(data):
            raise Bay2GameFailed(_why(data, "profile request failed"))
        cents = usd_to_cents_ceil((data.get("user") or {}).get("balance"))
        if cents is None:
            raise Bay2GameError("profile has no balance")
        return cents

    async def categories(self) -> list:
        data = await self._call("/categories", {})
        if not _ok(data):
            raise Bay2GameFailed(_why(data, "categories request failed"))
        return list(data.get("categories") or [])

    async def products(self, game_code: str, max_age: float = 60.0) -> list:
        cached = self._products_cache.get(game_code)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        data = await self._call("/products", {"game_code": game_code})
        if not _ok(data):
            raise Bay2GameFailed(_why(data, "products request failed"))
        items = []
        for p in data.get("products") or []:
            cents = usd_to_cents_ceil(p.get("sell_price"))
            if p.get("product_code") and cents is not None:
                items.append(SupplierProduct(
                    code=str(p["product_code"]), name=str(p.get("name") or ""),
                    price_cents=cents, active=str(p.get("status", "active")) == "active"))
        self._products_cache[game_code] = (time.monotonic(), items)
        return items

    async def find_product(self, game_code: str, product_code: str) -> Optional[SupplierProduct]:
        for p in await self.products(game_code):
            if p.code == product_code:
                return p
        return None

    # ---- orders ----------------------------------------------------------------

    async def create_order(self, product_code: str, player_id: str, zone_id: str,
                           reference: str) -> OrderResult:
        params = {"product_code": product_code, "game_user_id": player_id,
                  "reference": reference}
        if zone_id:
            params["game_zone_id"] = zone_id
        data = await self._call("/create_order", params, post=self._post)
        status = str(data.get("status") or "").upper()
        message = str(data.get("message") or "")
        if status == "SUCCESS":
            return OrderResult(
                reference=str(data.get("reference") or reference),
                amount_cents=usd_to_cents_ceil(data["amount"]) if data.get("amount") is not None else None,
                balance_after_cents=(usd_to_cents_ceil(data["balance_after"])
                                     if data.get("balance_after") is not None else None),
                message=message,
            )
        if status in ("FAILED", "ERROR"):
            raise Bay2GameFailed(message or "order failed")
        # Anything else is not a clear answer: do not guess.
        raise Bay2GameError(f"unclear answer from Bay2Game (HTTP {data.get('_http')})",
                            uncertain=True)

    async def check_order(self, reference: str) -> OrderStatus:
        data = await self._call("/check_order", {"reference": reference})
        if _ok(data) and isinstance(data.get("order"), dict):
            order = data["order"]
            raw = str(order.get("status") or "").lower()
            amount = order.get("amount")
            return OrderStatus(
                reference=reference,
                status=raw if raw in ("success", "failed") else "other",
                amount_cents=usd_to_cents_ceil(amount) if amount is not None else None,
            )
        message = str(data.get("message") or "")
        if "not found" in message.lower():
            raise OrderNotFound(message)
        raise Bay2GameError(message or "check_order failed", uncertain=True)
