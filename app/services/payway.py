"""ABA PayWay (KHQR) payments through your own PayWay payment link.

This replaces khpay.py. It has the SAME methods and return types as KhpayClient
(generate_qr / check / expire), so wallet.py and online_payments.py keep working.

How it works (no merchant API key needed - it does what the link's own web page does):
  1. GET the payment-link page and read two values from the page's own data
     (aba_data and request_time).
  2. POST list-payment-options with the amount -> ABA answers with a KHQR string,
     a client_id, a token and a Tran ID.
  3. We draw the KHQR as a PNG for the customer.
  4. check(): POST check-payment-status -> paid ONLY when ABA says action == "approved".

Safety rules kept from the original working design:
  * The page is reused for a short time and, after an HTTP 429, not loaded again for a
    while (retrying only keeps the block on). We never try to get around Cloudflare.
  * The status check needs the SAME device_id / token / request_time as the QR, so they
    are saved per payment in the payway_sessions table (survives restarts).
  * The amount inside the KHQR is read back and must equal what we asked for.
"""
import asyncio
import base64
import gzip
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import string
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.database.db import Database
from app.services.khpay import KhpayError, PaymentStatus, QrPayment, cents_to_amount

log = logging.getLogger(__name__)

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_API_URL = "https://link.payway.com.kh/api"
LINK_RE = re.compile(r"^https://link\.payway\.com\.kh/[A-Za-z0-9]+/?$")

# Plain, normal browser headers for loading the page (nothing more than a browser sends).
PAGE_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
    "Upgrade-Insecure-Requests": "1",
}

PAGE_REUSE_SECONDS = 60      # one page load can make many QRs (each has its own Tran ID)
COOLDOWN_SECONDS = 45        # no page loads for this long after a 429
PAGE_MAX_AGE_SECONDS = 240   # while paused, a saved page may be used up to this age
QR_LIFETIME_SECONDS = 180    # shown to the customer; the watcher adds a grace period


def sha512(text: str) -> str:
    return hashlib.sha512(text.encode()).hexdigest()


def hmac_sha512(text: str, key: str) -> str:
    return hmac.new(key.encode(), text.encode(), hashlib.sha512).hexdigest()


def random_id(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --------------------------------------------------------- reading the link page


def _unescape_js_string(body: str) -> str:
    """Body of a JS string literal (without quotes) -> the real text."""
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 >= len(body):
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v",
                  "0": "\0", "\\": "\\", "'": "'", '"': '"', "/": "/", "`": "`"}
        if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", body[i + 2:i + 6]):
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        elif nxt == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", body[i + 2:i + 4]):
            out.append(chr(int(body[i + 2:i + 4], 16)))
            i += 4
        else:
            out.append(simple.get(nxt, nxt))
            i += 2
    return "".join(out)


def _scan_string(text: str, i: int) -> int:
    """text[i] is a quote. Returns the index just after the closing quote."""
    quote = text[i]
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    raise ValueError("unterminated string")


def _split_args(text: str) -> list:
    """Split 'a,"b,c",{x:1},void 0' on top-level commas (strings and brackets respected)."""
    args, depth, start, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch in "\"'`":
            i = _scan_string(text, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(text[start:i].strip())
            start = i + 1
        i += 1
    last = text[start:].strip()
    if last or args:
        args.append(last)
    return args


def _literal(token: str):
    """A JS literal token -> Python value (strings and numbers only matter to us)."""
    token = token.strip()
    if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0]:
        return _unescape_js_string(token[1:-1])
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token


