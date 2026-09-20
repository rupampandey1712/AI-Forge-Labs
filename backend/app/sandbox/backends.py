"""Sandbox backends: subprocess (local dev) and docker (hardened).

Both implement the same tiny interface, so ``SandboxService`` — and every
caller above it — is unaware of which one is running. That is the whole reason
the protocol is JSON: swapping isolation strength must never be a code change
in the game.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.logging import get_logger
from app.sandbox.protocol import (
    RESULT_SENTINEL,
    ExecStatus,
    ExecutionRequest,
    ExecutionResult,
)

log = get_logger(__name__)

RUNNER_PATH = Path(__file__).with_name("runner_main.py")
IS_WINDOWS = sys.platform == "win32"


class SandboxBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "ok"


def _parse_runner_output(raw_stdout: str, raw_stderr: str) -> ExecutionResult | None:
    """Split player output from the framed result JSON.

    ``rpartition`` (not ``partition``) because a mischievous submission can
    print the sentinel itself; taking the *last* occurrence means the real
    result — always emitted last — wins.
    """
    if RESULT_SENTINEL not in raw_stdout:
        return None
    before, _, after = raw_stdout.rpartition(RESULT_SENTINEL)
    try:
        payload = json.loads(after.strip())
    except json.JSONDecodeError:
        return None
    result = ExecutionResult.from_json_dict(payload)
    # Anything printed before the sentinel that the runner did not capture
    # (e.g. output from a C extension writing to fd 1 directly) still belongs
    # to the player.
    leaked = before.strip()
    if leaked and leaked not in result.stdout:
        result.stdout = (leaked + "\n" + result.stdout).strip()
    if raw_stderr.strip() and raw_stderr.strip() not in result.stderr:
        result.stderr = (result.stderr + "\n" + raw_stderr.strip()).strip()
    return result


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the runner *and anything it spawned*.

    ``proc.kill()`` alone orphans grandchildren — a submission that spawns a
    busy loop would survive the timeout and quietly eat a core forever. This is
    exactly the class of bug the Debugging Dungeon teaches, so the sandbox had
    better not ship with it.
    """
    if proc.returncode is not None:
        return
    if IS_WINDOWS:
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        except Exception:
            proc.kill()
    else:
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    with contextlib.suppress(TimeoutError, ProcessLookupError):
        await asyncio.wait_for(proc.wait(), timeout=3)


class SubprocessBackend(SandboxBackend):
    """Separate OS process, resource-limited, scrubbed env, throwaway cwd.

    Suitable for local single-player use. NOT a security boundary against a
    determined attacker on a shared host — see ``runner_main`` for the full
    posture note. ``SANDBOX_MODE=docker`` is the deployable answer.
    """

    name = "subprocess"

    def __init__(self, python_executable: str | None = None) -> None:
        self.python = python_executable or sys.executable

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        payload = json.dumps(request.to_json_dict())
        workdir = tempfile.mkdtemp(prefix="aiforge-sbx-")
        started = time.perf_counter()

        # A minimal environment: the runner scrubs os.environ too, but not
        # inheriting secrets in the first place is strictly better.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Fixed hash seed keeps set/dict iteration order reproducible, so a
            # challenge that (wrongly) depends on it fails deterministically
            # instead of flaking — a flaky grader destroys trust in the game.
            "PYTHONHASHSEED": "0",
            "TMPDIR": workdir,
            "TEMP": workdir,
            "TMP": workdir,
        }
        if IS_WINDOWS:
            for key in ("SYSTEMROOT", "COMSPEC"):
                if key in os.environ:
                    env[key] = os.environ[key]

        kwargs: dict = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True  # own process group -> killpg works

        try:
            proc = await asyncio.create_subprocess_exec(
                self.python,
                "-I",  # isolated: ignore PYTHON* env and the user site dir
                "-B",
                str(RUNNER_PATH),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=env,
                **kwargs,
            )
        except OSError as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            return ExecutionResult(
                status=ExecStatus.SANDBOX_ERROR,
                error_message=f"Could not start the sandbox process: {exc}",
            )

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(payload.encode("utf-8")),
                # Grace on top of the in-runner limit: the runner tries to report
                # its own timeout first, and only a hung process hits this.
                timeout=request.timeout_seconds + 3.0,
            )
        except TimeoutError:
            timed_out = True
            await _kill_process_tree(proc)
            stdout_b, stderr_b = b"", b"Execution exceeded the wall-clock limit."
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if timed_out:
            return ExecutionResult(
                status=ExecStatus.TIMEOUT,
                timed_out=True,
                duration_ms=duration_ms,
                stderr="Execution timed out.",
                error_message=(
                    f"Your code did not finish within {request.timeout_seconds:.0f}s. "
                    "An infinite loop, a runaway recursion or an accidental O(n²) "
                    "over a large input are the usual suspects."
                ),
            )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        parsed = _parse_runner_output(stdout, stderr)
        if parsed is None:
            # The runner died before it could frame a result — MemoryError kills,
            # segfaults from a native extension, SIGKILL from an rlimit.
            killed_by_limit = proc.returncode not in (0, None)
            return ExecutionResult(
                status=ExecStatus.MEMORY if killed_by_limit else ExecStatus.SANDBOX_ERROR,
                exit_code=proc.returncode,
                stdout=stdout[:4000],
                stderr=stderr[:4000],
                duration_ms=duration_ms,
                error_message=(
                    "The sandbox process exited without reporting a result. This usually "
                    "means the memory limit was hit or the interpreter crashed."
                ),
            )
        parsed.exit_code = proc.returncode
        parsed.duration_ms = parsed.duration_ms or duration_ms
        return parsed


