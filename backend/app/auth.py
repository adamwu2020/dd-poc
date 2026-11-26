"""Email + password accounts with server-side sessions stored in an HttpOnly cookie."""

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.db import AuthSession, User, get_session, utcnow

COOKIE_NAME = "session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# scrypt parameters (~16 MB memory per hash)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

# Failed logins allowed per email within the window before further attempts are refused.
MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW_S = 15 * 60
_failed_logins: dict[str, deque[float]] = defaultdict(deque)

router = APIRouter(prefix="/api/auth")


# --- passwords -------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


# --- sessions --------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _start_session(db: AsyncSession, user: User, request: Request, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    max_age = config.settings.session_days * 86400
    db.add(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(seconds=max_age),
        )
    )
    await db.commit()
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="lax", secure=secure, path="/"
    )


async def current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User:
    """FastAPI dependency: the signed-in user, or 401."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        row = await db.get(AuthSession, _token_hash(token))
        if row and row.expires_at > utcnow():
            user = await db.get(User, row.user_id)
            if user:
                return user
    raise HTTPException(status_code=401, detail="Please sign in")


# --- API -------------------------------------------------------------------------


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("enter a valid email address")
        return v


class Registration(Credentials):
    password: str = Field(min_length=8, max_length=200)


class Account(BaseModel):
    email: str
    free_positive_left: int
    free_negative_left: int
    sample_credits: int
    price_per_sample_cents: int


def account(user: User) -> Account:
    return Account(
        email=user.email,
        free_positive_left=user.free_positive_left,
        free_negative_left=user.free_negative_left,
        sample_credits=user.sample_credits,
        price_per_sample_cents=config.settings.price_per_sample_cents,
    )


@router.post("/register", status_code=201)
async def register(
    body: Registration, request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> Account:
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        free_positive_left=config.settings.free_positive_samples,
        free_negative_left=config.settings.free_negative_samples,
        sample_credits=0,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    await _start_session(db, user, request, response)
    return account(user)


@router.post("/login")
async def login(
    body: Credentials, request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> Account:
    attempts = _failed_logins[body.email]
    now = time.monotonic()
    while attempts and now - attempts[0] > FAILED_LOGIN_WINDOW_S:
        attempts.popleft()
    if len(attempts) >= MAX_FAILED_LOGINS:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")

    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        attempts.append(now)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    attempts.clear()
    await _start_session(db, user, request, response)
    return account(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_session)) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me")
async def me(user: User = Depends(current_user)) -> Account:
    return account(user)
