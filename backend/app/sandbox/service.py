"""The sandbox facade the rest of the application talks to.

Responsibilities beyond picking a backend:

* **Admission control.** A bounded semaphore caps concurrent executions. Without
  it, twenty players submitting an accidental infinite loop would fork twenty
  CPU-burning processes and the *game server* would be the thing that falls
  over — the classic "the sandbox was isolated but the host wasn't" incident.
* **Static pre-screening.** Cheap AST checks reject the obviously-hostile before
  we pay for a process. This is a filter, never the boundary: it is trivially
  bypassable and is here to make abuse loud and to give the player a useful
  error rather than a mysterious ``PermissionError`` from inside the runner.
* **Uniform failure.** Callers get an ``ExecutionResult`` in every case,
  including "the sandbox itself broke". Grading code should never have to
  handle an exception from here.
"""

from __future__ import annotations

import ast
import asyncio
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.sandbox.backends import (
    DisabledBackend,
    DockerBackend,
    SandboxBackend,
    SubprocessBackend,
)
from app.sandbox.protocol import (
    ExecStatus,
    ExecutionRequest,
    ExecutionResult,
    TestCase,
)

log = get_logger(__name__)

#: Import targets that have no legitimate use in a challenge solution and a very
#: legitimate use in an attack. ``os`` and ``sys`` are deliberately NOT here:
#: plenty of real exercises touch them, and blocking them would teach players to
#: write worse Python to please the grader.
BLOCKED_IMPORTS = frozenset(
    {
        "ctypes",
        "socket",
        "socketserver",
        "http",
        "urllib",
        "urllib3",
        "requests",
        "httpx",
        "ftplib",
        "smtplib",
        "telnetlib",
        "paramiko",
        "subprocess",
        "multiprocessing",
        "pty",
        "fcntl",
        "mmap",
        "webbrowser",
        "importlib",
    }
)

#: Attribute/name patterns that only show up in sandbox-escape attempts.
BLOCKED_NAMES = frozenset(
    {"__subclasses__", "__globals__", "__builtins__", "__loader__", "__import__"}
)

MAX_SOURCE_BYTES = 100_000


class StaticCheckFailed(Exception):
    def __init__(self, reason: str, line: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.line = line


def static_prescreen(code: str) -> None:
    """Raise ``StaticCheckFailed`` for source we refuse to even start.

    Note the deliberate narrowness: we reject *imports* of network/process
    modules and the reflection tricks used for escapes. We do not attempt to
    reason about what the code does — that is undecidable, and pretending
    otherwise is how sandboxes get a false sense of safety.
    """
    if len(code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise StaticCheckFailed("Submission is too large.")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        # Syntax errors are the player's problem, not a security event — let the
        # runner report them with a proper message and line number.
        raise StaticCheckFailed(f"SyntaxError: {exc.msg}", exc.lineno) from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_IMPORTS:
                    raise StaticCheckFailed(
                        f"`import {alias.name}` is not available in the sandbox.", node.lineno
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BLOCKED_IMPORTS:
                raise StaticCheckFailed(
                    f"`from {node.module} import ...` is not available in the sandbox.", node.lineno
                )
        elif isinstance(node, ast.Attribute) and node.attr in BLOCKED_NAMES:
            raise StaticCheckFailed(f"Access to `{node.attr}` is blocked.", node.lineno)
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            raise StaticCheckFailed(f"Access to `{node.id}` is blocked.", node.lineno)


def build_backend(cfg: Settings) -> SandboxBackend:
    match cfg.sandbox_mode:
        case "docker":
            return DockerBackend(cfg.sandbox_docker_image)
        case "disabled":
            return DisabledBackend()
        case _:
            return SubprocessBackend()


class SandboxService:
    def __init__(self, cfg: Settings | None = None, backend: SandboxBackend | None = None) -> None:
        self.cfg = cfg or get_settings()
        self.backend = backend or build_backend(self.cfg)
        self._semaphore = asyncio.Semaphore(self.cfg.sandbox_max_concurrency)
        self._queue_depth = 0

    @property
    def mode(self) -> str:
        return self.backend.name

    async def healthcheck(self) -> tuple[bool, str]:
        return await self.backend.healthcheck()

    async def run(
        self,
        code: str,
        *,
        tests: list[TestCase] | None = None,
        setup_code: str = "",
        stdin: str = "",
        timeout_seconds: float | None = None,
        memory_mb: int | None = None,
        benchmark_repeat: int = 0,
        benchmark_code: str | None = None,
        prescreen: bool = True,
    ) -> ExecutionResult:
        if prescreen:
            try:
                static_prescreen(code)
            except StaticCheckFailed as exc:
                return ExecutionResult(
                    status=ExecStatus.ERROR,
                    error_type="StaticCheckFailed",
                    error_message=exc.reason,
                    stderr=(f"Line {exc.line}: " if exc.line else "") + exc.reason,
                )

        request = ExecutionRequest(
            code=code,
            setup_code=setup_code,
            tests=tests or [],
            stdin=stdin,
            timeout_seconds=timeout_seconds or self.cfg.sandbox_timeout_seconds,
            memory_mb=memory_mb or self.cfg.sandbox_memory_mb,
            max_output_bytes=self.cfg.sandbox_max_output_bytes,
            benchmark_repeat=benchmark_repeat,
            benchmark_code=benchmark_code,
        )

        self._queue_depth += 1
        try:
            # Bounded wait: if the queue is saturated, fail fast with a clear
            # message rather than leaving the player staring at a spinner.
            async with asyncio.timeout(request.timeout_seconds + 30):
                async with self._semaphore:
                    result = await self.backend.execute(request)
        except TimeoutError:
            return ExecutionResult(
                status=ExecStatus.SANDBOX_ERROR,
                error_message="The sandbox is saturated. Try again in a moment.",
            )
        finally:
            self._queue_depth -= 1

        log.info(
            "sandbox.executed",
            mode=self.backend.name,
            status=str(result.status),
            tests=result.tests_total,
            passed=result.tests_passed,
            duration_ms=result.duration_ms,
            queue_depth=self._queue_depth,
        )
        return result

    async def benchmark_pair(
        self,
        baseline_code: str,
        candidate_code: str,
        *,
        repeat: int = 5,
        setup_code: str = "",
    ) -> tuple[float | None, float | None, float | None]:
        """Time two implementations and return ``(baseline_ms, candidate_ms, speedup)``.

        Used by the NumPy/Pandas optimisation missions. Running both in the same
        sandbox configuration is the point: a speedup claim measured on two
        different machines is not a measurement.
        """
        base, cand = await asyncio.gather(
            self.run(
                baseline_code, setup_code=setup_code, benchmark_repeat=repeat, prescreen=False
            ),
            self.run(candidate_code, setup_code=setup_code, benchmark_repeat=repeat),
        )
        b_ms, c_ms = base.benchmark_ms, cand.benchmark_ms
        speedup = round(b_ms / c_ms, 2) if b_ms and c_ms and c_ms > 0 else None
        return b_ms, c_ms, speedup


@lru_cache(maxsize=1)
def get_sandbox_service() -> SandboxService:
    return SandboxService()
