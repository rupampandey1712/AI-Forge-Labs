"""The sandbox as a separate service, over real HTTP.

Spec §35/§66 requires that player code never execute inside the game server.
These tests check the property that actually delivers that in a deployment: the
game server can be configured to hold no execution capability at all, and to
reach a sandbox across a network boundary instead.

The valuable assertions here are the ones about the *boundary*, not about
execution — execution is covered by test_sandbox_security.py. What is unique to
this file is that the service refuses unauthenticated callers, clamps the
resource limits it is handed, degrades rather than raising when it is
unreachable, and imports nothing from the game.
"""

from __future__ import annotations

import httpx
import pytest

from app.sandbox.backends import RemoteBackend
from app.sandbox.protocol import ExecStatus, ExecutionRequest, ExecutionResult, TestCase, TestKind
from app.sandbox.server import create_sandbox_app

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def sandbox_client():
    """The sandbox service, served over ASGI."""
    app = create_sandbox_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sandbox") as client:
        yield client


class TestTheBoundary:
    def test_the_service_imports_nothing_from_the_game(self):
        """The whole value of the split is that this side knows nothing.

        If the sandbox ever imports a model, a service or the game's settings,
        it can read database credentials and the JWT signing key — and then a
        compromise of the process that runs hostile code by design becomes a
        compromise of everything.
        """
        import ast
        from pathlib import Path

        import app.sandbox.server as server_module

        # Anchored on the module, not the cwd. A boundary test that silently
        # depends on where pytest was invoked from is a boundary test that will
        # one day stop running without anyone noticing.
        source = Path(server_module.__file__).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)

        forbidden = [
            module
            for module in imported
            if module.startswith("app.") and not module.startswith("app.sandbox")
        ]
        assert not forbidden, (
            f"The sandbox service imports from the game: {forbidden}. "
            "It must depend only on app.sandbox and stdlib."
        )

    async def test_health_reports_the_backend_without_auth(self, sandbox_client):
        """Health must not require the token — an orchestrator probes it."""
        response = await sandbox_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["backend"] in {"subprocess", "docker"}

    async def test_docs_are_off_by_default(self):
        """An interactive explorer on a code-execution service is an invitation."""
        app = create_sandbox_app()
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        assert "/docs" not in paths


class TestAuthentication:
    async def test_a_configured_token_is_required(self, monkeypatch):
        monkeypatch.setattr("app.sandbox.server.SANDBOX_TOKEN", "s3cret")
        app = create_sandbox_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://sandbox") as client:
            unauthenticated = await client.post("/execute", json={"code": "x = 1"})
            assert unauthenticated.status_code == 401

            wrong = await client.post(
                "/execute", json={"code": "x = 1"}, headers={"X-Sandbox-Token": "wrong"}
            )
            assert wrong.status_code == 401

            correct = await client.post(
                "/execute", json={"code": "x = 1"}, headers={"X-Sandbox-Token": "s3cret"}
            )
            assert correct.status_code == 200

    async def test_health_stays_open_even_with_a_token(self, monkeypatch):
        monkeypatch.setattr("app.sandbox.server.SANDBOX_TOKEN", "s3cret")
        app = create_sandbox_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://sandbox") as client:
            assert (await client.get("/health")).status_code == 200


