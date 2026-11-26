"""Pricing, orders, and Stripe Checkout.

Flow: the client asks for a quote, then creates an order. Creating an order reserves
the user's free samples and credits. If anything is left to pay, the user is sent to
Stripe Checkout; the job starts once Stripe reports the payment (webhook, or a check
when the user returns). Unpaid orders expire and their reservation is released.
"""

import logging
import uuid
from datetime import UTC, timedelta
from typing import Protocol

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth import Account, account, current_user
from app.db import JobRecord, Order, User, get_session, session_scope, utcnow
from app.generation.llm import get_llm
from app.jobs import jobs
from app.schemas import GenerateRequest

logger = logging.getLogger(__name__)

# Stripe Checkout sessions must live at least 30 minutes.
CHECKOUT_TTL = timedelta(minutes=35)
# Extra time before releasing an unpaid order, in case a payment is still being confirmed.
RELEASE_GRACE = timedelta(minutes=5)

router = APIRouter(prefix="/api")


# --- pricing ---------------------------------------------------------------------


class Quote(BaseModel):
    total_samples: int
    positive_samples: int
    negative_samples: int
    free_positive: int
    free_negative: int
    credits_used: int
    paid_samples: int
    price_per_sample_cents: int
    amount_cents: int


def make_quote(req: GenerateRequest, user: User) -> Quote:
    n = len(req.conditions)
    positive, negative = req.positive_count * n, req.negative_count * n
    free_pos = min(positive, user.free_positive_left)
    free_neg = min(negative, user.free_negative_left)
    billable = positive + negative - free_pos - free_neg
    credits = min(billable, user.sample_credits)
    paid = billable - credits
    price = config.settings.price_per_sample_cents
    return Quote(
        total_samples=positive + negative,
        positive_samples=positive,
        negative_samples=negative,
        free_positive=free_pos,
        free_negative=free_neg,
        credits_used=credits,
        paid_samples=paid,
        price_per_sample_cents=price,
        amount_cents=paid * price,
    )


def _check_limit(req: GenerateRequest) -> None:
    if req.total_samples > config.settings.max_samples_per_job:
        raise HTTPException(
            status_code=422,
            detail=(
                f"this request would generate {req.total_samples} samples; "
                f"the limit is {config.settings.max_samples_per_job} per job"
            ),
        )


# --- payment gateways ------------------------------------------------------------


class PaymentGateway(Protocol):
    async def create_checkout(self, order: Order, email: str, base_url: str) -> tuple[str, str]:
        """Returns (session id, URL to send the user to)."""
        ...

    async def is_paid(self, session_id: str) -> bool: ...
    async def expire(self, session_id: str) -> None: ...


class StripeGateway:
    def __init__(self, secret_key: str):
        self._client = stripe.StripeClient(secret_key, http_client=stripe.HTTPXClient())

    async def create_checkout(self, order: Order, email: str, base_url: str) -> tuple[str, str]:
        session = await self._client.v1.checkout.sessions.create_async(
            params={
                "mode": "payment",
                "line_items": [
                    {
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": config.settings.price_per_sample_cents,
                            "product_data": {
                                "name": "Synthetic patient record",
                                "description": "One generated sample for LLM evaluation",
                            },
                        },
                        "quantity": order.paid_samples,
                    }
                ],
                "customer_email": email,
                "client_reference_id": order.id,
                "metadata": {"order_id": order.id},
                "success_url": f"{base_url}/?order={order.id}&checkout=success",
                "cancel_url": f"{base_url}/?order={order.id}&checkout=cancelled",
                "expires_at": int(order.expires_at.replace(tzinfo=UTC).timestamp()),
            }
        )
        return session.id, session.url or ""

    async def is_paid(self, session_id: str) -> bool:
        session = await self._client.v1.checkout.sessions.retrieve_async(session_id)
        return session.payment_status in ("paid", "no_payment_required")

    async def expire(self, session_id: str) -> None:
        await self._client.v1.checkout.sessions.expire_async(session_id)


