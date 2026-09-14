"""Password hashing and JWT issuing/verification.

WHY bcrypt directly instead of passlib: passlib has been effectively
unmaintained since 2020 and its bcrypt backend breaks against bcrypt>=4. We use
the ``bcrypt`` package directly — it is ~40 lines of wrapper and removes a
fragile dependency.

WHY the SHA-256 pre-hash: bcrypt silently truncates input at 72 bytes, so a
long passphrase would have its tail ignored (a real, quietly exploitable bug).
Hashing to a fixed 32-byte digest first removes the truncation cliff. We
base64-encode the digest because bcrypt rejects NUL bytes in its input.

TRADEOFF: pre-hashing makes our hashes non-portable to a plain bcrypt verifier.
That is acceptable here and is recorded in the hash's own ``scheme`` prefix so a
future migration can tell the formats apart.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AuthenticationError

TokenType = Literal["access", "refresh"]
_BCRYPT_ROUNDS = 12


def _prepare(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_prepare(password), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time verification that never raises on malformed stored hashes."""
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash uses fewer rounds than the current policy."""
    try:
        rounds = int(hashed.split("$")[2])
    except (IndexError, ValueError):
        return True
    return rounds < _BCRYPT_ROUNDS


# ── JWT ──────────────────────────────────────────────────────────────────────
def create_token(
    subject: str | uuid.UUID,
    token_type: TokenType = "access",
    *,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.access_token_expire_minutes)
            if token_type == "access"
            else timedelta(days=settings.refresh_token_expire_days)
        )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        # jti lets us revoke individual refresh tokens (denylist in Redis).
        "jti": secrets.token_urlsafe(16),
        "iss": "aiforge",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer="aiforge",
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token") from exc

    if expected_type and payload.get("typ") != expected_type:
        # Refusing an access token where a refresh token is required (and vice
        # versa) blocks a classic token-confusion escalation.
        raise AuthenticationError(f"Expected a {expected_type} token")
    return payload


def create_token_pair(subject: str | uuid.UUID, **claims: Any) -> tuple[str, str]:
    return (
        create_token(subject, "access", extra_claims=claims or None),
        create_token(subject, "refresh"),
    )


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
