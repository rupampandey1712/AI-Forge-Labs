"""FastAPI application factory.

WHY a factory rather than a module-level ``app = FastAPI()``: tests build a
fresh app with overridden dependencies, and a module-level instance forces
import-time side effects (engine creation, settings resolution) that then fight
with fixtures. ``create_app()`` costs nothing and removes a whole category of
test flakiness.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.routes import auth, content, gameplay, health, labs, player
from app.core.config import settings
from app.core.errors import ForgeError
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_engine

log = get_logger(__name__)

DESCRIPTION = """
**AI Forge Labs** — a Python & AI engineering RPG.

Learn it. Build it. Break it. Debug it. Explain it. Master it.

The API behind an engineering simulator that trains Python, backend, data, ML,
deep learning, LLM, RAG and agent skills through missions, debugging incidents,
production war rooms and adaptive interviews — with a spaced-repetition engine
that brings back what you are about to forget.
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Registration, login and token rotation."},
    {"name": "player", "description": "Profile, world map, skill trees, badges, leaderboard."},
    {"name": "content", "description": "Concepts, challenges, questions and code execution."},
    {"name": "gameplay", "description": "Missions, dailies, retention, interviews, analytics."},
    {
        "name": "labs",
        "description": (
            "Interactive labs: attention visualiser, RAG tuning bench, agent inspector, "
            "AI mentor and the evaluation harness. Every one works offline."
        ),
    },
    {"name": "health", "description": "Liveness and readiness probes."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown.

    Connectivity is verified here so a misconfigured database fails at boot with
    a clear message, rather than as a 500 on the first player request.
    """
    configure_logging(settings.log_level, settings.log_json)
    log.info(
        "app.starting",
        version=__version__,
        env=settings.app_env,
        dialect="sqlite" if settings.is_sqlite else "postgresql",
        sandbox=settings.sandbox_mode,
        llm=settings.llm_provider,
    )

    engine = get_engine()
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("app.database_ready")
    except Exception as exc:
        log.error("app.database_unreachable", error=str(exc)[:300])
        if settings.app_env == "production":
            raise

    yield

    from app.core.cache import get_cache

    await get_cache().close()
    await dispose_engine()
    log.info("app.stopped")


def create_app(**overrides: Any) -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        openapi_tags=TAGS_METADATA,
        # NOTE: we deliberately do NOT set a custom response class. Current
        # FastAPI serialises response-model payloads straight to JSON bytes via
        # Pydantic, which is faster than routing them through orjson by hand —
        # setting ORJSONResponse here now costs performance and emits a
        # deprecation warning.
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json",
        **overrides,
    )

    # Registered outermost-last: CORS must wrap everything so that even an error
    # response carries the headers a browser needs to read it.
    app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "server-timing", "x-ratelimit-remaining"],
    )

    install_exception_handlers(app)

    prefix = settings.api_v1_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(player.router, prefix=prefix)
    app.include_router(content.router, prefix=prefix)
    app.include_router(gameplay.router, prefix=prefix)
    app.include_router(labs.router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "tagline": "Learn it. Build it. Break it. Debug it. Explain it. Master it.",
            "version": __version__,
            "docs": "/docs",
            "api": prefix,
        }

    return app


def install_exception_handlers(app: FastAPI) -> None:
    """Map domain errors to HTTP once, in one place.

    Services raise ``ForgeError`` subclasses and never import FastAPI. This is
    the single translation point, which keeps error bodies identical across
    every endpoint — a contract the frontend can actually rely on.
    """

    @app.exception_handler(ForgeError)
    async def handle_forge_error(request: Request, exc: ForgeError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("error.domain", code=exc.code, message=exc.message, path=request.url.path)
        else:
            log.info("error.domain", code=exc.code, message=exc.message, path=request.url.path)
        headers = {"www-authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(exc.to_payload(), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Reshape Pydantic's errors into our envelope, and drop the "body"
        # prefix so the frontend can map errors straight onto form fields.
        fields = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][-1]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "validation_failed",
                    "message": "Some fields are invalid.",
                    "details": {"fields": fields},
                }
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": f"http_{exc.status_code}",
                    "message": str(exc.detail),
                    "details": {},
                }
            },
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("error.unhandled", path=request.url.path)
        # Never leak internals to the client. The request ID is the bridge
        # between what the player sees and what is in the logs.
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our side.",
                    "details": {"request_id": getattr(request.state, "request_id", None)},
                }
            },
            status_code=500,
        )


app = create_app()
