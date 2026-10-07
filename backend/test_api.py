"""High-value API integration tests using an isolated SQLite database.

The application defaults to MySQL in normal operation. Tests replace that
engine before the FastAPI lifespan starts, so they can never read or mutate a
developer's local database.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Set these before importing app modules: database.py constructs its engine at
# import time, while auth.py/payment.py read several settings during import.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["APP_ENV"] = "testing"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-that-is-not-used-in-production"
os.environ["ADMIN_USERNAME"] = "test-admin"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SMS_RESEND_COOLDOWN_SECONDS"] = "0"
os.environ["SMS_MAX_SENDS_PER_HOUR"] = "100"
os.environ["SMS_EXPOSE_TEST_CODE"] = "true"
os.environ["RESERVE_STOCK_ON_ORDER_CREATE"] = "false"
os.environ["HUBTEL_API_ID"] = ""
os.environ["HUBTEL_API_KEY"] = ""
os.environ["HUBTEL_WEBHOOK_SECRET"] = ""

from app import database as database_module  # noqa: E402
from app import main as main_module  # noqa: E402
from app import payment as payment_module  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.payment import HubtelPaymentAdapter, PaymentSession, payment_provider  # noqa: E402
from app import sms as sms_module  # noqa: E402
from app.sms import clear_codes  # noqa: E402


@dataclass(slots=True)
class ApiContext:
    client: TestClient
    database_path: Path

    def row(self, query: str, parameters: tuple = ()) -> sqlite3.Row | None:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(query, parameters).fetchone()

    def scalar(self, query: str, parameters: tuple = ()):
        row = self.row(query, parameters)
        return None if row is None else row[0]


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run each test against a new database and a complete app lifespan."""

    database_path = tmp_path / "ebaphone-test.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    # get_db resolves database_module.SessionLocal at request time. The
    # lifespan imported engine/SessionLocal into main.py, so patch both names.
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    main_module._admin_login_failures.clear()
    main_module._admin_ip_failures.clear()
    clear_codes()

    with TestClient(main_module.app) as client:
        yield ApiContext(client=client, database_path=database_path)

    clear_codes()
    main_module._admin_login_failures.clear()
    main_module._admin_ip_failures.clear()
    asyncio.run(engine.dispose())


def _register(api: ApiContext, *, name: str, phone: str) -> tuple[dict[str, str], dict]:
    response = api.client.post(
        "/api/auth/register",
        json={
            "name": name,
            "phone": phone,
            "password": "customer-password",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def _admin_headers(
    api: ApiContext,
    *,
    username: str = "test-admin",
    password: str = "test-admin-password",
) -> dict[str, str]:
    response = api.client.post(
        "/api/admin/auth/login",
        json={"account": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_order(
    api: ApiContext,
    headers: dict[str, str],
    *,
    phone: str,
    sku_id: int = 1,
    store_id: int = 1,
    payment_plan: str = "deposit",
    quantity: int = 1,
) -> dict:
    response = api.client.post(
        "/api/orders",
        headers=headers,
        json={
            "sku_id": sku_id,
            "payment_plan": payment_plan,
            "quantity": quantity,
            "fulfillment_type": "pickup",
            "store_id": store_id,
            "customer_name": "API Test Customer",
            "customer_phone": phone,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _inventory(api: ApiContext, sku_id: int = 1, store_id: int = 1) -> tuple[int, int, int]:
    row = api.row(
        "SELECT available, locked, sold FROM inventories WHERE sku_id = ? AND store_id = ?",
        (sku_id, store_id),
    )
    assert row is not None
    return row["available"], row["locked"], row["sold"]


def test_lifespan_seeds_catalog_and_requires_fulfillment(api: ApiContext):
    health = api.client.get("/api/health/ready")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"

    catalog = api.client.get("/api/skus")
    assert catalog.status_code == 200
    assert len(catalog.json()) == 6
    assert {item["category"] for item in catalog.json()} == {"phones", "audio", "cases-accessories"}

    invalid = api.client.post(
        "/api/orders",
        json={
            "sku_id": 1,
            "payment_plan": "full",
            "customer_name": "Test Customer",
            "customer_phone": "0240000000",
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Choose pickup or shipping"

    availability = api.client.get("/api/skus/1/availability")
    assert availability.status_code == 200
    assert {row["estimated_delivery"] for row in availability.json()} == {
        "Timing confirmed after address review"
    }

    coverage = api.client.get("/api/delivery/coverage")
    assert coverage.status_code == 200
    assert coverage.json()["zones"] == ["Accra", "Tema", "Kumasi"]


def test_sms_login_is_single_use_and_tokens_are_role_scoped(api: ApiContext):
    send = api.client.post("/api/auth/sms/send", json={"phone": "0888888888"})
    assert send.status_code == 200
    assert send.json()["phone"] == "+233888888888"
    assert send.json()["test_code"] == "888888"

    verify = api.client.post(
        "/api/auth/sms/verify",
        json={"phone": "0888888888", "code": "888888", "name": "SMS Customer"},
    )
    assert verify.status_code == 200
    customer_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
    me = api.client.get("/api/auth/me", headers=customer_headers)
    assert me.status_code == 200
    assert me.json()["phone"] == "+233888888888"

    replay = api.client.post(
        "/api/auth/sms/verify",
        json={"phone": "0888888888", "code": "888888"},
    )
    assert replay.status_code == 401

    assert api.client.get("/api/orders").status_code == 401
    assert api.client.get("/api/admin/auth/me", headers=customer_headers).status_code == 403
    admin_headers = _admin_headers(api)
    assert api.client.get("/api/auth/me", headers=admin_headers).status_code == 403
    assert api.client.get("/api/orders", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_customer_orders_are_isolated(api: ApiContext):
    owner_headers, owner = _register(api, name="Order Owner", phone="0240000001")
    other_headers, _ = _register(api, name="Other Customer", phone="0240000002")
    order = _create_order(api, owner_headers, phone=owner["phone"])

    owner_orders = api.client.get("/api/orders", headers=owner_headers)
    assert owner_orders.status_code == 200
    assert [item["id"] for item in owner_orders.json()] == [order["id"]]

    other_orders = api.client.get("/api/orders", headers=other_headers)
    assert other_orders.status_code == 200
    assert other_orders.json() == []
    assert api.client.get(f"/api/orders/{order['id']}", headers=other_headers).status_code == 404
    assert api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=other_headers).status_code == 404
    assert api.client.post(f"/api/orders/{order['id']}/simulate-payment").status_code == 401
    assert api.client.post(f"/api/orders/{order['id']}/payment-session").status_code == 401
    assert api.client.get(f"/api/orders/{order['id']}/payment-status").status_code == 401
    assert api.client.post(f"/api/orders/{order['id']}/payment-session", headers=other_headers).status_code == 404
    assert _inventory(api) == (3, 0, 0)


def test_payment_and_completion_are_inventory_idempotent(api: ApiContext):
    customer_headers, user = _register(api, name="Completion Customer", phone="0240000003")
    order = _create_order(api, customer_headers, phone=user["phone"])
    admin_headers = _admin_headers(api)
    assert _inventory(api) == (3, 0, 0)
    unpaid_settlement = api.client.post(
        f"/api/orders/{order['id']}/settle",
        headers=admin_headers,
        json={"payment_method": "cash"},
    )
    assert unpaid_settlement.status_code == 409

    first_payment = api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers)
    assert first_payment.status_code == 200
    assert first_payment.json()["stock_reserved"] is True
    assert _inventory(api) == (2, 1, 0)

    second_payment = api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers)
    assert second_payment.status_code == 200
    assert _inventory(api) == (2, 1, 0)
    assert api.scalar("SELECT COUNT(*) FROM payments WHERE order_id = ?", (order["id"],)) == 1

    unpaid_complete = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"note": "Balance not collected"},
    )
    assert unpaid_complete.status_code == 409
    assert "balance" in unpaid_complete.json()["detail"].lower()
    assert api.client.post(
        f"/api/orders/{order['id']}/settle",
        headers=customer_headers,
        json={"payment_method": "cash"},
    ).status_code == 403
    wrong_amount = api.client.post(
        f"/api/orders/{order['id']}/settle",
        headers=admin_headers,
        json={"amount": "1.00", "payment_method": "cash"},
    )
    assert wrong_amount.status_code == 400
    settled = api.client.post(
        f"/api/orders/{order['id']}/settle",
        headers=admin_headers,
        json={"payment_method": "cash", "reference": "SETTLE-1", "note": "Collected by customer"},
    )
    assert settled.status_code == 200
    assert settled.json()["payment_status"] == "paid"
    assert float(settled.json()["balance_due"]) == 0
    duplicate_settlement = api.client.post(
        f"/api/orders/{order['id']}/settle",
        headers=admin_headers,
        json={"payment_method": "cash", "reference": "SETTLE-1"},
    )
    assert duplicate_settlement.status_code == 200
    assert api.scalar(
        "SELECT COUNT(*) FROM payments WHERE order_id = ? AND purpose = 'settlement'",
        (order["id"],),
    ) == 1
    missing_pickup_code = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"note": "No code provided"},
    )
    assert missing_pickup_code.status_code == 409
    assert "pickup code" in missing_pickup_code.json()["detail"].lower()
    wrong_pickup_code = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"pickup_code": "WRONG1"},
    )
    assert wrong_pickup_code.status_code == 409
    assert "does not match" in wrong_pickup_code.json()["detail"].lower()
    first_complete = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"pickup_code": order["pickup_code"], "note": "Collected by customer"},
    )
    assert first_complete.status_code == 200
    assert first_complete.json()["order_status"] == "completed"
    assert _inventory(api) == (2, 0, 1)

    second_complete = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"pickup_code": order["pickup_code"], "note": "Duplicate request"},
    )
    assert second_complete.status_code == 200
    assert _inventory(api) == (2, 0, 1)