def _iife_parts(payload: str):
    """'(function(a,b){return {...}}("x",1))' -> (param names, body, argument tokens)."""
    m = re.match(r"\(\s*function\s*\(([^)]*)\)\s*\{", payload)
    if not m:
        return None
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    depth, i = 1, m.end()
    while i < len(payload) and depth:
        ch = payload[i]
        if ch in "\"'`":
            i = _scan_string(payload, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    body = payload[m.end():i - 1]
    rest = payload[i:].lstrip()
    if not rest.startswith("("):
        return None
    j, depth = 1, 1
    while j < len(rest) and depth:
        ch = rest[j]
        if ch in "\"'`":
            j = _scan_string(rest, j)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        j += 1
    return params, body, _split_args(rest[1:j - 1])


def _value_of(key: str, body: str, env: dict):
    """Value of the first `key: <literal or parameter name>` in the payload body."""
    m = re.search(r"(?<![A-Za-z0-9_$])[\"']?" + re.escape(key) + r"[\"']?\s*:\s*", body)
    if not m:
        return None
    rest = body[m.end():]
    if rest[:1] in "\"'":
        return _unescape_js_string(rest[1:_scan_string(rest, 0) - 1])
    num = re.match(r"-?\d+(?:\.\d+)?", rest)
    if num and not re.match(r"[A-Za-z_$]", rest[num.end():num.end() + 1] or " "):
        return int(num.group()) if "." not in num.group() else num.group()
    ident = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", rest)
    if ident:
        value = env.get(ident.group())
        return value if isinstance(value, (str, int)) else None
    return None


@dataclass
class LinkPage:
    link: str
    aba_data: str
    request_time: object      # str (or int) exactly as the page gives it
    merchant_name: str
    at: float                 # time.monotonic() when it was loaded


def parse_link_page(html: str, link: str = "") -> LinkPage:
    """Read aba_data and request_time out of the link page's window.__NUXT__ data."""
    m = re.search(r"<script>\s*(window\.__NUXT__\s*=[\s\S]*?);?\s*</script>", html)
    if not m:
        raise KhpayError("Invalid PayWay link page: page data not found")
    payload = re.sub(r"^window\.__NUXT__\s*=\s*", "", m.group(1)).strip().rstrip(";")
    try:
        parts = _iife_parts(payload)
        if parts:
            params, body, args = parts
            env = {name: _literal(arg) for name, arg in zip(params, args)}
        else:
            body, env = payload, {}
        aba_data = _value_of("aba_data", body, env)
        request_time = _value_of("request_time", body, env)
        merchant = (_value_of("outlet_name", body, env) or _value_of("company", body, env)
                    or "ABA Merchant")
    except (ValueError, IndexError):
        raise KhpayError("Could not read the PayWay link page data") from None
    if not isinstance(aba_data, str) or not aba_data or request_time in (None, ""):
        raise KhpayError("Could not read ABA session values from the link page")
    return LinkPage(link, aba_data, request_time, str(merchant), time.monotonic())


# ------------------------------------------------------------ reading the KHQR


def parse_emv(text: str) -> dict:
    """KHQR / EMV QR string -> {tag: value} (top level only)."""
    out, i = {}, 0
    while i + 4 <= len(text):
        tag, length = text[i:i + 2], text[i + 2:i + 4]
        if not length.isdigit():
            break
        n = int(length)
        out[tag] = text[i + 4:i + 4 + n]
        i += 4 + n
    return out


def check_qr_amount(qr_string: str, amount_cents: int) -> None:
    """The KHQR itself says how much it asks for (tag 54). It must be what we asked."""
    tags = parse_emv(qr_string)
    amount = tags.get("54")
    if amount is None:
        log.warning("KHQR has no amount tag - cannot double-check the amount")
        return
    try:
        cents = Decimal(amount) * 100
    except InvalidOperation:
        raise KhpayError("QR has an unreadable amount") from None
    if cents != Decimal(amount_cents):
        raise KhpayError(f"QR amount {amount} is not the requested "
                         f"{cents_to_amount(amount_cents)}")
    currency = tags.get("53")
    if currency and currency != "840":
        raise KhpayError("QR currency is not USD")


def qr_data_uri(text: str) -> str:
    try:
        import qrcode
    except ImportError:
        raise KhpayError("QR library missing: add qrcode[pil] to requirements.txt") from None
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


# ----------------------------------------------------------------- the client


class PaywayClient:
    def __init__(self, db: Database, link: str, api_url: str = DEFAULT_API_URL):
        self._db = db
        self._link = (link or "").strip()
        self._api = (api_url or DEFAULT_API_URL).rstrip("/")
        self._page: Optional[LinkPage] = None
        self._page_lock = asyncio.Lock()
        self._blocked_until = 0.0
        self._last_check: dict = {}          # tran_id -> (time, PaymentStatus)

    @property
    def link(self) -> str:
        return self._link

    def set_link(self, link: str) -> None:
        self._link = (link or "").strip()
        self._page = None
        self._blocked_until = 0.0

    # ---- low level -----------------------------------------------------------

    def _http_sync(self, method: str, url: str, headers: dict, body: Optional[dict],
                   timeout: int) -> tuple:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        def decode(raw: bytes, headers) -> str:
            if (headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            return raw.decode("utf-8", "replace")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, decode(resp.read(), resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, decode(exc.read(), exc.headers)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KhpayError(f"PayWay unreachable: {type(exc).__name__}") from None

    async def _http(self, method: str, url: str, headers: dict,
                    body: Optional[dict] = None, timeout: int = 12) -> tuple:
        return await asyncio.to_thread(self._http_sync, method, url, headers, body, timeout)

    def _api_headers(self, referer: str, token: Optional[str] = None) -> dict:
        headers = {"Content-Type": "application/json", "Origin": "https://link.payway.com.kh",
                   "Referer": referer, "User-Agent": BROWSER_UA}
        if token:
            headers["token"] = token
        return headers

    @staticmethod
    def _message(text: str, fallback: str) -> str:
        try:
            data = json.loads(text)
            return str((data.get("status") or {}).get("message") or data.get("error") or fallback)
        except (ValueError, AttributeError):
            return fallback

    # ---- the link page (reused, paused after a 429) ---------------------------

    async def _load_page(self, link: str) -> LinkPage:
        status, text = await self._http("GET", link, PAGE_HEADERS)
        if status >= 400:
            # A short look at what the other side said helps to tell Cloudflare from ABA.
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:200]
            log.warning("[PayWay] link page HTTP %s: %s", status, snippet)
        if status == 429:
            self._blocked_until = time.monotonic() + COOLDOWN_SECONDS
            log.warning("[PayWay] link page answered 429 - no page loads for %ss", COOLDOWN_SECONDS)
            raise KhpayError("PayWay link page is rate limited (429)", code="429", http_status=429)
        if status >= 400:
            raise KhpayError(f"PayWay link page error (HTTP {status})",
                             code=str(status), http_status=status)
        return parse_link_page(text, link)

    async def _get_page(self, link: str, fresh: bool = False) -> tuple:
        """Returns (page, reused)."""
        now = time.monotonic()
        saved = self._page if self._page and self._page.link == link else None
        blocked = now < self._blocked_until
        limit = PAGE_MAX_AGE_SECONDS if blocked else PAGE_REUSE_SECONDS
        if saved and not fresh and now - saved.at < limit:
            return saved, True
        if blocked:
            wait = int(self._blocked_until - now) + 1
            raise KhpayError(f"PayWay link page is rate limited (429) - paused {wait}s more",
                             code="429", http_status=429)
        async with self._page_lock:
            # Someone may have just loaded it while we waited for the lock.
            cur = self._page
            if cur and cur.link == link and time.monotonic() - cur.at < 5:
                return cur, True
            page = await self._load_page(link)
            self._page = page
            return page, False

    async def _list_options(self, page: LinkPage, amount: str) -> dict:
        extra = json.dumps({"amount": amount}, separators=(",", ":"))
        status, text = await self._http(
            "POST", f"{self._api}/pw-app/v1/payment/gateway/list-payment-options",
            self._api_headers(page.link),
            {"request_time": page.request_time, "aba_data": page.aba_data,
             "additional_fields": extra,
             "hash": sha512(str(page.request_time) + page.aba_data + extra)})
        if status == 429:
            raise KhpayError("PayWay is busy (429)", code="429", http_status=429)
        try:
            data = json.loads(text)
        except ValueError:
            raise KhpayError(f"PayWay returned an unreadable answer (HTTP {status})") from None
        if status >= 400 or not data.get("aba_data") or not data.get("token"):
            raise KhpayError(self._message(text, "Failed to start the ABA checkout"),
                             http_status=status)
        return data

    async def _request_qr(self, page: LinkPage, checkout: dict) -> dict:
        """Older separate step, used only if list-payment-options gave no qr_string."""
        status, text = await self._http(
            "POST", f"{self._api}/pw-app/v1/payment/gateway/abapay-khqr/request-qr",
            self._api_headers(page.link, checkout["token"]),
            {"request_time": page.request_time, "aba_data": checkout["aba_data"],
             "hash": hmac_sha512(str(page.request_time) + checkout["aba_data"], checkout["token"])})
        try:
            return json.loads(text)
        except ValueError:
            raise KhpayError(f"PayWay returned an unreadable QR answer (HTTP {status})") from None

    # ---- API used by the bot (same as KhpayClient) ----------------------------

    async def generate_qr(self, amount_cents: int, note: str, metadata: dict,
                          idempotency_key: str) -> QrPayment:
        link = self._link
        if not link:
            raise KhpayError("No PayWay link is set")
        amount = cents_to_amount(amount_cents)
        started = time.monotonic()
        page, reused = await self._get_page(link)
        try:
            checkout = await self._list_options(page, amount)
        except KhpayError as exc:
            if not reused or exc.code == "429":
                raise
            self._page = None                       # ABA refused the saved page: new page, once
            page, _ = await self._get_page(link, fresh=True)
            checkout = await self._list_options(page, amount)
        if checkout.get("qr_string"):
            qr = {"qr_string": checkout["qr_string"], "client_id": checkout.get("client_id"),
                  "status": checkout.get("status")}
        else:
            qr = await self._request_qr(page, checkout)
        qr_string = str(qr.get("qr_string") or "")
        client_id = str(qr.get("client_id") or "")
        if not qr_string or not client_id:
            raise KhpayError(self._status_message(qr, "ABA did not return a QR"))
        check_qr_amount(qr_string, amount_cents)
        tran_id = str((qr.get("status") or {}).get("tran_id") or client_id)
        device_id = random_id(10)
        await self._db.execute(
            "DELETE FROM payway_sessions WHERE created_at < datetime('now', '-2 days')")
        await self._db.execute(
            "INSERT OR REPLACE INTO payway_sessions "
            "(tran_id, client_id, device_id, request_time, token, payway_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tran_id, client_id, device_id, str(page.request_time), checkout["token"], link))
        image = await asyncio.to_thread(qr_data_uri, qr_string)
        log.info("[PayWay] QR for %s ($%s) in %dms (Tran %s)", note, amount,
                 (time.monotonic() - started) * 1000, tran_id)
        return QrPayment(transaction_id=tran_id, qr_image=image, qr_string=qr_string,
                         payment_url="", expires_in=QR_LIFETIME_SECONDS)

    @staticmethod
    def _status_message(data: dict, fallback: str) -> str:
        status = data.get("status") if isinstance(data, dict) else None
        return str((status or {}).get("message") or fallback) if isinstance(status, dict) else fallback

    async def check(self, transaction_id: str) -> PaymentStatus:
        """Paid ONLY when ABA says action == "approved"."""
        cached = self._last_check.get(transaction_id)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]                         # button spam / watcher: do not hammer ABA
        row = await self._db.fetchone(
            "SELECT * FROM payway_sessions WHERE tran_id = ?", (transaction_id,))
        if row is None:                              # e.g. an old KHPAY deposit: nothing to check
            return PaymentStatus(transaction_id, False, "expired", "no_session", None, "")
        status, text = await self._http(
            "POST", f"{self._api}/pw-app/v1/payment-link/check-payment-status",
            self._api_headers(row["payway_url"], row["token"]),
            {"client_id": row["client_id"], "device_id": row["device_id"],
             "request_time": row["request_time"],
             "hash": sha512(row["client_id"] + row["device_id"] + row["request_time"])},
            timeout=6)
        if status >= 400:
            raise KhpayError(self._message(text, f"PayWay status check failed (HTTP {status})"),
                             http_status=status)
        try:
            data = json.loads(text or "{}")
        except ValueError:
            raise KhpayError("PayWay returned an unreadable status answer") from None
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        action = str(inner.get("action") or data.get("action") or "request_qr").lower()
        paid = action == "approved"
        result = PaymentStatus(transaction_id, paid, "paid" if paid else "pending", action,
                               None, "")
        self._last_check[transaction_id] = (time.monotonic(), result)
        if len(self._last_check) > 500:
            self._last_check.clear()
        if action not in ("request_qr", "approved"):
            log.info("[PayWay] %s: %s", transaction_id, action)
        return result

    async def expire(self, transaction_id: str) -> None:
        """PayWay QR codes expire by themselves; nothing to tell ABA."""
        return None

    # ---- diagnostics for admins ------------------------------------------------

    async def self_test(self) -> str:
        """Load the link page fresh and report what was found (for /payway_test)."""
        if not self._link:
            raise KhpayError("No PayWay link is set")
        self._page = None
        page, _ = await self._get_page(self._link, fresh=True)
        return page.merchant_name
