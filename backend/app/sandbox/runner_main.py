"""Untrusted-code runner. THIS MODULE EXECUTES PLAYER CODE.

It is deliberately **standalone**: it imports nothing from ``app`` and nothing
outside the standard library, so the same file can be copied into a minimal
container image with no application code, no database driver and no secrets.

Run as::

    python -m app.sandbox.runner_main       # request JSON on stdin

Contract: stdin is one JSON object (see ``protocol.ExecutionRequest``); stdout
is whatever the player's code printed, then ``RESULT_SENTINEL``, then one JSON
object on a single line.

SECURITY POSTURE — read this before changing anything
-----------------------------------------------------
Process isolation here is *defence in depth*, not the primary boundary. Python
cannot sandbox itself: ``ctypes``, frame walking and C extensions defeat any
in-interpreter jail. The real boundaries, in order of strength:

1. ``docker`` backend — ``--network none``, read-only rootfs, dropped caps,
   non-root user, pids/memory/cpu limits. This is the supported production mode.
2. ``subprocess`` backend — separate process, rlimits (POSIX), wall-clock kill,
   scrubbed environment, throwaway cwd. Adequate for a single-player local game
   where the "attacker" is the person who owns the machine; NOT adequate for a
   multi-tenant deployment.

What this file *does* contribute: it prevents the accidents (runaway loops,
fork bombs, memory hogs, secrets read out of ``os.environ``) and it makes the
deliberate attacks noisy.
"""

from __future__ import annotations

import base64
import builtins
import contextlib
import io
import json
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

#: MUST match app.sandbox.protocol.RESULT_SENTINEL (asserted in the test suite).
RESULT_SENTINEL = "<<<AIFORGE_RESULT_V1>>>"

MAX_REPR = 2000


# ── Resource limits ──────────────────────────────────────────────────────────
def _apply_rlimits(memory_mb: int, cpu_seconds: int) -> None:
    """POSIX resource limits. No-ops on Windows, where the docker backend or a
    Job Object is the only real answer — never pretend otherwise."""
    try:
        import resource
    except ImportError:  # Windows
        return
    mem_bytes = memory_mb * 1024 * 1024
    for limit, value in (
        (resource.RLIMIT_AS, mem_bytes),
        (resource.RLIMIT_DATA, mem_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, 8 * 1024 * 1024),
        (resource.RLIMIT_NOFILE, 64),
    ):
        try:
            _soft, hard = resource.getrlimit(limit)
            new = value if hard in (resource.RLIM_INFINITY, -1) else min(value, hard)
            resource.setrlimit(limit, (new, hard))
        except (ValueError, OSError):
            pass
    # Block fork bombs where the platform supports it.
    if hasattr(resource, "RLIMIT_NPROC"):
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def _scrub_environment() -> None:
    """Remove everything the player's code has no business reading.

    Even in the subprocess backend the parent's environment holds SECRET_KEY,
    DATABASE_URL and possibly an API key. Inheriting those into untrusted code
    would make a ``print(os.environ)`` a credential dump.
    """
    keep = {
        "PATH",
        "PYTHONPATH",
        "PYTHONHASHSEED",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "HOME",
        "USERPROFILE",
    }
    for key in list(os.environ):
        if key not in keep:
            del os.environ[key]
    os.environ["AIFORGE_SANDBOX"] = "1"

    # Pin the BLAS/OpenMP thread pools to one thread. Two independent reasons,
    # and the first one was found the hard way by running the real container:
    #
    # 1. CORRECTNESS. OpenBLAS sizes its per-thread buffers from the host CPU
    #    count. On a many-core machine that allocation alone can exceed the
    #    256MB RLIMIT_AS, so *every* submission died with "OpenBLAS error:
    #    Memory allocation still failed after 10 retries" before running a line
    #    of the player's code.
    # 2. MEASUREMENT. The benchmark challenges claim things like "your
    #    vectorised version is 23x faster". That number is meaningless if the
    #    thread count varies with whatever else the host is doing, so timings
    #    are taken single-threaded and are therefore comparable between runs.
    #
    # Set after the scrub, or the scrub would remove them.
    for variable in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[variable] = "1"

    # matplotlib writes a font cache on first import and looks for HOME to
    # decide where. The scrub above removed HOME, so without this it prints a
    # multi-line warning into the player's stderr about a problem they did not
    # cause and cannot fix — noise in the one channel that should only ever
    # carry their own output. Agg because there is no display, and never will
    # be one.
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ["MPLCONFIGDIR"] = os.path.join(os.getcwd(), ".mplconfig")


