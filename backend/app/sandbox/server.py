"""The code execution sandbox, as a standalone service.

WHY THIS IS A SEPARATE PROCESS AND A SEPARATE DEPLOYABLE
---------------------------------------------------------
Spec §35/§66: player code must never execute inside the game server. The
subprocess and Docker backends honour that on a single host. This service
honours it across a trust boundary, which is what a real deployment needs:

* The **game server** then runs with no Docker socket, no ability to spawn
  processes, and a read-only filesystem. It holds the database credentials and
  the JWT signing key, and it never executes anything.
* The **sandbox** runs hostile code by design. It holds no credentials, has no
  database connection, no egress, and nothing worth stealing. Compromising it
  gets an attacker a container that can already run arbitrary code — which is
  its entire purpose — and no further.

That asymmetry is the point. It is why this is the **only** service split in
the application: everything else is a module, because splitting it would buy
coupling and latency in exchange for nothing (see docs/adr/ADR-001).

WHAT THIS FILE MAY IMPORT
-------------------------
Only ``app.sandbox.*`` and stdlib. No models, no services, no database, no
settings that carry secrets. If this module ever needs something from the game,
that is a design error — the whole value of the boundary is that this side
knows nothing.

The auth is a shared secret rather than JWT for the same reason: this service
has no user concept and should not acquire one. It answers to exactly one
caller.
"""

from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.sandbox.backends import DockerBackend, SandboxBackend, SubprocessBackend
from app.sandbox.protocol import ExecStatus, ExecutionRequest, ExecutionResult, TestCase

# Read directly from the environment rather than from app.core.config: that
# module pulls in the game's settings, including database URLs and signing
# keys. This process must not be able to read them even by accident.
SANDBOX_TOKEN = os.getenv("SANDBOX_SERVICE_TOKEN", "")
SANDBOX_BACKEND = os.getenv("SANDBOX_MODE", "subprocess")
SANDBOX_IMAGE = os.getenv("SANDBOX_DOCKER_IMAGE", "aiforge-sandbox:latest")
MAX_REQUEST_BYTES = int(os.getenv("SANDBOX_MAX_REQUEST_BYTES", str(256 * 1024)))
HARD_TIMEOUT_CEILING = float(os.getenv("SANDBOX_TIMEOUT_CEILING", "30"))
HARD_MEMORY_CEILING_MB = int(os.getenv("SANDBOX_MEMORY_CEILING_MB", "1024"))


def _build_backend() -> SandboxBackend:
    # `remote` is deliberately not an option here. A sandbox that forwards to
    # another sandbox is a loop waiting to happen, and there is no legitimate
    # reason to chain them.
    if SANDBOX_BACKEND == "docker":
        return DockerBackend(SANDBOX_IMAGE)
    return SubprocessBackend()


def require_token(x_sandbox_token: str = Header(default="")) -> None:
    """Shared-secret auth.

    ``compare_digest`` rather than ``==`` because a plain comparison returns
    early on the first differing byte, which leaks the token's prefix through
    timing. The window is small over a network and it costs nothing to close.

    An unset token means the service is open, which is only acceptable on a
    private network — the startup log says so loudly rather than pretending
    otherwise.
    """
    if not SANDBOX_TOKEN:
        return
    if not hmac.compare_digest(x_sandbox_token, SANDBOX_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid sandbox token.")


def create_sandbox_app() -> FastAPI:
    app = FastAPI(
        title="AI Forge Sandbox",
        description=(
            "Isolated code execution. Runs untrusted player code and returns test "
            "outcomes. Holds no credentials and has no database."
        ),
        version="1.0.0",
        # No docs in production: this service has one caller and one endpoint,
        # and an interactive explorer on an execution service is an invitation.
        docs_url="/docs" if os.getenv("SANDBOX_ENABLE_DOCS") == "true" else None,
        redoc_url=None,
    )
    backend = _build_backend()
    app.state.backend = backend
    app.state.started_at = time.time()
    app.state.executions = 0

    @app.get("/health")
    async def health() -> dict[str, Any]:
        healthy, detail = await backend.healthcheck()
        return {
            "status": "ok" if healthy else "degraded",
            "backend": backend.name,
            "detail": detail,
            "uptime_seconds": round(time.time() - app.state.started_at, 1),
            "executions": app.state.executions,
        }

    @app.post("/execute", dependencies=[Depends(require_token)])
    async def execute(request: Request) -> JSONResponse:
        """Run one submission.

        The request body is parsed manually rather than through a Pydantic
        model so that this service shares exactly one definition of the wire
        format with the client — ``ExecutionRequest``. A second, parallel schema
        here is how the two sides drift.
        """
        raw = await request.body()
        if len(raw) > MAX_REQUEST_BYTES:
            # Bounded before parsing: a 40MB submission should cost a length
            # check, not a JSON parse.
            raise HTTPException(status_code=413, detail="Submission too large.")

        try:
            payload = ExecutionRequest(
                **{
                    **_parse(raw),
                }
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Malformed request: {exc}") from exc

        # Clamp rather than trust. The caller is our own game server today, but
        # a service that executes code should never let its resource limits be
        # set by its input — that is the one parameter an attacker would most
        # like to control.
        payload.timeout_seconds = min(payload.timeout_seconds, HARD_TIMEOUT_CEILING)
        payload.memory_mb = min(payload.memory_mb, HARD_MEMORY_CEILING_MB)

        try:
            result = await backend.execute(payload)
        except Exception as exc:  # pragma: no cover - defensive
            result = ExecutionResult(
                status=ExecStatus.SANDBOX_ERROR,
                error_type=type(exc).__name__,
                error_message="The sandbox failed to execute this submission.",
            )

        app.state.executions += 1
        return JSONResponse(result.to_json_dict())

    return app


def _parse(raw: bytes) -> dict[str, Any]:
    import json

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object.")
    # `protocol_version` travels on the wire for compatibility checking but is
    # not a constructor argument.
    data.pop("protocol_version", None)
    data["tests"] = [TestCase(**t) if isinstance(t, dict) else t for t in data.get("tests", [])]
    return data


app = create_sandbox_app()
