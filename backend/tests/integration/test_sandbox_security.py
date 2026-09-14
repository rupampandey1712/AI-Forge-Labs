"""Sandbox behaviour and its security posture.

These tests encode the *contract* of the sandbox. If one of them starts failing,
untrusted code has gained a capability it should not have — treat it as a
security incident, not a flaky test.

Scope note: they verify the properties the subprocess backend actually
guarantees (isolation of the process, scrubbed environment, wall-clock kill,
blocked imports, bounded output). They deliberately do not claim the subprocess
backend is a hard security boundary — see ``app/sandbox/runner_main.py`` for why
``SANDBOX_MODE=docker`` is the deployable answer.
"""

from __future__ import annotations

import pytest

from app.sandbox.protocol import ExecStatus, TestCase, TestKind
from app.sandbox.service import SandboxService, StaticCheckFailed, static_prescreen

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
def sandbox() -> SandboxService:
    return SandboxService()


class TestCorrectness:
    async def test_passing_solution(self, sandbox):
        result = await sandbox.run(
            "def add(a, b):\n    return a + b",
            tests=[TestCase(name="adds", call="add(2, 3)", expect=5)],
        )
        assert result.status is ExecStatus.OK
        assert result.passed
        assert result.score == 1.0

    async def test_failing_solution_reports_the_diff(self, sandbox):
        result = await sandbox.run(
            "def add(a, b):\n    return a * b",
            tests=[TestCase(name="adds", call="add(2, 3)", expect=5)],
        )
        assert result.status is ExecStatus.FAILED
        outcome = result.outcomes[0]
        assert outcome.expected == "5"
        assert outcome.actual == "6"

    async def test_partial_credit_is_weighted_by_points(self, sandbox):
        result = await sandbox.run(
            "def f(x):\n    return x if x > 0 else 0",
            tests=[
                TestCase(name="positive", call="f(5)", expect=5, points=1.0),
                TestCase(name="negative", call="f(-5)", expect=-5, points=3.0),
            ],
        )
        assert result.score == pytest.approx(0.25), "points must weight the score"

    async def test_raises_kind(self, sandbox):
        code = "def f(x):\n    if x < 0:\n        raise ValueError('neg')\n    return x"
        good = await sandbox.run(
            code,
            tests=[
                TestCase(name="raises", kind=TestKind.RAISES, call="f(-1)", exception="ValueError")
            ],
        )
        assert good.passed

        bad = await sandbox.run(
            "def f(x):\n    return x",
            tests=[
                TestCase(name="raises", kind=TestKind.RAISES, call="f(-1)", exception="ValueError")
            ],
        )
        assert not bad.passed
        assert "did not raise" in bad.outcomes[0].actual

    async def test_predicate_kind_allows_many_correct_answers(self, sandbox):
        result = await sandbox.run(
            "def gen(n):\n    return (i for i in range(n))",
            tests=[
                TestCase(
                    name="is a generator",
                    kind=TestKind.PREDICATE,
                    call="gen(3)",
                    predicate="hasattr(result, '__next__')",
                )
            ],
        )
        assert result.passed

    async def test_error_before_tests_is_reported_cleanly(self, sandbox):
        result = await sandbox.run("raise ValueError('boom')")
        assert result.status is ExecStatus.ERROR
        assert result.error_type == "ValueError"
        assert "boom" in result.error_message

    async def test_traceback_excludes_our_runner_frames(self, sandbox):
        """The player should see their own line, not runner_main.py."""
        result = await sandbox.run("def f():\n    return 1/0\nf()")
        assert result.traceback
        assert "runner_main.py" not in result.traceback

    async def test_stdout_is_captured(self, sandbox):
        result = await sandbox.run("print('hello from the sandbox')")
        assert "hello from the sandbox" in result.stdout


