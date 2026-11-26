import asyncio
import hashlib
import hmac
import json
import os
import time
from collections import Counter
from datetime import timedelta

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from app import billing, config, db
from app.db import JobRecord, Order, User, utcnow
from app.generation.llm import GenerationError, MockLLM, get_llm
from app.jobs import recover_interrupted_jobs
from app.main import app


def _database_url(tmp_path) -> str:
    """SQLite by default; set TEST_DATABASE_URL to run against Postgres (tables are reset)."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"

    async def reset():
        engine_url, kwargs = db._engine_args(url)
        engine = create_async_engine(engine_url, **kwargs)
        async with engine.begin() as conn:
            await conn.run_sync(db.Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(reset())
    return url


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = config.Settings(
        database_url=_database_url(tmp_path),
        generation_mode="mock",
        payment_mode="mock",
        stripe_secret_key="",
        stripe_webhook_secret="whsec_test",
        public_url="",
        max_samples_per_job=20,
    )
    monkeypatch.setattr(config, "settings", s)
    return s


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_llm] = lambda: MockLLM(delay=0)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def register(client: TestClient, email: str = "a@example.com", password: str = "password123") -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def job_body(positive: int = 1, negative: int = 1, conditions=("Heart failure",)) -> dict:
    return {
        "department": "Cardiology",
        "conditions": list(conditions),
        "positive_count": positive,
        "negative_count": negative,
    }


def read_stream(client: TestClient, job_id: str) -> list[dict]:
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def run_in_app(client: TestClient, coro):
    """Run a coroutine on the app's event loop (where the DB engine lives)."""
    return client.portal.call(lambda: coro)


# --- accounts ------------------------------------------------------------------------


def test_register_login_logout(client):
    account = register(client, "Doc@Example.com")
    assert account == {
        "email": "doc@example.com",
        "free_positive_left": 1,
        "free_negative_left": 1,
        "sample_credits": 0,
        "price_per_sample_cents": 50,
    }
    assert client.get("/api/auth/me").json()["email"] == "doc@example.com"

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    bad = client.post("/api/auth/login", json={"email": "doc@example.com", "password": "nope-nope"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"email": "DOC@example.com", "password": "password123"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_register_validation(client):
    register(client)
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "not-an-email", "password": "password123"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422


def test_login_is_rate_limited(client):
    register(client, "rl@example.com")
    client.post("/api/auth/logout")
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "rl@example.com", "password": "wrong-password"})
    r = client.post("/api/auth/login", json={"email": "rl@example.com", "password": "password123"})
    assert r.status_code == 429


