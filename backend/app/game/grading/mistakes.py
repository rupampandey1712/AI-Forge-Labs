"""The Mistake Detector (spec §44).

Static analysis of submitted code that recognises *named engineering mistakes*
rather than style nits. Each detection produces a reusable ``pattern`` id, and
the mistake database then targets the pattern — so a player who blocks the
event loop once gets async missions, not a repeat of that exact exercise.

WHY AST and not regex: ``time.sleep(1)`` inside an ``async def`` is a serious
bug; the identical text inside a sync helper is correct code. Only a parse tree
knows the difference, and a grader that cries wolf is one players learn to
ignore.

Every pattern carries the four fields the mistake record needs — what, why,
the fix, and severity — because "you made mistake #17" teaches nothing.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Severity


@dataclass(slots=True)
class DetectedMistake:
    pattern: str
    title: str
    description: str
    why_it_matters: str
    correct_approach: str
    severity: Severity
    line: int | None = None
    concept_slug: str | None = None
    category: str | None = None
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "title": self.title,
            "description": self.description,
            "why_it_matters": self.why_it_matters,
            "correct_approach": self.correct_approach,
            "severity": self.severity.value,
            "line": self.line,
            "concept_slug": self.concept_slug,
            "category": self.category,
            "evidence": self.evidence,
        }


BLOCKING_CALLS = {
    ("time", "sleep"): "time.sleep()",
    ("requests", "get"): "requests.get()",
    ("requests", "post"): "requests.post()",
    ("subprocess", "run"): "subprocess.run()",
    ("subprocess", "check_output"): "subprocess.check_output()",
    ("os", "system"): "os.system()",
}


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: list[DetectedMistake] = []
        self._async_depth = 0
        self._loop_depth = 0
        self._function_stack: list[ast.AST] = []

    # ── async correctness ────────────────────────────────────────────────
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._async_depth += 1
        self._function_stack.append(node)
        self._check_mutable_defaults(node)
        self.generic_visit(node)
        self._function_stack.pop()
        self._async_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node)
        self._check_mutable_defaults(node)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            key = (func.value.id, func.attr)
            if self._async_depth and key in BLOCKING_CALLS:
                name = BLOCKING_CALLS[key]
                self.found.append(
                    DetectedMistake(
                        pattern="blocking_call_in_async",
                        title=f"{name} blocks the event loop",
                        description=(
                            f"`{name}` is a synchronous call made inside an `async def`. "
                            "While it runs, the event loop cannot service any other task."
                        ),
                        why_it_matters=(
                            "One blocking call in one endpoint stalls *every* concurrent "
                            "request on that worker. This is the single most common reason "
                            "an async service is slower under load than the sync version it "
                            "replaced — and it does not show up in local testing with one user."
                        ),
                        correct_approach=(
                            "Use the async equivalent (`await asyncio.sleep(...)`, an async "
                            "HTTP client), or push genuinely blocking work off the loop with "
                            "`await asyncio.to_thread(...)` / a worker queue."
                        ),
                        severity=Severity.CRITICAL,
                        line=node.lineno,
                        concept_slug="python-asyncio-event-loop",
                        category="python",
                        evidence=name,
                    )
                )
            # pandas: iterrows is a row-at-a-time Python loop over a DataFrame
            if func.attr == "iterrows":
                self.found.append(
                    DetectedMistake(
                        pattern="pandas_iterrows",
                        title="Row-by-row iteration over a DataFrame",
                        description="`.iterrows()` materialises a Series per row in Python.",
                        why_it_matters=(
                            "It is typically 50-200x slower than the vectorised equivalent and "
                            "loses dtype information on every row. A pipeline that takes 40 "
                            "minutes usually has an `iterrows` at the centre of it."
                        ),
                        correct_approach=(
                            "Express the operation over whole columns, or use `.apply` on a "
                            "column, `.map`, `np.where`, or a merge — in that order of preference."
                        ),
                        severity=Severity.HIGH,
                        line=node.lineno,
                        concept_slug="pandas-vectorization",
                        category="pandas",
                        evidence=".iterrows()",
                    )
                )
        if isinstance(func, ast.Name) and func.id == "eval":
            self.found.append(
                DetectedMistake(
                    pattern="eval_on_input",
                    title="eval() on untrusted input",
                    description="`eval` executes arbitrary code.",
                    why_it_matters="It turns any string you do not fully control into remote code execution.",
                    correct_approach="Use `ast.literal_eval`, `json.loads`, or an explicit parser.",
                    severity=Severity.CRITICAL,
                    line=node.lineno,
                    category="security",
                    evidence="eval(",
                )
            )
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        """A bare coroutine call: ``fetch()`` where ``await fetch()`` was meant."""
        if isinstance(node.value, ast.Call) and self._async_depth:
            f = node.value.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            # Heuristic, deliberately narrow: only flag names that read as
            # awaitable I/O, so we do not warn on every ordinary helper call.
            if any(
                name.startswith(p)
                for p in ("fetch", "get_", "load_", "save_", "send_", "query_", "read_", "write_")
            ):
                self.found.append(
                    DetectedMistake(
                        pattern="missing_await",
                        title=f"`{name}(...)` result is discarded — did you mean `await`?",
                        description="A coroutine call whose result is never awaited never runs.",
                        why_it_matters=(
                            "Python creates the coroutine object and throws it away. The code "
                            "appears to succeed, the work silently never happens, and you get "
                            "a 'coroutine was never awaited' warning buried in the logs."
                        ),
                        correct_approach="`await name(...)`, or `asyncio.create_task(...)` if you genuinely want it in the background.",
                        severity=Severity.HIGH,
                        line=node.lineno,
                        concept_slug="python-asyncio-coroutines",
                        category="python",
                        evidence=name,
                    )
                )
        self.generic_visit(node)

    # ── general correctness ──────────────────────────────────────────────
    def _check_mutable_defaults(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d]]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id in {"list", "dict", "set"}
            ):
                self.found.append(
                    DetectedMistake(
                        pattern="mutable_default_argument",
                        title="Mutable default argument",
                        description=f"`{node.name}` has a mutable default value.",
                        why_it_matters=(
                            "Defaults are evaluated once, at function definition. Every call "
                            "that relies on the default shares the same object, so state leaks "
                            "between unrelated calls — a bug that only appears on the second call."
                        ),
                        correct_approach="Default to `None` and create the container inside the function body.",
                        severity=Severity.HIGH,
                        line=node.lineno,
                        concept_slug="python-functions-arguments",
                        category="python",
                        evidence=f"def {node.name}(...)",
                    )
                )
                return

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        swallowed = all(isinstance(stmt, ast.Pass) for stmt in node.body)
        if node.type is None:
            self.found.append(
                DetectedMistake(
                    pattern="bare_except",
                    title="Bare `except:`",
                    description="A bare except catches everything, including KeyboardInterrupt and SystemExit.",
                    why_it_matters=(
                        "You cannot Ctrl-C the process, and a genuine bug becomes an invisible "
                        "no-op. Bare excepts are how a service ends up 'running' while doing nothing."
                    ),
                    correct_approach="Catch the narrowest exception you can actually handle.",
                    severity=Severity.HIGH,
                    line=node.lineno,
                    concept_slug="python-exceptions",
                    category="python",
                    evidence="except:",
                )
            )
        elif swallowed:
            self.found.append(
                DetectedMistake(
                    pattern="swallowed_exception",
                    title="Exception caught and discarded",
                    description="`except ...: pass` hides the failure entirely.",
                    why_it_matters=(
                        "The system keeps going in a state you did not design for, and the "
                        "eventual incident has no log line pointing at the cause."
                    ),
                    correct_approach="Log it with context, re-raise, or handle it — but do not pretend it did not happen.",
                    severity=Severity.MEDIUM,
                    line=node.lineno,
                    concept_slug="python-exceptions",
                    category="python",
                    evidence="except ...: pass",
                )
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            if (
                isinstance(op, (ast.Eq, ast.NotEq))
                and isinstance(comparator, ast.Constant)
                and (comparator.value is None or isinstance(comparator.value, bool))
            ):
                self.found.append(
                    DetectedMistake(
                        pattern="equality_with_singleton",
                        title="`== None` / `== True` instead of `is`",
                        description="Singletons should be compared by identity.",
                        why_it_matters=(
                            "`==` invokes `__eq__`, which a custom class (or a NumPy array, "
                            "or a pandas Series) can override — turning a simple None check "
                            "into an exception or an array of booleans."
                        ),
                        correct_approach="Use `is None` / `is not None`, and prefer plain truthiness to `== True`.",
                        severity=Severity.LOW,
                        line=node.lineno,
                        concept_slug="python-object-identity",
                        category="python",
                        evidence="== None",
                    )
                )
        self.generic_visit(node)

    # ── performance ──────────────────────────────────────────────────────
    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self._check_string_concat_in_loop(node)
        self._check_query_in_loop(node)
        self.generic_visit(node)
        self._loop_depth -= 1

    def _check_string_concat_in_loop(self, node: ast.For) -> None:
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.AugAssign)
                and isinstance(stmt.op, ast.Add)
                and isinstance(stmt.target, ast.Name)
                and isinstance(stmt.value, (ast.Constant, ast.JoinedStr))
                and (not isinstance(stmt.value, ast.Constant) or isinstance(stmt.value.value, str))
            ):
                self.found.append(
                    DetectedMistake(
                        pattern="string_concat_in_loop",
                        title="String built by repeated concatenation",
                        description="`s += ...` inside a loop rebuilds the whole string each pass.",
                        why_it_matters=(
                            "Strings are immutable, so this is O(n²) in the length of the "
                            "output. It is invisible on 100 items and catastrophic on 100,000."
                        ),
                        correct_approach="Append to a list and `''.join(parts)` once at the end.",
                        severity=Severity.MEDIUM,
                        line=stmt.lineno,
                        concept_slug="python-performance-strings",
                        category="python",
                        evidence="s += ...",
                    )
                )
                return

    def _check_query_in_loop(self, node: ast.For) -> None:
        """The N+1 signature: a database call inside an iteration."""
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Call):
                f = stmt.func
                attr = f.attr if isinstance(f, ast.Attribute) else ""
                if attr in {"execute", "query", "get", "scalar", "scalars", "first", "all"} and (
                    isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name)
                    and f.value.id in {"session", "db", "conn", "connection", "cursor"}
                ):
                    self.found.append(
                        DetectedMistake(
                            pattern="n_plus_one_query",
                            title="Database query inside a loop (N+1)",
                            description="Each iteration issues its own round trip to the database.",
                            why_it_matters=(
                                "100 parent rows become 101 queries. Latency is dominated by "
                                "round trips, not by the work, so the endpoint gets ~100x slower "
                                "with no change in CPU — and it only shows up once production "
                                "data is larger than your fixtures."
                            ),
                            correct_approach=(
                                "Fetch the children in one query (`selectinload`/`joinedload`, or "
                                "a single `WHERE id IN (...)`) and group in memory."
                            ),
                            severity=Severity.CRITICAL,
                            line=stmt.lineno,
                            concept_slug="sqlalchemy-n-plus-one",
                            category="sqlalchemy",
                            evidence=f"{f.value.id}.{attr}(...) in loop",
                        )
                    )
                    return


def detect_mistakes(code: str, *, category_hint: str | None = None) -> list[DetectedMistake]:
    """Return every mistake pattern found in ``code``.

    Never raises: a syntax error is the player's immediate feedback from the
    sandbox, not something the mistake tracker should also blow up on.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    visitor = _Visitor()
    visitor.visit(tree)

    # De-duplicate by pattern: three mutable defaults in one file is one lesson,
    # and three identical cards would bury the other findings.
    seen: dict[str, DetectedMistake] = {}
    for mistake in visitor.found:
        if mistake.pattern not in seen:
            if category_hint and mistake.category is None:
                mistake.category = category_hint
            seen[mistake.pattern] = mistake
    return list(seen.values())


@dataclass(slots=True)
class MistakeSummary:
    detected: list[DetectedMistake] = field(default_factory=list)
    critical_count: int = 0

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0

    @property
    def code_quality_score(self) -> float:
        """0..1 penalty-based quality score used for the clean-code XP bonus.

        Passing tests with a critical defect in the code should not earn the
        clean-code bonus — that is precisely the habit the game is trying not
        to reinforce.
        """
        penalty = 0.0
        for m in self.detected:
            penalty += {
                Severity.CRITICAL: 0.5,
                Severity.HIGH: 0.3,
                Severity.MEDIUM: 0.15,
                Severity.LOW: 0.05,
            }[m.severity]
        return round(max(0.0, 1.0 - penalty), 4)


def summarise(code: str, *, category_hint: str | None = None) -> MistakeSummary:
    found = detect_mistakes(code, category_hint=category_hint)
    return MistakeSummary(
        detected=found,
        critical_count=sum(1 for m in found if m.severity == Severity.CRITICAL),
    )
