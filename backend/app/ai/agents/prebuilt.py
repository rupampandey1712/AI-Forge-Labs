"""Prebuilt agent graphs for the Agent Factory.

Each graph is a *teaching artefact*: it demonstrates one pattern, and at least
one of them is deliberately broken so the player has something to diagnose.

| Graph                  | Teaches                                               |
| ---------------------- | ----------------------------------------------------- |
| `support_agent`        | Classify → retrieve → answer → evaluate → escalate     |
| `reflection_agent`     | A bounded self-correction loop                         |
| `runaway_agent`        | **Broken on purpose** — a loop with no exit condition  |
| `tool_agent`           | Tool selection, failure and retry                      |
| `research_agent`       | Parallel-ish fan-out then synthesis                    |
"""

from __future__ import annotations

from typing import Any

from app.ai.agents.graph import END, State, StateGraph, add, append, merge
from app.ai.llm.client import LLMClient, get_llm_client
from app.core.logging import get_logger

log = get_logger(__name__)

#: Shared reducers. `messages` must append or the agent forgets everything;
#: `tokens`/`cost` must add or only the last node's usage is recorded.
DEFAULT_REDUCERS = {
    "messages": append,
    "steps_taken": append,
    "tokens": add,
    "cost_usd": add,
    "retries": add,
    "metadata": merge,
    "evidence": append,
}


# ══ 1. Customer support agent ════════════════════════════════════════════════
def build_support_agent(llm: LLMClient | None = None, *, retriever=None) -> StateGraph:
    """Classify → retrieve → answer → self-evaluate → escalate or finish.

    The pattern worth internalising is the **evaluate** node. An agent that
    answers and stops has no idea whether it was right. One that scores its own
    answer and routes low confidence to a human is the difference between a demo
    and something you would put in front of customers.
    """
    client = llm or get_llm_client()

    async def classify(state: State) -> State:
        question = state["question"]
        prompt = (
            "Classify this customer request into exactly one of: "
            "billing, technical, account, other.\n\n"
            f"Request: {question}\n\n"
            'Respond with JSON: {"category": "...", "confidence": 0.0-1.0, "reason": "..."}'
        )
        data, response = await client.complete_json(prompt, temperature=0.0, max_tokens=200)
        category = str(data.get("category", "other")).lower()
        if category not in ("billing", "technical", "account", "other"):
            category = "other"
        return {
            "category": category,
            "classification_confidence": float(data.get("confidence", 0.5) or 0.5),
            "messages": [{"role": "system", "content": f"Classified as {category}"}],
            "tokens": response.usage.total_tokens,
            "cost_usd": response.cost_usd,
            "steps_taken": ["classify"],
        }

    async def retrieve(state: State) -> State:
        if retriever is None:
            return {
                "context": [],
                "steps_taken": ["retrieve(no-op)"],
                "messages": [{"role": "system", "content": "No retriever configured"}],
            }
        chunks = await retriever(state["question"], state.get("category", "other"))
        return {
            "context": chunks,
            "evidence": [c.get("title", "") for c in chunks],
            "steps_taken": ["retrieve"],
            "messages": [{"role": "system", "content": f"Retrieved {len(chunks)} chunks"}],
        }

    async def answer(state: State) -> State:
        context = "\n---\n".join(c.get("text", "") for c in state.get("context", []))
        prompt = (
            "Answer the customer's question using only the context. If the context "
            "is insufficient, say so plainly.\n\n"
            f"Context:\n{context or '(none)'}\n\nQuestion: {state['question']}\n\nAnswer:"
        )
        response = await client.complete(prompt, temperature=0.2, max_tokens=500)
        return {
            "answer": response.text.strip(),
            "messages": [{"role": "assistant", "content": response.text.strip()}],
            "tokens": response.usage.total_tokens,
            "cost_usd": response.cost_usd,
            "steps_taken": ["answer"],
        }

    async def evaluate(state: State) -> State:
        """Self-evaluation. The node that makes escalation possible."""
        context = "\n---\n".join(c.get("text", "") for c in state.get("context", []))
        prompt = (
            "Evaluate this answer for a customer.\n\n"
            f"Question: {state['question']}\n"
            f"Context: {context[:3000] or '(none)'}\n"
            f"Answer: {state.get('answer', '')}\n\n"
            'Respond with JSON: {"confidence": 0.0-1.0, "grounded": true/false, '
            '"issue": "<one sentence or empty>"}'
        )
        data, response = await client.complete_json(prompt, temperature=0.0, max_tokens=250)
        confidence = float(data.get("confidence", 0.5) or 0.5)
        # No retrieved context is itself grounds for escalation, regardless of
        # how confident the model claims to be — a fluent answer from nothing is
        # exactly the dangerous case.
        if not state.get("context"):
            confidence = min(confidence, 0.4)
        return {
            "confidence": confidence,
            "grounded": bool(data.get("grounded", False)),
            "issue": str(data.get("issue", ""))[:300],
            "tokens": response.usage.total_tokens,
            "cost_usd": response.cost_usd,
            "steps_taken": ["evaluate"],
        }

    async def escalate(state: State) -> State:
        return {
            "escalated": True,
            "needs_human": True,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"Escalated to a human: confidence {state.get('confidence', 0):.2f}. "
                        f"{state.get('issue', '')}"
                    ),
                }
            ],
            "steps_taken": ["escalate"],
        }

    async def finalize(state: State) -> State:
        return {
            "final_answer": state.get("answer", ""),
            "resolved": True,
            "steps_taken": ["finalize"],
        }

    def route_after_evaluate(state: State) -> str:
        if state.get("confidence", 0.0) < 0.6 or not state.get("grounded", False):
            return "low_confidence"
        return "confident"

    graph = StateGraph(reducers=DEFAULT_REDUCERS, name="support_agent")
    graph.add_node("classify", classify, kind="llm", description="Route the request by category")
    graph.add_node(
        "retrieve", retrieve, kind="retriever", description="Fetch knowledge-base context"
    )
    graph.add_node("answer", answer, kind="llm", description="Draft a grounded answer")
    graph.add_node("evaluate", evaluate, kind="llm", description="Score the draft before sending")
    graph.add_node(
        "escalate",
        escalate,
        kind="human",
        description="Hand to a human — pauses for approval",
        interrupt_before=True,
    )
    graph.add_node("finalize", finalize, kind="process", description="Send the answer")

    graph.set_entry_point("classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"low_confidence": "escalate", "confident": "finalize"},
        description="Escalate when confidence < 0.6 or the answer is ungrounded",
    )
    graph.add_edge("escalate", END)
    graph.add_edge("finalize", END)
    return graph.compile()


