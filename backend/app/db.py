"""Database models and engine (SQLite locally, Postgres/Supabase in production)."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC timestamp (stored the same way in SQLite and Postgres)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    free_positive_left: Mapped[int] = mapped_column(Integer)
    free_negative_left: Mapped[int] = mapped_column(Integer)
    # Paid-for or free samples that were not delivered (failed, cancelled), usable on any later job.
    sample_credits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime]


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    request: Mapped[dict[str, Any]]
    total_samples: Mapped[int]
    free_positive: Mapped[int]
    free_negative: Mapped[int]
    credits_used: Mapped[int]
    paid_samples: Mapped[int]
    amount_cents: Mapped[int]
    # pending -> fulfilled (job started) | expired (reservation released)
    status: Mapped[str] = mapped_column(String(16), index=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    job_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    request: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(String(16))
    total: Mapped[int]
    completed: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]


class SampleRecord(Base):
    __tablename__ = "samples"
    __table_args__ = (UniqueConstraint("job_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    index: Mapped[int]
    data: Mapped[dict[str, Any]]


# --- engine ----------------------------------------------------------------------

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_args(url: str) -> tuple[str, dict]:
    """Normalize a database URL for SQLAlchemy's async drivers.

    Accepts the `postgresql://...` URL that Supabase shows and switches it to asyncpg.
    Prepared-statement caches are disabled so Supabase's connection pooler works in
    both session and transaction mode.
    """
    if url.startswith(("postgres://", "postgresql://")):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query.pop("sslmode", None)
        query["prepared_statement_cache_size"] = "0"
        url = urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), ""))
        connect_args = {"statement_cache_size": 0}
        if "localhost" not in parts.netloc and "127.0.0.1" not in parts.netloc:
            connect_args["ssl"] = "require"
        return url, {"connect_args": connect_args, "pool_pre_ping": True}
    return url, {}


async def init_db(url: str) -> None:
    global _engine, _sessionmaker
    url, kwargs = _engine_args(url)
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


def session_scope() -> AsyncSession:
    assert _sessionmaker is not None, "init_db() has not been called"
    return _sessionmaker()


async def get_session():
    """FastAPI dependency: one session per request."""
    async with session_scope() as session:
        yield session
