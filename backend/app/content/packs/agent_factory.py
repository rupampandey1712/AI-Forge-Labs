"""The Agent Factory — graphs, state, termination, and the things that bankrupt you.

WHY THIS PACK IS SHAPED AROUND FAILURE: agent tutorials overwhelmingly show the
happy path — a graph that answers a question and stops. Nothing in that teaches
the two skills that matter in production, which are (a) proving a graph
terminates and (b) knowing what it cost when it did not.

So the concepts here are organised around the four ways agents actually fail:
they loop, they act without permission, they lose state between steps, and they
call a tool that returns something the author never considered. Every challenge
in this pack is executable pure Python — no framework, because the mechanics are
the lesson and a framework would hide them.

The interactive Agent Factory lab is the companion: it runs these same graph
shapes and lets the player scrub the execution. Content here is what makes the
lab mean something.
"""

from __future__ import annotations

from app.content.schema import (
    ChallengeSpec,
    ConceptSpec,
    ContentPack,
    MissionSpec,
    MissionStepSpec,
    QuestionSpec,
    example,
    mistake,
    opt,
    point,
    script,
)
from app.domain.enums import Category, Severity
from app.domain.enums import DifficultyTier as T
from app.domain.enums import InterviewLevel as L
from app.domain.enums import QuestionKind as Q

LG = Category.LANGGRAPH
LC = Category.LANGCHAIN
OBS = Category.LANGSMITH