def test_cancel_and_release_restore_inventory_only_once(api: ApiContext):
    customer_headers, user = _register(api, name="Cancellation Customer", phone="0240000004")
    cancelled_order = _create_order(api, customer_headers, phone=user["phone"])
    assert api.client.post(
        f"/api/orders/{cancelled_order['id']}/simulate-payment",
        headers=customer_headers,
    ).status_code == 200
    assert _inventory(api) == (2, 1, 0)

    cancelled = api.client.post(
        f"/api/orders/{cancelled_order['id']}/cancel",
        headers=customer_headers,
        json={"reason": "Changed my mind"},
    )
    assert cancelled.status_code == 409
    assert "refund" in cancelled.json()["detail"].lower()
    assert _inventory(api) == (2, 1, 0)

    duplicate_cancel = api.client.post(
        f"/api/orders/{cancelled_order['id']}/cancel",
        headers=customer_headers,
        json={"reason": "Duplicate cancellation"},
    )
    assert duplicate_cancel.status_code == 409
    assert _inventory(api) == (2, 1, 0)

    admin_headers = _admin_headers(api)
    released_paid_order = api.client.post(
        f"/api/orders/{cancelled_order['id']}/release",
        headers=admin_headers,
        json={"reason": "Unable to fulfil"},
    )
    assert released_paid_order.status_code == 409
    assert "refunded" in released_paid_order.json()["detail"].lower()
    assert _inventory(api) == (2, 1, 0)

    unpaid_order = _create_order(api, customer_headers, phone=user["phone"], sku_id=2)
    cancelled_unpaid = api.client.post(
        f"/api/orders/{unpaid_order['id']}/cancel",
        headers=customer_headers,
        json={"reason": "Ordered the wrong model"},
    )
    assert cancelled_unpaid.status_code == 200
    assert cancelled_unpaid.json()["order_status"] == "cancelled"


def test_hubtel_session_uses_order_scoped_return_urls(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "responseCode": "0000",
                "data": {
                    "checkoutId": "CHECKOUT-RETURN-1",
                    "checkoutUrl": "https://pay.example.test/checkout/1",
                },
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["request"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(payment_module.httpx, "AsyncClient", FakeAsyncClient)
    adapter = HubtelPaymentAdapter()
    adapter.api_id = "test-api-id"
    adapter.api_key = "test-api-key"
    adapter.return_url = "https://shop.example.test/?campaign=launch&status=merchant-active&orderId=stale#receipt"
    adapter.cancellation_url = "https://shop.example.test/cancel?campaign=launch&status=merchant-active&cancel=0#receipt"

    order_id = "EBA-260828120000-ABCD1234"
    session = asyncio.run(adapter.create_session(order_id, Decimal("125.50"), "GHS", "Test phone"))

    assert session.reference == "CHECKOUT-RETURN-1"
    payload = captured["request"]["json"]
    success_url = urlsplit(payload["returnUrl"])
    success_query = parse_qs(success_url.query)
    assert success_query == {
        "campaign": ["launch"],
        "status": ["merchant-active"],
        "paymentReturn": ["1"],
        "orderId": [order_id],
    }
    assert success_url.fragment == "receipt"

    cancellation_url = urlsplit(payload["cancellationUrl"])
    cancellation_query = parse_qs(cancellation_url.query)
    assert cancellation_query == {
        "campaign": ["launch"],
        "status": ["merchant-active"],
        "paymentReturn": ["1"],
        "orderId": [order_id],
        "paymentCancelled": ["1"],
    }
    assert cancellation_url.fragment == "receipt"
    assert payload["clientReference"] == order_id


def test_payment_callback_rejects_wrong_amount_and_is_idempotent(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    customer_headers, user = _register(api, name="Callback Customer", phone="0240000005")
    references: list[str] = []

    async def fake_create_session(order_id, amount, currency, description):
        reference = f"CHECKOUT-{len(references) + 1}"
        references.append(reference)
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)

    mismatch_order = _create_order(api, customer_headers, phone=user["phone"])
    mismatch_session = api.client.post(
        f"/api/orders/{mismatch_order['id']}/payment-session",
        headers=customer_headers,
    )
    assert mismatch_session.status_code == 200
    mismatch_reference = mismatch_session.json()["checkout_id"]
    mismatch = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": mismatch_reference, "Amount": "1.00"},
        },
    )
    assert mismatch.status_code == 200
    assert mismatch.json() == {"status": "rejected", "reason": "amount_mismatch"}
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", (mismatch_reference,)) == "amount_mismatch"
    assert _inventory(api) == (3, 0, 0)
    terminal_retry = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": mismatch_reference, "Amount": mismatch_order["deposit_amount"]},
        },
    )
    assert terminal_retry.status_code == 200
    assert terminal_retry.json()["status"] == "ignored"
    assert _inventory(api) == (3, 0, 0)

    paid_order = _create_order(api, customer_headers, phone=user["phone"])
    paid_session = api.client.post(
        f"/api/orders/{paid_order['id']}/payment-session",
        headers=customer_headers,
    )
    assert paid_session.status_code == 200
    paid_reference = paid_session.json()["checkout_id"]
    callback_payload = {
        "Status": "Success",
        "ResponseCode": "0000",
        "Data": {
            "CheckoutId": paid_reference,
            "Amount": paid_order["deposit_amount"],
            "Fee": "2.50",
            "CustomerPhoneNumber": user["phone"],
            "PaymentDetails": {"PaymentType": "mobile_money", "Channel": "mtn-gh"},
        },
    }
    first = api.client.post("/api/v1/callback/payNotify", json=callback_payload)
    assert first.status_code == 200
    assert first.json() == {"status": "success"}
    assert _inventory(api) == (2, 1, 0)

    duplicate = api.client.post("/api/v1/callback/payNotify", json=callback_payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["message"] == "Already processed"
    assert _inventory(api) == (2, 1, 0)
    assert api.scalar("SELECT COUNT(*) FROM payments WHERE order_id = ?", (paid_order["id"],)) == 1

    reference_only_order = _create_order(api, customer_headers, phone=user["phone"])
    reference_only_session = api.client.post(
        f"/api/orders/{reference_only_order['id']}/payment-session",
        headers=customer_headers,
    )
    assert reference_only_session.status_code == 200
    reference_only_callback = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {
                "ClientReference": reference_only_order["id"],
                "Amount": reference_only_order["deposit_amount"],
            },
        },
    )
    assert reference_only_callback.status_code == 200
    assert reference_only_callback.json() == {"status": "success"}
    assert api.scalar("SELECT payment_status FROM orders WHERE id = ?", (reference_only_order["id"],)) == "deposit_paid"


def test_admin_can_reconcile_a_lost_provider_callback(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    customer_headers, user = _register(api, name="Reconciliation Customer", phone="0240000093")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="RECONCILE-CHECKOUT", checkout_url="https://payments.test/reconcile", raw={})

    async def fake_transaction_status(client_reference):
        assert client_reference.startswith("EBA-")
        return {
            "responseCode": "0000",
            "data": {
                "status": "Success",
                "amount": "3899.70",
                "currency": "GHS",
            },
        }

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full")
    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200

    # The fake amount intentionally matches the seeded iPhone 15 Pro deposit
    # only when the order uses the deposit plan; use the actual persisted
    # amount in the response to keep this test independent of price fixtures.
    with sqlite3.connect(api.database_path) as connection:
        amount = connection.execute("SELECT amount FROM payments WHERE order_id = ?", (order["id"],)).fetchone()[0]
    async def fake_transaction_status_with_actual_amount(client_reference):
        return {"ResponseCode": "0000", "Data": {"Status": "Success", "Amount": str(amount), "Currency": "GHS"}}
    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status_with_actual_amount)

    admin_headers = _admin_headers(api)
    reconciled = api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=admin_headers)
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "reconciled"
    assert reconciled.json()["order"]["payment_status"] == "paid"
    assert _inventory(api) == (2, 1, 0)

    duplicate = api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=admin_headers)
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "already_paid"
    assert api.scalar("SELECT COUNT(*) FROM payments WHERE order_id = ?", (order["id"],)) == 1