def test_endpoints_require_login(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/orders/quote", json=job_body()).status_code == 401
    assert client.post("/api/orders", json=job_body()).status_code == 401
    assert client.get("/api/departments/Cardiology/conditions").status_code == 401


# --- pricing and orders --------------------------------------------------------------


def test_free_allowance_covers_one_positive_and_one_negative(client):
    register(client)
    quote = client.post("/api/orders/quote", json=job_body(1, 1)).json()
    assert quote["amount_cents"] == 0

    order = client.post("/api/orders", json=job_body(1, 1)).json()
    assert order["status"] == "fulfilled" and order["checkout_url"] is None
    events = read_stream(client, order["job_id"])
    assert events[-1]["status"] == "completed"
    assert Counter(e["sample"]["label"] for e in events if e["type"] == "sample") == {"positive": 1, "negative": 1}

    me = client.get("/api/auth/me").json()
    assert (me["free_positive_left"], me["free_negative_left"], me["sample_credits"]) == (0, 0, 0)

    # The allowance is per account: the next sample costs money.
    assert client.post("/api/orders/quote", json=job_body(1, 0)).json()["amount_cents"] == 50


def test_paid_order_goes_through_checkout(client):
    register(client)
    quote = client.post("/api/orders/quote", json=job_body(3, 2)).json()
    assert quote | {} == {
        "total_samples": 5,
        "positive_samples": 3,
        "negative_samples": 2,
        "free_positive": 1,
        "free_negative": 1,
        "credits_used": 0,
        "paid_samples": 3,
        "price_per_sample_cents": 50,
        "amount_cents": 150,
    }

    order = client.post("/api/orders", json=job_body(3, 2)).json()
    assert order["status"] == "pending" and order["job_id"] is None
    assert order["checkout_url"].endswith(f"/?order={order['order_id']}&mock_checkout=1")
    # The free samples are reserved while the order is pending.
    assert client.get("/api/auth/me").json()["free_positive_left"] == 0

    paid = client.post(f"/api/orders/{order['order_id']}/mock-pay").json()
    assert paid["status"] == "fulfilled"
    events = read_stream(client, paid["job_id"])
    assert events[-1]["status"] == "completed"
    assert sum(e["type"] == "sample" for e in events) == 5

    # Paying twice doesn't start a second job.
    again = client.post(f"/api/orders/{order['order_id']}/mock-pay").json()
    assert again["job_id"] == paid["job_id"]
    assert len(client.get("/api/jobs").json()) == 1


def test_cancelling_checkout_releases_reservation(client):
    register(client)
    order = client.post("/api/orders", json=job_body(2, 2)).json()
    cancelled = client.post(f"/api/orders/{order['order_id']}/cancel").json()
    assert cancelled["status"] == "expired"
    me = client.get("/api/auth/me").json()
    assert (me["free_positive_left"], me["free_negative_left"]) == (1, 1)
    # A cancelled order can't be paid afterwards.
    assert client.post(f"/api/orders/{order['order_id']}/mock-pay").json()["job_id"] is None


def test_expired_orders_are_released(client):
    register(client)
    order = client.post("/api/orders", json=job_body(2, 2)).json()

    async def expire():
        async with db.session_scope() as s:
            await s.execute(
                update(Order).where(Order.id == order["order_id"]).values(expires_at=utcnow() - timedelta(hours=1))
            )
            await s.commit()

    run_in_app(client, expire())
    me = client.get("/api/account").json()
    assert (me["free_positive_left"], me["free_negative_left"]) == (1, 1)
    assert client.get(f"/api/orders/{order['order_id']}").json()["status"] == "expired"


def test_sample_limit(client):
    register(client)
    assert client.post("/api/orders/quote", json=job_body(5, 5, ["A", "B"])).status_code == 200
    r = client.post("/api/orders", json=job_body(6, 5, ["A", "B"]))
    assert r.status_code == 422
    assert "limit is 20" in r.json()["detail"]


def test_paid_order_without_stripe_config_is_refused(client, settings, monkeypatch):
    monkeypatch.setattr(config, "settings", config.Settings(**{**settings.__dict__, "payment_mode": "stripe"}))
    register(client)
    assert client.post("/api/orders", json=job_body(2, 1)).status_code == 503
    # Nothing was reserved, and free orders still work.
    assert client.get("/api/auth/me").json()["free_positive_left"] == 1
    assert client.post("/api/orders", json=job_body(1, 1)).json()["status"] == "fulfilled"


# --- undelivered samples become credits ----------------------------------------------


def test_failed_samples_are_credited(client):
    class FlakyLLM(MockLLM):
        async def generate_record(self, spec):
            if spec.index == 0:
                raise GenerationError("model declined the request")
            return await super().generate_record(spec)

    app.dependency_overrides[get_llm] = lambda: FlakyLLM(delay=0)
    billing_llm = billing.get_llm
    billing.get_llm = lambda: FlakyLLM(delay=0)
    try:
        register(client)
        order = client.post("/api/orders", json=job_body(2, 1)).json()
        paid = client.post(f"/api/orders/{order['order_id']}/mock-pay").json()
        events = read_stream(client, paid["job_id"])
    finally:
        billing.get_llm = billing_llm

    assert events[-1]["status"] == "completed"
    assert [e["index"] for e in events if e["type"] == "sample_error"] == [0]
    me = client.get("/api/auth/me").json()
    assert me["sample_credits"] == 1
    # The credit is used before charging.
    quote = client.post("/api/orders/quote", json=job_body(1, 0)).json()
    assert (quote["credits_used"], quote["amount_cents"]) == (1, 0)


def test_fatal_error_credits_every_undelivered_sample(client):
    class BrokenLLM(MockLLM):
        async def generate_record(self, spec):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.AuthenticationError(
                "invalid x-api-key", response=httpx.Response(401, request=request), body=None
            )

    billing_llm = billing.get_llm
    billing.get_llm = lambda: BrokenLLM(delay=0)
    try:
        register(client)
        order = client.post("/api/orders", json=job_body(2, 2)).json()
        paid = client.post(f"/api/orders/{order['order_id']}/mock-pay").json()
        events = read_stream(client, paid["job_id"])
    finally:
        billing.get_llm = billing_llm

    assert events[-1]["status"] == "failed"
    assert "AuthenticationError" in events[-1]["error"]
    assert client.get("/api/auth/me").json()["sample_credits"] == 4


def test_interrupted_jobs_are_closed_and_credited(client):
    register(client)
    order = client.post("/api/orders", json=job_body(1, 1)).json()
    read_stream(client, order["job_id"])

    async def simulate_crash_and_restart():
        async with db.session_scope() as s:
            await s.execute(
                update(JobRecord).where(JobRecord.id == order["job_id"]).values(status="running", completed=1)
            )
            await s.commit()
        from app.jobs import jobs

        jobs._jobs.clear()
        await recover_interrupted_jobs()

    run_in_app(client, simulate_crash_and_restart())
    status = client.get(f"/api/jobs/{order['job_id']}").json()
    assert status["status"] == "failed" and "restart" in status["error"]
    assert client.get("/api/auth/me").json()["sample_credits"] == 1


# --- jobs belong to their owner ------------------------------------------------------


def test_jobs_are_private_and_persisted(client):
    register(client, "owner@example.com")
    order = client.post("/api/orders", json=job_body(1, 1)).json()
    job_id = order["job_id"]
    read_stream(client, job_id)

    # Results survive the job leaving memory (e.g. after a restart).
    from app.jobs import jobs

    jobs._jobs.clear()
    replay = read_stream(client, job_id)
    assert sum(e["type"] == "sample" for e in replay) == 2
    assert replay[-1] == {"type": "done", "status": "completed", "error": None}
    inputs = client.get(f"/api/jobs/{job_id}/export", params={"format": "jsonl", "part": "inputs"}).text
    assert all("diagnosis" not in json.loads(l)["record"] for l in inputs.splitlines())

    client.post("/api/auth/logout")
    register(client, "other@example.com")
    assert client.get("/api/jobs").json() == []
    for path in ("", "/stream", "/samples", "/export"):
        assert client.get(f"/api/jobs/{job_id}{path}").status_code == 404
    assert client.get(f"/api/orders/{order['order_id']}").status_code == 404


# --- Stripe ---------------------------------------------------------------------------


class FakeStripe:
    def __init__(self):
        self.paid: set[str] = set()
        self.expired: list[str] = []

    async def create_checkout(self, order, email, base_url):
        return f"cs_test_{order.id}", f"https://checkout.stripe.test/{order.id}"

    async def is_paid(self, session_id):
        return session_id in self.paid

    async def expire(self, session_id):
        self.expired.append(session_id)


@pytest.fixture
def stripe_client(client, settings, monkeypatch):
    monkeypatch.setattr(
        config, "settings", config.Settings(**{**settings.__dict__, "payment_mode": "stripe", "stripe_secret_key": "sk_test_x"})
    )
    fake = FakeStripe()
    monkeypatch.setattr(billing, "get_gateway", lambda: fake)
    return client, fake


def signed(payload: dict, secret: str = "whsec_test") -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={t},v1={sig}", "content-type": "application/json"}


def checkout_event(event_type: str, order_id: str, payment_status: str = "paid") -> dict:
    return {
        "id": "evt_test",
        "object": "event",
        "type": event_type,
        "data": {
            "object": {
                "id": f"cs_test_{order_id}",
                "object": "checkout.session",
                "client_reference_id": order_id,
                "metadata": {"order_id": order_id},
                "payment_status": payment_status,
            }
        },
    }


def test_stripe_webhook_fulfills_order(stripe_client):
    client, _ = stripe_client
    register(client)
    order = client.post("/api/orders", json=job_body(2, 1)).json()
    assert order["checkout_url"] == f"https://checkout.stripe.test/{order['order_id']}"

    body, headers = signed(checkout_event("checkout.session.completed", order["order_id"]))
    assert client.post("/api/stripe/webhook", content=body, headers=headers).status_code == 200
    job_id = client.get(f"/api/orders/{order['order_id']}").json()["job_id"]
    assert job_id
    assert read_stream(client, job_id)[-1]["status"] == "completed"

    # Stripe retries webhooks; a duplicate must not start another job.
    assert client.post("/api/stripe/webhook", content=body, headers=headers).status_code == 200
    assert len(client.get("/api/jobs").json()) == 1


def test_stripe_webhook_rejects_bad_signature(stripe_client):
    client, _ = stripe_client
    register(client)
    order = client.post("/api/orders", json=job_body(2, 1)).json()
    body, headers = signed(checkout_event("checkout.session.completed", order["order_id"]), secret="whsec_wrong")
    assert client.post("/api/stripe/webhook", content=body, headers=headers).status_code == 400
    assert client.get(f"/api/orders/{order['order_id']}").json()["status"] == "pending"


def test_stripe_expired_webhook_releases_reservation(stripe_client):
    client, _ = stripe_client
    register(client)
    order = client.post("/api/orders", json=job_body(2, 1)).json()
    body, headers = signed(checkout_event("checkout.session.expired", order["order_id"], "unpaid"))
    client.post("/api/stripe/webhook", content=body, headers=headers)
    assert client.get(f"/api/orders/{order['order_id']}").json()["status"] == "expired"
    assert client.get("/api/auth/me").json()["free_positive_left"] == 1


def test_return_from_checkout_settles_without_webhook(stripe_client):
    client, fake = stripe_client
    register(client)
    order = client.post("/api/orders", json=job_body(2, 1)).json()
    assert client.get(f"/api/orders/{order['order_id']}").json()["status"] == "pending"

    fake.paid.add(f"cs_test_{order['order_id']}")
    settled = client.get(f"/api/orders/{order['order_id']}").json()
    assert settled["status"] == "fulfilled" and settled["job_id"]


def test_cancel_expires_stripe_session(stripe_client):
    client, fake = stripe_client
    register(client)
    order = client.post("/api/orders", json=job_body(2, 1)).json()
    client.post(f"/api/orders/{order['order_id']}/cancel")
    assert fake.expired == [f"cs_test_{order['order_id']}"]


def test_stripe_checkout_params(monkeypatch):
    """The real gateway sends the right line items and redirect URLs to Stripe."""
    captured = {}

    class FakeSessions:
        async def create_async(self, params):
            captured.update(params)
            return type("S", (), {"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})()

    gateway = billing.StripeGateway("sk_test_x")
    gateway._client = type("C", (), {"v1": type("V", (), {"checkout": type("K", (), {"sessions": FakeSessions()})()})()})()
    order = Order(id="ord1", paid_samples=3, expires_at=utcnow() + timedelta(minutes=35))
    session_id, url = asyncio.run(gateway.create_checkout(order, "a@example.com", "https://app.test"))

    assert (session_id, url) == ("cs_1", "https://checkout.stripe.com/c/cs_1")
    assert captured["mode"] == "payment"
    assert captured["line_items"][0]["quantity"] == 3
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 50
    assert captured["success_url"] == "https://app.test/?order=ord1&checkout=success"
    assert captured["metadata"] == {"order_id": "ord1"}
    assert captured["expires_at"] - time.time() > 30 * 60