class TestIsolation:
    async def test_secrets_are_not_inherited(self, sandbox):
        """A print(os.environ) must never be a credential dump."""
        result = await sandbox.run(
            "import os\n"
            "leaked = [k for k in os.environ if k in "
            "('SECRET_KEY','DATABASE_URL','ANTHROPIC_API_KEY','GEMINI_API_KEY','OPENAI_API_KEY')]\n"
            "print(leaked)"
        )
        assert result.stdout.strip() == "[]"

    async def test_infinite_loop_is_killed(self, sandbox):
        result = await sandbox.run("while True:\n    pass", timeout_seconds=2)
        assert result.status is ExecStatus.TIMEOUT
        assert result.timed_out
        assert result.error_message, "a timeout must explain the usual causes"

    async def test_deep_recursion_does_not_crash_the_server(self, sandbox):
        result = await sandbox.run("def f(n):\n    return f(n+1)\nf(0)", timeout_seconds=5)
        assert result.status in (ExecStatus.ERROR, ExecStatus.TIMEOUT, ExecStatus.MEMORY)

    async def test_output_is_bounded(self, sandbox):
        result = await sandbox.run("for _ in range(200000):\n    print('x' * 100)")
        assert len(result.stdout.encode()) <= sandbox.cfg.sandbox_max_output_bytes + 1000
        assert result.truncated

    async def test_the_game_process_is_unaffected_by_a_crash(self, sandbox):
        """Execution happens in a separate process — the API must survive anything."""
        await sandbox.run("import sys; sys.exit(1)")
        follow_up = await sandbox.run(
            "def f():\n    return 42", tests=[TestCase(name="ok", call="f()", expect=42)]
        )
        assert follow_up.passed, "the sandbox must recover from a crashed submission"

    async def test_concurrent_executions_are_admitted_safely(self, sandbox):
        """Admission control: many submissions must not fork unbounded processes."""
        import asyncio

        results = await asyncio.gather(
            *[
                sandbox.run(
                    "def f():\n    return 1", tests=[TestCase(name="t", call="f()", expect=1)]
                )
                for _ in range(8)
            ]
        )
        assert all(r.passed for r in results)


class TestStaticPrescreen:
    @pytest.mark.parametrize(
        "code",
        [
            "import socket",
            "import subprocess",
            "from urllib import request",
            "import ctypes",
            "import multiprocessing",
            "().__class__.__subclasses__()",
            "print(__import__('os'))",
        ],
    )
    def test_blocks_hostile_patterns(self, code):
        with pytest.raises(StaticCheckFailed):
            static_prescreen(code)

    @pytest.mark.parametrize(
        "code",
        [
            "import os\nprint(os.getcwd())",
            "import sys\nprint(sys.version)",
            "import json, math, itertools, collections, functools, dataclasses",
            "import asyncio\nasync def f(): pass",
            "class A:\n    def __eq__(self, other): return True",
        ],
    )
    def test_allows_legitimate_code(self, code):
        """Over-blocking teaches players to write worse Python to please the grader."""
        static_prescreen(code)

    def test_syntax_error_is_not_treated_as_an_attack(self):
        with pytest.raises(StaticCheckFailed) as exc:
            static_prescreen("def f(:\n    pass")
        assert "SyntaxError" in exc.value.reason
        assert exc.value.line is not None

    def test_oversized_submission_is_refused(self):
        with pytest.raises(StaticCheckFailed):
            static_prescreen("x = 1\n" * 200_000)

    async def test_blocked_import_produces_a_helpful_message(self, sandbox):
        result = await sandbox.run("import socket")
        assert result.status is ExecStatus.ERROR
        assert "socket" in result.error_message
        assert "sandbox" in result.error_message.lower()


class TestBenchmarking:
    async def test_measures_a_real_speedup(self, sandbox):
        baseline, candidate, speedup = await sandbox.benchmark_pair(
            "total = 0\nfor i in range(200000):\n    total += i",
            "total = sum(range(200000))",
            repeat=3,
        )
        assert baseline and candidate
        assert speedup and speedup > 1.0, "the vectorised version must measure faster"

    async def test_benchmark_of_identical_code_is_near_one(self, sandbox):
        code = "total = sum(range(50000))"
        _b, _c, speedup = await sandbox.benchmark_pair(code, code, repeat=5)
        assert speedup is not None
        assert 0.3 < speedup < 3.0, "identical code must not report a large speedup"


def test_runner_sentinel_matches_the_protocol():
    """The runner is standalone (no app imports), so the sentinel is duplicated.
    This test is the guard that keeps the two copies in sync."""
    from app.sandbox import runner_main
    from app.sandbox.protocol import RESULT_SENTINEL

    assert runner_main.RESULT_SENTINEL == RESULT_SENTINEL


def test_runner_imports_nothing_from_the_app():
    """The runner must stay copyable into a minimal container with no app code."""
    import ast
    import pathlib

    source = pathlib.Path("app/sandbox/runner_main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("app") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app")