def test_amount_mismatch_reconciliation_requires_review_before_fulfilment(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """A provider re-check can recover a mismatched callback without taking stock."""

    customer_headers, user = _register(api, name="Mismatch Review Customer", phone="0240000021")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="MISMATCH-REVIEW", checkout_url="https://payments.test/mismatch-review", raw={})

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)
    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200
    mismatch = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": "MISMATCH-REVIEW", "Amount": "1.00", "Currency": "GHS"},
        },
    )
    assert mismatch.status_code == 200
    assert mismatch.json() == {"status": "rejected", "reason": "amount_mismatch"}
    assert api.scalar("SELECT payment_status FROM orders WHERE id = ?", (order["id"],)) == "pending"
    assert _inventory(api, store_id=1) == (3, 0, 0)

    async def fake_transaction_status(client_reference):
        assert client_reference == order["id"]
        return {
            "ResponseCode": "0000",
            "Data": {"Status": "Success", "Amount": str(order["total_amount"]), "Currency": "GHS"},
        }

    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status)
    admin_headers = _admin_headers(api)
    reconciled = api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=admin_headers)
    assert reconciled.status_code == 200, reconciled.text
    body = reconciled.json()
    assert body["status"] == "review_required"
    assert body["reason"] == "amount_validation"
    assert body["order"]["payment_status"] == "paid_pending_review"
    assert body["order"]["order_status"] == "payment_review"
    assert body["order"]["stock_reserved"] is False
    assert _inventory(api, store_id=1) == (3, 0, 0)

    # Both reconciliation and replacement-stock allocation are global-admin
    # operations; a store-scoped operator cannot move this financial hold.
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            """
            INSERT INTO admin_users
                (name, username, password_hash, role, store_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            ("Review Store Operator", "review-store-operator", hash_password("operator-password"), "operator", 1, 1),
        )
    operator_headers = _admin_headers(api, username="review-store-operator", password="operator-password")
    assert api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=operator_headers).status_code == 403
    assert api.client.post(
        f"/api/orders/{order['id']}/payment-review/fulfill",
        headers=operator_headers,
        json={"store_id": 2},
    ).status_code == 403

    fulfilled = api.client.post(
        f"/api/orders/{order['id']}/payment-review/fulfill",
        headers=admin_headers,
        json={"store_id": 2},
    )
    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()["status"] == "fulfilled"
    assert fulfilled.json()["order"]["payment_status"] == "paid"
    assert fulfilled.json()["order"]["order_status"] == "processing"
    assert _inventory(api, store_id=2) == (1, 1, 0)


def test_pending_reservations_expire_and_manual_release_is_idempotent(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    customer_headers, user = _register(api, name="Reservation Customer", phone="0240000008")
    sequence = 0

    async def fake_create_session(order_id, amount, currency, description):
        nonlocal sequence
        sequence += 1
        reference = f"RESERVATION-{sequence}"
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)

    expired_order = _create_order(api, customer_headers, phone=user["phone"])
    session = api.client.post(f"/api/orders/{expired_order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200
    assert _inventory(api) == (2, 1, 0)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", expired_order["id"]),
        )

    # Reading the customer's orders is a critical-path sweep in addition to
    # the lifespan background worker, making expiry deterministic here.
    refreshed = api.client.get("/api/orders", headers=customer_headers)
    assert refreshed.status_code == 200
    assert _inventory(api) == (3, 0, 0)
    assert api.scalar("SELECT status FROM payments WHERE order_id = ?", (expired_order["id"],)) == "expired"
    stored = api.row(
        "SELECT stock_reserved, reservation_expires_at, order_status FROM orders WHERE id = ?",
        (expired_order["id"],),
    )
    assert tuple(stored) == (0, None, "awaiting_payment")

    late_callback = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": session.json()["checkout_id"], "Amount": expired_order["deposit_amount"]},
        },
    )
    assert late_callback.status_code == 200
    assert late_callback.json() == {"status": "review_required", "reason": "reservation_expired"}
    assert _inventory(api) == (3, 0, 0)
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", (session.json()["checkout_id"],)) == "paid"
    assert api.scalar("SELECT payment_status FROM orders WHERE id = ?", (expired_order["id"],)) == "paid_pending_review"

    released_order = _create_order(api, customer_headers, phone=user["phone"])
    assert api.client.post(
        f"/api/orders/{released_order['id']}/payment-session",
        headers=customer_headers,
    ).status_code == 200
    assert _inventory(api) == (2, 1, 0)
    admin_headers = _admin_headers(api)
    for reason in ("Customer abandoned checkout", "Duplicate release"):
        released = api.client.post(
            f"/api/orders/{released_order['id']}/release",
            headers=admin_headers,
            json={"reason": reason},
        )
        assert released.status_code == 200
        assert released.json()["order_status"] == "released"
    assert _inventory(api) == (3, 0, 0)
    assert api.scalar("SELECT status FROM payments WHERE order_id = ?", (released_order["id"],)) == "cancelled"


def test_global_admin_can_fulfill_paid_review_at_another_store(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """A late, verified payment can be safely re-reserved at a chosen store."""

    customer_headers, user = _register(api, name="Payment Review Customer", phone="0240000018")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="REVIEW-FULFILL", checkout_url="https://payments.test/review", raw={})

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="deposit", store_id=1)
    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200, session.text
    assert _inventory(api, sku_id=1, store_id=1) == (2, 1, 0)

    # Force the reservation through the same expiry path used by the worker.
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200
    assert _inventory(api, sku_id=1, store_id=1) == (3, 0, 0)

    late_callback = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {
                "CheckoutId": "REVIEW-FULFILL",
                "Amount": order["deposit_amount"],
                "Currency": "GHS",
            },
        },
    )
    assert late_callback.status_code == 200
    assert late_callback.json() == {"status": "review_required", "reason": "reservation_expired"}

    admin_headers = _admin_headers(api)
    fulfilled = api.client.post(
        f"/api/orders/{order['id']}/payment-review/fulfill",
        headers=admin_headers,
        json={"store_id": 2, "note": "Customer approved alternate store"},
    )
    assert fulfilled.status_code == 200, fulfilled.text
    body = fulfilled.json()
    assert body["status"] == "fulfilled"
    assert body["order"]["payment_status"] == "deposit_paid"
    assert body["order"]["order_status"] == "awaiting_store_process"
    assert body["order"]["store_id"] == 2
    assert body["order"]["stock_reserved"] is True
    assert _inventory(api, sku_id=1, store_id=1) == (3, 0, 0)
    assert _inventory(api, sku_id=1, store_id=2) == (1, 1, 0)
    assert api.scalar(
        "SELECT action FROM audit_logs WHERE order_id = ? ORDER BY id DESC LIMIT 1",
        (order["id"],),
    ) == "payment_review_fulfilled"

    # Repeating the operator action is idempotent and cannot lock another unit.
    duplicate = api.client.post(
        f"/api/orders/{order['id']}/payment-review/fulfill",
        headers=admin_headers,
        json={"store_id": 2},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "already_resolved"
    assert _inventory(api, sku_id=1, store_id=2) == (1, 1, 0)


def test_paid_review_without_stock_stays_refundable(api: ApiContext, monkeypatch: pytest.MonkeyPatch):
    """No-stock review resolution must fail closed and preserve the review hold."""

    customer_headers, user = _register(api, name="No Stock Review Customer", phone="0240000019")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="REVIEW-NOSTOCK", checkout_url="https://payments.test/review-no-stock", raw={})

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)
    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200
    callback = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": "REVIEW-NOSTOCK", "Amount": order["deposit_amount"], "Currency": "GHS"},
        },
    )
    assert callback.status_code == 200
    # Empty every active store after the expired reservation has been
    # released, so the endpoint cannot pick a destination and must leave the
    # payment review state untouched.
    with sqlite3.connect(api.database_path) as connection:
        connection.execute("UPDATE inventories SET available = 0 WHERE sku_id = ?", (order["sku_id"],))
    admin_headers = _admin_headers(api)
    blocked = api.client.post(
        f"/api/orders/{order['id']}/payment-review/fulfill",
        headers=admin_headers,
        json={"store_id": 1},
    )
    assert blocked.status_code == 409
    assert "refund" in blocked.json()["detail"].lower()
    state = api.row(
        "SELECT payment_status, order_status, stock_reserved FROM orders WHERE id = ?",
        (order["id"],),
    )
    assert tuple(state) == ("paid_pending_review", "payment_review", 0)


def test_full_payment_review_can_request_provider_refund(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """A full late payment remains refundable even though it exceeds deposit_amount."""

    customer_headers, user = _register(api, name="Full Review Refund Customer", phone="0240000020")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="REVIEW-FULL-REFUND", checkout_url="https://payments.test/review-full", raw={})

    async def fake_refund(checkout_id):
        assert checkout_id == "REVIEW-FULL-REFUND"
        return {"responseCode": "0000"}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "refund", fake_refund)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)
    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200
    callback = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": "REVIEW-FULL-REFUND", "Amount": order["deposit_amount"], "Currency": "GHS"},
        },
    )
    assert callback.status_code == 200
    assert callback.json()["status"] == "review_required"
    assert float(order["deposit_amount"]) == float(order["total_amount"])

    refund = api.client.post(f"/api/orders/{order['id']}/refund", headers=_admin_headers(api))
    assert refund.status_code == 200, refund.text
    assert refund.json()["status"] == "refund_pending"
    assert api.scalar("SELECT payment_status FROM orders WHERE id = ?", (order["id"],)) == "refund_pending"


def test_refund_callback_releases_reserved_stock_once(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    customer_headers, user = _register(api, name="Refund Customer", phone="0240000006")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="REFUND-CHECKOUT", checkout_url="https://payments.test/refund", raw={})

    async def fake_refund(checkout_id):
        assert checkout_id == "REFUND-CHECKOUT"
        return {"responseCode": "0000"}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "refund", fake_refund)

    order = _create_order(api, customer_headers, phone=user["phone"])
    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200
    paid = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": "REFUND-CHECKOUT", "Amount": order["deposit_amount"]},
        },
    )
    assert paid.status_code == 200
    assert _inventory(api) == (2, 1, 0)

    refund = api.client.post(
        f"/api/orders/{order['id']}/refund",
        headers=_admin_headers(api),
    )
    assert refund.status_code == 200
    assert refund.json()["status"] == "refund_pending"
    assert api.scalar("SELECT payment_status FROM orders WHERE id = ?", (order["id"],)) == "refund_pending"

    callback_payload = {"responseCode": "0000", "Data": {"orderId": "REFUND-CHECKOUT"}}
    first_callback = api.client.post("/api/v1/callback/refundNotify", json=callback_payload)
    assert first_callback.status_code == 200
    assert first_callback.json() == {"status": "success"}
    assert _inventory(api) == (3, 0, 0)

    duplicate_callback = api.client.post("/api/v1/callback/refundNotify", json=callback_payload)
    assert duplicate_callback.status_code == 200
    assert duplicate_callback.json()["message"] == "Already processed"
    assert _inventory(api) == (3, 0, 0)
    stored_order = api.row(
        "SELECT payment_status, order_status, stock_reserved FROM orders WHERE id = ?",
        (order["id"],),
    )
    assert tuple(stored_order) == ("refunded", "cancelled", 0)


def test_store_operator_cannot_read_or_modify_another_store(api: ApiContext):
    customer_headers, user = _register(api, name="Scoped Order Customer", phone="0240000007")
    own_store_order = _create_order(api, customer_headers, phone=user["phone"], store_id=1)
    other_store_order = _create_order(api, customer_headers, phone=user["phone"], store_id=2)

    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            """
            INSERT INTO admin_users
                (name, username, password_hash, role, store_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                "Store One Operator",
                "store-one",
                hash_password("operator-password"),
                "operator",
                1,
                1,
            ),
        )

    operator_headers = _admin_headers(api, username="store-one", password="operator-password")
    visible = api.client.get("/api/orders", headers=operator_headers)
    assert visible.status_code == 200
    assert [order["id"] for order in visible.json()] == [own_store_order["id"]]
    assert api.client.get(f"/api/orders/{other_store_order['id']}", headers=operator_headers).status_code == 403
    forbidden_dispatch = api.client.post(
        f"/api/orders/{own_store_order['id']}/dispatch",
        headers=operator_headers,
        json={"store_id": 2},
    )
    assert forbidden_dispatch.status_code == 403

    forbidden_inventory = api.client.patch(
        "/api/admin/inventory",
        params={"sku_id": 1},
        headers=operator_headers,
        json={"store_id": 2, "available": 99},
    )
    assert forbidden_inventory.status_code == 403
    assert _inventory(api, store_id=2) == (2, 0, 0)

    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE inventories SET available = 0 WHERE sku_id = ? AND store_id = ?",
            (1, 2),
        )
    assert api.client.post(
        f"/api/orders/{own_store_order['id']}/simulate-payment",
        headers=customer_headers,
    ).status_code == 200
    unavailable_dispatch = api.client.post(
        f"/api/orders/{own_store_order['id']}/dispatch",
        headers=_admin_headers(api),
        json={"store_id": 2},
    )
    assert unavailable_dispatch.status_code == 409
    assert "available stock" in unavailable_dispatch.json()["detail"].lower()
    assert api.scalar("SELECT store_id FROM orders WHERE id = ?", (own_store_order["id"],)) == 1


