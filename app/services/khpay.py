"""Small client for the KHPAY REST API (https://khpay.site/api/v1).

Uses only the Python standard library (urllib in a worker thread), so it needs
no extra packages. The API key is sent ONLY in the Authorization header and is
never logged or placed in a request body.
"""
import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

log = logging.getLogger(__name__)


class KhpayError(Exception):
    """The gateway refused or could not be reached."""

    def __init__(self, message: str, code: str = "", http_status: int = 0):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class QrPayment:
    transaction_id: str
    qr_image: str          # "data:image/png;base64,...."
    qr_string: str
    payment_url: str
    expires_in: int        # seconds


@dataclass(frozen=True)
class PaymentStatus:
    transaction_id: str
    paid: bool
    status: str            # pending | paid | expired | failed
    action: str            # request_qr | scanned | approved
    amount_cents: Optional[int]
    currency: str


def cents_to_amount(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def amount_to_cents(value) -> Optional[int]:
    """'5.00' / 5 / 5.0 -> 500. Returns None if it is not a clean 2-decimal amount."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    cents = d * 100
    if cents != cents.to_integral_value():
        return None
    return int(cents)


class KhpayClient:
    def __init__(self, api_key: str, base_url: str = "https://khpay.site/api/v1",
                 test_mode: bool = False, timeout: int = 15):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._test_mode = test_mode
        self._timeout = timeout

    # ---- low level -----------------------------------------------------------

    def _request_sync(self, method: str, path: str, body: Optional[dict],
                      idempotency_key: Optional[str]) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": "diamond-zs-bot/1.0",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if self._test_mode:
            headers["X-Test-Mode"] = "true"
        req = urllib.request.Request(
            self._base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KhpayError(f"gateway unreachable: {type(exc).__name__}") from None
        try:
            payload = json.loads(raw.decode() or "{}")
        except ValueError:
            raise KhpayError("gateway returned invalid JSON", http_status=status) from None
        if status >= 400 or not payload.get("success", False):
            raise KhpayError(
                str(payload.get("error") or "gateway error"),
                code=str(payload.get("error_code") or payload.get("code") or ""),
                http_status=status,
            )
        data_part = payload.get("data")
        return data_part if isinstance(data_part, dict) else {}

    async def _request(self, method: str, path: str, body: Optional[dict] = None,
                       idempotency_key: Optional[str] = None) -> dict:
        return await asyncio.to_thread(
            self._request_sync, method, path, body, idempotency_key
        )

    # ---- API calls -----------------------------------------------------------

    async def generate_qr(self, amount_cents: int, note: str, metadata: dict,
                          idempotency_key: str) -> QrPayment:
        data = await self._request(
            "POST", "/qr/generate",
            {
                "amount": cents_to_amount(amount_cents),
                "currency": "USD",
                "note": note,
                "metadata": metadata,
            },
            idempotency_key=idempotency_key,
        )
        txn = str(data.get("transaction_id") or "")
        if not txn:
            raise KhpayError("gateway did not return a transaction id")
        # Never trust the gateway to have quietly changed the amount.
        returned = amount_to_cents(data.get("amount", cents_to_amount(amount_cents)))
        if returned != amount_cents:
            raise KhpayError("gateway returned a different amount")
        try:
            expires_in = int(data.get("expires_in") or 180)
        except (TypeError, ValueError):
            expires_in = 180
        return QrPayment(
            transaction_id=txn,
            qr_image=str(data.get("qr_image") or ""),
            qr_string=str(data.get("qr_string") or ""),
            payment_url=str(data.get("payment_url") or ""),
            expires_in=max(30, min(expires_in, 900)),
        )

    async def check(self, transaction_id: str) -> PaymentStatus:
        data = await self._request("GET", f"/qr/check/{transaction_id}")
        status = str(data.get("status") or "").lower()
        action = str(data.get("action") or "").lower()
        # KHPAY guide section 7: mark paid only when `paid` is true or action is approved.
        paid = data.get("paid") is True or action == "approved"
        return PaymentStatus(
            transaction_id=transaction_id,
            paid=paid,
            status="paid" if paid else status,
            action=action,
            amount_cents=amount_to_cents(data.get("amount")) if data.get("amount") is not None else None,
            currency=str(data.get("currency") or "").upper(),
        )

    async def expire(self, transaction_id: str) -> None:
        try:
            await self._request("POST", f"/qr/expire/{transaction_id}")
        except KhpayError:
            log.info("Could not expire gateway transaction %s (ignored)", transaction_id)

    async def account_info(self) -> dict:
        return await self._request("GET", "/me")