# ══ 2. Reflection agent — a BOUNDED loop ═════════════════════════════════════
def build_reflection_agent(llm: LLMClient | None = None, *, max_revisions: int = 3) -> StateGraph:
    """Draft → critique → revise, looping until good enough **or out of budget**.

    Contrast this with ``runaway_agent``: the topology is nearly identical. The
    only difference is that the router here checks a counter the loop itself
    increments. That one line is the whole lesson.
    """
    client = llm or get_llm_client()

    async def draft(state: State) -> State:
        response = await client.complete(
            f"Write a concise technical answer to: {state['question']}",
            temperature=0.4,
            max_tokens=400,
        )
        return {
            "draft": response.text.strip(),
            "revisions": 0,
            "tokens": response.usage.total_tokens,
            "steps_taken": ["draft"],
        }

    async def critique(state: State) -> State:
        prompt = (
            f"Critique this answer to '{state['question']}'. Be specific and harsh.\n\n"
            f"{state.get('draft', '')}\n\n"
            'Respond with JSON: {"quality": 0.0-1.0, "problems": ["..."], "good_enough": true/false}'
        )
        data, response = await client.complete_json(prompt, temperature=0.0, max_tokens=300)
        return {
            "quality": float(data.get("quality", 0.5) or 0.5),
            "problems": [str(p)[:200] for p in data.get("problems", [])][:5],
            "good_enough": bool(data.get("good_enough", False)),
            "tokens": response.usage.total_tokens,
            "steps_taken": ["critique"],
        }

    async def revise(state: State) -> State:
        problems = "\n".join(f"- {p}" for p in state.get("problems", []))
        response = await client.complete(
            f"Revise this answer, fixing these problems:\n{problems}\n\n{state.get('draft', '')}",
            temperature=0.3,
            max_tokens=500,
        )
        return {
            "draft": response.text.strip(),
            # The counter the router reads. Incrementing it here — inside the
            # loop — is what makes the bound real.
            "revisions": state.get("revisions", 0) + 1,
            "tokens": response.usage.total_tokens,
            "steps_taken": ["revise"],
        }

    async def publish(state: State) -> State:
        return {"final_answer": state.get("draft", ""), "steps_taken": ["publish"]}

    def route(state: State) -> str:
        if state.get("good_enough") or state.get("quality", 0.0) >= 0.8:
            return "done"
        if state.get("revisions", 0) >= max_revisions:
            # Budget exhausted. Ship the best draft rather than loop forever —
            # a bounded-quality answer beats an unbounded bill.
            return "budget_exhausted"
        return "revise"

    graph = StateGraph(reducers=DEFAULT_REDUCERS, name="reflection_agent")
    graph.add_node("draft", draft, kind="llm", description="First attempt")
    graph.add_node("critique", critique, kind="llm", description="Score and find problems")
    graph.add_node("revise", revise, kind="llm", description="Fix the problems")
    graph.add_node("publish", publish, kind="process", description="Ship it")

    graph.set_entry_point("draft")
    graph.add_edge("draft", "critique")
    graph.add_conditional_edges(
        "critique",
        route,
        {"revise": "revise", "done": "publish", "budget_exhausted": "publish"},
        description=f"Loop until quality >= 0.8 or {max_revisions} revisions",
    )
    graph.add_edge("revise", "critique")
    graph.add_edge("publish", END)
    return graph.compile()