class MockGateway:
    """Local development: 'pays' on a fake page served by the frontend."""

    async def create_checkout(self, order: Order, email: str, base_url: str) -> tuple[str, str]:
        return f"mock_{order.id}", f"{base_url}/?order={order.id}&mock_checkout=1"

    async def is_paid(self, session_id: str) -> bool:
        return False

    async def expire(self, session_id: str) -> None:
        return None


def get_gateway() -> PaymentGateway:
    s = config.settings
    if s.payment_mode == "mock":
        return MockGateway()
    if not s.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payments are not configured on this server")
    return StripeGateway(s.stripe_secret_key)


def _base_url(request: Request) -> str:
    if config.settings.public_url:
        return config.settings.public_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


# --- order state transitions -----------------------------------------------------


async def fulfill(order_id: str) -> str | None:
    """Mark a pending order fulfilled and start its job. Idempotent; returns the job id."""
    job_id = uuid.uuid4().hex[:12]
    async with session_scope() as db:
        result = await db.execute(
            update(Order)
            .where(Order.id == order_id, Order.status == "pending")
            .values(status="fulfilled", job_id=job_id)
        )
        order = await db.get(Order, order_id)
        if result.rowcount == 0:
            return order.job_id if order else None
        db.add(
            JobRecord(
                id=job_id,
                user_id=order.user_id,
                order_id=order.id,
                request=order.request,
                status="planning",
                total=order.total_samples,
            )
        )
        await db.commit()
    jobs.start(job_id, order.user_id, GenerateRequest(**order.request), get_llm())
    return job_id


async def release(order_id: str) -> bool:
    """Expire a pending order and give its reserved free samples and credits back."""
    async with session_scope() as db:
        result = await db.execute(
            update(Order).where(Order.id == order_id, Order.status == "pending").values(status="expired")
        )
        if result.rowcount == 0:
            return False
        order = await db.get(Order, order_id)
        await db.execute(
            update(User)
            .where(User.id == order.user_id)
            .values(
                free_positive_left=User.free_positive_left + order.free_positive,
                free_negative_left=User.free_negative_left + order.free_negative,
                sample_credits=User.sample_credits + order.credits_used,
            )
        )
        await db.commit()
        return True


async def _settle_if_paid(order: Order) -> None:
    """Ask Stripe whether a pending order was paid, and fulfill it if so."""
    if order.status != "pending" or not order.stripe_session_id or config.settings.payment_mode == "mock":
        return
    try:
        if await get_gateway().is_paid(order.stripe_session_id):
            await fulfill(order.id)
    except (stripe.StripeError, HTTPException) as e:
        logger.warning("could not check payment for order %s: %s", order.id, e)


async def sweep_expired_orders(user_id: int | None = None) -> None:
    """Release pending orders whose checkout has expired (after settling any that were paid)."""
    async with session_scope() as db:
        query = select(Order).where(Order.status == "pending", Order.expires_at < utcnow() - RELEASE_GRACE)
        if user_id is not None:
            query = query.where(Order.user_id == user_id)
        stale = (await db.execute(query)).scalars().all()
    for order in stale:
        await _settle_if_paid(order)
        await release(order.id)


# --- API -------------------------------------------------------------------------


class OrderView(BaseModel):
    order_id: str
    status: str
    quote: Quote
    checkout_url: str | None = None
    job_id: str | None = None


def _view(order: Order, checkout_url: str | None = None) -> OrderView:
    req = GenerateRequest(**order.request)
    n = len(req.conditions)
    return OrderView(
        order_id=order.id,
        status=order.status,
        checkout_url=checkout_url,
        job_id=order.job_id,
        quote=Quote(
            total_samples=order.total_samples,
            positive_samples=req.positive_count * n,
            negative_samples=req.negative_count * n,
            free_positive=order.free_positive,
            free_negative=order.free_negative,
            credits_used=order.credits_used,
            paid_samples=order.paid_samples,
            price_per_sample_cents=config.settings.price_per_sample_cents,
            amount_cents=order.amount_cents,
        ),
    )


