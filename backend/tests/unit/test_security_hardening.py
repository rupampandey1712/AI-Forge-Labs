"""Guards added after the security review: sandbox posture, proxy trust, rate-limit memory."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.api import middleware
from app.api.middleware import RateLimitMiddleware, client_address
from app.core.config import Settings

STRONG = "x" * 64


class TestProductionSandboxGuard:
    def test_subprocess_sandbox_is_refused_in_production(self):
        with pytest.raises(ValidationError, match="SANDBOX_MODE=subprocess"):
            Settings(app_env="production", secret_key=STRONG, sandbox_mode="subprocess")

    @pytest.mark.parametrize("mode", ["docker", "disabled"])
    def test_isolated_or_disabled_sandbox_is_allowed_in_production(self, mode):
        Settings(app_env="production", secret_key=STRONG, sandbox_mode=mode)

    def test_remote_sandbox_needs_a_strong_token_in_production(self):
        with pytest.raises(ValidationError, match="SANDBOX_SERVICE_TOKEN"):
            Settings(
                app_env="production",
                secret_key=STRONG,
                sandbox_mode="remote",
                sandbox_service_token="dev-only-sandbox-token-change-me",
            )
        Settings(
            app_env="production",
            secret_key=STRONG,
            sandbox_mode="remote",
            sandbox_service_token=STRONG,
        )

    def test_subprocess_sandbox_still_works_for_local_development(self):
        Settings(app_env="development", sandbox_mode="subprocess")


def _request(xff: str | None = None, host: str = "203.0.113.7") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


class TestClientAddress:
    def test_forwarded_header_is_ignored_by_default(self, monkeypatch):
        monkeypatch.setattr(middleware.settings, "trust_forwarded_for", False)
        assert client_address(_request(xff="1.2.3.4")) == "203.0.113.7"

    def test_forwarded_header_is_used_only_when_trusted(self, monkeypatch):
        monkeypatch.setattr(middleware.settings, "trust_forwarded_for", True)
        assert client_address(_request(xff="1.2.3.4, 10.0.0.1")) == "1.2.3.4"
        assert client_address(_request()) == "203.0.113.7"


class TestRateLimitMemory:
    def test_idle_clients_are_swept(self):
        limiter = RateLimitMiddleware(app=None, limit_per_minute=10)
        for i in range(50):
            limiter._hits[f"10.0.0.{i}"].append(0.0)  # all far in the past
        limiter._hits["active"].append(1_000.0)
        limiter._sweep(cutoff=500.0)
        assert list(limiter._hits) == ["active"]