# ══ 3. Runaway agent — BROKEN ON PURPOSE ═════════════════════════════════════
def build_runaway_agent(llm: LLMClient | None = None) -> StateGraph:
    """The infinite-loop boss.

    The bug: ``revise`` never increments a counter, and the router has no
    budget check — so "not good enough yet" routes back forever. The recursion
    limit catches it, and the halt message points at the node visit counts.

    The player's job is to find *why*, not just to raise the limit. Raising the
    limit is the wrong fix, and the debrief says so.
    """
    client = llm or get_llm_client()

    async def think(state: State) -> State:
        response = await client.complete(
            f"Think about: {state['question']}", temperature=0.5, max_tokens=200
        )
        return {
            "thought": response.text.strip(),
            "steps_taken": ["think"],
            "tokens": response.usage.total_tokens,
        }

    async def act(state: State) -> State:
        return {"acted": True, "steps_taken": ["act"]}

    async def check(state: State) -> State:
        # Always dissatisfied. No counter. No budget. No exit.
        return {"satisfied": False, "steps_taken": ["check"]}

    async def finish(state: State) -> State:
        return {"final_answer": state.get("thought", ""), "steps_taken": ["finish"]}

    def route(state: State) -> str:
        return "done" if state.get("satisfied") else "keep_going"

    graph = StateGraph(reducers=DEFAULT_REDUCERS, name="runaway_agent")
    graph.add_node("think", think, kind="llm", description="Reason about the task")
    graph.add_node("act", act, kind="tool", description="Take an action")
    graph.add_node("check", check, kind="process", description="Are we done? (never says yes)")
    graph.add_node("finish", finish, kind="process", description="Unreachable in practice")

    graph.set_entry_point("think")
    graph.add_edge("think", "act")
    graph.add_edge("act", "check")
    graph.add_conditional_edges(
        "check",
        route,
        {"keep_going": "think", "done": "finish"},
        description="⚠ No budget check — this edge is the bug",
    )
    graph.add_edge("finish", END)
    return graph.compile()


