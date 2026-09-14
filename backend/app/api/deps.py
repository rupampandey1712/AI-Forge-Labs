"""FastAPI dependencies.

WHY dependencies rather than module-level singletons or a DI container: FastAPI's
``Depends`` gives per-request lifetimes, automatic OpenAPI documentation for
auth, and — critically — ``app.dependency_overrides`` in tests. Swapping the
database or the sandbox for a test double is one line, with no mocking library
and no import patching.

The scoping mistake this file exists to avoid: a request-scoped resource (the
DB session) must never be captured by a longer-lived object. That is exactly the
"singleton depends on a request-scoped resource" interview question in §30, and
it is why services are constructed *per request* here rather than once at import.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.logging import user_id_ctx
from app.core.security import decode_token
from app.db.session import get_session
from app.models.user import PlayerProfile, User
from app.repositories.player import ProfileRepository, UserRepository
from app.sandbox.service import SandboxService, get_sandbox_service
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService
from app.services.content_service import ContentService
from app.services.daily_service import DailyService
from app.services.grading_service import GradingService
from app.services.interview_service import InterviewService
from app.services.mission_service import MissionService
from app.services.player_service import PlayerService
from app.services.progression_service import ProgressionService
from app.services.retention_service import RetentionService

# auto_error=False so we can raise our own domain error (and a consistent JSON
# body) instead of Starlette's bare 403 for a missing header.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DBSession = Annotated[AsyncSession, Depends(get_session)]


def _as_uuid(value: str) -> uuid.UUID:
    """A malformed `sub` claim is an auth failure, not a 500."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise AuthenticationError("Malformed authentication token.") from exc


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DBSession,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")
    payload = decode_token(credentials.credentials, expected_type="access")
    user = await UserRepository(session).get(_as_uuid(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("This account is unavailable.")
    user_id_ctx.set(str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_profile(user: CurrentUser, session: DBSession) -> PlayerProfile:
    profile = await ProfileRepository(session).get_for_user(user.id)
    if profile is None:
        raise AuthenticationError("No player profile is attached to this account.")
    return profile


CurrentProfile = Annotated[PlayerProfile, Depends(get_current_profile)]


async def get_optional_profile(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DBSession,
) -> PlayerProfile | None:
    """For endpoints that are richer when signed in but work signed out."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except AuthenticationError:
        return None
    return await ProfileRepository(session).get_for_user(_as_uuid(payload["sub"]))


OptionalProfile = Annotated[PlayerProfile | None, Depends(get_optional_profile)]


async def require_superuser(user: CurrentUser) -> User:
    if not user.is_superuser:
        raise PermissionDeniedError("Administrator access required.")
    return user


def get_user_agent(user_agent: Annotated[str | None, Header()] = None) -> str | None:
    return user_agent


# ── Service factories ────────────────────────────────────────────────────────
# Each is per-request and closes over the request's session. Adding a service is
# one function; no registry, no container, no magic.
def auth_service(session: DBSession) -> AuthService:
    return AuthService(session)


def player_service(session: DBSession) -> PlayerService:
    return PlayerService(session)


def content_service(session: DBSession) -> ContentService:
    return ContentService(session)


def progression_service(session: DBSession) -> ProgressionService:
    return ProgressionService(session)


def retention_service(session: DBSession) -> RetentionService:
    return RetentionService(session)


def mission_service(session: DBSession) -> MissionService:
    return MissionService(session)


def daily_service(session: DBSession) -> DailyService:
    return DailyService(session)


def interview_service(session: DBSession) -> InterviewService:
    return InterviewService(session)


def analytics_service(session: DBSession) -> AnalyticsService:
    return AnalyticsService(session)


def sandbox_service() -> SandboxService:
    # The sandbox IS process-wide on purpose: it owns the concurrency semaphore,
    # which only works as admission control if every request shares one instance.
    return get_sandbox_service()


def grading_service(
    session: DBSession, sandbox: Annotated[SandboxService, Depends(sandbox_service)]
) -> GradingService:
    return GradingService(session, sandbox)


AuthSvc = Annotated[AuthService, Depends(auth_service)]
PlayerSvc = Annotated[PlayerService, Depends(player_service)]
ContentSvc = Annotated[ContentService, Depends(content_service)]
ProgressionSvc = Annotated[ProgressionService, Depends(progression_service)]
RetentionSvc = Annotated[RetentionService, Depends(retention_service)]
MissionSvc = Annotated[MissionService, Depends(mission_service)]
DailySvc = Annotated[DailyService, Depends(daily_service)]
InterviewSvc = Annotated[InterviewService, Depends(interview_service)]
AnalyticsSvc = Annotated[AnalyticsService, Depends(analytics_service)]
GradingSvc = Annotated[GradingService, Depends(grading_service)]
SandboxSvc = Annotated[SandboxService, Depends(sandbox_service)]


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting.

    ``X-Forwarded-For`` is trusted here because the deployment puts this behind
    a reverse proxy. If it were exposed directly, trusting that header would let
    anyone forge their identity for rate-limit purposes — noted because the
    Security missions ask exactly this.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
