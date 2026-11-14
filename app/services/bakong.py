"""KHQR payments through the Bakong Open API of the National Bank of Cambodia (official).

Same methods and return types as the old KHPAY / PayWay clients (generate_qr / check /
expire / self_test), so wallet.py and online_payments.py keep working unchanged.

How it works - no web page, no Cloudflare:
  1. generate_qr(): the bot builds the KHQR text itself (EMV format + CRC16) for YOUR
     Bakong account, with the exact amount and a creation / expiry time (3 minutes).
     A bank app refuses to pay a KHQR after its expiry time, so it really stops at 3 min.
  2. The MD5 of that KHQR text is the payment's id.
  3. check(): POST /v1/check_transaction_by_md5 with your token. If Bakong knows a
     transaction for that MD5 the QR was paid, and Bakong tells us the amount, the
     currency and the receiving account - all three are verified before crediting.

Needs (Railway Variables):  BAKONG_ACCOUNT_ID  BAKONG_TOKEN  and optionally
BAKONG_MERCHANT_NAME, BAKONG_MERCHANT_CITY, BAKONG_EMAIL (to renew the token by itself).
"""
import asyncio
import binascii
import gzip
import hashlib
import json
import logging
import re
import secrets
import string
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from app.database.db import Database
from app.services.khpay import KhpayError, PaymentStatus, QrPayment, cents_to_amount
from app.services.payway import qr_data_uri

log = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api-bakong.nbc.gov.kh"
TOKEN_SETTING = "bakong_token"
QR_LIFETIME_SECONDS = 180
USER_AGENT = "diamond-zs-bot/1.0"


# ------------------------------------------------------------- logo on the QR
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
LOGO_SHARE = 0.20          # logo width as a share of the QR width (keep it small)