# ══ 4. Tool agent — selection, failure, retry ════════════════════════════════
def build_tool_agent(
    llm: LLMClient | None = None, *, tools: dict[str, Any] | None = None
) -> StateGraph:
    """Choose a tool, run it, handle failure, retry with a bound.

    Teaches the thing tool-calling tutorials skip: **what happens when the tool
    fails**. A tool that raises and an agent that does not handle it is how a
    demo becomes an outage.
    """
    client = llm or get_llm_client()
    available = tools or {
        "calculator": lambda q: f"calculated({q})",
        "search": lambda q: f"results for {q}",
        "database": lambda q: f"rows matching {q}",
    }

    async def select_tool(state: State) -> State:
        prompt = (
            f"Which tool best answers this? Available: {list(available)}\n\n"
            f"Question: {state['question']}\n\n"
            'Respond with JSON: {"tool": "...", "input": "...", "reason": "..."}'
        )
        data, response = await client.complete_json(prompt, temperature=0.0, max_tokens=200)
        chosen = str(data.get("tool", ""))
        return {
            "tool": chosen if chosen in available else "search",
            "tool_input": str(data.get("input", state["question"])),
            "tool_valid": chosen in available,
            "tokens": response.usage.total_tokens,
            "steps_taken": ["select_tool"],
        }

    async def run_tool(state: State) -> State:
        name = state.get("tool", "search")
        try:
            result = available[name](state.get("tool_input", ""))
            return {"tool_result": str(result), "tool_error": None, "steps_taken": [f"run:{name}"]}
        except Exception as exc:
            return {
                "tool_result": None,
                "tool_error": f"{type(exc).__name__}: {exc}",
                "retries": 1,
                "steps_taken": [f"run:{name}:failed"],
            }

    async def synthesize(state: State) -> State:
        response = await client.complete(
            f"Answer '{state['question']}' using this tool output:\n{state.get('tool_result', '')}",
            temperature=0.2,
            max_tokens=400,
        )
        return {
            "final_answer": response.text.strip(),
            "tokens": response.usage.total_tokens,
            "steps_taken": ["synthesize"],
        }

    async def give_up(state: State) -> State:
        return {
            "final_answer": (
                "I could not complete this request — the tools I have available failed. "
                f"Last error: {state.get('tool_error', 'unknown')}"
            ),
            "failed": True,
            "steps_taken": ["give_up"],
        }

    def route(state: State) -> str:
        if state.get("tool_error") is None:
            return "success"
        # Bounded retry. Unbounded retry against a genuinely broken tool is a
        # denial-of-service attack you wrote against yourself.
        return "retry" if state.get("retries", 0) < 2 else "give_up"

    graph = StateGraph(reducers=DEFAULT_REDUCERS, name="tool_agent")
    graph.add_node("select_tool", select_tool, kind="llm", description="Pick a tool")
    graph.add_node("run_tool", run_tool, kind="tool", description="Execute it")
    graph.add_node("synthesize", synthesize, kind="llm", description="Turn output into an answer")
    graph.add_node("give_up", give_up, kind="process", description="Fail honestly")

    graph.set_entry_point("select_tool")
    graph.add_edge("select_tool", "run_tool")
    graph.add_conditional_edges(
        "run_tool",
        route,
        {"success": "synthesize", "retry": "select_tool", "give_up": "give_up"},
        description="Retry at most twice, then fail honestly",
    )
    graph.add_edge("synthesize", END)
    graph.add_edge("give_up", END)
    return graph.compile()


# ══ Registry ═════════════════════════════════════════════════════════════════
GRAPH_BUILDERS = {
    "support_agent": build_support_agent,
    "reflection_agent": build_reflection_agent,
    "runaway_agent": build_runaway_agent,
    "tool_agent": build_tool_agent,
}

GRAPH_INFO = {
    "support_agent": {
        "title": "Customer Support Agent",
        "teaches": "Classify → retrieve → answer → self-evaluate → escalate",
        "difficulty": 5,
        "broken": False,
        "watch_for": "The evaluate node is what makes escalation possible at all.",
    },
    "reflection_agent": {
        "title": "Reflection Agent",
        "teaches": "A self-correction loop with a real budget",
        "difficulty": 6,
        "broken": False,
        "watch_for": "`revise` increments the counter the router reads. That is the bound.",
    },
    "runaway_agent": {
        "title": "Runaway Agent ⚠",
        "teaches": "Why agents loop forever — and why raising the limit is the wrong fix",
        "difficulty": 7,
        "broken": True,
        "watch_for": "Compare the node visit counts against the reflection agent's.",
    },
    "tool_agent": {
        "title": "Tool-Calling Agent",
        "teaches": "Tool selection, failure handling and bounded retry",
        "difficulty": 6,
        "broken": False,
        "watch_for": "What happens when the tool raises — most tutorials skip this.",
    },
}


def build_graph(slug: str, **kwargs: Any) -> StateGraph:
    builder = GRAPH_BUILDERS.get(slug)
    if builder is None:
        raise KeyError(f"unknown graph '{slug}'")
    return builder(**kwargs)