def test_callback_signature_is_required_when_webhook_secret_is_configured(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    customer_headers, user = _register(api, name="Signed Callback Customer", phone="0240000009")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="SIGNED-CHECKOUT", checkout_url="https://payments.test/signed", raw={})

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    order = _create_order(api, customer_headers, phone=user["phone"])
    assert api.client.post(
        f"/api/orders/{order['id']}/payment-session",
        headers=customer_headers,
    ).status_code == 200
    monkeypatch.setenv("HUBTEL_WEBHOOK_SECRET", "test-webhook-secret")

    callback_payload = {
        "Status": "Success",
        "ResponseCode": "0000",
        "Data": {"CheckoutId": "SIGNED-CHECKOUT", "Amount": order["deposit_amount"]},
    }
    rejected = api.client.post(
        "/api/v1/callback/payNotify",
        headers={"X-Hubtel-Signature": "sha256=invalid"},
        json=callback_payload,
    )
    assert rejected.status_code == 401
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", ("SIGNED-CHECKOUT",)) == "pending"
    assert _inventory(api) == (2, 1, 0)

    raw_payload = json.dumps(callback_payload, separators=(",", ":")).encode()
    signature = hmac.new(b"test-webhook-secret", raw_payload, hashlib.sha256).hexdigest()
    accepted = api.client.post(
        "/api/v1/callback/payNotify",
        headers={"Content-Type": "application/json", "X-Hubtel-Signature": f"sha256={signature}"},
        content=raw_payload,
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "success"
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", ("SIGNED-CHECKOUT",)) == "paid"
    assert api.scalar("SELECT reservation_expires_at FROM orders WHERE id = ?", (order["id"],)) is None


def test_shipping_order_must_be_tracked_before_completion(api: ApiContext):
    customer_headers, user = _register(api, name="Shipping Customer", phone="0240000010")
    created = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={
            "sku_id": 1,
            "payment_plan": "full",
            "fulfillment_type": "shipping",
            "store_id": 1,
            "shipping_address": "12 Independence Avenue, Accra",
            "customer_name": "Shipping Customer",
            "customer_phone": user["phone"],
        },
    )
    assert created.status_code == 200
    order = created.json()
    assert order["delivery_zone"] == "Accra"
    assert api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers).status_code == 200
    admin_headers = _admin_headers(api)

    premature = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"note": "Not shipped yet"},
    )
    assert premature.status_code == 409
    assert "shipped" in premature.json()["detail"].lower()
    tracked = api.client.post(
        f"/api/orders/{order['id']}/tracking",
        headers=admin_headers,
        json={"tracking_number": "DHL-GH-1001"},
    )
    assert tracked.status_code == 200
    assert tracked.json()["order_status"] == "shipped"
    completed = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"note": "Delivered to customer"},
    )
    assert completed.status_code == 200
    assert completed.json()["order_status"] == "completed"
    assert _inventory(api) == (2, 0, 1)


def test_order_fulfillment_and_shipping_address_validation(api: ApiContext):
    customer_headers, user = _register(api, name="Address Validation Customer", phone="0240000012")
    base_payload = {
        "sku_id": 1,
        "fulfillment_type": "shipping",
        "store_id": 1,
        "customer_name": "Address Validation Customer",
        "customer_phone": user["phone"],
        "shipping_address": "12 Independence Avenue, Accra",
    }

    deposit_shipping = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={**base_payload, "payment_plan": "deposit"},
    )
    assert deposit_shipping.status_code == 400
    assert "pickup only" in deposit_shipping.json()["detail"].lower()

    short_address = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={**base_payload, "payment_plan": "full", "shipping_address": "Accra"},
    )
    assert short_address.status_code == 422
    assert any("shipping_address" in str(error.get("loc", ())) for error in short_address.json()["detail"])

    long_address = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={**base_payload, "payment_plan": "full", "shipping_address": "A" * 501},
    )
    assert long_address.status_code == 422
    assert any("shipping_address" in str(error.get("loc", ())) for error in long_address.json()["detail"])

    unsupported_address = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={**base_payload, "payment_plan": "full", "shipping_address": "18 Palm Road, Cape Coast"},
    )
    assert unsupported_address.status_code == 409
    assert "accra" in unsupported_address.json()["detail"].lower()


def test_expiry_never_releases_paid_inventory(api: ApiContext):
    customer_headers, user = _register(api, name="Paid Reservation Customer", phone="0240000011")
    order = _create_order(api, customer_headers, phone=user["phone"])
    paid = api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers)
    assert paid.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET stock_reserved = 1, reservation_expires_at = ?, payment_status = 'deposit_paid' WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    api.client.get("/api/orders", headers=customer_headers)
    stored = api.row(
        "SELECT stock_reserved, reservation_expires_at FROM orders WHERE id = ?",
        (order["id"],),
    )
    assert tuple(stored) == (1, None)
    assert _inventory(api) == (2, 1, 0)


def test_finalized_orders_cannot_be_dispatched(api: ApiContext):
    """Dispatch must never reopen a cancelled, released, or completed order."""

    customer_headers, user = _register(api, name="Finalized Order Customer", phone="0240000012")
    admin_headers = _admin_headers(api)

    cancelled = _create_order(api, customer_headers, phone=user["phone"], sku_id=1)
    cancelled_response = api.client.post(
        f"/api/orders/{cancelled['id']}/cancel",
        headers=customer_headers,
        json={"reason": "No longer needed"},
    )
    assert cancelled_response.status_code == 200
    assert cancelled_response.json()["order_status"] == "cancelled"

    released = _create_order(api, customer_headers, phone=user["phone"], sku_id=2)
    released_response = api.client.post(
        f"/api/orders/{released['id']}/release",
        headers=admin_headers,
        json={"reason": "Customer abandoned checkout"},
    )
    assert released_response.status_code == 200
    assert released_response.json()["order_status"] == "released"

    completed = _create_order(
        api,
        customer_headers,
        phone=user["phone"],
        sku_id=3,
        payment_plan="full",
    )
    paid = api.client.post(f"/api/orders/{completed['id']}/simulate-payment", headers=customer_headers)
    assert paid.status_code == 200
    completed_response = api.client.post(
        f"/api/orders/{completed['id']}/complete",
        headers=admin_headers,
        json={"pickup_code": completed["pickup_code"], "note": "Handed over"},
    )
    assert completed_response.status_code == 200
    assert completed_response.json()["order_status"] == "completed"

    for order in (cancelled, released, completed):
        rejected = api.client.post(
            f"/api/orders/{order['id']}/dispatch",
            headers=admin_headers,
            json={"store_id": 1},
        )
        assert rejected.status_code == 409
        assert "finalized" in rejected.json()["detail"].lower()


def test_unpaid_or_unreserved_orders_cannot_be_dispatched(api: ApiContext):
    """Store transfers require confirmed payment and a live reservation."""

    customer_headers, user = _register(api, name="Unpaid Dispatch Customer", phone="0240000014")
    admin_headers = _admin_headers(api)
    order = _create_order(api, customer_headers, phone=user["phone"], sku_id=1, store_id=1)
    before = _inventory(api, sku_id=1, store_id=2)

    rejected = api.client.post(
        f"/api/orders/{order['id']}/dispatch",
        headers=admin_headers,
        json={"store_id": 2},
    )
    assert rejected.status_code == 409
    assert "payment" in rejected.json()["detail"].lower()
    assert api.scalar("SELECT store_id FROM orders WHERE id = ?", (order["id"],)) == 1
    assert _inventory(api, sku_id=1, store_id=2) == before

    paid = api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers)
    assert paid.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute("UPDATE orders SET stock_reserved = 0, reservation_expires_at = NULL WHERE id = ?", (order["id"],))
    rejected_unreserved = api.client.post(
        f"/api/orders/{order['id']}/dispatch",
        headers=admin_headers,
        json={"store_id": 2},
    )
    assert rejected_unreserved.status_code == 409
    assert "reserved" in rejected_unreserved.json()["detail"].lower()


