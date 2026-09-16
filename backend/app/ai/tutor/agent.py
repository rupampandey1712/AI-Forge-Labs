"""The AI Mentor — an agent that teaches instead of answering.

SPEC §58: the mentor must NOT immediately give answers. It escalates:

    Hint 1 → Hint 2 → concept reminder → partial explanation → full explanation

That escalation is implemented as a **graph**, not an if-ladder, for a reason
that is itself part of the curriculum: the player can open the LangGraph
Inspector and watch the mentor that is helping them run as a state machine. The
tool teaches its own mechanism.

Three agents live here:

| Agent               | Job                                                       |
| ------------------- | --------------------------------------------------------- |
| `MentorAgent`       | Escalating help, calibrated to what the player has tried   |
| `SocraticAgent`     | Asks the question that exposes the misconception           |
| `ContentAgent`      | Generates questions/explanations from a concept, validated |

All three degrade to deterministic offline behaviour with no API key.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai.agents.graph import END, State, StateGraph, append, merge
from app.ai.llm.client import LLMClient, get_llm_client
from app.core.logging import get_logger
from app.domain.enums import DifficultyTier, MentorPersona

log = get_logger(__name__)

HelpLevel = Literal["nudge", "hint", "concept", "partial", "full"]

ESCALATION: tuple[HelpLevel, ...] = ("nudge", "hint", "concept", "partial", "full")

PERSONA_VOICE: dict[str, str] = {
    MentorPersona.SENIOR_ENGINEER.value: (
        "A senior engineer who has debugged this exact class of problem at 3am. "
        "Direct, concrete, allergic to hand-waving. Uses real numbers."
    ),
    MentorPersona.ML_RESEARCHER.value: (
        "An ML researcher. Precise about what is empirically established versus "
        "folklore. Will say 'we don't actually know why that works'."
    ),
    MentorPersona.BACKEND_ARCHITECT.value: (
        "A backend architect. Thinks in boundaries, failure modes and what "
        "breaks at 10x. Names the trade-off before the solution."
    ),
    MentorPersona.AI_ARCHITECT.value: (
        "An AI platform architect. Fluent in retrieval, evaluation and cost. "
        "Suspicious of demos that have never met real data."
    ),
    MentorPersona.CODE_REVIEWER.value: (
        "A code reviewer. Asks 'what happens when this is called twice' and "
        "'what does this do at scale'. Praises specifically, criticises specifically."
    ),
    MentorPersona.INTERVIEWER.value: (
        "An interviewer. Will not give you the answer. Asks the follow-up that "
        "reveals whether you understand or memorised."
    ),
}


@dataclass(slots=True)
class MentorRequest:
    question: str
    concept_slug: str | None = None
    concept_title: str = ""
    concept_summary: str = ""
    code: str | None = None
    error: str | None = None
    tier: int = 5
    #: How many hints the player has already burned. Drives escalation.
    attempts: int = 0
    hints_used: int = 0
    persona: str = MentorPersona.SENIOR_ENGINEER.value
    #: Authored hints from the content pack, used before any generation.
    authored_hints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MentorResponse:
    level: HelpLevel
    message: str
    #: A question handed back to the player, when the right move is to ask.
    question_back: str | None = None
    next_level: HelpLevel | None = None
    reveals_answer: bool = False
    simulated: bool = False
    tokens: int = 0
    cost_usd: float = 0.0
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "question_back": self.question_back,
            "next_level": self.next_level,
            "reveals_answer": self.reveals_answer,
            "simulated": self.simulated,
            "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 6),
            "trace": self.trace,
        }


def escalation_for(attempts: int, hints_used: int) -> HelpLevel:
    """How much help has been earned.

    Escalation is driven by *demonstrated effort*, not by asking louder. A
    player on their first attempt gets a nudge no matter how many times they
    click — because handing over the answer at attempt one is the single
    fastest way to make a learning tool useless.
    """
    earned = min(len(ESCALATION) - 1, max(hints_used, attempts // 2))
    return ESCALATION[earned]


class MentorAgent:
    """Escalating help, delivered as a graph so the player can inspect it."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def build_graph(self, request: MentorRequest) -> StateGraph:
        llm = self.llm

        async def assess(state: State) -> State:
            """Decide how much help has been earned, before generating any."""
            level = escalation_for(request.attempts, request.hints_used)
            return {
                "level": level,
                "escalation_index": ESCALATION.index(level),
                "steps_taken": ["assess"],
                "metadata": {"attempts": request.attempts, "hints_used": request.hints_used},
            }

        async def use_authored(state: State) -> State:
            """Prefer hints a human wrote. They are always better than generated
            ones, because they were written knowing the specific trap."""
            index = request.hints_used
            if index < len(request.authored_hints):
                return {
                    "message": request.authored_hints[index],
                    "source": "authored",
                    "steps_taken": ["use_authored"],
                }
            return {"source": "generate", "steps_taken": ["use_authored(none left)"]}

        async def generate(state: State) -> State:
            level: HelpLevel = state["level"]
            prompt = _mentor_prompt(request, level)
            response = await llm.complete(
                prompt,
                system=(
                    f"You are a mentor at AI Forge Labs. {PERSONA_VOICE.get(request.persona, '')} "
                    "You NEVER give the full answer unless explicitly at the 'full' level. "
                    "Prefer asking one sharp question over explaining."
                ),
                temperature=0.4,
                max_tokens=450,
            )
            return {
                "message": response.text.strip(),
                "source": "generated",
                "simulated": response.simulated,
                "tokens": response.usage.total_tokens,
                "cost_usd": response.cost_usd,
                "steps_taken": ["generate"],
            }

        async def finalize(state: State) -> State:
            level: HelpLevel = state["level"]
            index = ESCALATION.index(level)
            return {
                "next_level": ESCALATION[index + 1] if index + 1 < len(ESCALATION) else None,
                "reveals_answer": level == "full",
                "steps_taken": ["finalize"],
            }

        def route(state: State) -> str:
            return "have_message" if state.get("message") else "need_generation"

        graph = StateGraph(reducers={"steps_taken": append, "metadata": merge}, name="mentor")
        graph.add_node("assess", assess, kind="process", description="How much help is earned?")
        graph.add_node(
            "use_authored", use_authored, kind="retriever", description="Prefer human-written hints"
        )
        graph.add_node("generate", generate, kind="llm", description="Generate at the earned level")
        graph.add_node("finalize", finalize, kind="process", description="Attach the next step")

        graph.set_entry_point("assess")
        graph.add_edge("assess", "use_authored")
        graph.add_conditional_edges(
            "use_authored",
            route,
            {"have_message": "finalize", "need_generation": "generate"},
            description="Authored hints always win over generated ones",
        )
        graph.add_edge("generate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def help(self, request: MentorRequest) -> MentorResponse:
        graph = self.build_graph(request)
        run = await graph.run({"question": request.question}, recursion_limit=10)
        state = run.final_state

        message = state.get("message") or _offline_fallback(request, state.get("level", "nudge"))
        return MentorResponse(
            level=state.get("level", "nudge"),
            message=message,
            question_back=_extract_question(message),
            next_level=state.get("next_level"),
            reveals_answer=bool(state.get("reveals_answer")),
            simulated=bool(state.get("simulated")),
            tokens=int(state.get("tokens", 0) or 0),
            cost_usd=float(state.get("cost_usd", 0.0) or 0.0),
            trace=[record.to_dict() for record in run.history],
        )


def _mentor_prompt(request: MentorRequest, level: HelpLevel) -> str:
    context = [f"The learner is working on: {request.question}"]
    if request.concept_title:
        context.append(f"Concept: {request.concept_title} — {request.concept_summary}")
    if request.code:
        context.append(f"Their current code:\n```python\n{request.code[:2000]}\n```")
    if request.error:
        context.append(f"The error they are seeing:\n{request.error[:800]}")
    context.append(f"This is a tier-{request.tier} problem (1=recall, 10=principal architecture).")
    context.append(
        f"They have made {request.attempts} attempt(s) and used {request.hints_used} hint(s)."
    )

    instruction = {
        "nudge": (
            "Give ONE short question that redirects their attention to the right place. "
            "Do not explain anything. Under 30 words."
        ),
        "hint": (
            "Give one concrete hint pointing at the mechanism — name the concept or the "
            "function involved, but do not show the fix. Under 50 words."
        ),
        "concept": (
            "Remind them of the underlying concept and why it behaves this way. Explain the "
            "mechanism, not their specific fix. Under 120 words."
        ),
        "partial": (
            "Walk them most of the way: explain the cause precisely and describe the shape of "
            "the fix, but leave the final step for them to write. Under 180 words."
        ),
        "full": (
            "They have earned the full answer. Explain the cause, give the fix with code, and "
            "state the one thing they should remember so this does not recur."
        ),
    }[level]

    return "\n\n".join(context) + f"\n\nYour task ({level} level): {instruction}"


def _offline_fallback(request: MentorRequest, level: HelpLevel) -> str:
    """Deterministic help when no provider is configured.

    Generic, but genuinely useful — these are the questions that unstick most
    problems, which is why they are the fallback rather than an apology.
    """
    return {
        "nudge": (
            "Before changing anything: what did you *expect* this to do, and what did it "
            "actually do? Write both down. The gap is usually the bug."
        ),
        "hint": (
            "Narrow it. Find the smallest input that still shows the problem, then read the "
            "error from the bottom up — the last line is what broke, the lines above are how "
            "you got there."
        ),
        "concept": (
            f"Re-read the mechanism behind {request.concept_title or 'this concept'}. Most bugs "
            "at this tier come from an assumption about *when* something happens — at "
            "definition time or call time, eagerly or lazily — rather than from the syntax."
        ),
        "partial": (
            "Work backwards from the failing assertion. What value would have to be true one "
            "line earlier for it to pass? Now check whether that value is what you think it is. "
            "Print it if you are not certain."
        ),
        "full": (
            "No provider is configured, so I cannot generate the full explanation. Reveal the "
            "reference solution instead — and then write down, in your own words, why it works. "
            "Reading a solution you have not explained back to yourself does not stick."
        ),
    }[level]


def _extract_question(message: str) -> str | None:
    questions = [s.strip() for s in re.split(r"(?<=[?])\s+", message) if s.strip().endswith("?")]
    return questions[0] if questions else None


# ══ Socratic agent ═══════════════════════════════════════════════════════════
class SocraticAgent:
    """Asks the question that exposes the misconception.

    Distinct from the mentor: the mentor helps you finish the task, this one
    checks whether you understood it. Used after a *pass*, which is where
    understanding is most often absent and least often checked.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    async def probe(
        self,
        *,
        concept_title: str,
        concept_summary: str,
        player_answer: str,
        tier: int = 5,
    ) -> dict[str, Any]:
        prompt = (
            f"A learner just gave this answer about '{concept_title}':\n\n"
            f"{player_answer[:2000]}\n\n"
            f"Concept summary: {concept_summary}\n\n"
            "Ask ONE follow-up question that would reveal whether they actually understand "
            "or merely pattern-matched. Target the most likely misconception.\n\n"
            'Respond with JSON: {"question": "...", "targets_misconception": "...", '
            '"good_answer_contains": ["...", "..."]}'
        )
        data, response = await self.llm.complete_json(prompt, temperature=0.5, max_tokens=300)
        return {
            "question": str(data.get("question", ""))
            or f"You said that — now: what would break if the opposite were true about {concept_title}?",
            "targets_misconception": str(data.get("targets_misconception", "")),
            "good_answer_contains": [str(x) for x in data.get("good_answer_contains", [])][:5],
            "tier": min(10, tier + 1),
            "simulated": response.simulated,
        }


# ══ Content generation agent ═════════════════════════════════════════════════
GENERATION_SCHEMA = """{
  "prompt": "<the question>",
  "context": "<code snippet or scenario, or empty string>",
  "kind": "mcq | explain | scenario | tradeoff | debugging | predict_output",
  "options": [{"id":"a","text":"...","correct":true,"why":"..."}],
  "expected_answer": "<short reference answer>",
  "ideal_senior_answer": "<what a strong senior answer contains>",
  "common_wrong_answer": "<the most likely wrong answer, and why it is wrong>",
  "rubric": [{"point":"<what a good answer says>","keywords":["...","..."],"weight":2.0}],
  "hints": ["<escalating hint 1>", "<hint 2>", "<hint 3>"],
  "followups": ["<harder follow-up 1>", "<follow-up 2>"]
}"""


@dataclass(slots=True)
class GeneratedQuestion:
    prompt: str
    kind: str
    tier: int
    context: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    expected_answer: str = ""
    ideal_senior_answer: str = ""
    common_wrong_answer: str = ""
    rubric: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    #: Problems found by validation. Non-empty means do not serve this.
    issues: list[str] = field(default_factory=list)
    simulated: bool = False

    @property
    def is_usable(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "kind": self.kind,
            "tier": self.tier,
            "context": self.context,
            "options": self.options,
            "expected_answer": self.expected_answer,
            "ideal_senior_answer": self.ideal_senior_answer,
            "common_wrong_answer": self.common_wrong_answer,
            "rubric": self.rubric,
            "hints": self.hints,
            "followups": self.followups,
            "issues": self.issues,
            "is_usable": self.is_usable,
            "simulated": self.simulated,
        }


class ContentAgent:
    """Generates questions from a concept — and validates them before serving.

    WHY the validation step is the important half: an LLM will happily produce
    a multiple-choice question with two correct answers, a rubric whose keywords
    never appear in its own model answer, or four distractors with no
    explanation. Serving any of those teaches the player something false.

    So every generated question is run through the *same grader the game uses*,
    and rejected if the model answer cannot pass its own rubric. That is the
    identical check `test_content_integrity.py` applies to hand-authored
    content — generated content is held to the same bar, not a lower one.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    async def generate_question(
        self,
        *,
        concept_title: str,
        concept_summary: str,
        concept_explanation: str,
        tier: int,
        kind: str = "explain",
        avoid: list[str] | None = None,
    ) -> GeneratedQuestion:
        tier_brief = _TIER_BRIEF.get(tier, _TIER_BRIEF[5])
        avoid_block = (
            "Do NOT repeat these existing questions:\n"
            + "\n".join(f"- {a}" for a in (avoid or [])[:8])
            + "\n\n"
            if avoid
            else ""
        )

        prompt = (
            f"Write ONE tier-{tier} interview question about: {concept_title}\n\n"
            f"Concept summary: {concept_summary}\n"
            f"Key mechanics: {concept_explanation[:1500]}\n\n"
            f"Tier {tier} means: {tier_brief}\n\n"
            f"{avoid_block}"
            f"Question kind: {kind}\n\n"
            "Requirements:\n"
            "- The question must test the MECHANISM, not vocabulary recall.\n"
            "- If MCQ: exactly one correct option, and EVERY option needs a 'why'.\n"
            "- The rubric keywords must actually appear in your ideal_senior_answer.\n"
            "- Hints must escalate and must not give the answer away.\n\n"
            f"Respond with ONLY this JSON:\n{GENERATION_SCHEMA}"
        )

        data, response = await self.llm.complete_json(prompt, temperature=0.7, max_tokens=1600)
        question = GeneratedQuestion(
            prompt=str(data.get("prompt", "")).strip(),
            kind=str(data.get("kind", kind)),
            tier=tier,
            context=str(data.get("context", "")),
            options=_clean_options(data.get("options", [])),
            expected_answer=str(data.get("expected_answer", "")),
            ideal_senior_answer=str(data.get("ideal_senior_answer", "")),
            common_wrong_answer=str(data.get("common_wrong_answer", "")),
            rubric=_clean_rubric(data.get("rubric", [])),
            hints=[str(h) for h in data.get("hints", [])][:5],
            followups=[str(f) for f in data.get("followups", [])][:4],
            simulated=response.simulated,
        )
        question.issues = validate_generated(question)
        if question.issues:
            log.warning(
                "content_agent.rejected",
                concept=concept_title,
                tier=tier,
                issues=question.issues,
            )
        return question

    async def explain_concept(
        self, *, concept_title: str, depth: Literal["brief", "standard", "deep"] = "standard"
    ) -> dict[str, Any]:
        words = {"brief": 80, "standard": 250, "deep": 600}[depth]
        prompt = (
            f"Explain '{concept_title}' to a working engineer in about {words} words.\n\n"
            "Lead with the mechanism — what actually happens, not what it is called. "
            "Include one concrete failure this causes in production. "
            "Do not pad, do not define terms the reader already knows."
        )
        response = await self.llm.complete(prompt, temperature=0.3, max_tokens=words * 2)
        return {
            "explanation": response.text.strip(),
            "depth": depth,
            "simulated": response.simulated,
            "tokens": response.usage.total_tokens,
        }


_TIER_BRIEF: dict[int, str] = {
    1: "recall a fact",
    2: "explain why something behaves that way",
    3: "implement it correctly",
    4: "diagnose a bug in given code",
    5: "make it faster, and say by how much",
    6: "design a solution and justify the structure",
    7: "explain it to another engineer so they can act on it",
    8: "diagnose a production incident from evidence",
    9: "argue a trade-off and name what would change your mind",
    10: "design the architecture and its failure modes",
}


def _clean_options(raw: Any) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        options.append(
            {
                "id": str(item.get("id") or chr(ord("a") + i)),
                "text": str(item.get("text", "")),
                "correct": bool(item.get("correct", False)),
                "why": str(item.get("why", "")),
            }
        )
    return options[:6]


def _clean_rubric(raw: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        keywords = item.get("keywords") or []
        points.append(
            {
                "point": str(item.get("point", "")),
                "keywords": [str(k).lower() for k in keywords if str(k).strip()][:8],
                "weight": float(item.get("weight", 1.0) or 1.0),
                "dimension": str(item.get("dimension", "correctness")),
            }
        )
    return points[:8]


def validate_generated(question: GeneratedQuestion) -> list[str]:
    """Hold generated content to the hand-authored bar.

    The last check is the one that matters most: the generated *model answer*
    must pass the generated *rubric*. An LLM that writes a rubric its own ideal
    answer fails has produced a question that is impossible to score correctly,
    and no amount of downstream prompting fixes that.
    """
    from app.game.grading.rubric import grade_free_text

    issues: list[str] = []

    if len(question.prompt) < 25:
        issues.append("prompt is too short to be a real question")
    if not question.ideal_senior_answer:
        issues.append("no ideal answer — the player could not see the gap")

    if question.kind in ("mcq", "multi_select"):
        correct = [o for o in question.options if o["correct"]]
        if len(question.options) < 3:
            issues.append("fewer than 3 options")
        if not correct:
            issues.append("no correct option")
        if question.kind == "mcq" and len(correct) > 1:
            issues.append("MCQ has more than one correct option")
        missing_why = [o["id"] for o in question.options if not o["why"].strip()]
        if missing_why:
            issues.append(f"options {missing_why} have no explanation")
    else:
        if not question.rubric:
            issues.append("free-text question with no rubric is ungradable")
        else:
            empty = [p["point"] for p in question.rubric if not p["keywords"]]
            if empty:
                issues.append(f"{len(empty)} rubric point(s) have no matchable keywords")

            grade = grade_free_text(
                question.ideal_senior_answer, question.rubric, tier=question.tier
            )
            if grade.dimension_scores.get("correctness", 0.0) < 0.6:
                issues.append(
                    f"the ideal answer scores only "
                    f"{grade.dimension_scores.get('correctness', 0):.2f} against its own rubric "
                    f"(missing: {grade.missing_points[:3]})"
                )

    if len(question.hints) < 2:
        issues.append("fewer than 2 hints — no escalation ladder")

    return issues


def parse_json_block(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction, for callers outside ``LLMClient``."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def tier_for_difficulty(tier: DifficultyTier | int) -> int:
    return int(tier)