def _disable_network() -> None:
    """Best-effort in-process network block for the subprocess backend.

    Trivially bypassable (``ctypes``, a fresh import machinery), which is
    exactly why the docker backend uses ``--network none`` instead of trusting
    this. It is here to turn "my solution silently called an API" from a
    surprise into an immediate, legible error.
    """
    try:
        import socket

        def _blocked(*_args: Any, **_kwargs: Any):
            raise PermissionError("Network access is disabled inside the sandbox.")

        socket.socket = _blocked  # type: ignore[assignment]
        socket.create_connection = _blocked  # type: ignore[assignment]
        socket.getaddrinfo = _blocked  # type: ignore[assignment]
    except Exception:
        pass


# ── Value formatting ─────────────────────────────────────────────────────────
def _safe_repr(value: Any) -> str:
    try:
        text = repr(value)
    except Exception as exc:  # a __repr__ that raises is the player's bug
        return f"<unreprable {type(value).__name__}: {exc}>"
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + f"... ({len(text)} chars)"


def _compare(actual: Any, expected: Any, kind: str, tolerance: float) -> bool:
    if kind == "approx":
        return _approx_equal(actual, expected, tolerance)
    try:
        if actual == expected:
            return True
    except Exception:
        return False
    # NumPy/pandas return arrays from ``==``; fall back to their own equality.
    try:
        import numpy as np

        if isinstance(actual, np.ndarray) or isinstance(expected, np.ndarray):
            return bool(np.array_equal(np.asarray(actual), np.asarray(expected)))
    except Exception:
        pass
    return False


def _approx_equal(actual: Any, expected: Any, tol: float) -> bool:
    import math

    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=tol, abs_tol=tol)
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(
            _approx_equal(a, e, tol) for a, e in zip(actual, expected, strict=False)
        )
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _approx_equal(actual[k], expected[k], tol) for k in expected
        )
    try:
        import numpy as np

        return bool(np.allclose(np.asarray(actual), np.asarray(expected), rtol=tol, atol=tol))
    except Exception:
        return _compare(actual, expected, "equals", tol)


def _short_traceback(limit: int = 6) -> str:
    """Traceback with our own frames stripped.

    A player debugging their generator should not have to scroll past
    ``runner_main.py`` frames to find their own line — the error message is part
    of the teaching material.
    """
    lines = traceback.format_exc(limit=limit).splitlines()
    keep = [ln for ln in lines if "runner_main.py" not in ln]
    return "\n".join(keep)[:4000]