def test_order_quantity_scales_amounts_and_inventory_lifecycle(api: ApiContext):
    customer_headers, user = _register(api, name="Quantity Customer", phone="0240000015")
    admin_headers = _admin_headers(api)
    order = _create_order(api, customer_headers, phone=user["phone"], sku_id=1, store_id=1, payment_plan="full", quantity=2)
    assert order["quantity"] == 2
    assert float(order["unit_price"]) == 12999.0
    assert float(order["total_amount"]) == 25998.0
    assert float(order["deposit_amount"]) == 25998.0

    paid = api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers)
    assert paid.status_code == 200, paid.text
    assert _inventory(api, sku_id=1, store_id=1) == (1, 2, 0)
    completed = api.client.post(f"/api/orders/{order['id']}/complete", headers=admin_headers, json={"pickup_code": order["pickup_code"], "note": "Picked up"})
    assert completed.status_code == 200, completed.text
    assert _inventory(api, sku_id=1, store_id=1) == (1, 0, 2)


def test_quantity_dispatch_preserves_inventory_totals(api: ApiContext):
    customer_headers, user = _register(api, name="Quantity Dispatch Customer", phone="0240000017")
    admin_headers = _admin_headers(api)
    order = _create_order(api, customer_headers, phone=user["phone"], sku_id=1, store_id=1, payment_plan="full", quantity=2)
    assert api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers).status_code == 200
    assert _inventory(api, sku_id=1, store_id=1) == (1, 2, 0)
    assert _inventory(api, sku_id=1, store_id=2) == (2, 0, 0)
    moved = api.client.post(f"/api/orders/{order['id']}/dispatch", headers=admin_headers, json={"store_id": 2})
    assert moved.status_code == 200, moved.text
    assert _inventory(api, sku_id=1, store_id=1) == (3, 0, 0)
    assert _inventory(api, sku_id=1, store_id=2) == (0, 2, 0)


def test_refund_uses_older_paid_attempt_after_newer_failed_attempt(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """A failed retry must not mask the earlier Hubtel charge that needs refunding."""

    customer_headers, user = _register(api, name="Payment Attempt Refund Customer", phone="0240000022")
    references: list[str] = []

    async def fake_create_session(order_id, amount, currency, description):
        reference = f"ATTEMPT-REFUND-{len(references) + 1}"
        references.append(reference)
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    refunded: list[str] = []

    async def fake_refund(checkout_id):
        refunded.append(checkout_id)
        return {"responseCode": "0000"}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "refund", fake_refund)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)

    first = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert first.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200

    second = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert second.status_code == 200
    failed_retry = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Failed",
            "ResponseCode": "1001",
            "Data": {"CheckoutId": second.json()["checkout_id"]},
        },
    )
    assert failed_retry.status_code == 200
    assert failed_retry.json()["status"] == "ignored"

    late_success = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": first.json()["checkout_id"], "Amount": order["deposit_amount"], "Currency": "GHS"},
        },
    )
    assert late_success.status_code == 200
    assert late_success.json()["status"] == "review_required"

    refund = api.client.post(f"/api/orders/{order['id']}/refund", headers=_admin_headers(api))
    assert refund.status_code == 200, refund.text
    assert refund.json()["status"] == "refund_pending"
    assert refunded == [first.json()["checkout_id"]]


def test_reconcile_skips_newer_terminal_failed_attempt(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """A lost callback can still be reconciled after a later retry fails."""

    customer_headers, user = _register(api, name="Payment Attempt Reconcile Customer", phone="0240000023")
    references: list[str] = []

    async def fake_create_session(order_id, amount, currency, description):
        reference = f"ATTEMPT-RECONCILE-{len(references) + 1}"
        references.append(reference)
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    async def fake_transaction_status(client_reference):
        assert client_reference == order["id"]
        return {"ResponseCode": "0000", "Data": {"Status": "Success", "Amount": str(order["deposit_amount"]), "Currency": "GHS"}}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="deposit", store_id=1)

    first = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert first.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200

    second = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert second.status_code == 200
    failed_retry = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Failed",
            "ResponseCode": "1001",
            "Data": {"CheckoutId": second.json()["checkout_id"]},
        },
    )
    assert failed_retry.status_code == 200
    assert failed_retry.json()["status"] == "ignored"

    reconciled = api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=_admin_headers(api))
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "review_required"
    assert reconciled.json()["reason"] == "reservation_expired"
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", (first.json()["checkout_id"],)) == "paid"


def test_late_old_callback_preserves_new_reservation_until_reconciled(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """An old success cannot release a newer checkout's stock lock."""

    customer_headers, user = _register(api, name="Payment Reservation Owner Customer", phone="0240000024")
    references: list[str] = []
    refunded: list[str] = []

    async def fake_create_session(order_id, amount, currency, description):
        reference = f"OWNER-CHECKOUT-{len(references) + 1}"
        references.append(reference)
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    async def fake_refund(checkout_id):
        refunded.append(checkout_id)
        return {"responseCode": "0000"}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "refund", fake_refund)
    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)

    first = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert first.status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200

    second = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert second.status_code == 200
    assert _inventory(api, sku_id=1, store_id=1) == (2, 1, 0)

    late_success = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": first.json()["checkout_id"], "Amount": order["deposit_amount"], "Currency": "GHS"},
        },
    )
    assert late_success.status_code == 200
    assert late_success.json() == {"status": "review_required", "reason": "reservation_expired"}
    # The second checkout still owns the lock; the old callback did not return
    # its unit to available stock.
    assert _inventory(api, sku_id=1, store_id=1) == (2, 1, 0)
    state = api.row(
        "SELECT payment_status, order_status, stock_reserved, reservation_payment_id FROM orders WHERE id = ?",
        (order["id"],),
    )
    assert tuple(state) == ("paid_pending_review", "payment_review", 1, 2)

    blocked_refund = api.client.post(f"/api/orders/{order['id']}/refund", headers=_admin_headers(api))
    assert blocked_refund.status_code == 409
    assert "pending" in blocked_refund.json()["detail"].lower()

    async def fake_transaction_status(client_reference):
        assert client_reference == order["id"]
        return {"ResponseCode": "1001", "Data": {"Status": "Failed"}}

    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status)
    reconciled = api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=_admin_headers(api))
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "failed"
    assert _inventory(api, sku_id=1, store_id=1) == (3, 0, 0)
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", (second.json()["checkout_id"],)) == "failed"

    refund = api.client.post(f"/api/orders/{order['id']}/refund", headers=_admin_headers(api))
    assert refund.status_code == 200, refund.text
    assert refunded == [first.json()["checkout_id"]]


@pytest.mark.parametrize("unresolved_status", ["expired", "amount_mismatch", "currency_mismatch"])
def test_refund_stays_fail_closed_for_every_unresolved_payment_attempt(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
    unresolved_status: str,
):
    """A stale/invalid retry must be reconciled before an older charge is refunded."""

    status_index = ("expired", "amount_mismatch", "currency_mismatch").index(unresolved_status)
    customer_headers, user = _register(
        api,
        name=f"Unresolved Refund Customer {unresolved_status}",
        phone=f"02400000{25 + status_index:02d}",
    )
    references: list[str] = []

    async def fake_create_session(order_id, amount, currency, description):
        reference = f"UNRESOLVED-{unresolved_status.upper()}-{len(references) + 1}"
        references.append(reference)
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    refunded: list[str] = []

    async def fake_refund(checkout_id):
        refunded.append(checkout_id)
        return {"responseCode": "0000"}

    async def fake_transaction_status(client_reference):
        assert client_reference == order["id"]
        return {"ResponseCode": "1001", "Data": {"Status": "Failed"}}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "refund", fake_refund)
    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status)

    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)
    first = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert first.status_code == 200, first.text

    # Let the first checkout's local reservation expire, then record the
    # provider attempt as the earlier paid charge.  The order is temporarily
    # reopened only to create a second checkout attempt; this mirrors the
    # state produced by a late callback after a customer retries payment.
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200
    first_amount = api.scalar(
        "SELECT amount FROM payments WHERE provider_reference = ?",
        (first.json()["checkout_id"],),
    )
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE payments SET status = 'paid' WHERE provider_reference = ?",
            (first.json()["checkout_id"],),
        )
        connection.execute(
            """
            UPDATE orders
            SET payment_status = 'pending', order_status = 'awaiting_payment',
                paid_amount = ?, remaining_amount = 0,
                stock_reserved = 0, reservation_expires_at = NULL,
                reservation_payment_id = NULL
            WHERE id = ?
            """,
            (first_amount, order["id"]),
        )

    second = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert second.status_code == 200, second.text
    if unresolved_status == "expired":
        with sqlite3.connect(api.database_path) as connection:
            connection.execute(
                "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
                ("2000-01-01 00:00:00", order["id"]),
            )
        assert api.client.get("/api/orders", headers=customer_headers).status_code == 200
    else:
        with sqlite3.connect(api.database_path) as connection:
            connection.execute(
                "UPDATE payments SET status = ? WHERE provider_reference = ?",
                (unresolved_status, second.json()["checkout_id"]),
            )

    admin_headers = _admin_headers(api)
    blocked = api.client.post(f"/api/orders/{order['id']}/refund", headers=admin_headers)
    assert blocked.status_code == 409
    assert "reconcile" in blocked.json()["detail"].lower()

    reconciled = api.client.post(f"/api/orders/{order['id']}/payment-reconcile", headers=admin_headers)
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "failed"
    assert api.scalar(
        "SELECT status FROM payments WHERE provider_reference = ?",
        (second.json()["checkout_id"],),
    ) == "failed"
    assert _inventory(api, sku_id=1, store_id=1) == (3, 0, 0)

    refund = api.client.post(f"/api/orders/{order['id']}/refund", headers=admin_headers)
    assert refund.status_code == 200, refund.text
    assert refund.json()["status"] == "refund_pending"
    assert refunded == [first.json()["checkout_id"]]