class TestResourceLimitsAreNotTrusted:
    """The one parameter an attacker would most like to control is the limit."""

    async def test_timeout_is_clamped_to_the_ceiling(self, monkeypatch, sandbox_client):
        monkeypatch.setattr("app.sandbox.server.HARD_TIMEOUT_CEILING", 2.0)
        response = await sandbox_client.post(
            "/execute", json={"code": "x = 1", "timeout_seconds": 9999.0, "tests": []}
        )
        assert response.status_code == 200
        # The clamp is observable: a request asking for a 9999s timeout on an
        # infinite loop must still come back promptly.
        looping = await sandbox_client.post(
            "/execute",
            json={"code": "while True:\n    pass", "timeout_seconds": 9999.0, "tests": []},
        )
        assert looping.status_code == 200
        assert looping.json()["timed_out"] is True

    async def test_memory_is_clamped_to_the_ceiling(self, monkeypatch, sandbox_client):
        monkeypatch.setattr("app.sandbox.server.HARD_MEMORY_CEILING_MB", 64)
        response = await sandbox_client.post(
            "/execute", json={"code": "x = 1", "memory_mb": 999_999, "tests": []}
        )
        assert response.status_code == 200

    async def test_an_oversized_body_is_rejected_before_parsing(self, monkeypatch, sandbox_client):
        monkeypatch.setattr("app.sandbox.server.MAX_REQUEST_BYTES", 500)
        response = await sandbox_client.post("/execute", json={"code": "x = 1" + "#" * 5000})
        assert response.status_code == 413

    async def test_a_malformed_body_is_a_422_not_a_500(self, sandbox_client):
        assert (await sandbox_client.post("/execute", json=[1, 2, 3])).status_code == 422
        assert (await sandbox_client.post("/execute", json={"nonsense": True})).status_code == 422


class TestTheWireFormat:
    def test_the_result_round_trips(self):
        """One serialisation shared by the runner frame and the HTTP body.

        A second, parallel schema on either side is how the two drift, and the
        drift shows up as a field the game silently reads as None.
        """
        original = ExecutionResult(
            status=ExecStatus.OK,
            stdout="hello",
            duration_ms=12.5,
            outcomes=[],
            benchmark_ms=3.25,
        )
        restored = ExecutionResult.from_json_dict(original.to_json_dict())
        assert restored.status == original.status
        assert restored.stdout == original.stdout
        assert restored.duration_ms == original.duration_ms
        assert restored.benchmark_ms == original.benchmark_ms

    async def test_test_outcomes_survive_the_network_hop(self, sandbox_client):
        """The outcomes list is what grading reads. It must arrive intact."""
        request = ExecutionRequest(
            code="def double(x):\n    return x * 2",
            tests=[
                TestCase(name="doubles", kind=TestKind.EQUALS, call="double(4)", expect=8),
                TestCase(
                    name="hidden zero",
                    kind=TestKind.EQUALS,
                    call="double(0)",
                    expect=0,
                    hidden=True,
                ),
            ],
        )
        response = await sandbox_client.post("/execute", json=request.to_json_dict())
        assert response.status_code == 200

        result = ExecutionResult.from_json_dict(response.json())
        assert result.passed, result.error_message
        assert result.tests_total == 2
        assert result.tests_passed == 2
        assert [o.name for o in result.outcomes] == ["doubles", "hidden zero"]
        assert any(o.hidden for o in result.outcomes)


class TestRemoteBackendDegradesSafely:
    async def test_an_unreachable_sandbox_returns_an_error_not_an_exception(self):
        """Losing a submission because the sandbox restarted is worse than
        reporting the outage, so the backend degrades rather than propagating."""
        backend = RemoteBackend("http://127.0.0.1:1")  # nothing listens on port 1
        result = await backend.execute(ExecutionRequest(code="x = 1"))
        assert result.status == ExecStatus.SANDBOX_ERROR
        assert not result.passed
        assert "unavailable" in result.error_message.lower()

    async def test_healthcheck_reports_unreachable_rather_than_raising(self):
        healthy, detail = await RemoteBackend("http://127.0.0.1:1").healthcheck()
        assert healthy is False
        assert "unreachable" in detail

    def test_remote_mode_refuses_to_start_without_a_url(self):
        """Silently falling back to in-process execution would defeat the whole
        point of the mode — so it is a startup failure, loudly."""
        from app.core.config import Settings
        from app.sandbox.service import build_backend

        cfg = Settings(sandbox_mode="remote", sandbox_service_url="")
        with pytest.raises(RuntimeError, match="SANDBOX_SERVICE_URL"):
            build_backend(cfg)

    def test_remote_mode_builds_when_configured(self):
        from app.core.config import Settings
        from app.sandbox.service import build_backend

        cfg = Settings(sandbox_mode="remote", sandbox_service_url="http://sandbox:8001")
        backend = build_backend(cfg)
        assert isinstance(backend, RemoteBackend)
        assert backend.name == "remote"


