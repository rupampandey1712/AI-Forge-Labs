"""The Knowledge Retention Engine — forgetting curve + adaptive spaced repetition.

This is the mechanism that makes the game worth reopening after six months, so
it gets the most careful modelling in the codebase.

THE MODEL
---------
Each (player, concept) pair carries a ``ReviewState``:

* ``stability`` — the memory's strength, expressed as an *interval in days* at
  which recall probability would be exactly ``TARGET_RETENTION`` (0.90).
* ``ease`` — an SM-2 style multiplier describing how easily this particular
  concept sticks *for this particular player*.
* ``mastery`` — a durable competence estimate (EWMA over graded performance,
  weighted by the difficulty tier the player demonstrated it at).

Recall probability decays exponentially between reviews::

    R(t) = exp(-t / S)        where  S = interval / -ln(TARGET_RETENTION)

WHY exponential rather than FSRS' power law: it has one parameter, it is
trivially explainable to the player (and the game *teaches* its own mechanics in
the Retention Dashboard), and its error versus the power law only matters at
intervals far beyond this game's horizon. The scheduler is where the real
adaptivity lives.

WHY mastery decays but never hits zero: relearning is dramatically faster than
first learning (Ebbinghaus' "savings" effect). ``RETENTION_FLOOR`` encodes that
— a concept you once mastered and abandoned lands at ~35% of peak, not 0%.
That is also good game design: returning after a year should feel like rust,
not amnesia.

Everything here is pure. No clock reads, no database, no randomness without an
injected seed — so the whole engine is deterministic under test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from app.domain.enums import DifficultyTier

# ── Tunables (all in one place so balance changes are a single diff) ──────────
TARGET_RETENTION = 0.90
#: S such that R(interval) == TARGET_RETENTION  ->  S = interval / 0.10536
_LN_TARGET = -math.log(TARGET_RETENTION)

MIN_EASE = 1.3
MAX_EASE = 2.9
DEFAULT_EASE = 2.35

MIN_INTERVAL_DAYS = 0.5
MAX_INTERVAL_DAYS = 365.0

#: The canonical ladder from the spec. Used for the first few reviews, after
#: which the ease factor takes over and the schedule becomes personal.
LADDER_DAYS: tuple[float, ...] = (1.0, 3.0, 7.0, 14.0, 30.0, 60.0, 90.0)

RETENTION_FLOOR = 0.35
MASTERY_ALPHA = 0.30  # EWMA weight for a new observation

#: Below this recall probability a concept is "due"; below the second it is a
#: full decay *alert* that spawns an emergency repair mission.
DUE_THRESHOLD = 0.90
DECAY_ALERT_THRESHOLD = 0.72
CRITICAL_DECAY_THRESHOLD = 0.45


@dataclass(frozen=True, slots=True)
class ReviewState:
    """Per-(player, concept) memory state. Immutable; ``review`` returns a new one."""

    stability_days: float = 0.0
    ease: float = DEFAULT_EASE
    interval_days: float = 0.0
    repetitions: int = 0
    lapses: int = 0
    attempts: int = 0
    correct: int = 0
    mastery: float = 0.0
    peak_mastery: float = 0.0
    confidence: float = 0.0
    last_seen: datetime | None = None
    last_correct: datetime | None = None
    last_incorrect: datetime | None = None
    due_at: datetime | None = None
    highest_tier_cleared: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.attempts if self.attempts else 0.0

    @property
    def is_new(self) -> bool:
        return self.attempts == 0


@dataclass(frozen=True, slots=True)
class DecayReport:
    """What the dashboard renders for a single concept."""

    retrievability: float
    forgetting_probability: float
    effective_mastery: float
    peak_mastery: float
    mastery_drop: float
    days_since_practice: float
    is_due: bool
    is_decayed: bool
    is_critical: bool
    urgency: float  # 0..1, the sort key for "what should I do next"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def stability_from_interval(interval_days: float) -> float:
    """Convert a scheduling interval into the decay constant ``S``."""
    return max(interval_days, MIN_INTERVAL_DAYS) / _LN_TARGET


def retrievability(state: ReviewState, now: datetime | None = None) -> float:
    """P(recall) right now. 1.0 for a concept never studied is meaningless, so
    an unseen concept reports 0.0 — it cannot decay, it was never learned."""
    if state.last_seen is None or state.stability_days <= 0:
        return 0.0
    now = now or datetime.now(UTC)
    elapsed_days = max(0.0, (now - state.last_seen).total_seconds() / 86400.0)
    return float(math.exp(-elapsed_days / state.stability_days))


def effective_mastery(state: ReviewState, now: datetime | None = None) -> float:
    """Mastery as the player would experience it *today*.

    This is the number the dashboard shows ("91% -> 68%"). It blends durable
    competence with current recall probability, floored by the savings effect.
    """
    if state.attempts == 0:
        return 0.0
    r = retrievability(state, now)
    return _clamp(state.mastery * (RETENTION_FLOOR + (1.0 - RETENTION_FLOOR) * r), 0.0, 1.0)


def decay_report(state: ReviewState, now: datetime | None = None) -> DecayReport:
    now = now or datetime.now(UTC)
    r = retrievability(state, now)
    eff = effective_mastery(state, now)
    days = (now - state.last_seen).total_seconds() / 86400.0 if state.last_seen else float("inf")
    peak = max(state.peak_mastery, state.mastery)
    drop = max(0.0, peak - eff)

    is_due = state.last_seen is not None and r < DUE_THRESHOLD
    is_decayed = state.last_seen is not None and r < DECAY_ALERT_THRESHOLD
    is_critical = state.last_seen is not None and r < CRITICAL_DECAY_THRESHOLD

    # Urgency deliberately weights *how much was lost* as heavily as *how low it
    # is now*: forgetting a concept you had at 95% is a bigger deal than a
    # concept you only ever reached 40% on.
    urgency = _clamp(0.55 * (1.0 - r) + 0.45 * min(1.0, drop / 0.5), 0.0, 1.0)
    if state.lapses:
        urgency = _clamp(urgency + 0.05 * min(3, state.lapses), 0.0, 1.0)

    return DecayReport(
        retrievability=round(r, 4),
        forgetting_probability=round(1.0 - r, 4),
        effective_mastery=round(eff, 4),
        peak_mastery=round(peak, 4),
        mastery_drop=round(drop, 4),
        days_since_practice=round(days, 2) if math.isfinite(days) else -1.0,
        is_due=is_due,
        is_decayed=is_decayed,
        is_critical=is_critical,
        urgency=round(urgency, 4),
    )


# ── Grading ──────────────────────────────────────────────────────────────────
#: Difficulty multiplier applied to mastery gains. Clearing a tier-9 tradeoff
#: says far more about your competence than clearing a tier-1 recall question,
#: and mastery must reflect *depth demonstrated*, not just count of correct
#: answers. This is what stops the game asking "what is a list?" forever.
TIER_MASTERY_WEIGHT: dict[int, float] = {
    1: 0.35,
    2: 0.50,
    3: 0.68,
    4: 0.80,
    5: 0.88,
    6: 0.94,
    7: 0.97,
    8: 1.00,
    9: 1.05,
    10: 1.10,
}

#: Mastery *ceiling* per tier. You cannot reach 90% mastery of asyncio by only
#: ever answering tier-1/2 questions about it — the ceiling forces depth.
TIER_MASTERY_CEILING: dict[int, float] = {
    1: 0.25,
    2: 0.40,
    3: 0.58,
    4: 0.70,
    5: 0.80,
    6: 0.87,
    7: 0.92,
    8: 0.96,
    9: 0.99,
    10: 1.00,
}


def mastery_ceiling(highest_tier_cleared: int) -> float:
    """Highest mastery reachable given the deepest tier the player has cleared.

    A player who has cleared nothing yet is treated as tier 1: they can still
    accumulate a little mastery from attempts, but they cannot climb past the
    recall-level ceiling until they demonstrate depth.
    """
    return TIER_MASTERY_CEILING[_clamp_tier(highest_tier_cleared)]


def _clamp_tier(tier: int) -> int:
    return int(_clamp(float(tier), 1, 10))


def _quality(score: float, hints_used: int, confidence: float) -> float:
    """Map a 0..1 outcome score to an SM-2-like 0..1 recall quality.

    Hints are *not* free: a solution reached after three hints was not recalled,
    it was reconstructed with help, and scheduling it like a clean recall would
    make the player forget it again right before the real interview.
    """
    penalty = min(0.45, 0.15 * hints_used)
    q = _clamp(score - penalty, 0.0, 1.0)
    # Overconfidence is itself a signal: being sure and wrong should schedule a
    # much earlier review than being unsure and wrong.
    if q < 0.5 and confidence > 0.7:
        q = max(0.0, q - 0.10)
    return q


def _next_interval(state: ReviewState, quality: float) -> tuple[float, float, int, int]:
    """Return ``(interval_days, ease, repetitions, lapses)``."""
    passed = quality >= 0.6
    ease = state.ease
    reps = state.repetitions
    lapses = state.lapses

    # SM-2 ease update, rewritten for a continuous quality in 0..1.
    # q=1.0 -> +0.10, q=0.6 -> -0.14, q=0.0 -> -0.80 (clamped by MIN_EASE).
    delta = 0.10 - (1.0 - quality) * (0.58 + (1.0 - quality) * 0.42)
    ease = _clamp(ease + delta, MIN_EASE, MAX_EASE)

    if not passed:
        lapses += 1
        reps = 0
        # A lapse does not reset to zero: partial credit keeps the ladder from
        # punishing a single bad night, but repeated lapses compound.
        interval = _clamp(
            max(MIN_INTERVAL_DAYS, state.interval_days * 0.25 / (1 + 0.5 * lapses)),
            MIN_INTERVAL_DAYS,
            7.0,
        )
        return interval, ease, reps, lapses

    reps += 1
    if reps <= len(LADDER_DAYS) and state.interval_days < LADDER_DAYS[-1]:
        # Early reviews follow the canonical ladder, modulated by ease so a
        # player who nails everything moves through it faster.
        base = LADDER_DAYS[min(reps, len(LADDER_DAYS)) - 1]
        interval = base * (ease / DEFAULT_EASE)
    else:
        interval = max(state.interval_days, LADDER_DAYS[-1]) * ease

    # Quality modulates the step: a barely-passed review earns a shorter gap.
    interval *= 0.75 + 0.35 * quality
    return _clamp(interval, MIN_INTERVAL_DAYS, MAX_INTERVAL_DAYS), ease, reps, lapses


def review(
    state: ReviewState,
    *,
    score: float,
    tier: DifficultyTier | int,
    now: datetime,
    hints_used: int = 0,
    confidence: float | None = None,
    time_pressure: float = 1.0,
) -> ReviewState:
    """Fold one graded attempt into the memory state.

    ``score``          0..1 outcome (tests passed, rubric score, MCQ correctness)
    ``tier``           the difficulty tier the player actually faced
    ``hints_used``     hints consumed before succeeding
    ``confidence``     player's self-report 0..1 (drives calibration feedback)
    ``time_pressure``  >1 means they were slower than par; damps mastery gain
    """
    tier_int = _clamp_tier(int(tier))
    conf = state.confidence if confidence is None else _clamp(confidence, 0.0, 1.0)
    q = _quality(_clamp(score, 0.0, 1.0), hints_used, conf)
    passed = q >= 0.6

    interval, ease, reps, lapses = _next_interval(state, q)
    stability = stability_from_interval(interval)

    # --- Mastery: EWMA toward the tier-weighted observation, under a ceiling --
    weight = TIER_MASTERY_WEIGHT[tier_int]
    observation = q * weight
    if time_pressure > 1.0:
        observation *= _clamp(1.0 / time_pressure, 0.6, 1.0)

    # When the player has decayed, the EWMA must start from *effective* mastery,
    # not from the stale peak — otherwise a single review would "restore" a
    # year-old 95% instantly and the whole retention loop would be cosmetic.
    baseline = effective_mastery(state, now) if state.attempts else 0.0
    new_mastery = baseline + MASTERY_ALPHA * (observation - baseline)

    highest = max(state.highest_tier_cleared, tier_int if passed else 0)
    new_mastery = _clamp(new_mastery, 0.0, mastery_ceiling(highest))

    return replace(
        state,
        stability_days=stability,
        ease=ease,
        interval_days=interval,
        repetitions=reps,
        lapses=lapses,
        attempts=state.attempts + 1,
        correct=state.correct + (1 if passed else 0),
        mastery=round(new_mastery, 4),
        peak_mastery=round(max(state.peak_mastery, new_mastery), 4),
        confidence=round(conf, 4),
        last_seen=now,
        last_correct=now if passed else state.last_correct,
        last_incorrect=state.last_incorrect if passed else now,
        due_at=now + timedelta(days=interval),
        highest_tier_cleared=highest,
    )


def bootstrap(now: datetime, tier: DifficultyTier | int = DifficultyTier.REMEMBER) -> ReviewState:
    """State for a concept the player has just been introduced to but not tested."""
    return ReviewState(
        stability_days=stability_from_interval(LADDER_DAYS[0]),
        interval_days=LADDER_DAYS[0],
        last_seen=now,
        due_at=now + timedelta(days=LADDER_DAYS[0]),
        highest_tier_cleared=0,
        mastery=0.0,
    )


def next_review_at(state: ReviewState) -> datetime | None:
    return state.due_at


def calibration_error(state: ReviewState) -> float:
    """How badly the player's self-assessment tracks reality (0 = perfectly calibrated).

    Surfaced in the dashboard because miscalibration — not ignorance — is what
    sinks senior interviews. A player at 40% accuracy reporting 0.9 confidence
    needs a different intervention than one who simply hasn't practised.
    """
    if state.attempts < 3:
        return 0.0
    return round(abs(state.confidence - state.accuracy), 4)
