"""Test fixtures.

DESIGN: an in-memory SQLite database per test, created from ``Base.metadata``
and torn down with the test. Costs ~30ms and gives every test a guaranteed-clean
database, which removes the single biggest source of flaky suites — order
dependence between tests that share state.

WHY not a transactional rollback fixture against a shared DB: it is faster, but
it breaks the moment the code under test calls ``commit()`` (which ours does,
because the request *is* the unit of work). Testing with a different transaction
model than production runs is how "passes in CI, fails in prod" happens.

WHY ``dependency_overrides`` rather than patching: it is FastAPI's supported
seam. The app under test is the real app, wired to a test database and a
deterministic sandbox — no import patching, no mock library.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app
from app.models import Base
from app.models.progress import SkillProgress
from app.models.user import PlayerProfile, User


@pytest.fixture(scope="session", autouse=True)
def _test_settings():
    """Force test configuration before anything reads it."""
    import os

    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = ""
    os.environ["SANDBOX_MODE"] = "subprocess"
    os.environ["CACHE_ENABLED"] = "false"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def engine():
    # StaticPool keeps ONE connection, so the schema created here is visible to
    # the code under test. Without it, in-memory SQLite gives each connection
    # its own empty database and every query fails with "no such table".
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def sessionmaker_(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(sessionmaker_) -> AsyncGenerator[AsyncSession, None]:
    async with sessionmaker_() as s:
        yield s
        await s.commit()


@pytest.fixture
async def seeded_session(session) -> AsyncSession:
    """A session with skills and every content pack seeded."""
    from app.content.seeder import seed_all

    await seed_all(session)
    await session.commit()
    return session


@pytest.fixture
async def app(sessionmaker_):
    application = create_app()

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker_() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    application.dependency_overrides[get_session] = override_get_session
    return application


@pytest.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client talking to the real app over ASGI — no network, no server."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def seeded_app(app, sessionmaker_):
    from app.content.seeder import seed_all

    async with sessionmaker_() as s:
        await seed_all(s)
        await s.commit()
    return app


@pytest.fixture
async def seeded_client(seeded_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=seeded_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api() -> str:
    return get_settings().api_v1_prefix


@pytest.fixture
async def player(session) -> PlayerProfile:
    """A profile with all 16 skill rows, created directly (no HTTP)."""
    from app.core.security import hash_password
    from app.game.skills.registry import DEFAULT_UNLOCKED_BUILDINGS, SKILLS

    user = User(
        email=f"p{uuid.uuid4().hex[:8]}@test.dev",
        username=f"p{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("test-password-1234"),
    )
    session.add(user)
    await session.flush()
    profile = PlayerProfile(
        user_id=user.id,
        display_name="Test Player",
        unlocked_buildings=list(DEFAULT_UNLOCKED_BUILDINGS),
    )
    session.add(profile)
    await session.flush()
    session.add_all([SkillProgress(profile_id=profile.id, skill_slug=s.slug.value) for s in SKILLS])
    await session.flush()
    return profile


@pytest.fixture
async def auth_headers(seeded_client, api) -> dict[str, str]:
    """Register a fresh player over HTTP and return its Authorization header."""
    suffix = uuid.uuid4().hex[:8]
    response = await seeded_client.post(
        f"{api}/auth/register",
        json={
            "email": f"user{suffix}@test.dev",
            "username": f"user{suffix}",
            "password": "Test-Password-2026!",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


@pytest.fixture
def frozen_now() -> datetime:
    """A fixed instant. Every retention test injects this rather than reading
    the clock, so the suite cannot become time-dependent."""
    return datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
