"""The wire contract between the game server and the execution sandbox.

WHY a serialisable protocol rather than direct function calls: it is the seam
that makes isolation possible. Everything crossing it is plain JSON, so the
sandbox can be a subprocess today, a container tomorrow and a remote worker
pool later without the game server changing a line. If the sandbox could accept
a Python callable, that portability — and the isolation — would be gone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

PROTOCOL_VERSION = 1
#: Runner stdout is mixed with whatever the player's code prints, so the JSON
#: result is framed by a sentinel the player is vanishingly unlikely to emit.
RESULT_SENTINEL = "<<<AIFORGE_RESULT_V1>>>"


class TestKind(StrEnum):
    # pytest collects any class named Test*; these are domain types, not tests.
    __test__ = False

    EQUALS = "equals"
    APPROX = "approx"
    RAISES = "raises"
    PREDICATE = "predicate"
    SCRIPT = "script"
    STDOUT = "stdout"


class ExecStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"  # ran, but tests did not pass
    ERROR = "error"  # user code raised at import/definition time
    TIMEOUT = "timeout"
    MEMORY = "memory_exceeded"
    SANDBOX_ERROR = "sandbox_error"  # our fault, not the player's


@dataclass(slots=True)
class TestCase:
    __test__ = False  # not a pytest class — see TestKind

    name: str
    kind: TestKind = TestKind.EQUALS
    call: str | None = None
    expect: Any = None
    exception: str | None = None
    predicate: str | None = None
    script: str | None = None
    expect_stdout: str | None = None
    tolerance: float = 1e-6
    points: float = 1.0
    hidden: bool = False
    description: str = ""
    timeout_seconds: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        known = set(cls.__slots__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(slots=True)
class TestOutcome:
    __test__ = False

    name: str
    passed: bool
    hidden: bool = False
    points: float = 0.0
    max_points: float = 1.0
    expected: str | None = None
    actual: str | None = None
    message: str = ""
    duration_ms: float = 0.0
    traceback: str | None = None


@dataclass(slots=True)
class ExecutionRequest:
    code: str
    setup_code: str = ""
    tests: list[TestCase] = field(default_factory=list)
    stdin: str = ""
    timeout_seconds: float = 8.0
    memory_mb: int = 256
    max_output_bytes: int = 64 * 1024
    #: Benchmarks run the body N times and report the best wall time, which is
    #: what makes "your NumPy version is 23x faster" a measurement, not a claim.
    benchmark_repeat: int = 0
    benchmark_code: str | None = None
    allow_packages: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tests"] = [
            {**asdict(t), "kind": str(t.kind)} if isinstance(t, TestCase) else t for t in self.tests
        ]
        d["protocol_version"] = PROTOCOL_VERSION
        return d


@dataclass(slots=True)
class ExecutionResult:
    status: ExecStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: float = 0.0
    timed_out: bool = False
    peak_memory_kb: int | None = None
    outcomes: list[TestOutcome] = field(default_factory=list)
    error_type: str | None = None
    error_message: str = ""
    traceback: str | None = None
    benchmark_ms: float | None = None
    truncated: bool = False

    @property
    def tests_total(self) -> int:
        return len(self.outcomes)

    @property
    def tests_passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def points(self) -> float:
        return sum(o.points for o in self.outcomes)

    @property
    def max_points(self) -> float:
        return sum(o.max_points for o in self.outcomes)

    @property
    def score(self) -> float:
        """Normalised 0..1. Weighted by points so a hard hidden case can count
        for more than a smoke test."""
        mx = self.max_points
        return round(self.points / mx, 4) if mx else 0.0

    @property
    def passed(self) -> bool:
        return (
            self.status == ExecStatus.OK
            and self.tests_total > 0
            and self.tests_passed == self.tests_total
        )

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> ExecutionResult:
        outcomes = [TestOutcome(**o) for o in data.get("outcomes", [])]
        return cls(
            status=ExecStatus(data.get("status", "sandbox_error")),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code"),
            duration_ms=data.get("duration_ms", 0.0),
            timed_out=data.get("timed_out", False),
            peak_memory_kb=data.get("peak_memory_kb"),
            outcomes=outcomes,
            error_type=data.get("error_type"),
            error_message=data.get("error_message", ""),
            traceback=data.get("traceback"),
            benchmark_ms=data.get("benchmark_ms"),
            truncated=data.get("truncated", False),
        )