class DockerBackend(SandboxBackend):
    """Container-per-execution. The supported mode for any shared deployment.

    Every flag below closes a specific hole:

    ``--network none``      no exfiltration, no calling an LLM API on our key
    ``--read-only``         no tampering with the image; ``/tmp`` is a tmpfs
    ``--cap-drop ALL``      no ptrace, no mount, no raw sockets
    ``--security-opt no-new-privileges``  setuid binaries cannot escalate
    ``--user 65534``        nobody; nothing on disk is owned by it
    ``--pids-limit``        fork bombs die instead of taking down the host
    ``--memory / --cpus``   one submission cannot starve the others
    ``--rm``                no container accretion on a long-lived host
    """

    name = "docker"

    def __init__(self, image: str, *, cpus: float = 1.0) -> None:
        self.image = image
        self.cpus = cpus

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "image",
                "inspect",
                self.image,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
        except (OSError, TimeoutError) as exc:
            return False, f"docker unavailable: {exc}"
        if proc.returncode != 0:
            return False, f"sandbox image '{self.image}' is not built"
        return True, "ok"

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        payload = json.dumps(request.to_json_dict())
        started = time.perf_counter()
        args = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--pids-limit",
            "64",
            "--memory",
            f"{request.memory_mb}m",
            "--memory-swap",
            f"{request.memory_mb}m",  # no swap => the limit is real
            "--cpus",
            str(self.cpus),
            "--workdir",
            "/tmp",
            self.image,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return ExecutionResult(
                status=ExecStatus.SANDBOX_ERROR,
                error_message=f"Could not start the sandbox container: {exc}",
            )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(payload.encode("utf-8")),
                timeout=request.timeout_seconds + 10.0,  # + container start cost
            )
        except TimeoutError:
            await _kill_process_tree(proc)
            return ExecutionResult(
                status=ExecStatus.TIMEOUT,
                timed_out=True,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error_message=f"Execution exceeded {request.timeout_seconds:.0f}s.",
            )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        parsed = _parse_runner_output(stdout, stderr)
        if parsed is None:
            # Docker reports OOM kills as exit code 137 (128 + SIGKILL).
            oom = proc.returncode == 137
            return ExecutionResult(
                status=ExecStatus.MEMORY if oom else ExecStatus.SANDBOX_ERROR,
                exit_code=proc.returncode,
                stdout=stdout[:4000],
                stderr=stderr[:4000],
                error_message=(
                    f"Container exceeded the {request.memory_mb}MB memory limit."
                    if oom
                    else "The sandbox container exited without reporting a result."
                ),
            )
        parsed.exit_code = proc.returncode
        return parsed


class DisabledBackend(SandboxBackend):
    """Explicit off switch. Returns a clear error instead of silently passing."""

    name = "disabled"

    async def healthcheck(self) -> tuple[bool, str]:
        return False, "sandbox disabled by configuration"

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            status=ExecStatus.SANDBOX_ERROR,
            error_message="Code execution is disabled on this server (SANDBOX_MODE=disabled).",
        )


class RemoteBackend(SandboxBackend):
    """Calls a separate sandbox *service* over HTTP.

    WHY THIS EXISTS, and why it is the only service split in the codebase:
    spec §35 requires that player code never execute inside the game server's
    process. The subprocess and Docker backends satisfy that on one host; this
    one satisfies it across a *trust* boundary, which is what a real deployment
    needs. The game server can then run with no Docker socket, no ability to
    spawn processes, and a read-only filesystem — because it never executes
    anything.

    Every other seam in this application stayed a module for the reasons in
    ADR-001. This one is a network call because the thing on the other side is
    hostile by design, and a process boundary is the only boundary that means
    anything against hostile code.

    The failure mode is deliberately conservative: an unreachable sandbox
    returns SANDBOX_ERROR rather than raising. A player seeing "the sandbox is
    unavailable" is a degraded experience; a 500 from the submit endpoint loses
    their attempt.
    """

    name = "remote"

    def __init__(self, base_url: str, token: str = "", timeout_margin: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        # Margin over the *execution* timeout: the sandbox enforces its own
        # limit and returns a timed-out result, which is far more useful than a
        # client-side timeout that tells the player nothing. The HTTP timeout
        # exists only to catch a sandbox that has died entirely.
        self.timeout_margin = timeout_margin

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Sandbox-Token"] = self.token
        return headers

    async def healthcheck(self) -> tuple[bool, str]:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health", headers=self._headers())
            if response.status_code == 200:
                return True, f"remote sandbox ok ({self.base_url})"
            return False, f"remote sandbox returned {response.status_code}"
        except Exception as exc:
            return False, f"remote sandbox unreachable: {type(exc).__name__}"

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        import httpx

        try:
            async with httpx.AsyncClient(
                timeout=request.timeout_seconds + self.timeout_margin
            ) as client:
                response = await client.post(
                    f"{self.base_url}/execute",
                    headers=self._headers(),
                    json=request.to_json_dict(),
                )
            response.raise_for_status()
            return ExecutionResult.from_json_dict(response.json())
        except Exception as exc:
            # Losing a submission because the sandbox restarted is a worse
            # outcome than reporting the outage, so this degrades rather than
            # propagating.
            log.error("sandbox.remote_failed", url=self.base_url, error=str(exc))
            return ExecutionResult(
                status=ExecStatus.SANDBOX_ERROR,
                error_type=type(exc).__name__,
                error_message=(
                    "The code execution service is unavailable. Your work is not lost — "
                    "try running it again in a moment."
                ),
            )
