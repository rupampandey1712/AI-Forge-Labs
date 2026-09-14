"""Domain exception hierarchy + a single HTTP translation point.

WHY a domain hierarchy instead of raising ``HTTPException`` in services:
services are also used by the CLI, the seeder and the workers, none of which
have an HTTP response to raise. Services speak domain errors; the API layer
owns the mapping to status codes (see ``install_exception_handlers``). This is
the practical half of "don't let your transport leak into your domain".
"""

from __future__ import annotations

from typing import Any


class ForgeError(Exception):
    """Base class for every error the game domain raises deliberately."""

    status_code: int = 400
    code: str = "forge_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(ForgeError):
    status_code = 404
    code = "not_found"


class ConflictError(ForgeError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(ForgeError):
    status_code = 422
    code = "validation_failed"


class AuthenticationError(ForgeError):
    status_code = 401
    code = "unauthenticated"


class PermissionDeniedError(ForgeError):
    status_code = 403
    code = "permission_denied"


class RateLimitedError(ForgeError):
    status_code = 429
    code = "rate_limited"


class LockedError(ForgeError):
    """The player has not unlocked this content yet — a gameplay rule, not a bug."""

    status_code = 423
    code = "content_locked"


class SandboxError(ForgeError):
    status_code = 500
    code = "sandbox_error"


class SandboxTimeout(SandboxError):
    status_code = 408
    code = "sandbox_timeout"


class ExternalServiceError(ForgeError):
    status_code = 502
    code = "external_service_error"
