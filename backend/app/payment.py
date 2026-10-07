import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

load_dotenv()


@dataclass
class PaymentSession:
    reference: str
    checkout_url: str | None
    raw: dict


def _payment_return_url(base_url: str, order_id: str, *, cancelled: bool = False) -> str:
    """Attach an order-scoped return marker without discarding configured URL state."""

    parts = urlsplit(base_url)
    managed_keys = {
        "paymentreturn",
        "payment_return",
        "order",
        "orderid",
        "order_id",
        "clientreference",
        "client_reference",
        "cancel",
        "cancelled",
        "canceled",
        "paymentcancelled",
        "payment_cancelled",
    }
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in managed_keys
    ]
    query.extend((("paymentReturn", "1"), ("orderId", order_id)))
    if cancelled:
        query.append(("paymentCancelled", "1"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class HubtelPaymentAdapter:
    """Boundary for Hubtel checkout, status, refund and webhook signing."""

    def __init__(self):
        self.base_url = os.getenv("HUBTEL_PAY_BASE_URL", "https://payproxyapi.hubtel.com")
        self.txn_status_base_url = os.getenv("HUBTEL_TXN_STATUS_BASE_URL", "https://api-txnstatus.hubtel.com")
        self.refund_base_url = os.getenv("HUBTEL_REFUND_BASE_URL", "https://refund-api.hubtel.com")
        self.callback_url = os.getenv("HUBTEL_CALLBACK_URL", "http://localhost:8000/api/v1/callback/payNotify")
        self.account_number = os.getenv("HUBTEL_ACCOUNT_NUMBER", "2030491")
        self.api_id = os.getenv("HUBTEL_API_ID", "")
        self.api_key = os.getenv("HUBTEL_API_KEY", "")
        self.return_url = os.getenv("HUBTEL_RETURN_URL", "http://localhost:4173/")
        self.cancellation_url = os.getenv("HUBTEL_CANCELLATION_URL", "http://localhost:4173/")
        self.refund_callback_url = os.getenv(
            "HUBTEL_REFUND_CALLBACK_URL",
            "http://localhost:8000/api/v1/callback/refundNotify",
        )

    @property
    def configured(self):
        return bool(self.api_id and self.api_key)

    async def create_session(self, order_id: str, amount: Decimal, currency: str, description: str) -> PaymentSession:
        if not self.configured:
            raise RuntimeError("Hubtel payment is not configured. Set HUBTEL_API_ID and HUBTEL_API_KEY.")
        payload = {
            "totalAmount": f"{amount:.2f}",
            "description": description,
            "callbackUrl": self.callback_url,
            "returnUrl": _payment_return_url(self.return_url, order_id),
            "merchantAccountNumber": self.account_number,
            "cancellationUrl": _payment_return_url(self.cancellation_url, order_id, cancelled=True),
            "clientReference": order_id[:36],
        }
        token = base64.b64encode(f"{self.api_id}:{self.api_key}".encode()).decode()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.base_url}/items/initiate", json=payload, headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise RuntimeError("Hubtel returned an invalid payment response")
        if str(raw.get("responseCode", "")) != "0000":
            raise RuntimeError(raw.get("message", "Hubtel payment initiation failed"))
        data = raw.get("data") or {}
        reference = data.get("checkoutId")
        checkout_url = data.get("checkoutUrl") or data.get("checkout_url")
        if not reference or not checkout_url:
            raise RuntimeError("Hubtel payment response is missing checkout details")
        return PaymentSession(reference=str(reference), checkout_url=str(checkout_url), raw=data)

    async def verify_webhook(self, payload: bytes, signature: str | None) -> bool:
        """Verify an optional HMAC callback signature.

        Hubtel accounts that do not expose a signing secret can leave
        ``HUBTEL_WEBHOOK_SECRET`` unset; callback processing still requires a
        known checkout reference and validates the amount/idempotency.  When a
        secret is configured, a missing or mismatched signature is rejected.
        """

        secret = os.getenv("HUBTEL_WEBHOOK_SECRET", "").strip()
        if not secret:
            return True
        if not signature:
            return False
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        supplied = signature.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, supplied)

    async def transaction_status(self, client_reference: str) -> dict:
        if not self.configured:
            raise RuntimeError("Hubtel payment is not configured")
        token = base64.b64encode(f"{self.api_id}:{self.api_key}".encode()).decode()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.txn_status_base_url}/transactions/{self.account_number}/status", params={"clientReference": client_reference}, headers={"Authorization": f"Basic {token}"})
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise RuntimeError("Hubtel returned an invalid transaction status response")
        return raw

    async def refund(self, checkout_id: str) -> dict:
        if not self.configured:
            raise RuntimeError("Hubtel payment is not configured")
        token = base64.b64encode(f"{self.api_id}:{self.api_key}".encode()).decode()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.refund_base_url}/refund/{self.account_number}/order/{checkout_id}", json={"callbackUrl": self.refund_callback_url}, headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict) or str(raw.get("responseCode", "")) != "0000":
            raise RuntimeError("Hubtel refund request was rejected")
        return raw


# Backward-compatible name for local integrations created before the adapter
# was correctly labelled as Hubtel.
GalaCreditPaymentAdapter = HubtelPaymentAdapter
payment_provider = HubtelPaymentAdapter()
