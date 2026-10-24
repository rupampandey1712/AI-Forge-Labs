"""HTTP middleware: request IDs, timing, security headers, rate limiting.

Order matters and is set in ``main.py``. Starlette runs middleware in reverse
registration order on the way in, so the request-context middleware is
registered *last* to run *first* — every other layer (and every log line it
emits) then has a request ID available.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx

log = get_logger("http")

Handler = Callable[[Request], Awaitable[Response]]

#: Paths excluded from access logging — probes would otherwise dominate the log.
QUIET_PATHS = frozenset({"/api/v1/health/live", "/api/v1/health/ready", "/metrics", "/favicon.ico"})


def client_address(request: Request) -> str:
    """The client IP used for rate limiting.

    ``X-Forwarded-For`` is honoured only when ``TRUST_FORWARDED_FOR`` is set,
    i.e. a reverse proxy in front is known to overwrite it. Trusting it
    unconditionally lets any client choose its own identity and get a fresh
    rate-limit bucket on every request.
    """
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, time the request, and emit one structured access log."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        incoming = request.headers.get("x-request-id")
        request_id = incoming or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            log.exception(
                "http.unhandled",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            request_id_ctx.reset(token)
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        # Server-Timing shows up natively in browser devtools, which makes the
        # frontend's latency panel free.
        response.headers["server-timing"] = f"app;dur={duration_ms:.1f}"

        if request.url.path not in QUIET_PATHS:
            emit = log.warning if response.status_code >= 500 else log.info
            emit(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
        request_id_ctx.reset(token)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers.

    Note what is NOT here: a Content-Security-Policy. The frontend is served by
    Vite/nginx, not by this API, so a CSP set here would be both ineffective and
    misleading. Putting a security control where it cannot work is worse than
    not having it, because it stops people looking for the real one.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "permissions-policy", "geolocation=(), microphone=(), camera=()"
        )
        if settings.app_env == "production":
            response.headers.setdefault(
                "strict-transport-security", "max-age=31536000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter, in-process.

    HONEST LIMITATION: this counts per *process*. With four workers the real
    limit is 4x the configured value, and it resets on deploy. That is fine for
    a single-player game and is deliberately left visible rather than hidden
    behind a class named ``DistributedRateLimiter`` that is not one. The
    production answer is Redis (a sorted set per key) or the ingress — and the
    Backend City missions have the player build exactly that.
    """

    #: Above this many tracked clients, idle windows are swept so a flood of
    #: distinct addresses cannot grow the table without bound.
    SWEEP_THRESHOLD = 10_000

    def __init__(self, app, limit_per_minute: int = 240) -> None:
        super().__init__(app)
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _sweep(self, cutoff: float) -> None:
        stale = [k for k, w in self._hits.items() if not w or w[-1] < cutoff]
        for k in stale:
            del self._hits[k]

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        if request.url.path in QUIET_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        key = client_address(request)
        now = time.monotonic()
        cutoff = now - 60.0
        if len(self._hits) > self.SWEEP_THRESHOLD:
            self._sweep(cutoff)
        window = self._hits[key]
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= self.limit:
            retry_after = max(1, int(60 - (now - window[0])))
            log.warning("http.rate_limited", client=key, path=request.url.path)
            return JSONResponse(
                status_code=429,
                headers={"retry-after": str(retry_after)},
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": f"Too many requests. Retry in {retry_after}s.",
                        "details": {"limit_per_minute": self.limit},
                    }
                },
            )

        window.append(now)
        response = await call_next(request)
        response.headers["x-ratelimit-limit"] = str(self.limit)
        response.headers["x-ratelimit-remaining"] = str(max(0, self.limit - len(window)))
        return response
