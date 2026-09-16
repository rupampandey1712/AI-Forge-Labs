"""A LangGraph-style state machine, built from first principles.

WHY implement it rather than import LangGraph: the Agent Factory's whole point
is that a player must be able to *see* why an agent looped forever, where state
mutated, and which edge fired. Importing a framework makes those the framework's
internals. Three hundred lines of explicit state machine makes them the lesson.

The API is deliberately LangGraph-shaped (`add_node`, `add_edge`,
`add_conditional_edges`, `START`, `END`, `recursion_limit`, `interrupt_before`)
so everything transfers directly.

WHAT IS MODELLED, and why each one matters:

* **Typed state with reducers** — nodes return a *partial* update, not a whole
  state. Without that, two nodes writing the same key silently clobber each
  other and the bug is invisible.
* **Conditional edges** — routing as data, so the graph is inspectable before
  it runs.
* **Recursion limit** — every agent loops eventually. A guard turns "the agent
  hung and burned $400" into a clean, diagnosable halt.
* **Checkpoints** — the full state at every step, which is the only way graph
  debugging ever clicks.
* **Interrupts (human-in-the-loop)** — pause before a node, surface it, resume.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.logging import get_logger

log = get_logger(__name__)

START = "__start__"
END = "__end__"

State = dict[str, Any]
NodeFn = Callable[[State], Awaitable[State] | State]
RouterFn = Callable[[State], str]
#: How two writes to the same state key are combined.
Reducer = Callable[[Any, Any], Any]


# ── Reducers ─────────────────────────────────────────────────────────────────
def replace(_old: Any, new: Any) -> Any:
    """Last write wins. The default, and the right choice for scalars."""
    return new


def append(old: Any, new: Any) -> Any:
    """Accumulate into a list — the reducer for message history.

    This is why an agent's `messages` key grows instead of being overwritten by
    whichever node ran last. Getting this wrong is the single most common
    LangGraph bug, and it presents as "the agent forgot everything".
    """
    if old is None:
        return list(new) if isinstance(new, list) else [new]
    base = list(old) if isinstance(old, list) else [old]
    return base + (list(new) if isinstance(new, list) else [new])


def merge(old: Any, new: Any) -> Any:
    """Shallow dict merge — for accumulating metadata."""
    if not isinstance(old, dict):
        return new
    return {**old, **(new if isinstance(new, dict) else {})}


def add(old: Any, new: Any) -> Any:
    """Numeric accumulation — token counts, costs, retry tallies."""
    return (old or 0) + (new or 0)


# ── Records ──────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class StepRecord:
    """One node execution. The Inspector renders exactly this."""

    step: int
    node: str
    status: Literal["ok", "error", "interrupted", "skipped"]
    duration_ms: float
    state_before: State
    state_after: State
    state_diff: dict[str, Any]
    edge_taken: str | None = None
    edge_reason: str | None = None
    error: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "node": self.node,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "state_diff": _jsonable(self.state_diff),
            "state_after": _jsonable(self.state_after),
            "edge_taken": self.edge_taken,
            "edge_reason": self.edge_reason,
            "error": self.error,
            "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass(slots=True)
class GraphRun:
    status: Literal["completed", "halted", "error", "interrupted"]
    final_state: State
    history: list[StepRecord] = field(default_factory=list)
    halted_reason: str | None = None
    interrupted_at: str | None = None
    steps: int = 0
    total_ms: float = 0.0
    node_visits: dict[str, int] = field(default_factory=dict)

    @property
    def looped(self) -> bool:
        """True when any node ran more than twice — the infinite-loop smell."""
        return any(count > 2 for count in self.node_visits.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "final_state": _jsonable(self.final_state),
            "history": [record.to_dict() for record in self.history],
            "halted_reason": self.halted_reason,
            "interrupted_at": self.interrupted_at,
            "steps": self.steps,
            "total_ms": round(self.total_ms, 2),
            "node_visits": self.node_visits,
            "looped": self.looped,
        }


@dataclass(slots=True)
class NodeSpec:
    name: str
    fn: NodeFn
    description: str = ""
    #: Rendered as the node's badge in the Inspector.
    kind: str = "process"
    interrupt_before: bool = False


@dataclass(slots=True)
class ConditionalEdge:
    source: str
    router: RouterFn
    mapping: dict[str, str]
    description: str = ""


class GraphError(RuntimeError):
    """A graph that cannot be executed — a construction bug, not a runtime one."""


# ── The graph ────────────────────────────────────────────────────────────────
class StateGraph:
    """Build, validate and run a state machine.

    ``compile()`` is separate from ``run()`` on purpose: an unreachable node or
    an edge to nowhere is a *construction* error, and finding it at build time
    beats discovering it three steps into a production run.
    """

    # ``Mapping`` rather than ``dict``: dict is invariant in its value type, so a
    # caller's ``dict[str, Callable[[Any, Any], Any]]`` would not satisfy
    # ``dict[str, Reducer]``. We only ever read from it, so the covariant type
    # is both more permissive and more honest about what we do with it.
    def __init__(
        self, *, reducers: Mapping[str, Reducer] | None = None, name: str = "graph"
    ) -> None:
        self.name = name
        self.nodes: dict[str, NodeSpec] = {}
        self.edges: dict[str, str] = {}
        self.conditional_edges: dict[str, ConditionalEdge] = {}
        self.entry: str | None = None
        self.reducers: dict[str, Reducer] = dict(reducers or {})
        self._compiled = False

    # -- construction ---------------------------------------------------
    def add_node(
        self,
        name: str,
        fn: NodeFn,
        *,
        description: str = "",
        kind: str = "process",
        interrupt_before: bool = False,
    ) -> StateGraph:
        if name in (START, END):
            raise GraphError(f"'{name}' is reserved")
        if name in self.nodes:
            raise GraphError(f"duplicate node '{name}'")
        self.nodes[name] = NodeSpec(name, fn, description, kind, interrupt_before)
        self._compiled = False
        return self

    def add_edge(self, source: str, target: str) -> StateGraph:
        if source in self.conditional_edges:
            raise GraphError(f"'{source}' already has conditional edges; a node cannot have both")
        self.edges[source] = target
        self._compiled = False
        return self

    def add_conditional_edges(
        self, source: str, router: RouterFn, mapping: dict[str, str], *, description: str = ""
    ) -> StateGraph:
        if source in self.edges:
            raise GraphError(f"'{source}' already has a static edge")
        self.conditional_edges[source] = ConditionalEdge(source, router, mapping, description)
        self._compiled = False
        return self

    def set_entry_point(self, name: str) -> StateGraph:
        self.entry = name
        self._compiled = False
        return self

    # -- validation -----------------------------------------------------
    def compile(self) -> StateGraph:
        """Validate the graph. Raises on anything that cannot execute."""
        if not self.nodes:
            raise GraphError("graph has no nodes")
        if self.entry is None:
            raise GraphError("no entry point set")
        if self.entry not in self.nodes:
            raise GraphError(f"entry point '{self.entry}' is not a node")

        known = set(self.nodes) | {END}
        for source, target in self.edges.items():
            if source not in self.nodes:
                raise GraphError(f"edge from unknown node '{source}'")
            if target not in known:
                raise GraphError(f"edge '{source}' -> unknown target '{target}'")

        for source, edge in self.conditional_edges.items():
            if source not in self.nodes:
                raise GraphError(f"conditional edge from unknown node '{source}'")
            for label, target in edge.mapping.items():
                if target not in known:
                    raise GraphError(
                        f"conditional edge '{source}' [{label}] -> unknown target '{target}'"
                    )

        dangling = [
            name
            for name in self.nodes
            if name not in self.edges and name not in self.conditional_edges
        ]
        if dangling:
            # A node with no outgoing edge silently ends the run. That is almost
            # never intended, and it is invisible until you wonder why the agent
            # stopped early.
            raise GraphError(
                f"nodes with no outgoing edge (add an edge to END if deliberate): {dangling}"
            )

        unreachable = self._unreachable()
        if unreachable:
            raise GraphError(f"unreachable nodes: {sorted(unreachable)}")

        self._compiled = True
        return self

    def _unreachable(self) -> set[str]:
        reachable: set[str] = set()
        frontier = [self.entry] if self.entry else []
        while frontier:
            current = frontier.pop()
            if current in reachable or current == END:
                continue
            reachable.add(current)
            if current in self.edges:
                frontier.append(self.edges[current])
            if current in self.conditional_edges:
                frontier.extend(self.conditional_edges[current].mapping.values())
        return set(self.nodes) - reachable

    # -- introspection ---------------------------------------------------
    def to_diagram(self) -> dict[str, Any]:
        """Serialise the topology for the Inspector — before any run.

        Being able to see the graph *without executing it* is the difference
        between debugging a diagram and debugging a stack trace.
        """
        nodes = [
            {
                "id": name,
                "label": name.replace("_", " ").title(),
                "kind": spec.kind,
                "description": spec.description,
                "interrupt_before": spec.interrupt_before,
                "is_entry": name == self.entry,
            }
            for name, spec in self.nodes.items()
        ]
        nodes.append({"id": END, "label": "END", "kind": "terminal", "description": ""})

        edges = [
            {"source": s, "target": t, "kind": "static", "label": ""} for s, t in self.edges.items()
        ]
        for source, edge in self.conditional_edges.items():
            edges.extend(
                {
                    "source": source,
                    "target": target,
                    "kind": "conditional",
                    "label": label,
                    "description": edge.description,
                }
                for label, target in edge.mapping.items()
            )
        return {"name": self.name, "entry": self.entry, "nodes": nodes, "edges": edges}

    def find_cycles(self) -> list[list[str]]:
        """Every cycle in the graph.

        A cycle is not a bug — retry loops and reflection loops are cycles. It
        *is* a place that needs a termination argument, and the Agent Factory
        asks the player to make that argument for each one found here.
        """
        cycles: list[list[str]] = []
        state: dict[str, int] = {}

        def successors(node: str) -> list[str]:
            out = []
            if node in self.edges:
                out.append(self.edges[node])
            if node in self.conditional_edges:
                out.extend(self.conditional_edges[node].mapping.values())
            return [n for n in out if n != END]

        def visit(node: str, path: list[str]) -> None:
            if state.get(node) == 1:
                cycles.append([*path[path.index(node) :], node])
                return
            if state.get(node) == 2:
                return
            state[node] = 1
            for nxt in successors(node):
                visit(nxt, [*path, node])
            state[node] = 2

        if self.entry:
            visit(self.entry, [])
        return cycles

    # -- execution -------------------------------------------------------
    def _apply(self, state: State, update: State) -> tuple[State, dict[str, Any]]:
        """Fold a node's partial update into the state via its reducers."""
        new_state = dict(state)
        diff: dict[str, Any] = {}
        for key, value in (update or {}).items():
            reducer = self.reducers.get(key, replace)
            before = new_state.get(key)
            after = reducer(before, value)
            new_state[key] = after
            if before != after:
                diff[key] = {"before": _jsonable(before), "after": _jsonable(after)}
        return new_state, diff

    async def run(
        self,
        initial_state: State,
        *,
        recursion_limit: int = 25,
        resume_from: State | None = None,
        resume_at: str | None = None,
        skip_interrupts: bool = False,
    ) -> GraphRun:
        """Execute until END, the recursion limit, an error or an interrupt."""
        if not self._compiled:
            self.compile()

        state: State = dict(resume_from or initial_state)
        current = resume_at or self.entry
        history: list[StepRecord] = []
        visits: dict[str, int] = {}
        started = time.perf_counter()
        step = 0

        while current and current != END:
            if step >= recursion_limit:
                # The guard that turns a runaway agent into a diagnosable halt.
                # Without it this is the "$400 overnight" story every team has.
                log.warning("agent.recursion_limit", graph=self.name, node=current, steps=step)
                return GraphRun(
                    status="halted",
                    final_state=state,
                    history=history,
                    halted_reason=(
                        f"Recursion limit of {recursion_limit} steps reached at '{current}'. "
                        f"Node visit counts: {visits}. A node visited many times means a "
                        f"conditional edge is never routing to END."
                    ),
                    steps=step,
                    total_ms=(time.perf_counter() - started) * 1000,
                    node_visits=visits,
                )

            spec = self.nodes[current]

            if spec.interrupt_before and not skip_interrupts and current != resume_at:
                return GraphRun(
                    status="interrupted",
                    final_state=state,
                    history=history,
                    interrupted_at=current,
                    steps=step,
                    total_ms=(time.perf_counter() - started) * 1000,
                    node_visits=visits,
                )

            visits[current] = visits.get(current, 0) + 1
            before = dict(state)
            node_started = time.perf_counter()

            try:
                result = spec.fn(state)
                update = await result if hasattr(result, "__await__") else result
                state, diff = self._apply(state, update or {})
                status: Literal["ok", "error"] = "ok"
                error = None
            except Exception as exc:  # a node failure must not kill the run
                diff = {}
                status = "error"
                error = f"{type(exc).__name__}: {exc}"
                log.exception("agent.node_failed", graph=self.name, node=current)

            duration = (time.perf_counter() - node_started) * 1000
            next_node, reason = self._next(current, state)

            history.append(
                StepRecord(
                    step=step,
                    node=current,
                    status=status,
                    duration_ms=duration,
                    state_before=before,
                    state_after=dict(state),
                    state_diff=diff,
                    edge_taken=next_node,
                    edge_reason=reason,
                    error=error,
                    tokens=int(state.get("_tokens_delta", 0) or 0),
                )
            )
            state.pop("_tokens_delta", None)

            if status == "error":
                return GraphRun(
                    status="error",
                    final_state=state,
                    history=history,
                    halted_reason=error,
                    steps=step + 1,
                    total_ms=(time.perf_counter() - started) * 1000,
                    node_visits=visits,
                )

            current = next_node
            step += 1

        return GraphRun(
            status="completed",
            final_state=state,
            history=history,
            steps=step,
            total_ms=(time.perf_counter() - started) * 1000,
            node_visits=visits,
        )

    def _next(self, current: str, state: State) -> tuple[str | None, str | None]:
        if current in self.conditional_edges:
            edge = self.conditional_edges[current]
            try:
                label = edge.router(state)
            except Exception as exc:
                return END, f"router raised {type(exc).__name__}: {exc}"
            target = edge.mapping.get(label)
            if target is None:
                # An unmapped label ends the run rather than crashing — but it
                # says so, because a typo'd route silently terminating is one of
                # the hardest agent bugs to spot.
                return END, f"router returned unmapped label '{label}'"
            return target, f"routed on '{label}'"
        return self.edges.get(current, END), None


def _jsonable(value: Any) -> Any:
    """Make state safe for JSON, truncating anything huge."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in list(value)[:50]]
    if isinstance(value, (str, int, float, bool, type(None))):
        if isinstance(value, str) and len(value) > 2000:
            return value[:2000] + f"… ({len(value)} chars)"
        return value
    return str(value)[:500]