class TestProcessDeathIsDiagnosedCorrectly:
    """A runner that dies without reporting must be diagnosed from its signal.

    Both of these shipped, and both were found by running the real container
    rather than by a test: every non-zero exit was reported as the memory limit,
    so an infinite loop killed by the CPU rlimit told the player to look for a
    memory leak. In a product whose Debugging Dungeon teaches "read the
    evidence", a wrong diagnosis is worse than a vague one.
    """

    @pytest.mark.parametrize(
        "returncode,expected,keyword",
        [
            (-24, ExecStatus.TIMEOUT, "cpu"),  # SIGXCPU
            (152, ExecStatus.TIMEOUT, "cpu"),  # 128 + SIGXCPU, as Docker reports it
            (-9, ExecStatus.MEMORY, "memory"),  # SIGKILL
            (137, ExecStatus.MEMORY, "memory"),  # 128 + SIGKILL, the Docker OOM code
            (-6, ExecStatus.MEMORY, "alloc"),  # SIGABRT
            (-11, ExecStatus.SANDBOX_ERROR, "segfault"),  # SIGSEGV
            (139, ExecStatus.SANDBOX_ERROR, "segfault"),  # 128 + SIGSEGV
            (1, ExecStatus.ERROR, "exited with status"),
        ],
    )
    def test_each_death_gets_its_own_diagnosis(self, returncode, expected, keyword):
        from app.sandbox.backends import _classify_death

        status, message = _classify_death(returncode)
        assert status == expected, f"{returncode} -> {status}, expected {expected}"
        assert keyword in message.lower(), f"{returncode}: {message!r} lacks {keyword!r}"

    def test_a_cpu_kill_is_never_reported_as_memory(self):
        """The specific regression. SIGXCPU points at an infinite loop, and
        telling the player it was memory sends them to the wrong fix."""
        from app.sandbox.backends import _classify_death

        status, message = _classify_death(-24)
        assert status != ExecStatus.MEMORY
        assert "memory" not in message.lower()

    def test_a_clean_exit_with_no_result_is_our_fault_not_the_players(self):
        from app.sandbox.backends import _classify_death

        status, message = _classify_death(0)
        assert status == ExecStatus.SANDBOX_ERROR
        assert "bug in the sandbox" in message.lower()


class TestBlasThreadsArePinned:
    """OpenBLAS sizes its buffers from the host CPU count.

    On a many-core machine that allocation alone exceeded the 256MB RLIMIT_AS,
    so every submission in the container died with "Memory allocation still
    failed after 10 retries" before running a line of player code. Pinning to
    one thread also makes the benchmark challenges' timings comparable between
    runs, which is what lets them claim a speed-up factor honestly.
    """

    def test_the_runner_pins_every_thread_pool_variable(self):
        import ast
        from pathlib import Path

        import app.sandbox.runner_main as runner_module

        source = Path(runner_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        scrub = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_scrub_environment"
        )
        pinned = {
            const.value
            for node in ast.walk(scrub)
            for const in ast.walk(node)
            if isinstance(const, ast.Constant)
            and isinstance(const.value, str)
            and const.value.endswith("_NUM_THREADS")
        }
        assert {"OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"} <= pinned

    async def test_numpy_runs_under_the_default_memory_limit(self, sandbox_client):
        """The end-to-end version: import numpy and use it inside the sandbox's
        real limits. This is what was failing in the container."""
        request = ExecutionRequest(
            code=(
                "import numpy as np\n"
                "def total(n):\n"
                "    return float(np.arange(n, dtype=float).sum())"
            ),
            tests=[TestCase(name="sums", kind=TestKind.EQUALS, call="total(5)", expect=10.0)],
            memory_mb=256,
        )
        response = await sandbox_client.post("/execute", json=request.to_json_dict())
        assert response.status_code == 200
        result = ExecutionResult.from_json_dict(response.json())
        assert result.status != ExecStatus.MEMORY, (
            f"numpy blew the memory limit before running: {result.stderr[:300]}"
        )
        assert result.passed, result.error_message or result.stderr[:300]