@pytest.mark.parametrize("newer_status", ["failed", "expired"])
def test_payment_status_does_not_hide_older_paid_attempt(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
    newer_status: str,
):
    """A retry's terminal/stale row must not mask an earlier confirmed charge."""

    customer_headers, user = _register(
        api,
        name=f"Payment Status Customer {newer_status}",
        phone=f"02400000{28 + (0 if newer_status == 'failed' else 1):02d}",
    )
    references: list[str] = []
    lookups: list[str] = []

    async def fake_create_session(order_id, amount, currency, description):
        reference = f"STATUS-{newer_status.upper()}-{len(references) + 1}"
        references.append(reference)
        return PaymentSession(reference=reference, checkout_url=f"https://payments.test/{reference}", raw={})

    async def fake_transaction_status(client_reference):
        lookups.append(client_reference)
        return {"ResponseCode": "0000", "Data": {"Status": "Success"}}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "transaction_status", fake_transaction_status)

    order = _create_order(api, customer_headers, phone=user["phone"], payment_plan="full", store_id=1)
    first = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert first.status_code == 200, first.text

    # Expire the first reservation so a customer can start a retry, then
    # preserve the first provider row as the confirmed charge.
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE orders SET reservation_expires_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", order["id"]),
        )
    assert api.client.get("/api/orders", headers=customer_headers).status_code == 200
    second = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert second.status_code == 200, second.text
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE payments SET status = 'paid' WHERE provider_reference = ?",
            (first.json()["checkout_id"],),
        )
        connection.execute(
            "UPDATE payments SET status = ? WHERE provider_reference = ?",
            (newer_status, second.json()["checkout_id"]),
        )

    status = api.client.get(f"/api/orders/{order['id']}/payment-status", headers=customer_headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["local_status"] == "paid"
    assert body["remote"]["ResponseCode"] == "0000"
    assert lookups == [order["id"]]


def test_order_idempotency_key_includes_quantity(api: ApiContext):
    customer_headers, user = _register(api, name="Quantity Idempotency Customer", phone="0240000016")
    payload = {
        "sku_id": 1,
        "quantity": 2,
        "payment_plan": "deposit",
        "fulfillment_type": "pickup",
        "store_id": 1,
        "customer_name": "API Test Customer",
        "customer_phone": user["phone"],
    }
    first = api.client.post("/api/orders", headers={**customer_headers, "X-Idempotency-Key": "qty-key-1"}, json=payload)
    assert first.status_code == 200, first.text
    retry = api.client.post("/api/orders", headers={**customer_headers, "X-Idempotency-Key": "qty-key-1"}, json=payload)
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    payload["quantity"] = 1
    mismatch = api.client.post("/api/orders", headers={**customer_headers, "X-Idempotency-Key": "qty-key-1"}, json=payload)
    assert mismatch.status_code == 409


def test_refund_pending_blocks_fulfillment_and_failure_can_retry(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    """Refund callbacks may fail and later succeed, but fulfilment stays blocked meanwhile."""

    customer_headers, user = _register(api, name="Refund Retry Customer", phone="0240000013")

    async def fake_create_session(order_id, amount, currency, description):
        return PaymentSession(reference="REFUND-RETRY", checkout_url="https://payments.test/refund-retry", raw={})

    async def fake_refund(checkout_id):
        assert checkout_id == "REFUND-RETRY"
        return {"accepted": True}

    monkeypatch.setattr(payment_provider, "create_session", fake_create_session)
    monkeypatch.setattr(payment_provider, "refund", fake_refund)

    created = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={
            "sku_id": 1,
            "payment_plan": "deposit",
            "fulfillment_type": "pickup",
            "store_id": 1,
            "customer_name": "Refund Retry Customer",
            "customer_phone": user["phone"],
        },
    )
    assert created.status_code == 200, created.text
    order = created.json()

    session = api.client.post(f"/api/orders/{order['id']}/payment-session", headers=customer_headers)
    assert session.status_code == 200, session.text
    paid = api.client.post(
        "/api/v1/callback/payNotify",
        json={
            "Status": "Success",
            "ResponseCode": "0000",
            "Data": {"CheckoutId": "REFUND-RETRY", "Amount": order["deposit_amount"]},
        },
    )
    assert paid.status_code == 200, paid.text

    admin_headers = _admin_headers(api)
    refund = api.client.post(f"/api/orders/{order['id']}/refund", headers=admin_headers)
    assert refund.status_code == 200, refund.text
    assert refund.json()["status"] == "refund_pending"

    blocked_actions = (
        ("complete", {"note": "Should be blocked"}),
        ("settle", {"payment_method": "cash"}),
        ("tracking", {"tracking_number": "DHL-GH-REFUND"}),
        ("dispatch", {"store_id": 1}),
    )
    for action, payload in blocked_actions:
        response = api.client.post(
            f"/api/orders/{order['id']}/{action}",
            headers=admin_headers,
            json=payload,
        )
        assert response.status_code == 409
        assert "refund" in response.json()["detail"].lower()

    failed_callback = api.client.post(
        "/api/v1/callback/refundNotify",
        json={"responseCode": "1001", "Data": {"orderId": "REFUND-RETRY"}},
    )
    assert failed_callback.status_code == 200
    assert failed_callback.json() == {"status": "ignored"}
    failed_state = api.row(
        "SELECT payment_status, paid_amount, remaining_amount FROM orders WHERE id = ?",
        (order["id"],),
    )
    assert failed_state is not None
    assert failed_state["payment_status"] == "deposit_paid"
    assert float(failed_state["paid_amount"]) == float(order["deposit_amount"])
    assert float(failed_state["remaining_amount"]) == float(order["unit_price"]) - float(order["deposit_amount"])
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", ("REFUND-RETRY",)) == "refund_failed"

    success_callback = api.client.post(
        "/api/v1/callback/refundNotify",
        json={"responseCode": "0000", "Data": {"orderId": "REFUND-RETRY"}},
    )
    assert success_callback.status_code == 200
    assert success_callback.json() == {"status": "success"}
    refunded_state = api.row(
        "SELECT payment_status, order_status, paid_amount, remaining_amount, stock_reserved FROM orders WHERE id = ?",
        (order["id"],),
    )
    assert refunded_state is not None
    assert tuple(refunded_state) == ("refunded", "cancelled", 0, 0, 0)
    assert api.scalar("SELECT status FROM payments WHERE provider_reference = ?", ("REFUND-RETRY",)) == "refunded"
    assert _inventory(api) == (3, 0, 0)


def test_sms_rejects_unicode_input_and_locks_after_failed_attempt_limit(api: ApiContext):
    unicode_phone = "０２４１２３４５６７"
    malformed_phone = api.client.post("/api/auth/sms/send", json={"phone": unicode_phone})
    assert malformed_phone.status_code == 422
    mixed_phone = api.client.post("/api/auth/sms/send", json={"phone": "02412abc567"})
    assert mixed_phone.status_code == 422

    send = api.client.post("/api/auth/sms/send", json={"phone": "0888888888"})
    assert send.status_code == 200
    assert send.json()["test_code"] == "888888"

    unicode_code = api.client.post(
        "/api/auth/sms/verify",
        json={"phone": "0888888888", "code": "１２３４５６"},
    )
    assert unicode_code.status_code == 422

    for _ in range(sms_module.MAX_VERIFY_ATTEMPTS):
        wrong = api.client.post(
            "/api/auth/sms/verify",
            json={"phone": "0888888888", "code": "000000"},
        )
        assert wrong.status_code == 401

    correct_after_lockout = api.client.post(
        "/api/auth/sms/verify",
        json={"phone": "0888888888", "code": "888888"},
    )
    assert correct_after_lockout.status_code == 401


def test_sms_throttle_returns_machine_readable_retry_after(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
):
    async def throttled_send(phone, db):
        raise sms_module.SmsRateLimitError("Please wait before requesting another code", 17)

    monkeypatch.setattr(main_module, "send_code", throttled_send)
    response = api.client.post("/api/auth/sms/send", json={"phone": "0240000099"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json() == {
        "detail": "Please wait before requesting another code",
        "retry_after": 17,
    }


def test_production_startup_validation_requires_sms_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_module, "PRODUCTION", True)
    monkeypatch.setattr(main_module, "JWT_SECRET", "j" * 64)
    monkeypatch.setattr(main_module, "OTP_HASH_SECRET", "o" * 64)
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:4173")
    monkeypatch.setenv("HUBTEL_WEBHOOK_SECRET", "real-webhook-secret")
    monkeypatch.setenv("HUBTEL_ACCOUNT_NUMBER", "merchant-test-account")
    monkeypatch.setenv("HUBTEL_API_ID", "test-api-id")
    monkeypatch.setenv("HUBTEL_API_KEY", "test-api-key")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-production-password")
    monkeypatch.setenv("SMS_EXPOSE_TEST_CODE", "false")
    monkeypatch.delenv("SMS_PROVIDER_URL", raising=False)

    with pytest.raises(RuntimeError, match="SMS_PROVIDER_URL"):
        main_module._validate_runtime_config()

    monkeypatch.setenv("SMS_PROVIDER_URL", "https://sms.example.test/send")
    monkeypatch.delenv("SMS_EXPOSE_TEST_CODE", raising=False)
    with pytest.raises(RuntimeError, match="SMS_EXPOSE_TEST_CODE"):
        main_module._validate_runtime_config()

    monkeypatch.setenv("SMS_EXPOSE_TEST_CODE", "false")
    monkeypatch.delenv("HUBTEL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HUBTEL_API_KEY"):
        main_module._validate_runtime_config()


def test_seed_migrates_exact_legacy_banner_title(api: ApiContext):
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "INSERT INTO banners (title, subtitle, sort_order, active) VALUES (?, ?, ?, ?)",
            ("Your next iPhone, made affordable.", "Legacy copy", 99, 1),
        )

    async def rerun_seed():
        async with main_module.SessionLocal() as db:
            await main_module.seed(db)

    asyncio.run(rerun_seed())
    banners = api.client.get("/api/banners")
    assert banners.status_code == 200
    titles = {item["title"] for item in banners.json()}
    assert "Your next device, made affordable." in titles
    assert "Your next iPhone, made affordable." not in titles


def test_order_creation_idempotency_returns_original_and_rejects_reuse(api: ApiContext):
    customer_headers, user = _register(api, name="Idempotent Customer", phone="0240000015")
    request_headers = {**customer_headers, "X-Idempotency-Key": "order-key-001"}
    payload = {
        "sku_id": 1,
        "payment_plan": "deposit",
        "fulfillment_type": "pickup",
        "store_id": 1,
        "customer_name": "Idempotent Customer",
        "customer_phone": user["phone"],
    }
    first = api.client.post("/api/orders", headers=request_headers, json=payload)
    assert first.status_code == 200, first.text
    second = api.client.post("/api/orders", headers=request_headers, json=payload)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert api.scalar("SELECT COUNT(*) FROM orders WHERE idempotency_key = ?", ("order-key-001",)) == 1

    changed = {**payload, "sku_id": 2}
    conflicting = api.client.post("/api/orders", headers=request_headers, json=changed)
    assert conflicting.status_code == 409
    assert "idempotency" in conflicting.json()["detail"].lower()

    too_long = api.client.post(
        "/api/orders",
        headers={**customer_headers, "X-Idempotency-Key": "x" * 129},
        json=payload,
    )
    assert too_long.status_code == 400
    assert "idempotency" in too_long.json()["detail"].lower()


def test_order_creation_can_atomically_hold_inventory(monkeypatch: pytest.MonkeyPatch, api: ApiContext):
    monkeypatch.setattr(main_module, "RESERVE_STOCK_ON_ORDER_CREATE", True)
    customer_headers, user = _register(api, name="Inventory Hold Customer", phone="0240000016")

    first = _create_order(api, customer_headers, phone=user["phone"], sku_id=1, store_id=1)
    second = _create_order(api, customer_headers, phone=user["phone"], sku_id=1, store_id=1)
    third = _create_order(api, customer_headers, phone=user["phone"], sku_id=1, store_id=1)
    assert first["stock_reserved"] is True
    assert second["stock_reserved"] is True
    assert third["stock_reserved"] is True
    assert _inventory(api, sku_id=1, store_id=1) == (0, 3, 0)

    unavailable = api.client.post(
        "/api/orders",
        headers=customer_headers,
        json={
            "sku_id": 1,
            "payment_plan": "deposit",
            "fulfillment_type": "pickup",
            "store_id": 1,
            "customer_name": "Inventory Hold Customer",
            "customer_phone": user["phone"],
        },
    )
    assert unavailable.status_code == 409
    assert _inventory(api, sku_id=1, store_id=1) == (0, 3, 0)

    released = api.client.post(
        f"/api/orders/{first['id']}/cancel",
        headers=customer_headers,
        json={"reason": "Release held stock"},
    )
    assert released.status_code == 200
    assert _inventory(api, sku_id=1, store_id=1) == (1, 2, 0)


def test_sms_challenge_survives_memory_reset_and_stores_only_hash(api: ApiContext):
    send = api.client.post("/api/auth/sms/send", json={"phone": "0888888888"})
    assert send.status_code == 200
    row = api.row("SELECT code_hash FROM sms_challenges WHERE phone = ?", ("+233888888888",))
    assert row is not None
    assert "888888" not in row["code_hash"]

    # The fallback dictionary is intentionally cleared; verification must use
    # the persisted challenge row and therefore still succeed.
    clear_codes()
    verify = api.client.post(
        "/api/auth/sms/verify",
        json={"phone": "0888888888", "code": "888888", "name": "Persistent OTP Customer"},
    )
    assert verify.status_code == 200, verify.text
    assert api.scalar("SELECT code_hash FROM sms_challenges WHERE phone = ?", ("+233888888888",)) == ""


def test_global_admin_can_create_catalog_store_and_staff_with_scope_guards(api: ApiContext):
    admin_headers = _admin_headers(api)

    product = api.client.post(
        "/api/admin/skus",
        headers=admin_headers,
        json={
            "product_name": "USB-C Fast Charger",
            "brand": "EBAphone",
            "category": "Cases & Accessories",
            "variant": "30W Ghana plug",
            "price": "249.00",
            "deposit_rate": "100",
            "initial_stock": {"1": 4, "2": 2},
        },
    )
    assert product.status_code == 201, product.text
    product_body = product.json()
    assert product_body["category"] == "cases-accessories"
    assert int(product_body["store_stock"]["1"]) == 4
    assert int(product_body["store_stock"]["3"]) == 0
    duplicate = api.client.post(
        "/api/admin/skus",
        headers=admin_headers,
        json={
            "product_name": "usb-c fast charger",
            "brand": "EBAphone",
            "category": "cases-accessories",
            "variant": "30w ghana plug",
            "price": 249,
        },
    )
    assert duplicate.status_code == 409

    store = api.client.post(
        "/api/admin/stores",
        headers=admin_headers,
        json={
            "name": "Tema Community Store",
            "address": "Community 1, Tema",
            "phone": "0303 555 104",
            "open_hours": "Mon-Sat 09:00-18:00",
        },
    )
    assert store.status_code == 201, store.text
    store_id = store.json()["id"]
    assert api.scalar(
        "SELECT COUNT(*) FROM inventories WHERE store_id = ?",
        (store_id,),
    ) == api.scalar("SELECT COUNT(*) FROM skus")
    stock = api.client.patch(
        "/api/admin/inventory",
        params={"sku_id": product_body["id"]},
        headers=admin_headers,
        json={"store_id": store_id, "available": 3},
    )
    assert stock.status_code == 200, stock.text
    assert int(stock.json()["store_stock"][str(store_id)]) == 3

    missing_store = api.client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Unassigned Operator",
            "username": "unassigned",
            "password": "operator-password",
            "role": "operator",
        },
    )
    assert missing_store.status_code == 400
    staff = api.client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Tema Operator",
            "username": "TEMA-OPS",
            "password": "operator-password",
            "role": "operator",
            "store_id": store_id,
        },
    )
    assert staff.status_code == 201, staff.text
    staff_body = staff.json()
    assert staff_body["username"] == "tema-ops"
    assert "password" not in staff_body

    operator_headers = _admin_headers(api, username="tema-ops", password="operator-password")
    own_stores = api.client.get("/api/admin/stores", headers=operator_headers)
    assert own_stores.status_code == 200
    assert [item["id"] for item in own_stores.json()] == [store_id]
    assert api.client.get("/api/admin/users", headers=operator_headers).status_code == 403
    assert api.client.post(
        "/api/admin/skus",
        headers=operator_headers,
        json={
            "product_name": "Forbidden Product",
            "brand": "Test",
            "variant": "One",
            "price": 10,
        },
    ).status_code == 403

    self_deactivate = api.client.patch(
        "/api/admin/users/1",
        headers=admin_headers,
        json={"active": False},
    )
    assert self_deactivate.status_code == 409