# ═════════════════════════════════════════════════════════════════════════════
# CONCEPTS
# ═════════════════════════════════════════════════════════════════════════════
CONCEPTS = [
    ConceptSpec(
        slug="agent-graph-state",
        title="Graph State and Reducers",
        category=LG,
        skill_node="lg.state",
        difficulty=5,
        summary=(
            "A node returns a partial update, not a whole state. The reducer decides how that "
            "update merges — and choosing the wrong one loses data silently."
        ),
        explanation="""
The single design decision that makes graph frameworks work: a node does not
receive the state and hand back a new one. It receives the state and returns
**only the keys it changed**. The framework merges.

    def classify(state):
        return {"category": "billing"}      # not the whole state

Why this matters more than it looks:

* **Nodes compose.** A node that returns the whole state must know about every
  key, including ones added later by unrelated features. A node that returns a
  fragment does not.
* **The diff is the debugging unit.** "This node set `category` to `billing`" is
  a sentence you can act on. "The state is now this 40-key dict" is not.
* **Merging is explicit.** Which brings us to reducers.

A **reducer** is the function that combines the old value with the new one, per
key. The default is `replace`, and it is the right default — but it is wrong
often enough to be dangerous:

    replace   new value wins            counters, flags, the current answer
    append    old + [new]               message history, a tool-call log
    merge     {**old, **new}            accumulating a metadata dict
    add       old + new                 token counts, retry budgets, costs

**The failure this prevents.** Message history with the default `replace`
reducer means every node overwrites the conversation with its own single
message. The agent then appears to have amnesia — it answers the last question
as though the first never happened — and the bug looks like a model problem
rather than a one-line state configuration. It is the most common first bug in
every agent codebase.
""",
        examples=[
            example(
                "The reducer is the whole difference",
                """
# replace: the history is clobbered on every node
graph = StateGraph()
graph.run({"messages": ["hi"]})   # -> {"messages": ["latest only"]}

# append: the history accumulates, which is what a conversation is
graph = StateGraph(reducers={"messages": append})
graph.run({"messages": ["hi"]})   # -> {"messages": ["hi", "latest"]}
""",
                note="Same graph, same nodes. One line of configuration decides whether the "
                "agent can remember anything.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Leaving message history on the default replace reducer",
                "Every node overwrites the conversation with its own message, so the agent "
                "appears to forget everything. It reads as a model failure and gets debugged "
                "for hours in the prompt.",
                "Declare an `append` reducer for any accumulating key — history, tool calls, "
                "retrieved documents, errors.",
                Severity.HIGH,
            ),
            mistake(
                "Returning the full state from a node",
                "The node now couples to every key in the schema, including keys added later "
                "for unrelated reasons, and a key it forgets to copy is silently dropped.",
                "Return only the keys this node changed. Let the reducer merge.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Debugging an agent that 'forgets' the user's first message",
            "Accumulating a per-run token budget across every LLM node",
        ],
        related=["agent-termination", "agent-conditional-edges"],
        tags=["agents", "langgraph", "state"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="agent-conditional-edges",
        title="Conditional Edges and Routers",
        category=LG,
        skill_node="lg.edges",
        difficulty=5,
        summary=(
            "A router is a pure function from state to the name of the next node. Keeping the "
            "decision separate from the work is what makes a graph testable."
        ),
        explanation="""
There are two kinds of edge. A **direct** edge always goes to the same place. A
**conditional** edge calls a router — a function that reads the state and returns
a *string* naming where to go next:

    def route(state) -> str:
        if state["confidence"] < 0.6:
            return "escalate"
        return "respond"

    graph.add_conditional_edges("evaluate", route, {"escalate": "human", "respond": "reply"})

**Why the router is a separate function, and not an `if` inside the node.** Three
reasons, and they compound:

1. **It is testable in isolation.** A router is a pure function from a dict to a
   string. You can exhaustively test the routing logic with no LLM, no network
   and no graph — which is the only way to be confident about branches that only
   fire in rare states.
2. **It is inspectable before you run.** The mapping from router outputs to node
   names is data, so the graph can be drawn, cycle-checked and reviewed without
   executing anything.
3. **It separates deciding from doing.** A node that both calls a model and
   decides where to go next cannot be reused in a graph that decides differently.

**The failure mode to know.** If the router returns a string that is not in the
mapping, the graph has no edge to follow. A good framework raises immediately; a
sloppy one silently halts, and you get an agent that "sometimes just stops" with
no error and no explanation. Always make the mapping exhaustive, and make the
default branch explicit rather than implied.
""",
        examples=[
            example(
                "A router is trivially testable",
                """
def route(state):
    if state.get("error"):
        return "recover"
    if state["confidence"] < 0.6:
        return "escalate"
    return "respond"

assert route({"confidence": 0.9}) == "respond"
assert route({"confidence": 0.2}) == "escalate"
assert route({"confidence": 0.9, "error": "timeout"}) == "recover"
""",
                note="Three lines of test cover every branch. No model, no network, no graph.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Embedding routing logic inside the node function",
                "The decision can no longer be tested without executing the node, which usually "
                "means calling a model — so the rare branches never get tested at all.",
                "Extract the router as a pure function. Test it exhaustively.",
                Severity.MEDIUM,
            ),
            mistake(
                "A router that can return a key not in the mapping",
                "The graph has nowhere to go. Depending on the framework this either raises at "
                "runtime in production or silently halts mid-run.",
                "Make the mapping exhaustive over the router's return values, and add a "
                "fallback branch rather than relying on a default.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Routing a support ticket to retrieval, escalation or a direct answer",
            "Unit-testing agent control flow in CI without spending a token",
        ],
        requires=["agent-graph-state"],
        tags=["agents", "langgraph", "control-flow"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="agent-termination",
        title="Termination — Why Agents Loop Forever",
        category=LG,
        skill_node="lg.control",
        difficulty=7,
        summary=(
            "A cycle is not a bug. A cycle with no monotonically-advancing counter is. The "
            "recursion limit is a safety net, never the fix."
        ),
        explanation="""
Agents loop because looping is the point — reflect, revise, retry. The question
is never "does this graph have a cycle" but **"what guarantees the cycle exits"**.

A cycle terminates when something changes monotonically toward a bound. Three
things can play that role:

* **A counter the router reads.** `attempts` increments in the loop body and the
  router routes to END at `attempts >= 3`. This is the one that always works.
* **A shrinking work queue.** The loop pops items and never pushes more than it
  popped.
* **A confidence threshold plus a counter.** On its own a threshold is not a
  guarantee — if the model's confidence never rises, the loop runs forever. The
  counter is what makes it bounded.

**The broken pattern, which is extremely common:**

    def route(state):
        if state["confidence"] > 0.8:
            return "done"
        return "retry"          # nothing in the loop changes confidence

That graph terminates only if the model happens to become confident. It is not
bounded; it is lucky.

**Why raising the recursion limit is the wrong fix.** The limit exists to convert
an infinite loop into a diagnosable halt. Raising it from 25 to 100 does not make
the agent finish — it makes it fail four times slower and four times more
expensively. The correct response to hitting the limit is always to find the
edge that never routes to END.

**What this costs when it escapes.** Each loop iteration is at least one model
call. A runaway loop on a production endpoint, with retries, running overnight
before anyone looks at the dashboard, is the "$4,000 weekend" story every team
that ships agents eventually has. Bound the loop *and* cap the per-run token
budget — they fail independently.
""",
        examples=[
            example(
                "Bounded vs lucky",
                """
# BOUNDED: revise increments the counter the router reads.
def revise(state):
    return {"draft": improve(state["draft"]), "attempts": state["attempts"] + 1}

def route(state):
    if state["score"] > 0.8 or state["attempts"] >= 3:
        return "done"
    return "revise"

# LUCKY: nothing in the loop advances toward the exit condition.
def route_broken(state):
    return "done" if state["score"] > 0.8 else "revise"
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Relying on a quality threshold alone to exit a loop",
                "If the model never reaches the threshold, the loop never exits. The graph is "
                "not bounded, it is merely usually lucky.",
                "Always pair a quality condition with a hard attempt counter. `score > 0.8 or "
                "attempts >= 3`.",
                Severity.CRITICAL,
            ),
            mistake(
                "Raising the recursion limit when a graph hits it",
                "The limit is the detector, not the disease. Raising it converts a fast, cheap "
                "failure into a slow, expensive one.",
                "Treat hitting the limit as a bug report about a conditional edge. Find the "
                "branch that never routes to END.",
                Severity.HIGH,
            ),
            mistake(
                "No per-run cost ceiling",
                "Step limits bound iterations, not spend. One iteration with a 100k-token "
                "context costs more than fifty small ones.",
                "Track cumulative tokens in state with an `add` reducer and halt on budget as "
                "well as on step count.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Reviewing an agent PR: 'what bounds this loop?' is the first question",
            "Explaining a $4,000 overnight bill to a finance team",
        ],
        requires=["agent-conditional-edges"],
        related=["agent-cost-control"],
        tags=["agents", "termination", "production"],
        estimated_minutes=11,
    ),
    ConceptSpec(
        slug="agent-human-in-the-loop",
        title="Human-in-the-Loop Checkpoints",
        category=LG,
        skill_node="lg.hitl",
        difficulty=7,
        summary=(
            "An interrupt turns an agent's decision into a proposal. It requires durable state, "
            "which is why it is an architecture decision and not a feature flag."
        ),
        explanation="""
`interrupt_before` on a node means: when execution reaches this node, **stop,
persist the state, and return**. A human reviews. Later, a separate request
resumes from exactly that point with the decision folded into state.

The mechanism is simple. The requirement it imposes is not: **the state must be
durable and serialisable.** If your graph state holds an open database session,
a file handle or a live HTTP client, it cannot be checkpointed, and no amount of
interrupt configuration will help. That constraint should shape the state schema
from the beginning — it is much harder to retrofit.

**What deserves a gate.** The test is not "is the model likely to be right". A
model that is right 99% of the time still sends one wrong refund in a hundred,
and the cost asymmetry is what matters:

* Spends money, sends external communication, or deletes data → gate it.
* Touches production configuration → gate it.
* Reads and summarises → do not gate it; you will train people to click
  through, and then the gates that matter get clicked through too.

**The approval must be scoped.** A single approval should authorise one action,
not a session. A graph with two gates must stop at both — "approved once"
becoming blanket permission is a privilege-escalation bug with extra steps.

**And record the decision in state.** The audit trail for "who approved this
refund and when" has to survive the run. Fold the decision, the approver and the
timestamp into state at resume, so the trace is the record.
""",
        examples=[
            example(
                "The shape of a gated run",
                """
run = graph.run(state)
assert run.status == "interrupted"
assert run.interrupted_at == "issue_refund"
# ... state is persisted; a human looks at it; hours may pass ...

resumed = graph.run(
    {},
    resume_from={**run.final_state, "approved": True, "approver": "rupam"},
    resume_at="issue_refund",
)
""",
                note="`resume_at` both restarts at the node and suppresses *that* node's own "
                "interrupt. A later gate still stops.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Holding non-serialisable objects in graph state",
                "A database session or HTTP client cannot be persisted, so the run cannot be "
                "checkpointed and the interrupt silently becomes useless.",
                "Keep state to plain data. Pass clients through configuration or a context "
                "object, never through the state that gets serialised.",
                Severity.HIGH,
            ),
            mistake(
                "Gating everything",
                "Approval fatigue. People click through every prompt, including the one that "
                "actually mattered, and the gate provides less safety than none at all because "
                "it creates false confidence.",
                "Gate only irreversible or costly actions. Make those few gates informative "
                "enough to be worth reading.",
                Severity.MEDIUM,
            ),
            mistake(
                "Treating one approval as session-wide permission",
                "An agent authorised for one refund proceeds to issue five. This is privilege "
                "escalation, whatever it is called in the codebase.",
                "Scope each approval to one action. Re-gate on every subsequent gated node.",
                Severity.CRITICAL,
            ),
        ],
        real_world_usage=[
            "A support agent that drafts refunds but never issues one unreviewed",
            "Any agent with write access to production",
        ],
        requires=["agent-termination"],
        tags=["agents", "safety", "production"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="agent-tool-design",
        title="Designing Tools an Agent Can Actually Use",
        category=LC,
        skill_node="lc.tools",
        difficulty=6,
        summary=(
            "The model picks a tool by reading its description. A vague description is not a "
            "documentation problem — it is the bug."
        ),
        explanation="""
Tool selection is a reading-comprehension task performed by the model on your
docstrings. Everything follows from that.

**Descriptions are the interface.** `search(query)` — "searches" — gives the
model nothing to discriminate on when there are four search tools. Say what it
searches, what it returns, and critically **when not to use it**:

    "Search internal engineering runbooks by keyword. Returns up to 5 excerpts
     with document titles. Use for operational and on-call procedures. Do NOT
     use for customer data or billing questions — use `lookup_account` for those."

**Fewer tools work better.** Selection accuracy degrades noticeably past roughly
a dozen tools, and two tools with overlapping descriptions are worse than one
tool with a parameter. If two tools are being confused, merge them.

**Errors are a prompt, not an exception.** When a tool fails, the model sees the
error text and decides what to do next. So the error must be actionable:

    bad:  "Error: 400"
    good: "No account found for id 'ABC'. Account ids are 8 digits, e.g. 10482203.
           Use `search_accounts` with a name or email to find the id first."

The second one tells the model how to recover. The first produces a retry with
the same bad input, then another, until the loop bound fires.

**Validate before executing.** The model will pass a malformed argument
eventually; it is a probabilistic system. A tool that raises an unhandled
exception takes down the run. Validate, and return the validation message as the
tool result so the model can correct itself.

**Make tools idempotent where you can.** Agents retry. A `create_ticket` tool
that runs twice should produce one ticket, which usually means an idempotency
key derived from the request rather than a fresh UUID per call.
""",
        examples=[
            example(
                "An error that teaches the model how to recover",
                """
def lookup_account(account_id: str) -> str:
    if not account_id.isdigit() or len(account_id) != 8:
        # Returned, not raised: the model reads this and can fix its own call.
        return (
            f"Invalid account_id {account_id!r}. Expected 8 digits, e.g. '10482203'. "
            "Use search_accounts(name=...) to find an id first."
        )
    ...
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "One-line tool descriptions",
                "The model cannot discriminate between similar tools, so it picks the wrong one "
                "and the failure looks like a reasoning problem rather than a docstring problem.",
                "State what it does, what it returns, and when NOT to use it. Name the "
                "alternative tool explicitly.",
                Severity.HIGH,
            ),
            mistake(
                "Letting tool exceptions propagate",
                "An unhandled exception ends the run. The model had no chance to recover from a "
                "mistake it could easily have corrected.",
                "Catch, and return a description of the failure as the tool result.",
                Severity.HIGH,
            ),
            mistake(
                "Non-idempotent write tools",
                "Agents retry on timeout and ambiguity. A non-idempotent create tool produces "
                "duplicate tickets, duplicate charges, duplicate emails.",
                "Derive an idempotency key from the request content, and make repeat calls "
                "return the original result.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Cutting tool-selection errors by rewriting six docstrings",
            "Stopping an agent from filing the same ticket four times",
        ],
        related=["agent-termination"],
        tags=["agents", "tools", "langchain"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="agent-cost-control",
        title="Observability and Cost Control",
        category=OBS,
        skill_node="obs.tracing",
        difficulty=6,
        summary=(
            "An agent is a distributed system whose most expensive component is billed per "
            "token. Without per-step traces you cannot debug it or afford it."
        ),
        explanation="""
A single agent run is a dozen model calls, several tool calls and a branch
history. Debugging that from a final answer is like debugging a microservice
architecture from the HTTP status code.

**What a trace must record, per step:** the node name, the input state, the
output diff, the prompt actually sent, the response, token counts split into
input and output, latency, and the edge taken with the reason. The last one is
what turns "it did the wrong thing" into "it routed to `escalate` because
confidence was 0.58".

**Why token counts belong on every step, not just the run.** Costs in agents are
never uniform. One node with a bloated system prompt, called on every loop
iteration, will be 80% of the bill while looking like 8% of the code. You cannot
see that from a run total.

**Input and output tokens must be separated** because output is typically 3–5x
the price. A step producing 2,000 output tokens can cost more than one consuming
10,000 input tokens, and optimising the wrong one wastes the effort.

**The three limits that fail independently**, so you need all three:

* **Step limit** — bounds iterations. Does not bound spend.
* **Token budget** — bounds spend. Does not bound wall-clock time.
* **Wall-clock timeout** — bounds latency. Does not bound either of the above.

An agent can sit inside the step limit and still cost $40 in one run because each
step carried a 100k-token context.

**Cache what repeats.** The system prompt and tool definitions are identical on
every iteration of a loop; prompt caching makes those near-free. On a
ten-iteration loop that is often the single largest saving available, and it
requires no change to the graph at all.
""",
        examples=[
            example(
                "A budget that halts the run",
                """
# `add` reducer: each node's usage accumulates rather than replacing.
graph = StateGraph(reducers={"tokens_used": add, "cost_usd": add})

def route(state):
    if state["cost_usd"] > 0.50:
        return "halt_over_budget"     # a real exit, not an exception
    return "continue"
""",
                note="The budget is part of the graph's control flow, not an afterthought "
                "wrapped around it — which means it appears in the diagram and in review.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Logging only the final answer",
                "Every intermediate decision is invisible, so a wrong answer cannot be "
                "attributed to a node, a prompt or a routing decision.",
                "Trace every step with its state diff and the edge taken.",
                Severity.HIGH,
            ),
            mistake(
                "A step limit with no token budget",
                "Ten steps with a 100k context costs far more than fifty small ones. The step "
                "limit gives a false sense of cost control.",
                "Accumulate tokens in state with an `add` reducer and route to a halt node on "
                "budget exhaustion.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Finding the one node responsible for 80% of an agent's cost",
            "Answering 'why did it do that' from a trace instead of a guess",
        ],
        related=["agent-termination"],
        tags=["agents", "observability", "cost"],
        estimated_minutes=9,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# CHALLENGES
# ═════════════════════════════════════════════════════════════════════════════
CHALLENGES = [
    ChallengeSpec(
        slug="agent-implement-reducers",
        title="Implement the State Reducers",
        category=LG,
        tier=T.IMPLEMENT,
        prompt="""
Implement `merge_state(state, update, reducers)`.

* `state` is the current state dict.
* `update` is the partial dict a node returned.
* `reducers` maps a key to one of the strings `"replace"`, `"append"`, `"merge"`
  or `"add"`. Any key not listed defaults to `"replace"`.

Semantics:

* `replace` — the new value wins.
* `append` — the result is the old list plus the new value. If the new value is
  itself a list, extend by it rather than nesting it.
* `merge` — dict union, new keys winning.
* `add`  — numeric addition.

Return a **new** dict. The caller keeps the old one for the step diff, so
mutating it destroys the trace.
""",
        starter_code="def merge_state(state, update, reducers):\n    ...\n",
        reference_solution="""
def merge_state(state, update, reducers):
    # A new dict, always: the caller diffs old against new to build the step
    # record, so mutating `state` in place would erase the very thing the
    # trace is made of.
    out = dict(state)

    for key, value in update.items():
        strategy = reducers.get(key, "replace")
        current = state.get(key)

        if strategy == "append":
            base = list(current) if isinstance(current, list) else ([] if current is None else [current])
            # A list update extends rather than nesting — otherwise a node
            # returning two messages produces [[m1, m2]] and every consumer
            # downstream has to special-case it.
            out[key] = base + list(value) if isinstance(value, list) else base + [value]
        elif strategy == "merge":
            out[key] = {**(current or {}), **(value or {})}
        elif strategy == "add":
            out[key] = (current or 0) + value
        else:
            out[key] = value

    return out
""",
        solution_explanation=(
            "The three details that matter: a new dict so the step diff survives; `append` "
            "extending rather than nesting when handed a list; and `add`/`merge` treating a "
            "missing key as the identity (0 and {}) so the first node does not need to "
            "pre-seed every accumulator."
        ),
        tests=[
            script(
                "replace is the default",
                """
assert merge_state({"a": 1}, {"a": 2}, {}) == {"a": 2}
""",
            ),
            script(
                "append accumulates instead of clobbering",
                """
out = merge_state({"messages": ["hi"]}, {"messages": "there"}, {"messages": "append"})
assert out == {"messages": ["hi", "there"]}, out
""",
                points=2.0,
            ),
            script(
                "append extends rather than nesting when given a list",
                """
out = merge_state({"log": ["a"]}, {"log": ["b", "c"]}, {"log": "append"})
assert out == {"log": ["a", "b", "c"]}, f"nested instead of extended: {out}"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "add accumulates a budget",
                """
out = merge_state({"tokens": 100}, {"tokens": 40}, {"tokens": "add"})
assert out == {"tokens": 140}, out
""",
                points=1.5,
            ),
            script(
                "accumulators work from an absent key",
                """
assert merge_state({}, {"tokens": 5}, {"tokens": "add"}) == {"tokens": 5}
assert merge_state({}, {"msgs": "x"}, {"msgs": "append"}) == {"msgs": ["x"]}
assert merge_state({}, {"meta": {"a": 1}}, {"meta": "merge"}) == {"meta": {"a": 1}}
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "merge is a dict union with the new value winning",
                """
out = merge_state({"m": {"a": 1, "b": 2}}, {"m": {"b": 9}}, {"m": "merge"})
assert out == {"m": {"a": 1, "b": 9}}, out
""",
                hidden=True,
                points=1.5,
            ),
            script(
                "the original state is not mutated",
                """
state = {"messages": ["hi"], "n": 1}
merge_state(state, {"messages": "x", "n": 2}, {"messages": "append", "n": "add"})
assert state == {"messages": ["hi"], "n": 1}, f"mutated the caller's state: {state}"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "keys absent from the update are preserved",
                """
out = merge_state({"a": 1, "b": 2}, {"a": 9}, {})
assert out == {"a": 9, "b": 2}, out
""",
                hidden=True,
            ),
        ],
        concepts=["agent-graph-state"],
        hints=[
            "Start from a copy of `state`, then apply each key of `update` in turn.",
            "For `append`, what should happen when the key does not exist yet?",
            "For `append`, what if the node returns a list of two messages rather than one?",
        ],
        explanation_prompts=[
            point(
                "Explains why nodes return partial updates",
                "partial",
                "only the keys",
                "compose",
                "diff",
                weight=2,
            ),
            point(
                "Names the append-vs-replace failure on message history",
                "history",
                "forget",
                "overwrit",
                "clobber",
                weight=3,
            ),
            point(
                "Notes the new dict preserves the step diff",
                "diff",
                "mutate",
                "copy",
                "trace",
                weight=2,
            ),
        ],
        expected_complexity="O(k) in the size of the update",
        par_seconds=480,
    ),
    ChallengeSpec(
        slug="agent-fix-runaway-loop",
        title="Bound the Runaway Loop",
        category=LG,
        tier=T.DEBUG,
        prompt="""
This agent loop ran 2,100 times overnight before the recursion limit stopped it,
at a cost of roughly $380.

`run_agent(initial, step, judge, limit)` drives a refine loop:

* call `step(state)` to produce an update, merge it into the state,
* call `judge(state)` which returns a quality score in `[0, 1]`,
* stop when the score is good enough.

Fix it so that:

* it stops when `judge` returns **≥ 0.8**, and
* it stops after at most `limit` iterations **regardless** of the score, and
* it returns `(state, reason)` where `reason` is `"quality"` or `"budget"`.

The recursion limit is the safety net that caught this. It is not the fix.
""",
        broken_code="""
def run_agent(initial, step, judge, limit=25):
    state = dict(initial)
    while True:
        state.update(step(state))
        if judge(state) > 0.8:
            return state, "quality"
""",
        starter_code="",
        reference_solution="""
def run_agent(initial, step, judge, limit=25):
    state = dict(initial)

    # The counter is the termination guarantee. The quality threshold on its own
    # is not a bound — it is a hope that the judge eventually cooperates, and on
    # the run that cost $380 it did not.
    for _ in range(limit):
        state.update(step(state))
        # `>=` not `>`: a judge that returns exactly the threshold has met the
        # bar, and the strict comparison is why one prior run spun on 0.8.
        if judge(state) >= 0.8:
            return state, "quality"

    return state, "budget"
""",
        solution_explanation=(
            "Two bugs. The `while True` had no bound at all — the only exit was the quality "
            "threshold, so a judge that plateaus below 0.8 loops until something external "
            "kills it. And `> 0.8` excludes exactly 0.8, which is the value a clamped or "
            "rounded judge returns most often. A bounded loop plus an inclusive comparison, "
            "and the reason string so the caller can tell a success from a budget exhaustion."
        ),
        tests=[
            script(
                "stops on quality",
                """
scores = iter([0.3, 0.6, 0.95])
state, reason = run_agent({"n": 0}, lambda s: {"n": s["n"] + 1}, lambda s: next(scores), limit=25)
assert reason == "quality", reason
assert state["n"] == 3, state
""",
                points=2.0,
            ),
            script(
                "stops on budget when quality never arrives",
                """
state, reason = run_agent({"n": 0}, lambda s: {"n": s["n"] + 1}, lambda s: 0.1, limit=7)
assert reason == "budget", reason
assert state["n"] == 7, f"ran {state['n']} times with a limit of 7"
""",
                points=3.0,
            ),
            script(
                "exactly 0.8 counts as good enough",
                """
state, reason = run_agent({"n": 0}, lambda s: {"n": s["n"] + 1}, lambda s: 0.8, limit=10)
assert reason == "quality", "0.8 should meet a >= 0.8 bar"
assert state["n"] == 1
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "a limit of 1 runs exactly once",
                """
state, reason = run_agent({"n": 0}, lambda s: {"n": s["n"] + 1}, lambda s: 0.0, limit=1)
assert state["n"] == 1 and reason == "budget", (state, reason)
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "a limit of 0 does no work at all",
                """
state, reason = run_agent({"n": 0}, lambda s: {"n": s["n"] + 1}, lambda s: 0.0, limit=0)
assert state["n"] == 0 and reason == "budget", (state, reason)
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "the caller's initial state is not mutated",
                """
initial = {"n": 0}
run_agent(initial, lambda s: {"n": s["n"] + 1}, lambda s: 1.0, limit=3)
assert initial == {"n": 0}, f"mutated the caller's dict: {initial}"
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["agent-termination"],
        hints=[
            "`while True` with one exit condition is only bounded if that condition is guaranteed.",
            "What does the loop do when `judge` returns 0.79 forever?",
            "Check the comparison operator against the stated threshold of 0.8.",
        ],
        explanation_prompts=[
            point(
                "Identifies the unbounded loop",
                "while true",
                "no bound",
                "unbounded",
                "counter",
                weight=3,
            ),
            point(
                "Catches the off-by-one on the threshold",
                ">=",
                "0.8",
                "inclusive",
                "strict",
                weight=2,
            ),
            point(
                "Says raising the recursion limit is not the fix",
                "not the fix",
                "safety net",
                "raising the limit",
                weight=2.5,
                dimension="production_awareness",
            ),
        ],
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="agent-route-exhaustively",
        title="A Router That Cannot Fall Off the Graph",
        category=LG,
        tier=T.IMPLEMENT,
        prompt="""
Implement `make_router(mapping, fallback)`.

It returns a function `route(state) -> str` which:

* reads `state["intent"]`,
* returns `mapping[intent]` when the intent is known,
* returns `fallback` for an unknown or missing intent — **never** a name that is
  not a value of `mapping` or the fallback itself.

Additionally, `make_router` must raise `ValueError` **at construction time** if
`fallback` is not one of the mapping's target node names. A router that can emit
a node the graph does not contain is a runtime halt with no error message, and
catching it at construction is the whole point.
""",
        starter_code="def make_router(mapping, fallback):\n    ...\n",
        reference_solution="""
def make_router(mapping, fallback):
    targets = set(mapping.values())
    # Validating here rather than at route time is deliberate: an invalid
    # fallback discovered mid-run is an agent that silently stops in
    # production, while one discovered at construction is an import error.
    if fallback not in targets:
        raise ValueError(
            f"fallback {fallback!r} is not one of the routable targets {sorted(targets)}"
        )

    def route(state):
        intent = state.get("intent")
        # `.get` rather than `in`: an unhashable or missing intent must take the
        # fallback, not raise from inside the graph.
        try:
            return mapping.get(intent, fallback)
        except TypeError:
            return fallback

    return route
""",
        solution_explanation=(
            "The validation is the challenge. A router is called deep inside a run, often on a "
            "rare branch, so a bad target surfaces in production weeks later as 'the agent "
            "sometimes just stops'. Checking at construction converts that into an error at "
            "import. The `TypeError` guard covers an unhashable intent — the model can produce "
            "anything, including a list."
        ),
        tests=[
            script(
                "routes a known intent",
                """
route = make_router({"billing": "charge_node", "tech": "support_node"}, "support_node")
assert route({"intent": "billing"}) == "charge_node"
""",
            ),
            script(
                "unknown intent takes the fallback",
                """
route = make_router({"billing": "charge_node"}, "charge_node")
assert route({"intent": "nonsense"}) == "charge_node"
assert route({}) == "charge_node"
""",
                points=2.0,
            ),
            script(
                "an invalid fallback raises at construction, not at run time",
                """
try:
    make_router({"billing": "charge_node"}, "nowhere")
except ValueError:
    pass
else:
    raise AssertionError("accepted a fallback that is not a real node")
""",
                points=3.0,
            ),
            script(
                "never returns a name outside the graph",
                """
mapping = {"a": "n1", "b": "n2"}
route = make_router(mapping, "n2")
allowed = set(mapping.values())
for intent in ["a", "b", "zzz", None, "", 0]:
    assert route({"intent": intent}) in allowed, intent
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "an unhashable intent takes the fallback instead of raising",
                """
route = make_router({"a": "n1"}, "n1")
assert route({"intent": ["a", "b"]}) == "n1"
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["agent-conditional-edges"],
        hints=[
            "What are the legal return values? Compute that set once, at construction.",
            "What should happen when `state` has no `intent` key at all?",
            "A model can return anything, including a list. Is your lookup safe against that?",
        ],
        explanation_prompts=[
            point(
                "Explains why an unmapped return value is dangerous",
                "no edge",
                "halt",
                "silently",
                "stops",
                weight=3,
            ),
            point(
                "Justifies validating at construction time",
                "construction",
                "import",
                "early",
                "fail fast",
                weight=2.5,
            ),
            point(
                "Notes routers are pure and therefore testable",
                "pure",
                "test",
                "no llm",
                weight=2,
            ),
        ],
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="agent-tool-error-recovery",
        title="Tool Errors the Model Can Recover From",
        category=LC,
        tier=T.PRODUCTION,
        prompt="""
Implement `safe_tool(fn, name, recovery_hint)` — a wrapper that turns a tool
function into one an agent can survive.

The returned callable takes the same arguments and:

* returns `fn(...)`'s result as a string when it succeeds,
* on **any** exception, returns a string (never raises) containing the tool
  name, the exception type, its message, and `recovery_hint`,
* is truncated to at most 500 characters, because an unbounded tool output
  becomes an unbounded prompt and then an unbounded bill.

The point is that the model *reads* the failure and corrects itself. An error it
cannot act on produces an identical retry until the loop bound fires.
""",
        starter_code=("def safe_tool(fn, name, recovery_hint):\n    ...\n"),
        reference_solution="""
def safe_tool(fn, name, recovery_hint):
    def wrapped(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        # `Exception`, deliberately not `BaseException`. KeyboardInterrupt and
        # SystemExit are not failures the model can recover from, and swallowing
        # them means an operator cannot stop a runaway agent and the worker will
        # not shut down cleanly. Catching them would buy nothing and cost
        # control of the process.
        except Exception as exc:
            # Returned, not raised. A raised exception ends the run; a returned
            # message is a prompt the model can act on, which is the whole
            # difference between a dead agent and a self-correcting one.
            message = (
                f"{name} failed: {type(exc).__name__}: {exc}. {recovery_hint}"
            )
            return message[:500]
        # Truncation applies to success too: a tool returning a 40k-character
        # page silently becomes 40k characters of context on every subsequent
        # iteration of the loop.
        return str(result)[:500]

    return wrapped
""",
        solution_explanation=(
            "Three properties, each protecting against a different failure. Returning instead "
            "of raising keeps the run alive and gives the model something to act on. The "
            "recovery hint is what makes the retry different from the first attempt. And the "
            "truncation bounds the context — a tool that returns a whole web page turns every "
            "later iteration of the loop into a far more expensive call.\n\n"
            "The boundary is `Exception`, not `BaseException`. KeyboardInterrupt and SystemExit "
            "are not conditions the model can recover from, and catching them would mean an "
            "operator cannot Ctrl-C a runaway agent and the worker will not shut down. "
            "'Never raises' is the wrong goal; 'never raises anything the caller could have "
            "handled' is the right one."
        ),
        tests=[
            script(
                "passes through a successful result as a string",
                """
tool = safe_tool(lambda x: x * 2, "double", "pass a number")
assert tool(21) == "42"
""",
            ),
            script(
                "an exception becomes a readable message, not a crash",
                """
def boom(x):
    raise ValueError("account not found")

tool = safe_tool(boom, "lookup", "Use search_accounts first.")
out = tool("abc")
assert isinstance(out, str)
assert "lookup" in out and "ValueError" in out
assert "account not found" in out
assert "Use search_accounts first." in out, out
""",
                points=3.0,
            ),
            script(
                "catches every ordinary exception",
                """
for bad in (ValueError, TypeError, ZeroDivisionError, KeyError, AttributeError, RuntimeError):
    def raiser(_, exc=bad):
        raise exc("x")
    tool = safe_tool(raiser, "t", "hint")
    result = tool(1)
    assert isinstance(result, str), f"{bad.__name__} escaped the wrapper"
    assert bad.__name__ in result, f"{bad.__name__} not named in the message"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "does NOT swallow KeyboardInterrupt or SystemExit",
                """
# `except Exception` is correct here and `except BaseException` is not.
# Swallowing Ctrl-C means an operator cannot stop a runaway agent, and
# swallowing SystemExit means the worker will not shut down. Neither is
# something the model can recover from anyway, so catching them buys nothing
# and costs control of the process.
for fatal in (KeyboardInterrupt, SystemExit):
    def raiser(_, exc=fatal):
        raise exc("stop")
    tool = safe_tool(raiser, "t", "hint")
    try:
        tool(1)
    except fatal:
        pass
    else:
        raise AssertionError(
            f"{fatal.__name__} was swallowed - the wrapper is catching BaseException"
        )
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "output is truncated on both paths",
                """
big = safe_tool(lambda: "x" * 10_000, "big", "hint")
assert len(big()) <= 500, len(big())

def long_error():
    raise RuntimeError("y" * 10_000)
err = safe_tool(long_error, "err", "hint")
assert len(err()) <= 500, len(err())
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "keyword arguments survive the wrapper",
                """
tool = safe_tool(lambda a, b=1: a + b, "add", "hint")
assert tool(2, b=5) == "7"
""",
                hidden=True,
                points=1.5,
            ),
        ],
        concepts=["agent-tool-design", "agent-cost-control"],
        hints=[
            "What happens to the agent run if the tool raises? Is that ever the outcome you want?",
            "The model has to read the error. What does it need to know to do better next time?",
            "Should this wrapper catch KeyboardInterrupt? What would that cost an operator trying to stop a runaway agent?",
        ],
        explanation_prompts=[
            point(
                "Explains that errors are prompts the model reads",
                "model reads",
                "prompt",
                "recover",
                "correct itself",
                weight=3,
            ),
            point(
                "Justifies truncation in terms of context and cost",
                "context",
                "token",
                "cost",
                "bloat",
                weight=2.5,
                dimension="production_awareness",
            ),
            point(
                "Notes an unrecoverable error produces identical retries",
                "same retry",
                "identical",
                "loop",
                "again",
                weight=2,
            ),
            point(
                "Catches Exception rather than BaseException, and says why",
                "baseexception",
                "keyboardinterrupt",
                "systemexit",
                "ctrl-c",
                weight=2,
                dimension="depth",
            ),
        ],
        par_seconds=480,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# QUESTIONS
# ═════════════════════════════════════════════════════════════════════════════
QUESTIONS = [
    QuestionSpec(
        slug="q-agent-amnesia",
        kind=Q.DEBUGGING,
        category=LG,
        tier=T.DEBUG,
        level=L.MID,
        prompt=(
            "An agent answers each turn as though the conversation just started — it has no "
            "memory of the user's earlier messages, even within a single run. The model and "
            "prompt are unchanged from a working version. What is the most likely cause?"
        ),
        concepts=["agent-graph-state"],
        expected_answer=(
            "The `messages` key is using the default replace reducer, so each node overwrites "
            "the history with its own message."
        ),
        ideal_senior_answer=(
            "The reducer on the message key. The default is `replace`, so every node that "
            "returns `{'messages': [...]}` overwrites the entire history with just its own "
            "message rather than appending to it. The agent is not forgetting — the history is "
            "being deleted on every step.\n\n"
            "I would confirm it in thirty seconds from the trace: look at the state diff on two "
            "consecutive nodes and check whether the message list grows or stays length one. "
            "The fix is declaring an `append` reducer for that key.\n\n"
            "What makes this worth naming as a pattern is that it does not look like a state "
            "bug. It looks like a model failure, so people go and rewrite the prompt, add "
            "memory instructions, try a bigger model — and none of it can work, because the "
            "data was thrown away before the model ever saw it."
        ),
        common_wrong_answer=(
            "Assuming the context window is too small, or that the model needs an explicit "
            "instruction to remember. Both send you into prompt engineering for a bug that is "
            "one line of state configuration."
        ),
        rubric=[
            point("Names the reducer as the cause", "reducer", "replace", "append", weight=3),
            point(
                "Explains nodes return partial updates that get merged",
                "partial",
                "merge",
                "overwrit",
                "clobber",
                weight=2.5,
            ),
            point(
                "Gives a concrete way to confirm it",
                "trace",
                "state diff",
                "length",
                "inspect",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Notes it presents as a model problem",
                "looks like",
                "model",
                "prompt",
                "misdiagnos",
                weight=1.5,
                dimension="depth",
            ),
        ],
        followups=[
            "Which other keys typically need a non-default reducer?",
            "How would you prevent this class of bug for the next person?",
        ],
        tags=["agents", "debugging"],
        par_seconds=240,
    ),
    QuestionSpec(
        slug="q-agent-recursion-limit",
        kind=Q.MCQ,
        category=LG,
        tier=T.PRODUCTION,
        level=L.SENIOR,
        prompt=(
            "An agent hits its recursion limit of 25 in production. A teammate opens a PR "
            "raising it to 200. What is the correct review response?"
        ),
        concepts=["agent-termination"],
        options=[
            opt(
                "a",
                "Reject it: the limit is the detector. Find the conditional edge that never routes to END",
                correct=True,
                why="A graph that runs 25 steps without terminating will run 200 without "
                "terminating. Raising the limit makes the same failure eight times slower and "
                "eight times more expensive, and it removes the signal that something is wrong.",
            ),
            opt(
                "b",
                "Approve it — 25 is a low limit for a complex agent",
                why="Possibly true in general, and irrelevant here. The graph is not running out "
                "of room, it is not terminating.",
            ),
            opt(
                "c",
                "Approve it but add an alert when the new limit is hit",
                why="You already have that signal — it is the limit being hit right now. "
                "Raising it and alerting on it is a more expensive version of today.",
            ),
            opt(
                "d",
                "Approve it and add a retry so the run has a second chance",
                why="A retry of a non-terminating loop is two non-terminating loops.",
            ),
        ],
        expected_answer="Reject it and find the unbounded cycle.",
        ideal_senior_answer=(
            "Reject. A graph that does not terminate in 25 steps does not terminate in 200 — "
            "raising the limit converts a fast, cheap failure into a slow, expensive one and "
            "throws away the signal. The review question is 'what bounds this cycle?', and the "
            "answer has to be a counter that the router reads, not a quality threshold the "
            "model may never satisfy. I would also ask whether there is a token budget at all, "
            "because a step limit alone does not bound spend."
        ),
        common_wrong_answer="Treating the limit as a tuning parameter rather than a detector.",
        followups=["What would you require in the PR instead?", "Which limits fail independently?"],
        tags=["agents", "review", "production"],
        par_seconds=150,
    ),
    QuestionSpec(
        slug="q-agent-explain-termination",
        kind=Q.EXPLAIN,
        category=LG,
        tier=T.EXPLAIN,
        level=L.SENIOR,
        prompt=(
            "How do you prove an agent graph terminates? Walk me through what you look for in "
            "review, and what you would put in place so the question does not depend on review."
        ),
        concepts=["agent-termination", "agent-cost-control"],
        expected_answer=(
            "Find every cycle, and for each one identify a value that changes monotonically "
            "toward a bound that the router actually reads."
        ),
        ideal_senior_answer=(
            "Termination is a property of the cycles, so the first step is to enumerate them — "
            "statically, from the graph, before running anything. A graph with no cycles "
            "terminates trivially.\n\n"
            "For each cycle I look for a monotonically advancing quantity *that the router "
            "reads*. Usually that is an attempt counter incremented in the loop body; it can "
            "also be a shrinking work queue. The failure I see most is a quality threshold used "
            "as the only exit: 'loop until confidence > 0.8'. That is not a bound, because "
            "nothing guarantees confidence ever rises. It terminates when it gets lucky.\n\n"
            "The two-part check is: does something change every iteration, and does the router "
            "actually consult it? Both halves fail in practice — I have seen a counter "
            "incremented correctly and then never read.\n\n"
            "For what does not depend on review: the recursion limit stays, as a detector and "
            "not a fix. Alongside it I want a token budget accumulated in state with an `add` "
            "reducer, because steps and spend are independent — ten steps with a 100k context "
            "costs more than fifty small ones — and a wall-clock timeout, because neither of "
            "those bounds latency. Then a CI test that asserts every cycle in the graph has a "
            "counter-based exit, so the property is checked by a machine rather than by whoever "
            "happens to review the PR."
        ),
        common_wrong_answer=(
            "'The recursion limit handles it.' That is a crash guard, not a termination "
            "argument, and it says nothing about cost."
        ),
        rubric=[
            point("Starts by enumerating cycles", "cycle", "loop", "back edge", weight=2.5),
            point(
                "Requires a monotonically advancing quantity",
                "counter",
                "monotonic",
                "increment",
                "advance",
                weight=3,
            ),
            point(
                "Rejects a threshold-only exit as unbounded",
                "threshold",
                "confidence",
                "not guaranteed",
                "may never",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Checks the router actually reads the counter",
                "router reads",
                "router",
                "consult",
                weight=2,
            ),
            point(
                "Names token budget and timeout as independent limits",
                "token budget",
                "timeout",
                "cost",
                "independent",
                weight=2.5,
                dimension="production_awareness",
            ),
            point(
                "Proposes automating the check",
                "ci",
                "test",
                "automat",
                "lint",
                weight=2,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "How would you write that CI test?",
            "When is an unbounded loop actually acceptable?",
        ],
        tags=["agents", "termination", "interview"],
        par_seconds=420,
    ),
    QuestionSpec(
        slug="q-agent-hitl-scope",
        kind=Q.SCENARIO,
        category=LG,
        tier=T.PRODUCTION,
        level=L.SENIOR,
        prompt=(
            "Your refund agent pauses for human approval before issuing a refund. A product "
            "manager asks: once an operator has approved one refund in a session, can we skip "
            "the prompt for the rest of that session? It would save a lot of clicks. "
            "What do you say?"
        ),
        concepts=["agent-human-in-the-loop"],
        expected_answer=(
            "No — an approval must be scoped to one action. Session-wide approval is privilege "
            "escalation. Address the click volume differently."
        ),
        ideal_senior_answer=(
            "No, and I want to separate the two things being asked, because the underlying "
            "complaint is legitimate.\n\n"
            "Session-wide approval means one click authorises every subsequent refund the agent "
            "decides to issue, including ones the operator never saw. That is privilege "
            "escalation — the approval is being reinterpreted as consent for actions that did "
            "not exist when it was given. If the agent misclassifies five tickets after the "
            "first approval, five refunds go out and the audit trail says a human approved "
            "them.\n\n"
            "But the click fatigue is a real problem, and ignoring it means operators start "
            "approving without reading, which is worse than no gate because it manufactures "
            "false confidence. So I would attack it from the other side:\n\n"
            "Auto-approve below a value threshold — refunds under £20 do not need a human, and "
            "that is a policy decision the business can make explicitly and audit. Batch the "
            "approvals so an operator reviews ten at once in a single screen with the reasoning "
            "visible, rather than ten modal dialogs. And look at *why* there are so many: if "
            "the agent is escalating 80% of tickets, the classifier is the problem and the gate "
            "is just where it becomes visible.\n\n"
            "All three of those reduce clicks without making the approval mean something it did "
            "not mean when it was given."
        ),
        common_wrong_answer=(
            "Agreeing because the agent 'is usually right'. Accuracy is not the argument — the "
            "cost asymmetry is. A 99% accurate agent still issues one wrong refund in a hundred, "
            "and that is exactly the case the gate exists for."
        ),
        rubric=[
            point(
                "Refuses session-wide approval", "no", "scope", "per action", "one action", weight=3
            ),
            point(
                "Names it as privilege escalation or equivalent",
                "escalat",
                "authoris",
                "consent",
                "blanket",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Takes the click-fatigue complaint seriously",
                "fatigue",
                "click through",
                "real problem",
                "legitimate",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Offers concrete alternatives",
                "threshold",
                "batch",
                "auto-approve",
                "value",
                weight=2.5,
            ),
            point(
                "Mentions the audit trail",
                "audit",
                "trail",
                "who approved",
                "record",
                weight=1.5,
                dimension="production_awareness",
            ),
            point(
                "Questions the escalation rate itself",
                "why so many",
                "classifier",
                "rate",
                "upstream",
                weight=1.5,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "What would you log at the moment of approval?",
            "Where would you set the auto-approve threshold, and how would you defend it?",
        ],
        tags=["agents", "safety", "interview"],
        par_seconds=420,
    ),
    QuestionSpec(
        slug="q-agent-tool-description",
        kind=Q.MCQ,
        category=LC,
        tier=T.DEBUG,
        level=L.MID,
        prompt=(
            "An agent with eight tools keeps calling `search_docs` when it should call "
            "`lookup_account`. The model is capable and the prompt is detailed. Where do you "
            "look first?"
        ),
        concepts=["agent-tool-design"],
        options=[
            opt(
                "a",
                "The tool descriptions — especially whether each says when NOT to use it",
                correct=True,
                why="Tool selection is the model reading your descriptions. Two tools that both "
                "say 'searches for information' are indistinguishable. Adding 'Do NOT use for "
                "account or billing questions — use lookup_account' resolves most of these, and "
                "it is a five-minute fix rather than a model change.",
            ),
            opt(
                "b",
                "The system prompt — add an instruction about which tool to prefer",
                why="Possible as a patch, but the descriptions are where the model is actually "
                "looking at selection time, and the system prompt has to repeat it for every "
                "confusable pair.",
            ),
            opt(
                "c",
                "The model — switch to a larger one",
                why="Expensive, slow to validate, and it does not fix descriptions that are "
                "genuinely ambiguous. A larger model reading the same two identical "
                "descriptions has the same problem.",
            ),
            opt(
                "d",
                "The temperature — lower it for more deterministic selection",
                why="Makes the same wrong choice more consistently.",
            ),
        ],
        expected_answer="The tool descriptions, particularly the negative cases.",
        ideal_senior_answer=(
            "The descriptions. Selection is a reading-comprehension task over the docstrings, so "
            "two tools whose descriptions overlap are a specification bug, not a model bug. I "
            "would rewrite both to say what they return and explicitly when not to use them, "
            "naming the alternative. If they are still confused after that, they probably should "
            "be one tool with a parameter — and I would also check whether eight tools is too "
            "many, since selection accuracy degrades as the set grows."
        ),
        rubric=[point("Points at the descriptions", "description", "docstring", weight=3)],
        followups=["What would you write in the description?", "When would you merge two tools?"],
        tags=["agents", "tools"],
        par_seconds=150,
    ),
    QuestionSpec(
        slug="q-agent-cost-attribution",
        kind=Q.TRADEOFF,
        category=OBS,
        tier=T.STAFF_TRADEOFF,
        level=L.STAFF,
        prompt=(
            "Your agent costs $0.42 per run against a $0.05 budget. You have run totals but no "
            "per-step data. How do you approach this, and what would you have built differently?"
        ),
        concepts=["agent-cost-control"],
        expected_answer=(
            "Instrument per-step token usage first — cost in agents is never uniform, so "
            "optimising without attribution is guessing."
        ),
        ideal_senior_answer=(
            "I would not optimise anything until I can attribute the spend, because cost in an "
            "agent is never uniformly distributed and the intuitive answer is usually wrong. "
            "Step one is per-step token counts, split into input and output, keyed by node. "
            "That is an afternoon of instrumentation and it makes the rest of the work "
            "targeted rather than speculative.\n\n"
            "What I expect to find, in rough order of likelihood: a system prompt re-sent on "
            "every loop iteration, so a 3,000-token preamble is paid ten times per run; a "
            "retrieval node passing far more context than the answer needs; and a loop running "
            "more iterations than anyone realised.\n\n"
            "The fixes then rank themselves. Prompt caching on the static preamble is usually "
            "the single biggest win and changes no logic at all. Tightening retrieval from k=10 "
            "to k=4 often costs nothing in quality — that is measurable against the eval set. "
            "Routing the easy 70% of requests to a smaller model is a real quality trade and "
            "needs evidence. Cutting the loop bound is the last resort because it trades "
            "correctness for money.\n\n"
            "What I would have built differently: token accounting in the state from day one, "
            "with an `add` reducer and a budget the router checks, so exceeding it is a "
            "controlled halt rather than a surprise on the invoice. Cost is a functional "
            "requirement for an agent in the way it simply is not for a CRUD endpoint, and "
            "retrofitting the measurement is always more work than building it in."
        ),
        common_wrong_answer=(
            "Immediately switching to a cheaper model. It might work, it degrades quality by an "
            "unknown amount, and you still cannot say where the money went — so the next "
            "regression is equally blind."
        ),
        rubric=[
            point(
                "Instruments before optimising",
                "measure",
                "instrument",
                "attribut",
                "per-step",
                weight=3,
            ),
            point(
                "Separates input and output tokens",
                "input",
                "output",
                "separate",
                weight=2,
                dimension="depth",
            ),
            point(
                "Identifies the repeated system prompt",
                "system prompt",
                "every iteration",
                "repeat",
                "preamble",
                weight=2.5,
            ),
            point(
                "Proposes prompt caching",
                "cach",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Ranks fixes by quality risk",
                "trade",
                "quality",
                "risk",
                "last resort",
                weight=2.5,
                dimension="tradeoff_awareness",
            ),
            point(
                "Argues for budget in state from the start",
                "budget",
                "state",
                "day one",
                "reducer",
                weight=2,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "How would you decide the smaller model is good enough?",
            "What would you alert on?",
        ],
        tags=["agents", "cost", "interview"],
        par_seconds=480,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# MISSIONS
# ═════════════════════════════════════════════════════════════════════════════
MISSIONS = [
    MissionSpec(
        slug="mission-runaway-agent",
        title="Incident: The $380 Overnight Loop",
        kind="incident",
        category=LG,
        building="agent_factory",
        tier=T.DEBUG,
        briefing="""
**08:15.** The weekly AI spend alert fires. One agent consumed $380 between
23:40 and 06:10 on a single request.

The run eventually stopped — the recursion limit caught it after 2,100 steps.
Nobody was awake to see it start.

The PR that shipped last week is titled *"improve answer quality with a
reflection loop"*. It was approved by two people.
""",
        objective="Find why the loop never exited, bound it correctly, and say what review missed.",
        artifacts={
            "node_visits": ('{"draft": 1, "critique": 1050, "revise": 1049, "finalise": 0}'),
            "the_router": (
                "def route(state):\n"
                '    if state["score"] > 0.8:\n'
                '        return "finalise"\n'
                '    return "revise"'
            ),
            "score_history": (
                "step   4: score=0.71\n"
                "step  40: score=0.74\n"
                "step 400: score=0.74\n"
                "step 900: score=0.74\n"
                "step 2098: score=0.74   <- plateaued 2,000 steps ago"
            ),
            "cost_breakdown": (
                "critique  1050 calls  x ~3,100 tok  = $214\n"
                "revise    1049 calls  x ~2,400 tok  = $166\n"
                "finalise     0 calls                =   $0"
            ),
            "reviewer_comment": (
                'PR review: "LGTM, nice quality improvement. Recursion limit is 2500 so we '
                'have plenty of headroom."'
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="question",
                title="Read the visit counts",
                question="q-agent-recursion-limit",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Bound the loop",
                challenge="agent-fix-runaway-loop",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="What should review have asked?",
                prompt=(
                    "Two engineers approved this PR. Neither is careless. Write the review "
                    "question that would have caught it, and explain why 'the recursion limit "
                    "is 2500 so we have headroom' is exactly the wrong reassurance."
                ),
                config={
                    "rubric": [
                        point(
                            "Formulates the 'what bounds this cycle' question",
                            "what bounds",
                            "terminat",
                            "exit",
                            "counter",
                            weight=3,
                        ),
                        point(
                            "Explains the limit is a detector, not headroom",
                            "detector",
                            "safety net",
                            "not a fix",
                            "headroom",
                            weight=3,
                            dimension="production_awareness",
                        ),
                        point(
                            "Notes the score plateaued — the exit was never reachable",
                            "plateau",
                            "never reach",
                            "0.74",
                            "0.8",
                            weight=2.5,
                        ),
                        point(
                            "Raises cost bounds as a separate concern",
                            "budget",
                            "token",
                            "cost",
                            "spend",
                            weight=2,
                            dimension="architecture_thinking",
                        ),
                    ]
                },
            ),
            MissionStepSpec(
                step_type="journal",
                title="The question you will ask next time",
                prompt="One review question you will now ask on every agent PR.",
                required=False,
            ),
        ],
        concepts=["agent-termination", "agent-cost-control", "agent-conditional-edges"],
        success_criteria=[
            "Root cause identified as an exit condition that was never reachable",
            "Loop bounded with a counter the router reads",
            "Understands why raising the recursion limit is the wrong response",
        ],
        debrief="""
The score plateaued at 0.74 after roughly forty steps and then two thousand more
calls changed nothing. The exit condition was `score > 0.8`, so the loop was
never going to end — it was waiting on an event that had already stopped being
possible.

The reviewer's comment is the part worth sitting with. "The recursion limit is
2500 so we have headroom" treats the crash guard as capacity. It is not
capacity; it is the smoke detector, and a PR whose safety argument is "the smoke
detector is loud enough" has no safety argument.

Two things go in the checklist. **What bounds this cycle** — and the answer has
to be a counter that the router reads, not a quality threshold the model may
never satisfy. And **what bounds the spend** — because a step limit and a token
budget fail independently, and the $380 here was 1,050 calls that each looked
perfectly reasonable on their own.
""",
        required_level=14,
        estimated_minutes=30,
        par_seconds=1800,
    ),
    MissionSpec(
        slug="mission-build-support-agent",
        title="Build a Support Agent That Can Be Deployed",
        kind="agent_lab",
        category=LG,
        building="agent_factory",
        tier=T.DESIGN,
        briefing="""
You are building the support agent for real. It classifies a ticket, retrieves
context, drafts a response, evaluates its own confidence, and escalates when it
is unsure.

The bar is not "it works on the demo ticket". The bar is that you can answer
three questions about it in a deployment review:

1. What bounds every cycle?
2. What can it do without a human, and what can it not?
3. When it gives a wrong answer, how do you find out which step went wrong?
""",
        objective="Assemble the pieces and defend the design against a deployment review.",
        artifacts={
            "required_nodes": (
                "classify  -> categorise the ticket\n"
                "retrieve  -> fetch relevant docs\n"
                "draft     -> compose a response\n"
                "evaluate  -> score its own confidence\n"
                "escalate  -> hand to a human  [interrupt_before]\n"
                "respond   -> send the reply"
            ),
            "non_negotiables": (
                "- Sending a reply to a customer is irreversible. Gate it or justify not gating it.\n"
                "- The retrieve->draft->evaluate path may loop. Bound it.\n"
                "- Every step must be attributable in a trace."
            ),
            "open_in_the_lab": (
                "The Agent Factory lab has this exact graph as `support_agent`. Inspect its "
                "topology and step through a run before you write anything."
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="challenge",
                title="State merging",
                challenge="agent-implement-reducers",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="A router that cannot fall off the graph",
                challenge="agent-route-exhaustively",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Tools that survive their own failures",
                challenge="agent-tool-error-recovery",
            ),
            MissionStepSpec(
                step_type="question",
                title="Scope the approval",
                question="q-agent-hitl-scope",
            ),
            MissionStepSpec(
                step_type="design",
                title="Defend it in the deployment review",
                prompt=(
                    "Answer the three review questions for your design. Be specific: name the "
                    "counter that bounds the loop, name exactly which actions are gated and why "
                    "those and not others, and describe what you would record per step to make "
                    "a wrong answer attributable."
                ),
                config={
                    "rubric": [
                        point(
                            "Names a concrete counter bounding the loop",
                            "counter",
                            "attempts",
                            "max",
                            "increment",
                            weight=3,
                        ),
                        point(
                            "Gates irreversible actions specifically",
                            "irreversible",
                            "send",
                            "refund",
                            "gate",
                            weight=3,
                        ),
                        point(
                            "Argues against gating everything",
                            "fatigue",
                            "not everything",
                            "click through",
                            weight=2,
                            dimension="tradeoff_awareness",
                        ),
                        point(
                            "Specifies per-step trace contents",
                            "state diff",
                            "edge",
                            "token",
                            "per step",
                            weight=2.5,
                            dimension="production_awareness",
                        ),
                        point(
                            "Includes a cost bound as well as a step bound",
                            "budget",
                            "token",
                            "cost",
                            weight=2,
                            dimension="architecture_thinking",
                        ),
                    ]
                },
            ),
        ],
        concepts=[
            "agent-graph-state",
            "agent-conditional-edges",
            "agent-termination",
            "agent-human-in-the-loop",
            "agent-tool-design",
        ],
        success_criteria=[
            "Every cycle has a counter-based bound",
            "Irreversible actions are gated; reads are not",
            "Per-step tracing makes a wrong answer attributable to a node",
        ],
        debrief="""
The three review questions are the whole difference between an agent demo and an
agent deployment, and none of them is about the model.

What bounds the cycle is a correctness question. What is gated is a safety
question, and the answer "everything" is as wrong as "nothing" — approval fatigue
means the gate that mattered gets clicked through along with the fifty that did
not. And attributability is what makes the thing maintainable: without per-step
traces, every future bug report is "it gave a bad answer", which is not
actionable.

Open the same graph in the Agent Factory lab and step through a run. The visit
counts and state diffs you scrub through there are precisely the trace this
mission asked you to specify.
""",
        required_level=18,
        estimated_minutes=45,
        par_seconds=2700,
    ),
]

PACK = ContentPack(
    name="agent_factory",
    concepts=CONCEPTS,
    challenges=CHALLENGES,
    questions=QUESTIONS,
    missions=MISSIONS,
)