# ── Test execution ───────────────────────────────────────────────────────────
def _run_test(test: dict[str, Any], namespace: dict[str, Any]) -> dict[str, Any]:
    name = test.get("name", "test")
    kind = test.get("kind", "equals")
    points_max = float(test.get("points", 1.0))
    hidden = bool(test.get("hidden", False))
    outcome: dict[str, Any] = {
        "name": name,
        "passed": False,
        "hidden": hidden,
        "points": 0.0,
        "max_points": points_max,
        "expected": None,
        "actual": None,
        "message": "",
        "duration_ms": 0.0,
        "traceback": None,
    }
    started = time.perf_counter()
    buf = io.StringIO()
    try:
        if kind == "script":
            with redirect_stdout(buf):
                exec(test.get("script") or "", namespace)
            outcome["passed"] = True

        elif kind == "raises":
            expected_exc = test.get("exception") or "Exception"
            outcome["expected"] = f"raises {expected_exc}"
            try:
                with redirect_stdout(buf):
                    eval(compile(test["call"], "<test>", "eval"), namespace)
            except BaseException as exc:
                actual_name = type(exc).__name__
                outcome["actual"] = f"raised {actual_name}: {exc}"
                mro = {c.__name__ for c in type(exc).__mro__}
                outcome["passed"] = expected_exc in mro
                if not outcome["passed"]:
                    outcome["message"] = f"Expected {expected_exc}, got {actual_name}"
            else:
                outcome["actual"] = "did not raise"
                outcome["message"] = f"Expected {expected_exc} to be raised, but nothing was."

        elif kind == "stdout":
            with redirect_stdout(buf):
                exec(compile(test.get("call") or "", "<test>", "exec"), namespace)
            produced = buf.getvalue()
            expected = test.get("expect_stdout") or ""
            outcome["expected"] = expected
            outcome["actual"] = produced
            outcome["passed"] = produced.strip() == expected.strip()
            if not outcome["passed"]:
                outcome["message"] = "Printed output did not match."

        elif kind == "predicate":
            with redirect_stdout(buf):
                result = eval(compile(test["call"], "<test>", "eval"), namespace)
            scope = dict(namespace)
            scope["result"] = result
            outcome["actual"] = _safe_repr(result)
            outcome["expected"] = test.get("predicate")
            outcome["passed"] = bool(eval(compile(test["predicate"], "<predicate>", "eval"), scope))
            if not outcome["passed"]:
                outcome["message"] = f"Condition failed: {test.get('predicate')}"

        else:  # equals / approx
            with redirect_stdout(buf):
                result = eval(compile(test["call"], "<test>", "eval"), namespace)
            expected = test.get("expect")
            outcome["expected"] = _safe_repr(expected)
            outcome["actual"] = _safe_repr(result)
            outcome["passed"] = _compare(result, expected, kind, float(test.get("tolerance", 1e-6)))
            if not outcome["passed"]:
                outcome["message"] = "Returned value did not match the expected value."

    except BaseException as exc:
        outcome["passed"] = False
        outcome["message"] = f"{type(exc).__name__}: {exc}"
        outcome["traceback"] = _short_traceback()
    finally:
        outcome["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)

    if outcome["passed"]:
        outcome["points"] = points_max
    if hidden:
        # Hidden cases reveal *that* they failed and their name, never the data.
        # Otherwise a player could reconstruct the whole hidden suite by
        # submitting garbage and reading the diffs.
        outcome["expected"] = None
        outcome["actual"] = None
        if not outcome["passed"] and not outcome["message"]:
            outcome["message"] = "Hidden test failed."
    return outcome


def _benchmark(code: str, namespace: dict[str, Any], repeat: int) -> float | None:
    """Best-of-N wall time in ms. Best-of, not mean: we want the machine's
    capability, not the noise from whatever else the OS was doing."""
    if repeat <= 0 or not code:
        return None
    compiled = compile(code, "<benchmark>", "exec")
    best = float("inf")
    sink = io.StringIO()
    for _ in range(repeat):
        start = time.perf_counter()
        with redirect_stdout(sink):
            exec(compiled, namespace)
        best = min(best, time.perf_counter() - start)
    return round(best * 1000, 4)


#: A captured figure is returned inline, so it is bounded hard. 2MB of base64
#: is roughly a 1.5MB PNG — far more than a matplotlib chart needs, and small
#: enough that a submission cannot use figures as a channel for bulk data.
MAX_FIGURE_BYTES = 2 * 1024 * 1024
MAX_FIGURES = 4


def _capture_figures() -> list[dict[str, Any]]:
    """Serialise any matplotlib figures the submission left open.

    WHY THE SANDBOX RETURNS BYTES RATHER THAN UPLOADING THEM: it has no network
    and no credentials, by design. Giving it a storage connection string to
    write a PNG would hand the one process that runs hostile code a writable
    path out of its own jail. So figures travel back over the existing result
    protocol and the game server stores them.

    Failing to capture is never fatal. A challenge that produced a correct
    answer and an unserialisable figure has still passed, and turning that into
    a sandbox error would fail the player for our problem.
    """
    if "matplotlib" not in sys.modules:
        return []
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []

    figures: list[dict[str, Any]] = []
    try:
        numbers = list(plt.get_fignums())[:MAX_FIGURES]
    except Exception:
        return []

    for number in numbers:
        try:
            figure = plt.figure(number)
            buffer = io.BytesIO()
            figure.savefig(buffer, format="png", dpi=96, bbox_inches="tight")
            raw = buffer.getvalue()
            if not raw or len(raw) > MAX_FIGURE_BYTES:
                continue
            figures.append(
                {
                    "index": number,
                    "format": "png",
                    "bytes": len(raw),
                    "data": base64.b64encode(raw).decode("ascii"),
                }
            )
        except Exception:
            continue

    with contextlib.suppress(Exception):
        plt.close("all")
    return figures


def main() -> int:
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit({"status": "sandbox_error", "error_message": f"Malformed request: {exc}"})
        return 2

    timeout = float(request.get("timeout_seconds", 8.0))
    _apply_rlimits(int(request.get("memory_mb", 256)), max(1, int(timeout) + 1))
    _scrub_environment()
    _disable_network()

    max_output = int(request.get("max_output_bytes", 65536))
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    namespace: dict[str, Any] = {"__name__": "__main__", "__builtins__": builtins}
    result: dict[str, Any] = {
        "status": "ok",
        "outcomes": [],
        "stdout": "",
        "stderr": "",
        "duration_ms": 0.0,
        "timed_out": False,
        "truncated": False,
    }

    started = time.perf_counter()
    try:
        if stdin_data := request.get("stdin", ""):
            sys.stdin = io.StringIO(stdin_data)

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            if setup := request.get("setup_code"):
                exec(compile(setup, "<setup>", "exec"), namespace)
            exec(compile(request.get("code", ""), "<submission>", "exec"), namespace)

    except BaseException as exc:
        result["status"] = "error"
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)[:2000]
        result["traceback"] = _short_traceback()
    else:
        for test in request.get("tests", []):
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                result["outcomes"].append(_run_test(test, namespace))
        if any(not o["passed"] for o in result["outcomes"]):
            result["status"] = "failed"

        if request.get("benchmark_repeat"):
            try:
                with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                    result["benchmark_ms"] = _benchmark(
                        request.get("benchmark_code") or request.get("code", ""),
                        namespace,
                        int(request["benchmark_repeat"]),
                    )
            except BaseException as exc:
                result["stderr"] += f"\n[benchmark failed] {type(exc).__name__}: {exc}"

    # Captured before the timing is finalised so that savefig's cost is not
    # attributed to the player's code — the benchmark challenges compare these
    # numbers, so a stray 40ms of PNG encoding would be a measurement bug.
    result["figures"] = _capture_figures()

    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    out, truncated_out = _truncate(stdout_buf.getvalue(), max_output)
    err, truncated_err = _truncate(stderr_buf.getvalue(), max_output)
    result["stdout"], result["stderr"] = out, err
    result["truncated"] = truncated_out or truncated_err

    try:
        import resource

        result["peak_memory_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        pass

    _emit(result)
    return 0


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text, False
    head = encoded[:limit].decode("utf-8", errors="ignore")
    return head + f"\n... [output truncated at {limit} bytes]", True


def _emit(payload: dict[str, Any]) -> None:
    sys.__stdout__.write("\n" + RESULT_SENTINEL + "\n")
    sys.__stdout__.write(json.dumps(payload, default=str))
    sys.__stdout__.flush()


if __name__ == "__main__":
    raise SystemExit(main())
