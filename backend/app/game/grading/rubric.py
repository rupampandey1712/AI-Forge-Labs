"""Deterministic free-text grading.

WHY a rubric grader when an LLM judge exists: the game must work fully offline,
must grade the same answer the same way twice, and must be able to tell the
player *exactly* what was missing. An LLM judge is available and better at
nuance (see ``app/ai/evaluation``), but it is an enhancement layered on top of
this, never a prerequisite for playing.

HOW it works. Each question carries a rubric: a list of *points* the answer
should make, each with a weight, a set of surface forms, and the scoring
dimension it belongs to. Coverage of those points drives ``correctness``; the
other six dimensions of spec §57 are scored from linguistic signals that
distinguish a junior answer from a staff one:

    junior  "Caching stores data so it's faster."
    senior  "Cache the read path in Redis with a 60s TTL..."
    staff   "...but the invalidation story is the real cost, and at our write
             rate a stale-while-revalidate window is cheaper than fan-out."

The staff answer is not longer — it is *comparative*, *quantified* and
*failure-aware*. Those are exactly what the signal groups below detect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

DIMENSIONS = (
    "correctness",
    "depth",
    "practical_experience",
    "tradeoff_awareness",
    "clarity",
    "architecture_thinking",
    "production_awareness",
)

#: Relative contribution to the final 0-10 score.
DIMENSION_WEIGHTS: dict[str, float] = {
    "correctness": 0.34,
    "depth": 0.18,
    "tradeoff_awareness": 0.13,
    "practical_experience": 0.11,
    "production_awareness": 0.10,
    "architecture_thinking": 0.08,
    "clarity": 0.06,
}

TRADEOFF_SIGNALS = (
    "trade-off",
    "tradeoff",
    "however",
    "but ",
    "although",
    "at the cost",
    "downside",
    "drawback",
    "versus",
    " vs ",
    "instead of",
    "rather than",
    "in exchange",
    "the price",
    "compromise",
    "depends on",
    "it depends",
    "on the other hand",
    "whereas",
    "unless",
    "caveat",
    "limitation",
)

PRACTICAL_SIGNALS = (
    "in production",
    "in practice",
    "i've seen",
    "we had",
    "i had",
    "at my",
    "real world",
    "in my experience",
    "actually",
    "we ended up",
    "shipped",
    "on-call",
    "postmortem",
    "root cause",
    "incident",
    "we measured",
    "profiled",
    "benchmark",
    "load test",
)

PRODUCTION_SIGNALS = (
    "latency",
    "throughput",
    "p95",
    "p99",
    "slo",
    "sla",
    "monitor",
    "alert",
    "rollback",
    "rollout",
    "canary",
    "feature flag",
    "backpressure",
    "retry",
    "idempot",
    "timeout",
    "circuit breaker",
    "graceful",
    "degrade",
    "capacity",
    "observability",
    "metric",
    "trace",
    "log",
    "cost",
    "quota",
    "rate limit",
    "failure mode",
    "blast radius",
    "outage",
)

ARCHITECTURE_SIGNALS = (
    "coupling",
    "cohesion",
    "boundary",
    "interface",
    "abstraction",
    "layer",
    "separation of concerns",
    "dependency",
    "contract",
    "single responsibility",
    "composition",
    "inversion",
    "scalab",
    "horizontal",
    "vertical",
    "shard",
    "partition",
    "queue",
    "async",
    "event-driven",
    "cache",
    "replica",
    "consistency",
    "stateless",
    "bottleneck",
)

DEPTH_SIGNALS = (
    "under the hood",
    "internally",
    "because",
    "the reason",
    "which means",
    "implementation",
    "bytecode",
    "reference count",
    "event loop",
    "descriptor",
    "b-tree",
    "query plan",
    "gradient",
    "attention",
    "embedding",
    "protocol",
    "specifically",
    "concretely",
    "for example",
    "e.g.",
)

HEDGE_SIGNALS = ("i think", "maybe", "probably", "not sure", "i guess", "kind of", "sort of")

#: Answers shorter than this cannot demonstrate depth no matter what they say.
MIN_SUBSTANTIVE_WORDS = 12
#: Past this, extra length stops helping — rambling is a clarity problem.
IDEAL_MAX_WORDS = 320


@dataclass(slots=True)
class RubricPoint:
    """One thing a good answer says."""

    point: str
    weight: float = 1.0
    keywords: tuple[str, ...] = ()
    dimension: str = "correctness"
    #: Requires ALL of these instead of ANY — for points that only count when
    #: two ideas appear together ("cache" AND "invalidation").
    require_all: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RubricPoint:
        kws = data.get("keywords") or data.get("aliases") or []
        if isinstance(kws, str):
            kws = [kws]
        if kw := data.get("keyword"):
            kws = [kw, *kws]
        return cls(
            point=data.get("point") or data.get("keyword") or "",
            weight=float(data.get("weight", 1.0)),
            # Normalised with the same function as the answer text — otherwise a
            # keyword like "o(n^2)" can never match anything.
            keywords=tuple(_normalise(str(k)) for k in kws if str(k).strip()),
            dimension=data.get("dimension", "correctness"),
            require_all=bool(data.get("require_all", False)),
        )


@dataclass(slots=True)
class RubricGrade:
    score: float  # 0..10
    dimension_scores: dict[str, float] = field(default_factory=dict)
    hit_points: list[str] = field(default_factory=list)
    missing_points: list[str] = field(default_factory=list)
    normalised: float = 0.0  # 0..1, for the retention engine
    word_count: int = 0
    graded_by: str = "rubric"


def _normalise(text: str) -> str:
    """Fold text to a comparable form.

    Punctuation is collapsed so "async/await" matches "async await" and code
    fences cannot hide a keyword. Whitespace is collapsed too, so a keyword
    written as "o(n^2)" (which normalises to "o n 2") still matches an answer
    that wrote "O(n**2)" or "O(n squared)".

    CRITICAL: rubric keywords must go through this *same* function — see
    ``RubricPoint.from_dict``. An earlier version normalised only the answer,
    so every keyword containing a bracket or a caret silently never matched
    and correctness scored 0 for genuinely correct answers.
    """
    lowered = text.lower().replace("`", " ")
    collapsed = re.sub(r"[^a-z0-9+#./ -]+", " ", lowered)
    return re.sub(r"\s+", " ", collapsed).strip()


@lru_cache(maxsize=32)
def _normalised_signals(signals: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_normalise(s) for s in signals if _normalise(s)))


def _count_signals(text: str, signals: tuple[str, ...]) -> int:
    """Count distinct signal phrases present. Signals are normalised to match
    the folded text (e.g. "trade-off" and "p99" survive; "e.g." folds to "e.g")."""
    return sum(1 for s in _normalised_signals(signals) if s in text)


def _saturating(count: float, full_at: float) -> float:
    """0..1 that approaches 1 as ``count`` approaches ``full_at``.

    Saturating rather than linear so an answer cannot game the grader by
    stuffing in twenty trade-off words.
    """
    if full_at <= 0:
        return 0.0
    return min(1.0, count / full_at)


def grade_free_text(
    answer: str,
    rubric: list[dict[str, Any]] | list[RubricPoint],
    *,
    tier: int = 5,
    expected_answer: str = "",
    require_words: int = MIN_SUBSTANTIVE_WORDS,
) -> RubricGrade:
    """Score a free-text answer 0-10 across the seven dimensions."""
    points = [p if isinstance(p, RubricPoint) else RubricPoint.from_dict(p) for p in rubric]
    text = _normalise(answer)
    words = [w for w in text.split() if w]
    word_count = len(words)

    if word_count < 3:
        return RubricGrade(
            score=0.0,
            dimension_scores=dict.fromkeys(DIMENSIONS, 0.0),
            missing_points=[p.point for p in points],
            word_count=word_count,
        )

    # ── correctness: weighted rubric coverage ────────────────────────────
    hit: list[str] = []
    missing: list[str] = []
    earned = 0.0
    available = sum(p.weight for p in points) or 1.0
    for p in points:
        if not p.keywords:
            missing.append(p.point)
            continue
        matched = (
            all(k in text for k in p.keywords)
            if p.require_all
            else any(k in text for k in p.keywords)
        )
        if matched:
            hit.append(p.point)
            earned += p.weight
        else:
            missing.append(p.point)

    correctness = earned / available if points else _fallback_correctness(text, expected_answer)

    # ── the other six dimensions ─────────────────────────────────────────
    # Each is "signal density, saturating", with the bar raised for higher
    # tiers: a tier-9 answer must *earn* its trade-off score, a tier-2 gets
    # credit for mentioning one at all.
    # Smooth rather than stepped so tier 8 and tier 10 are genuinely different
    # bars: 1.0 at tier 1, ~2.6 at tier 8, 3.0 at tier 10.
    tier_factor = 1.0 + (max(1, min(10, tier)) - 1) / 4.5

    depth_raw = _count_signals(text, DEPTH_SIGNALS) + len(hit)
    depth = _saturating(depth_raw, 2 + tier_factor * 2)
    if word_count < require_words:
        depth *= word_count / require_words

    tradeoffs = _saturating(_count_signals(text, TRADEOFF_SIGNALS), tier_factor)
    practical = _saturating(_count_signals(text, PRACTICAL_SIGNALS), tier_factor)
    production = _saturating(_count_signals(text, PRODUCTION_SIGNALS), 1 + tier_factor)
    architecture = _saturating(_count_signals(text, ARCHITECTURE_SIGNALS), 1 + tier_factor)

    # Numbers are a strong practical signal: "reduced p99 from 800ms to 120ms"
    # is a different kind of claim from "made it faster".
    if re.search(r"\b\d+\s*(ms|s|x|%|gb|mb|qps|rps|k|m)\b", text):
        practical = min(1.0, practical + 0.25)
        production = min(1.0, production + 0.15)

    clarity = _clarity(answer, word_count)
    hedges = _count_signals(text, HEDGE_SIGNALS)
    if hedges:
        # Hedging is not a crime, but an interview answer that hedges three
        # times reads as uncertainty regardless of its content.
        clarity = max(0.0, clarity - 0.12 * hedges)

    dims = {
        "correctness": round(correctness, 4),
        "depth": round(depth, 4),
        "tradeoff_awareness": round(tradeoffs, 4),
        "practical_experience": round(practical, 4),
        "production_awareness": round(production, 4),
        "architecture_thinking": round(architecture, 4),
        "clarity": round(clarity, 4),
    }

    weighted = sum(dims[d] * DIMENSION_WEIGHTS[d] for d in DIMENSIONS)

    # An answer that is wrong cannot be rescued by sounding senior. The cap
    # rises with correctness so a half-right answer tops out around 6.5/10.
    ceiling = 0.35 + 0.65 * correctness
    final = min(weighted, ceiling)

    return RubricGrade(
        score=round(final * 10, 2),
        dimension_scores=dims,
        hit_points=hit,
        missing_points=missing,
        normalised=round(final, 4),
        word_count=word_count,
    )


def _clarity(raw: str, word_count: int) -> float:
    """Structure over verbosity."""
    if word_count < 8:
        return 0.2
    sentences = [s for s in re.split(r"[.!?\n]+", raw) if s.strip()]
    if not sentences:
        return 0.3
    avg_len = word_count / len(sentences)
    # 8-28 words per sentence reads well; outside that, penalise gently.
    length_score = 1.0 if 8 <= avg_len <= 28 else max(0.35, 1.0 - abs(avg_len - 18) / 40)
    verbosity = 1.0 if word_count <= IDEAL_MAX_WORDS else max(0.5, IDEAL_MAX_WORDS / word_count)
    structure = 1.0 if re.search(r"(^|\n)\s*([-*\d]|first|second|finally)", raw.lower()) else 0.9
    return min(1.0, length_score * verbosity * structure)


def _fallback_correctness(text: str, expected: str) -> float:
    """Token overlap with the model answer when no rubric was authored.

    Crude on purpose. Every seeded question carries a real rubric; this only
    catches the case where a question was added without one, and it fails
    toward being generous rather than silently scoring everyone zero.
    """
    if not expected:
        return 0.5
    expected_tokens = {w for w in _normalise(expected).split() if len(w) > 4}
    if not expected_tokens:
        return 0.5
    answer_tokens = {w for w in text.split() if len(w) > 4}
    overlap = len(expected_tokens & answer_tokens) / len(expected_tokens)
    return min(1.0, overlap * 1.6)


def grade_mcq(
    selected: list[str], options: list[dict[str, Any]], *, partial_credit: bool = True
) -> tuple[bool, float, list[str]]:
    """Grade single- and multi-select questions.

    Multi-select uses Jaccard-style partial credit with a penalty for wrong
    picks — otherwise "select everything" would score full marks, which teaches
    the player to guess instead of to discriminate.
    """
    correct_ids = {o["id"] for o in options if o.get("correct")}
    chosen = set(selected)
    if not correct_ids:
        return False, 0.0, []

    if len(correct_ids) == 1 and len(chosen) <= 1:
        ok = chosen == correct_ids
        return ok, 1.0 if ok else 0.0, sorted(correct_ids)

    if not partial_credit:
        ok = chosen == correct_ids
        return ok, 1.0 if ok else 0.0, sorted(correct_ids)

    hits = len(chosen & correct_ids)
    wrong = len(chosen - correct_ids)
    score = max(0.0, (hits - wrong) / len(correct_ids))
    return chosen == correct_ids, round(score, 4), sorted(correct_ids)


def verdict_for_score(score_10: float) -> str:
    """Interview verdict language, scaled the way a real debrief reads."""
    if score_10 >= 8.5:
        return "strong_hire"
    if score_10 >= 7.0:
        return "hire"
    if score_10 >= 5.5:
        return "lean_hire"
    if score_10 >= 4.0:
        return "lean_no_hire"
    return "no_hire"


def level_gap_feedback(score_10: float, tier: int) -> dict[str, str]:
    """What the next seniority band would have added. This is the payload that
    turns a score into learning (spec §57: "show what is missing")."""
    gaps: dict[str, str] = {}
    if score_10 < 6:
        gaps["senior"] = (
            "A senior answer would name the mechanism, not just the behaviour — "
            "say *why* it works, not only *that* it works."
        )
    if score_10 < 8:
        gaps["staff"] = (
            "A staff answer would compare at least one alternative and state the "
            "condition under which you would choose the other one."
        )
    if score_10 < 9 and tier >= 8:
        gaps["principal"] = (
            "A principal answer would connect this to failure modes, cost and "
            "organisational impact — what breaks at 10x, and who pays for it."
        )
    return gaps
