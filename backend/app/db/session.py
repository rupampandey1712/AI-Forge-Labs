"""Engine + session lifecycle.

WHY async SQLAlchemy: the game is I/O bound (Postgres, Redis, sandbox workers,
LLM calls). An async stack lets one worker hold thousands of in-flight requests
during a 40s LLM call instead of one thread each. The *cost* is that a single
blocking call poisons the whole event loop — which is precisely the bug the
"Blocking Event Loop" debugging missions teach.

WHY ``expire_on_commit=False``: with the default, touching any attribute after
``commit()`` triggers a lazy refresh — which in async code raises
``MissingGreenlet`` instead of silently issuing a query. Disabling expiry lets
services return ORM objects that the response serializer can safely read.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(cfg: Settings) -> dict[str, Any]:
    if cfg.is_sqlite:
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in cfg.sqlalchemy_url:
            # An in-memory SQLite DB is per-connection. StaticPool keeps ONE
            # connection so the schema created in a fixture is visible to the
            # code under test. Without this, tests fail with "no such table".
            kwargs["poolclass"] = StaticPool
        else:
            kwargs["poolclass"] = NullPool
        return kwargs
    return {
        "pool_size": cfg.db_pool_size,
        "max_overflow": cfg.db_max_overflow,
        "pool_pre_ping": True,  # survives Postgres restarts / idle reaping
        "pool_recycle": 1800,
    }


def create_engine(cfg: Settings | None = None) -> AsyncEngine:
    cfg = cfg or get_settings()
    return create_async_engine(
        cfg.sqlalchemy_url, echo=cfg.db_echo, future=True, **_engine_kwargs(cfg)
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine()
        log.info("db.engine_created", dialect=_engine.dialect.name)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False, class_=AsyncSession
        )
    return _sessionmaker


def override_engine(engine: AsyncEngine) -> None:
    """Point the process at a different engine (used by tests and the seeder)."""
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, committed on success.

    WHY commit here rather than in each service: it makes the *request* the unit
    of work. A mission submission that awards XP, updates three skills, writes a
    learning event and schedules a review either lands entirely or not at all.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Same unit-of-work semantics for non-HTTP callers (CLI, workers, seeds)."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
