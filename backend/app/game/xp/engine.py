"""XP, levels and ranks — pure functions, no I/O.

WHY a pure module: progression rules are the part of a game most likely to be
tweaked and the part most expensive to get wrong. Keeping them free of database
and HTTP concerns means they are exhaustively unit-testable in milliseconds
(see ``tests/unit/test_xp_engine.py``) and can be reused by the seeder, the
analytics jobs and a future balance-simulation script.

DESIGN of the curve: XP-to-level is superlinear (exponent 1.6) so that early
levels arrive fast enough to build a habit, while Principal-tier levels take
real work. The *award* side is deliberately capped and bonus-driven so that
grinding tier-1 questions can never out-earn genuine tier-9 work — the reward
system must point at depth, not volume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

from app.domain.enums import (
    RANK_ORDER,
    DifficultyTier,
    ExperienceBand,
    Rank,
    XPSource,
)

MAX_LEVEL = 100
_CURVE_BASE = 100.0
_CURVE_EXPONENT = 1.6


@lru_cache(maxsize=1)
def _cumulative_table() -> tuple[int, ...]:
    """Total XP required to *have reached* each level; index 0 == level 1."""
    return tuple(int(_CURVE_BASE * (lvl**_CURVE_EXPONENT)) for lvl in range(MAX_LEVEL))


def total_xp_for_level(level: int) -> int:
    """Cumulative XP needed to reach ``level`` (level 1 costs 0)."""
    level = max(1, min(level, MAX_LEVEL))
    return _cumulative_table()[level - 1]


def xp_to_next_level(level: int) -> int:
    if level >= MAX_LEVEL:
        return 0
    return total_xp_for_level(level + 1) - total_xp_for_level(level)


def level_for_xp(total_xp: int) -> int:
    """Invert the curve. Binary search keeps this O(log n) and allocation-free."""
    if total_xp <= 0:
        return 1
    table = _cumulative_table()
    lo, hi = 0, len(table) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if table[mid] <= total_xp:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


# ── Ranks ────────────────────────────────────────────────────────────────────
# Levels at which each rank unlocks. Spaced so the first three arrive inside the
# first few sessions (retention) and the last three demand sustained mastery.
RANK_LEVEL_THRESHOLDS: dict[Rank, int] = {
    Rank.PYTHON_APPRENTICE: 1,
    Rank.PYTHON_DEVELOPER: 5,
    Rank.BACKEND_ENGINEER: 12,
    Rank.SENIOR_PYTHON_ENGINEER: 22,
    Rank.ML_ENGINEER: 32,
    Rank.DEEP_LEARNING_ENGINEER: 42,
    Rank.AI_ENGINEER: 52,
    Rank.LLM_ENGINEER: 62,
    Rank.AI_PLATFORM_ENGINEER: 72,
    Rank.STAFF_AI_ENGINEER: 84,
    Rank.PRINCIPAL_AI_ENGINEER: 95,
}

RANK_EXPERIENCE_BAND: dict[Rank, ExperienceBand] = {
    Rank.PYTHON_APPRENTICE: ExperienceBand.BAND_0_1,
    Rank.PYTHON_DEVELOPER: ExperienceBand.BAND_0_1,
    Rank.BACKEND_ENGINEER: ExperienceBand.BAND_1_3,
    Rank.SENIOR_PYTHON_ENGINEER: ExperienceBand.BAND_3_5,
    Rank.ML_ENGINEER: ExperienceBand.BAND_3_5,
    Rank.DEEP_LEARNING_ENGINEER: ExperienceBand.BAND_5_7,
    Rank.AI_ENGINEER: ExperienceBand.BAND_5_7,
    Rank.LLM_ENGINEER: ExperienceBand.BAND_5_7,
    Rank.AI_PLATFORM_ENGINEER: ExperienceBand.BAND_7_10,
    Rank.STAFF_AI_ENGINEER: ExperienceBand.BAND_7_10,
    Rank.PRINCIPAL_AI_ENGINEER: ExperienceBand.BAND_10_PLUS,
}


def rank_for_level(level: int) -> Rank:
    current = Rank.PYTHON_APPRENTICE
    for rank in RANK_ORDER:
        if level >= RANK_LEVEL_THRESHOLDS[rank]:
            current = rank
        else:
            break
    return current


def next_rank(rank: Rank) -> Rank | None:
    idx = RANK_ORDER.index(rank)
    return RANK_ORDER[idx + 1] if idx + 1 < len(RANK_ORDER) else None


def experience_band_for_level(level: int) -> ExperienceBand:
    return RANK_EXPERIENCE_BAND[rank_for_level(level)]


# ── Awarding ─────────────────────────────────────────────────────────────────
# Base XP per difficulty tier. Superlinear on purpose: a tier-9 staff tradeoff
# is worth ~13x a tier-1 recall question, so depth always beats grinding.
TIER_BASE_XP: dict[DifficultyTier, int] = {
    DifficultyTier.REMEMBER: 10,
    DifficultyTier.UNDERSTAND: 18,
    DifficultyTier.IMPLEMENT: 32,
    DifficultyTier.DEBUG: 48,
    DifficultyTier.OPTIMIZE: 62,
    DifficultyTier.DESIGN: 78,
    DifficultyTier.EXPLAIN: 90,
    DifficultyTier.PRODUCTION: 110,
    DifficultyTier.STAFF_TRADEOFF: 130,
    DifficultyTier.PRINCIPAL_ARCHITECTURE: 160,
}

SOURCE_MULTIPLIER: dict[XPSource, float] = {
    XPSource.MISSION_COMPLETE: 1.0,
    XPSource.CHALLENGE_PASSED: 1.0,
    XPSource.FIRST_ATTEMPT_BONUS: 0.30,
    XPSource.SPEED_BONUS: 0.20,
    XPSource.CLEAN_CODE_BONUS: 0.25,
    XPSource.EXPLANATION_BONUS: 0.35,
    XPSource.ARCHITECTURE_BONUS: 0.40,
    XPSource.BUG_FOUND: 0.50,
    XPSource.TEST_WRITTEN: 0.30,
    XPSource.OPTIMIZATION: 0.45,
    XPSource.CODE_REVIEW: 0.40,
    XPSource.DIFFICULTY_BONUS: 0.25,
    XPSource.STREAK_BONUS: 0.15,
    XPSource.BOSS_DEFEATED: 2.50,
    XPSource.DAILY_COMPLETE: 1.00,
    XPSource.RETENTION_REPAIR: 0.60,
    XPSource.INTERVIEW_ANSWER: 1.0,
    XPSource.JOURNAL_ENTRY: 0.10,
    XPSource.ACHIEVEMENT: 1.0,
}


@dataclass(frozen=True, slots=True)
class XPGrant:
    """One line of the XP ledger. Immutable — the ledger is append-only."""

    source: XPSource
    amount: int
    reason: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AwardContext:
    """Everything the award rules need, gathered by the caller.

    Passing a context object rather than ten keyword arguments means adding a
    new reward signal (say, "wrote a property-based test") does not churn every
    call site.
    """

    tier: DifficultyTier
    passed: bool
    first_attempt: bool = False
    attempts: int = 1
    elapsed_seconds: float | None = None
    par_seconds: float | None = None
    explanation_score: float | None = None  # 0..1
    architecture_score: float | None = None  # 0..1
    code_quality_score: float | None = None  # 0..1
    tests_written: int = 0
    bugs_found: int = 0
    optimization_factor: float | None = None  # e.g. 23.0 for a 23x speed-up
    streak_days: int = 0
    is_boss: bool = False
    is_retention_repair: bool = False


# A failed attempt still yields a sliver of XP: the game must never punish
# *engaging* with a hard problem, only reward solving it far more.
FAILURE_XP_FRACTION = 0.08
STREAK_CAP_DAYS = 30


def compute_award(ctx: AwardContext) -> list[XPGrant]:
    """Turn an attempt into an itemised list of XP grants.

    Returning a *list* rather than a total is what makes the level-up panel able
    to show "+48 base, +14 first attempt, +17 explanation" — players learn the
    reward function, and the reward function teaches what good engineering is.
    """
    base = TIER_BASE_XP[ctx.tier]
    grants: list[XPGrant] = []

    if not ctx.passed:
        amount = max(1, int(base * FAILURE_XP_FRACTION))
        return [
            XPGrant(
                XPSource.CHALLENGE_PASSED,
                amount,
                "Attempted a hard problem — partial credit",
                {"passed": False, "tier": int(ctx.tier)},
            )
        ]

    primary = XPSource.BOSS_DEFEATED if ctx.is_boss else XPSource.CHALLENGE_PASSED
    primary_amount = int(base * SOURCE_MULTIPLIER[primary])
    grants.append(
        XPGrant(
            primary,
            primary_amount,
            f"Tier {int(ctx.tier)} objective cleared",
            {"tier": int(ctx.tier)},
        )
    )

    if ctx.first_attempt and ctx.attempts <= 1:
        grants.append(
            XPGrant(
                XPSource.FIRST_ATTEMPT_BONUS,
                int(base * SOURCE_MULTIPLIER[XPSource.FIRST_ATTEMPT_BONUS]),
                "Solved on the first attempt",
            )
        )

    if (
        ctx.elapsed_seconds is not None
        and ctx.par_seconds
        and ctx.elapsed_seconds < ctx.par_seconds
    ):
        # Scale by how far under par, capped at the full speed multiplier so
        # that a lucky 2-second submit cannot dominate the award.
        ratio = 1.0 - (ctx.elapsed_seconds / ctx.par_seconds)
        grants.append(
            XPGrant(
                XPSource.SPEED_BONUS,
                max(1, int(base * SOURCE_MULTIPLIER[XPSource.SPEED_BONUS] * min(1.0, ratio * 1.5))),
                f"Finished in {ctx.elapsed_seconds:.0f}s (par {ctx.par_seconds:.0f}s)",
            )
        )

    for score, source, label in (
        (ctx.explanation_score, XPSource.EXPLANATION_BONUS, "Explained the WHY"),
        (ctx.architecture_score, XPSource.ARCHITECTURE_BONUS, "Sound architectural reasoning"),
        (ctx.code_quality_score, XPSource.CLEAN_CODE_BONUS, "Clean, readable implementation"),
    ):
        if score is not None and score > 0:
            grants.append(
                XPGrant(
                    source,
                    max(1, int(base * SOURCE_MULTIPLIER[source] * min(1.0, score))),
                    label,
                )
            )

    if ctx.tests_written:
        grants.append(
            XPGrant(
                XPSource.TEST_WRITTEN,
                max(
                    1,
                    int(
                        base
                        * SOURCE_MULTIPLIER[XPSource.TEST_WRITTEN]
                        * min(3, ctx.tests_written)
                        / 3
                    ),
                ),
                f"Wrote {ctx.tests_written} test(s)",
            )
        )

    if ctx.bugs_found:
        grants.append(
            XPGrant(
                XPSource.BUG_FOUND,
                max(
                    1,
                    int(base * SOURCE_MULTIPLIER[XPSource.BUG_FOUND] * min(4, ctx.bugs_found) / 4),
                ),
                f"Identified {ctx.bugs_found} defect(s)",
            )
        )

    if ctx.optimization_factor and ctx.optimization_factor > 1.5:
        # Logarithmic: going 2x -> 20x should feel great but not 10x the XP.
        scaled = min(1.0, math.log10(ctx.optimization_factor) / 2.0)
        grants.append(
            XPGrant(
                XPSource.OPTIMIZATION,
                max(1, int(base * SOURCE_MULTIPLIER[XPSource.OPTIMIZATION] * scaled)),
                f"{ctx.optimization_factor:.1f}x faster",
            )
        )

    if ctx.tier >= DifficultyTier.PRODUCTION:
        grants.append(
            XPGrant(
                XPSource.DIFFICULTY_BONUS,
                int(base * SOURCE_MULTIPLIER[XPSource.DIFFICULTY_BONUS]),
                "Senior-plus difficulty",
            )
        )

    if ctx.streak_days > 1:
        factor = min(ctx.streak_days, STREAK_CAP_DAYS) / STREAK_CAP_DAYS
        grants.append(
            XPGrant(
                XPSource.STREAK_BONUS,
                max(1, int(base * SOURCE_MULTIPLIER[XPSource.STREAK_BONUS] * factor)),
                f"{ctx.streak_days}-day streak",
            )
        )

    if ctx.is_retention_repair:
        grants.append(
            XPGrant(
                XPSource.RETENTION_REPAIR,
                int(base * SOURCE_MULTIPLIER[XPSource.RETENTION_REPAIR]),
                "Repaired decayed knowledge",
            )
        )

    return grants


@dataclass(frozen=True, slots=True)
class ProgressionResult:
    """What changed after applying XP — drives the level-up animation."""

    xp_gained: int
    total_xp: int
    previous_level: int
    new_level: int
    previous_rank: Rank
    new_rank: Rank
    leveled_up: bool
    ranked_up: bool
    xp_into_level: int
    xp_for_next_level: int
    progress_pct: float
    grants: tuple[XPGrant, ...]


def apply_xp(current_total_xp: int, grants: list[XPGrant]) -> ProgressionResult:
    gained = sum(g.amount for g in grants)
    new_total = max(0, current_total_xp + gained)
    prev_level = level_for_xp(current_total_xp)
    new_level = level_for_xp(new_total)
    prev_rank = rank_for_level(prev_level)
    new_rank = rank_for_level(new_level)

    floor_xp = total_xp_for_level(new_level)
    span = xp_to_next_level(new_level)
    into = new_total - floor_xp
    return ProgressionResult(
        xp_gained=gained,
        total_xp=new_total,
        previous_level=prev_level,
        new_level=new_level,
        previous_rank=prev_rank,
        new_rank=new_rank,
        leveled_up=new_level > prev_level,
        ranked_up=new_rank != prev_rank,
        xp_into_level=into,
        xp_for_next_level=span,
        progress_pct=round(100.0 * into / span, 2) if span else 100.0,
        grants=tuple(grants),
    )


# Coins are the cosmetic/utility currency (hints, retries, mentor consults).
# Deliberately decoupled from XP so spending coins can never cost progression.
def coins_for_grants(grants: list[XPGrant]) -> int:
    return max(1, sum(g.amount for g in grants) // 10)
