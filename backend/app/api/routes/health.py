"""Health and readiness probes.

Two endpoints, deliberately different (this distinction is itself a DevOps
mission):

``/health/live``  — is the process alive? No dependencies touched. If this
                    fails, restart the container.
``/health/ready`` — can it serve traffic? Checks the database, cache and
                    sandbox. If this fails, take it out of the load balancer but
                    do NOT restart it — the fault is usually downstream.

Conflating them is how a brief database blip turns into a restart loop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import DBSession, SandboxSvc
from app.core.config import settings
from app.schemas.common import HealthStatus

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "alive", "version": __version__}


@router.get("/ready", response_model=HealthStatus)
async def ready(session: DBSession, sandbox: SandboxSvc, response: Response) -> HealthStatus:
    details: dict[str, Any] = {}

    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = "error"
        details["database_error"] = str(exc)[:200]

    cache_status = "disabled"
    if settings.cache_enabled and settings.redis_url:
        try:
            from app.core.cache import get_cache

            cache = get_cache()
            cache_status = "ok" if await cache.ping() else "degraded"
        except Exception as exc:
            cache_status = "degraded"
            details["cache_error"] = str(exc)[:200]

    sandbox_ok, sandbox_detail = await sandbox.healthcheck()
    if not sandbox_ok:
        details["sandbox_detail"] = sandbox_detail

    # Redis being down degrades performance but not correctness, so it does not
    # fail readiness. The database and sandbox do.
    healthy = db_status == "ok" and sandbox_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthStatus(
        status="ready" if healthy else "degraded",
        version=__version__,
        environment=settings.app_env,
        database=db_status,
        cache=cache_status,
        sandbox=sandbox.mode if sandbox_ok else f"{sandbox.mode}:unavailable",
        checked_at=datetime.now(UTC),
        details=details,
    )


@router.get("/info")
async def info() -> dict[str, Any]:
    """Non-secret runtime configuration, for the in-game observability panel."""
    return {
        "name": settings.app_name,
        "version": __version__,
        "environment": settings.app_env,
        "database_dialect": "sqlite" if settings.is_sqlite else "postgresql",
        "sandbox_mode": settings.sandbox_mode,
        "llm_provider": settings.llm_provider,
        "llm_configured": settings.llm_configured,
        "api_prefix": settings.api_v1_prefix,
    }