async def _own_order(order_id: str, user: User, db: AsyncSession) -> Order:
    order = await db.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@router.post("/orders/quote")
async def quote_order(req: GenerateRequest, user: User = Depends(current_user)) -> Quote:
    _check_limit(req)
    await sweep_expired_orders(user.id)
    async with session_scope() as db:
        fresh = await db.get(User, user.id)
    return make_quote(req, fresh)


@router.post("/orders", status_code=201)
async def create_order(
    req: GenerateRequest, request: Request, user: User = Depends(current_user)
) -> OrderView:
    _check_limit(req)
    await sweep_expired_orders(user.id)
    gateway: PaymentGateway | None = None

    async with session_scope() as db:
        locked = (await db.execute(select(User).where(User.id == user.id).with_for_update())).scalar_one()
        q = make_quote(req, locked)
        if q.amount_cents > 0:
            gateway = get_gateway()  # fail before reserving if payments are unavailable
        order = Order(
            id=uuid.uuid4().hex,
            user_id=user.id,
            request=req.model_dump(),
            total_samples=q.total_samples,
            free_positive=q.free_positive,
            free_negative=q.free_negative,
            credits_used=q.credits_used,
            paid_samples=q.paid_samples,
            amount_cents=q.amount_cents,
            status="pending",
            expires_at=utcnow() + CHECKOUT_TTL,
        )
        locked.free_positive_left -= q.free_positive
        locked.free_negative_left -= q.free_negative
        locked.sample_credits -= q.credits_used
        db.add(order)
        await db.commit()

    if gateway is None:
        await fulfill(order.id)
        async with session_scope() as db:
            return _view(await db.get(Order, order.id))

    try:
        session_id, url = await gateway.create_checkout(order, user.email, _base_url(request))
    except stripe.StripeError as e:
        logger.error("stripe checkout failed for order %s: %s", order.id, e)
        await release(order.id)
        raise HTTPException(status_code=502, detail="Could not start the payment. Please try again.")
    async with session_scope() as db:
        await db.execute(update(Order).where(Order.id == order.id).values(stripe_session_id=session_id))
        await db.commit()
        return _view(await db.get(Order, order.id), checkout_url=url)


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> OrderView:
    order = await _own_order(order_id, user, db)
    if order.status == "pending":
        await _settle_if_paid(order)
        await db.refresh(order)
    return _view(order)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> OrderView:
    order = await _own_order(order_id, user, db)
    if order.status == "pending":
        if order.stripe_session_id and config.settings.payment_mode != "mock":
            try:
                await get_gateway().expire(order.stripe_session_id)
            except stripe.StripeError:
                # Already completed or expired: settle by asking Stripe for its state.
                await _settle_if_paid(order)
        await release(order.id)
        await db.refresh(order)
    return _view(order)


@router.post("/orders/{order_id}/mock-pay")
async def mock_pay(
    order_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> OrderView:
    if config.settings.payment_mode != "mock":
        raise HTTPException(status_code=404, detail="not found")
    order = await _own_order(order_id, user, db)
    await fulfill(order.id)
    await db.refresh(order)
    return _view(order)


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request) -> dict:
    secret = config.settings.stripe_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="webhook not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature"), secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="invalid signature")

    session = event.data.object.to_dict()
    order_id = (session.get("metadata") or {}).get("order_id") or session.get("client_reference_id")
    if not order_id:
        return {"received": True}
    if event.type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if session.get("payment_status") in ("paid", "no_payment_required"):
            await fulfill(order_id)
    elif event.type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        await release(order_id)
    return {"received": True}


@router.get("/account")
async def get_account(user: User = Depends(current_user)) -> Account:
    await sweep_expired_orders(user.id)
    async with session_scope() as db:
        return account(await db.get(User, user.id))