def test_store_deactivation_requires_active_orders_to_be_resolved(api: ApiContext):
    admin_headers = _admin_headers(api)
    store = api.client.post(
        "/api/admin/stores",
        headers=admin_headers,
        json={
            "name": "Cape Coast Store",
            "address": "Cape Coast Central",
            "phone": "0332 555 105",
            "open_hours": "Mon-Sat 09:00-18:00",
        },
    ).json()
    stock = api.client.patch(
        "/api/admin/inventory",
        params={"sku_id": 1},
        headers=admin_headers,
        json={"store_id": store["id"], "available": 2},
    )
    assert stock.status_code == 200
    staff = api.client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Cape Coast Operator",
            "username": "cape-coast-ops",
            "password": "operator-password",
            "role": "operator",
            "store_id": store["id"],
        },
    )
    assert staff.status_code == 201, staff.text
    staff_login = api.client.post(
        "/api/admin/auth/login",
        json={"account": "cape-coast-ops", "password": "operator-password"},
    )
    assert staff_login.status_code == 200, staff_login.text
    staff_headers = {"Authorization": f"Bearer {staff_login.json()['access_token']}"}
    customer_headers, customer = _register(api, name="Cape Coast Customer", phone="0240000017")
    order = _create_order(
        api,
        customer_headers,
        phone=customer["phone"],
        sku_id=1,
        store_id=store["id"],
    )

    blocked = api.client.patch(
        f"/api/admin/stores/{store['id']}",
        headers=admin_headers,
        json={"active": False},
    )
    assert blocked.status_code == 409
    assert "active orders" in blocked.json()["detail"].lower()

    cancelled = api.client.post(
        f"/api/orders/{order['id']}/cancel",
        headers=customer_headers,
        json={"reason": "No longer needed"},
    )
    assert cancelled.status_code == 200
    deactivated = api.client.patch(
        f"/api/admin/stores/{store['id']}",
        headers=admin_headers,
        json={"active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["active"] is False
    assert all(item["id"] != store["id"] for item in api.client.get("/api/stores").json())
    assert api.client.get("/api/admin/auth/me", headers=staff_headers).status_code == 401
    blocked_staff_login = api.client.post(
        "/api/admin/auth/login",
        json={"account": "cape-coast-ops", "password": "operator-password"},
    )
    assert blocked_staff_login.status_code == 403
    assert "store is inactive" in blocked_staff_login.json()["detail"].lower()


def test_customer_profile_and_support_inbox_workflow(api: ApiContext):
    """Customer details persist and staff can work the support inbox."""

    customer_headers, customer = _register(api, name="Support Customer", phone="0240000020")
    profile = api.client.patch(
        "/api/auth/me",
        headers=customer_headers,
        json={
            "name": "Support Customer Updated",
            "email": "support@example.com",
            "default_address": "12 Independence Avenue, Accra",
        },
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["name"] == "Support Customer Updated"
    assert profile.json()["email"] == "support@example.com"
    assert profile.json()["default_address"] == "12 Independence Avenue, Accra"
    assert api.client.patch("/api/auth/me", headers=customer_headers, json={"name": None}).status_code == 422

    order = _create_order(api, customer_headers, phone=customer["phone"], store_id=1)
    created = api.client.post(
        "/api/support/messages",
        headers=customer_headers,
        json={"message": "Please check stock for my order"},
    )
    assert created.status_code == 201, created.text
    conversation = created.json()
    assert conversation["customer_name"] == "Support Customer Updated"
    assert conversation["message_count"] == 2
    assert {message["sender_type"] for message in conversation["messages"]} == {"customer", "assistant"}

    admin_headers = _admin_headers(api)
    customers = api.client.get("/api/admin/customers", headers=admin_headers)
    assert customers.status_code == 200
    customer_row = next(item for item in customers.json() if item["id"] == customer["id"])
    assert customer_row["order_count"] == 1
    assert customer_row["default_address"] == "12 Independence Avenue, Accra"
    edited = api.client.patch(
        f"/api/admin/customers/{customer['id']}",
        headers=admin_headers,
        json={"notes": "Prefers store pickup", "active": True},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["notes"] == "Prefers store pickup"

    inbox = api.client.get("/api/admin/support/conversations", headers=admin_headers)
    assert inbox.status_code == 200
    assert any(item["id"] == conversation["id"] for item in inbox.json())
    detail = api.client.get(
        f"/api/admin/support/conversations/{conversation['id']}",
        headers=admin_headers,
    )
    assert detail.status_code == 200
    reply = api.client.post(
        f"/api/admin/support/conversations/{conversation['id']}/messages",
        headers=admin_headers,
        json={"message": "We are checking the nearest store now."},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "waiting_customer"
    assert any(message["sender_type"] == "admin" for message in reply.json()["messages"])
    closed = api.client.patch(
        f"/api/admin/support/conversations/{conversation['id']}",
        headers=admin_headers,
        json={"status": "resolved"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "resolved"
    reopened = api.client.patch(
        f"/api/admin/support/conversations/{conversation['id']}",
        headers=admin_headers,
        json={"status": "open"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"


def test_store_scoped_staff_only_sees_related_support_conversations(api: ApiContext):
    first_headers, first_user = _register(api, name="Store One Support", phone="0240000021")
    second_headers, second_user = _register(api, name="Store Two Support", phone="0240000022")
    first_order = _create_order(api, first_headers, phone=first_user["phone"], store_id=1, sku_id=1)
    second_order = _create_order(api, second_headers, phone=second_user["phone"], store_id=2, sku_id=2)
    first_conversation = api.client.post(
        "/api/support/messages", headers=first_headers, json={"message": "Store one help"}
    ).json()
    second_conversation = api.client.post(
        "/api/support/messages", headers=second_headers, json={"message": "Store two help"}
    ).json()

    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            """
            INSERT INTO admin_users
                (name, username, password_hash, role, store_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            ("Store One Support Operator", "support-store-one", hash_password("operator-password"), "operator", 1, 1),
        )
    operator_headers = _admin_headers(api, username="support-store-one", password="operator-password")
    visible = api.client.get("/api/admin/support/conversations", headers=operator_headers)
    assert visible.status_code == 200
    visible_ids = {item["id"] for item in visible.json()}
    assert first_conversation["id"] in visible_ids
    assert second_conversation["id"] not in visible_ids
    assert api.client.get(
        f"/api/admin/support/conversations/{second_conversation['id']}",
        headers=operator_headers,
    ).status_code == 404
    assert api.client.post(
        f"/api/admin/support/conversations/{second_conversation['id']}/messages",
        headers=operator_headers,
        json={"message": "Should not be visible"},
    ).status_code == 404


def test_admin_login_is_throttled_after_repeated_failures(monkeypatch: pytest.MonkeyPatch, api: ApiContext):
    monkeypatch.setattr(main_module, "ADMIN_LOGIN_MAX_FAILURES", 5)
    for _ in range(5):
        rejected = api.client.post(
            "/api/admin/auth/login",
            json={"account": "test-admin", "password": "incorrect-password"},
        )
        assert rejected.status_code == 401
    throttled = api.client.post(
        "/api/admin/auth/login",
        json={"account": "test-admin", "password": "incorrect-password"},
    )
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) > 0


def test_legacy_password_endpoints_are_hidden_outside_testing(monkeypatch: pytest.MonkeyPatch, api: ApiContext):
    monkeypatch.setattr(main_module, "RUNTIME_ENV", "production")
    monkeypatch.setenv("LEGACY_PASSWORD_AUTH_ENABLED", "false")
    registration = api.client.post(
        "/api/auth/register",
        json={"name": "Hidden Password User", "phone": "0240000090", "password": "customer-password"},
    )
    login = api.client.post(
        "/api/auth/login",
        json={"account": "0240000090", "password": "customer-password"},
    )
    assert registration.status_code == 404
    assert login.status_code == 404


def test_catalog_guards_store_scope_inactive_stock_and_zero_deposit(api: ApiContext):
    admin_headers = _admin_headers(api)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            """
            INSERT INTO admin_users
                (name, username, password_hash, role, store_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            ("Store One Inventory", "stock-store-one", hash_password("operator-password"), "operator", 1, 1),
        )
    operator_headers = _admin_headers(api, username="stock-store-one", password="operator-password")
    scoped = api.client.get("/api/admin/skus", headers=operator_headers)
    assert scoped.status_code == 200
    assert scoped.json()
    assert all(set(item["store_stock"]) == {"1"} for item in scoped.json())

    paused = api.client.patch("/api/admin/stores/2", headers=admin_headers, json={"active": False})
    assert paused.status_code == 200, paused.text
    public_catalog = api.client.get("/api/skus")
    assert public_catalog.status_code == 200
    assert all("2" not in item["store_stock"] for item in public_catalog.json())
    canonical_cases = api.client.get("/api/skus", params={"category": "cases-accessories"})
    alias_cases = api.client.get("/api/skus", params={"category": "Cases & accessories"})
    assert canonical_cases.status_code == 200
    assert alias_cases.status_code == 200
    assert canonical_cases.json()
    assert {item["id"] for item in alias_cases.json()} == {item["id"] for item in canonical_cases.json()}

    invalid_product = api.client.post(
        "/api/admin/skus",
        headers=admin_headers,
        json={
            "product_name": "Invalid Free Deposit",
            "brand": "EBAphone",
            "category": "cases-accessories",
            "variant": "Validation only",
            "price": 10,
            "deposit_rate": 0,
        },
    )
    assert invalid_product.status_code == 422


def test_customer_with_active_order_cannot_be_paused(api: ApiContext):
    customer_headers, customer = _register(api, name="Active Customer", phone="0240000091")
    order = _create_order(api, customer_headers, phone=customer["phone"], store_id=1)
    admin_headers = _admin_headers(api)
    blocked = api.client.patch(
        f"/api/admin/customers/{customer['id']}",
        headers=admin_headers,
        json={"active": False},
    )
    assert blocked.status_code == 409
    assert "active orders" in blocked.json()["detail"].lower()

    cancelled = api.client.post(
        f"/api/orders/{order['id']}/cancel",
        headers=customer_headers,
        json={"reason": "Resolve before account pause"},
    )
    assert cancelled.status_code == 200
    paused = api.client.patch(
        f"/api/admin/customers/{customer['id']}",
        headers=admin_headers,
        json={"active": False},
    )
    assert paused.status_code == 200
    assert paused.json()["active"] is False


def test_dispatch_can_explicitly_create_in_transit_reservation(api: ApiContext):
    customer_headers, user = _register(api, name="Transfer Customer", phone="0240000092")
    order = _create_order(api, customer_headers, phone=user["phone"], store_id=1, payment_plan="full")
    assert api.client.post(f"/api/orders/{order['id']}/simulate-payment", headers=customer_headers).status_code == 200
    with sqlite3.connect(api.database_path) as connection:
        connection.execute("UPDATE inventories SET available = 0 WHERE sku_id = ? AND store_id = ?", (1, 2))

    admin_headers = _admin_headers(api)
    regular = api.client.post(
        f"/api/orders/{order['id']}/dispatch",
        headers=admin_headers,
        json={"store_id": 2},
    )
    assert regular.status_code == 409
    transfer = api.client.post(
        f"/api/orders/{order['id']}/dispatch",
        headers=admin_headers,
        json={"store_id": 2, "allow_in_transit": True},
    )
    assert transfer.status_code == 200, transfer.text
    assert transfer.json()["store_id"] == 2
    assert transfer.json()["order_status"] == "stock_in_transit"
    assert _inventory(api, store_id=1) == (2, 0, 0)
    assert _inventory(api, store_id=2) == (0, 1, 0)

    blocked_complete = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"note": "Stock has not arrived"},
    )
    assert blocked_complete.status_code == 409
    assert "receives the transfer" in blocked_complete.json()["detail"].lower()

    blocked_tracking = api.client.post(
        f"/api/orders/{order['id']}/tracking",
        headers=admin_headers,
        json={"tracking_number": "DHL-GH-IN-TRANSIT"},
    )
    assert blocked_tracking.status_code == 409
    assert "receives the transfer" in blocked_tracking.json()["detail"].lower()

    blocked_settlement = api.client.post(
        f"/api/orders/{order['id']}/settle",
        headers=admin_headers,
        json={"payment_method": "cash"},
    )
    assert blocked_settlement.status_code == 409
    assert "receives the transfer" in blocked_settlement.json()["detail"].lower()

    blocked_dispatch = api.client.post(
        f"/api/orders/{order['id']}/dispatch",
        headers=admin_headers,
        json={"store_id": 3},
    )
    assert blocked_dispatch.status_code == 409

    received = api.client.post(
        f"/api/orders/{order['id']}/receive-transfer",
        headers=admin_headers,
        json={"note": "Received and inspected"},
    )
    assert received.status_code == 200, received.text
    assert received.json()["order_status"] == "processing"
    assert _inventory(api, store_id=2) == (0, 1, 0)

    completed = api.client.post(
        f"/api/orders/{order['id']}/complete",
        headers=admin_headers,
        json={"pickup_code": order["pickup_code"], "note": "Customer collected"},
    )
    assert completed.status_code == 200, completed.text
    assert _inventory(api, store_id=2) == (0, 0, 1)