def _put_logo(img):
    """Put the shop logo, on a white square, in the middle of a QR image (PIL)."""
    from PIL import Image
    img = img.convert("RGBA")
    side = int(img.width * LOGO_SHARE)
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo.thumbnail((side, side), Image.LANCZOS)
    pad = max(6, side // 10)
    plate = Image.new("RGBA", (logo.width + 2 * pad, logo.height + 2 * pad), "white")
    plate.alpha_composite(logo, (pad, pad))
    img.paste(plate, ((img.width - plate.width) // 2, (img.height - plate.height) // 2))
    return img.convert("RGB")


def qr_data_uri_with_logo(text: str) -> str:
    """Same kind of 'data:image/png;base64,...' string as qr_data_uri, with the logo.
    Uses the highest error correction (H) so the bank apps can still read it."""
    import base64
    import io
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                       box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    # Big picture (about 1200 px wide) so the logo stays sharp when the customer zooms in.
    qr.box_size = max(10, 1200 // (qr.modules_count + 2 * qr.border))
    img = _put_logo(qr.make_image(fill_color="black", back_color="white").get_image())
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def make_qr_image(text: str) -> str:
    """QR with the logo when the logo file exists; if anything goes wrong, the plain
    QR is used instead, so a logo problem can never stop a deposit."""
    if LOGO_PATH.is_file():
        try:
            return qr_data_uri_with_logo(text)
        except Exception:
            log.exception("[Bakong] QR with logo failed - using the plain QR")
    return qr_data_uri(text)


# ----------------------------------------------------------------- KHQR text


def tlv(tag: str, value: str) -> str:
    """One EMV field: 2-digit tag + 2-digit length (in bytes) + value."""
    size = len(value.encode("utf-8"))
    if size > 99:
        raise ValueError(f"KHQR field {tag} is too long")
    return f"{tag}{size:02d}{value}"


def crc16(text: str) -> str:
    """CRC-16/CCITT-FALSE (init 0xFFFF, poly 0x1021), as 4 upper-case hex digits."""
    return f"{binascii.crc_hqx(text.encode('utf-8'), 0xFFFF):04X}"


def build_khqr(account_id: str, merchant_name: str, merchant_city: str, amount_cents: int,
               bill_number: str, created_ms: int, expires_ms: int) -> str:
    """Dynamic KHQR for an individual Bakong account, in USD, with an expiry time."""
    body = "".join([
        tlv("00", "01"),                                   # payload format
        tlv("01", "12"),                                   # dynamic QR (has an amount)
        tlv("29", tlv("00", account_id)),                  # Bakong account (individual)
        tlv("52", "5999"),                                 # merchant category
        tlv("53", "840"),                                  # USD
        tlv("54", cents_to_amount(amount_cents)),          # amount, e.g. 5.00
        tlv("58", "KH"),
        tlv("59", merchant_name),
        tlv("60", merchant_city),
        tlv("62", tlv("01", bill_number)),                 # bill number (makes every QR unique)
        tlv("99", tlv("00", str(created_ms)) + tlv("01", str(expires_ms))),
    ]) + "6304"
    return body + crc16(body)


def parse_khqr(text: str) -> dict:
    """Top-level fields of a KHQR / EMV string (byte-length aware). Used for checks."""
    raw, out, i = text.encode("utf-8"), {}, 0
    while i + 4 <= len(raw):
        tag, length = raw[i:i + 2].decode(), raw[i + 2:i + 4].decode()
        if not length.isdigit():
            break
        n = int(length)
        out[tag] = raw[i + 4:i + 4 + n].decode("utf-8", "replace")
        i += 4 + n
    return out


def verify_khqr(text: str) -> bool:
    return len(text) > 8 and text[-8:-4] == "6304" and crc16(text[:-4]) == text[-4:]


def clean_ref(value: str, limit: int = 25) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value)[:limit]


# ---------------------------------------------------------------- the client


def _to_cents(value) -> Optional[int]:
    try:
        cents = Decimal(str(value)) * 100
    except (InvalidOperation, ValueError):
        return None
    return int(cents) if cents == cents.to_integral_value() else None


class BakongClient:
    def __init__(self, db: Database, account_id: str, merchant_name: str, merchant_city: str,
                 token: str, email: str = "", api_url: str = ""):
        self._db = db
        self.account_id = (account_id or "").strip()
        self.merchant_name = (merchant_name or "Diamond ZS").strip()[:25]
        self.merchant_city = (merchant_city or "Phnom Penh").strip()[:15]
        self._token = (token or "").strip()
        self._email = (email or "").strip()
        self._api = (api_url or DEFAULT_API_URL).rstrip("/")
        self._renew_lock = asyncio.Lock()
        self._last_check: dict = {}

    @property
    def link(self) -> str:                     # so shared admin code can show something
        return f"Bakong ({self.account_id})"

    def set_token(self, token: str) -> None:
        self._token = (token or "").strip()

    # ---- low level -----------------------------------------------------------

    def _http_sync(self, url: str, headers: dict, body: dict, timeout: int) -> tuple:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers,
                                     method="POST")

        def decode(raw: bytes, resp_headers) -> str:
            if (resp_headers.get("Content-Encoding") or "").lower() == "gzip":
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
            raise KhpayError(f"Bakong unreachable: {type(exc).__name__}") from None

    async def _http(self, url: str, headers: dict, body: dict, timeout: int = 10) -> tuple:
        return await asyncio.to_thread(self._http_sync, url, headers, body, timeout)

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "Accept": "application/json",
                "Accept-Encoding": "gzip", "User-Agent": USER_AGENT,
                "Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _json(text: str) -> dict:
        try:
            data = json.loads(text or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _looks_like_token_problem(status: int, data: dict) -> bool:
        message = str(data.get("responseMessage") or "").lower()
        return status == 401 or "token" in message or "unauthor" in message

    async def _renew_token(self) -> bool:
        """Ask Bakong for a new token with the registered email. True if it worked."""
        if not self._email:
            return False
        async with self._renew_lock:
            status, text = await self._http(
                f"{self._api}/v1/renew_token",
                {"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
                {"email": self._email})
            data = self._json(text)
            token = (data.get("data") or {}).get("token") if isinstance(data.get("data"), dict) else None
            if status == 200 and data.get("responseCode") == 0 and token:
                self._token = str(token)
                await self._db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (TOKEN_SETTING, self._token))
                log.info("[Bakong] token renewed")
                return True
            log.warning("[Bakong] token renewal failed (HTTP %s): %s", status,
                        str(data.get("responseMessage") or "")[:120])
            return False

    async def _check_md5(self, md5: str) -> dict:
        """POST check_transaction_by_md5, renewing the token once if it has expired."""
        for attempt in (1, 2):
            status, text = await self._http(
                f"{self._api}/v1/check_transaction_by_md5", self._headers(), {"md5": md5}, 8)
            data = self._json(text)
            if self._looks_like_token_problem(status, data):
                if attempt == 1 and await self._renew_token():
                    continue
                raise KhpayError("Bakong token is missing, wrong or expired. Send a new one "
                                 "with /bakong_token", code="token", http_status=status)
            if status == 403:
                raise KhpayError("Bakong refused this server (HTTP 403)", code="403",
                                 http_status=403)
            if status == 429:
                raise KhpayError("Bakong is busy (429)", code="429", http_status=429)
            if status >= 500 or not data:
                raise KhpayError(f"Bakong error (HTTP {status})", http_status=status)
            return data
        raise KhpayError("Bakong token problem")

    # ---- API used by the bot (same as the other clients) ----------------------

    async def generate_qr(self, amount_cents: int, note: str, metadata: dict,
                          idempotency_key: str) -> QrPayment:
        if not self.account_id:
            raise KhpayError("No Bakong account is set (BAKONG_ACCOUNT_ID)")
        deposit = clean_ref(str((metadata or {}).get("deposit_id") or ""), 12)
        bill = clean_ref("DZS" + deposit + secrets.choice(string.ascii_uppercase) +
                         str(secrets.randbelow(10000)))
        created = int(time.time() * 1000)
        try:
            qr = build_khqr(self.account_id, self.merchant_name, self.merchant_city,
                            amount_cents, bill, created, created + QR_LIFETIME_SECONDS * 1000)
        except ValueError as exc:
            raise KhpayError(f"Cannot build the KHQR: {exc}") from None
        tags = parse_khqr(qr)
        if tags.get("54") != cents_to_amount(amount_cents) or not verify_khqr(qr):
            raise KhpayError("The generated KHQR failed its own check")   # never show a bad QR
        image = await asyncio.to_thread(make_qr_image, qr)
        md5 = hashlib.md5(qr.encode("utf-8")).hexdigest()
        log.info("[Bakong] QR for %s ($%s) md5 %s", note, cents_to_amount(amount_cents), md5)
        return QrPayment(transaction_id=md5, qr_image=image, qr_string=qr, payment_url="",
                         expires_in=QR_LIFETIME_SECONDS)

    async def check(self, transaction_id: str) -> PaymentStatus:
        """Paid ONLY when Bakong returns a transaction for this MD5."""
        cached = self._last_check.get(transaction_id)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]
        data = await self._check_md5(transaction_id)
        info = data.get("data") if isinstance(data.get("data"), dict) else None
        if data.get("responseCode") == 0 and info:
            to_account = str(info.get("toAccountId") or "")
            if to_account and to_account.lower() != self.account_id.lower():
                raise KhpayError(f"Bakong says the money went to {to_account}, not to us")
            result = PaymentStatus(
                transaction_id, True, "paid", "approved",
                _to_cents(info.get("amount")), str(info.get("currency") or "").upper())
        elif data.get("responseCode") == 1:        # "transaction could not be found" = not paid yet
            result = PaymentStatus(transaction_id, False, "pending", "request_qr", None, "")
        else:
            raise KhpayError(str(data.get("responseMessage") or "Bakong gave an unclear answer"))
        self._last_check[transaction_id] = (time.monotonic(), result)
        if len(self._last_check) > 500:
            self._last_check.clear()
        return result

    async def expire(self, transaction_id: str) -> None:
        """The QR carries its own expiry time; nothing to tell Bakong."""
        return None

    # ---- diagnostics for admins ------------------------------------------------

    async def self_test(self) -> str:
        """Check the token and the connection (asks about a made-up payment: 'not found' = OK)."""
        if not self.account_id:
            raise KhpayError("No Bakong account is set (BAKONG_ACCOUNT_ID)")
        await self._check_md5("0" * 32)
        return f"{self.merchant_name} ({self.account_id})"
