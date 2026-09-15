"""Declarative unlock rules for badges and achievements.

WHY declarative: with ~60 badges, an ``if`` ladder becomes unreadable and
untestable, and every new badge means touching progression logic. Instead each
badge stores a small JSON criteria object and this module is the single
interpreter for it. Adding a badge is then a seed-data change, not a code
change — and the interpreter is exhaustively unit-tested once.

Criteria grammar (all keys optional; ALL present keys must hold)::

    {
      "stat": "challenges_passed",      # any numeric PlayerProfile column
      "gte": 50,
      "skill": "python",                # scope a stat/mastery to one skill
      "mastery_gte": 0.8,
      "tier_cleared_gte": 8,
      "level_gte": 22,
      "rank_at_least": "senior_python_engineer",
      "streak_gte": 30,
      "all_skills_mastery_gte": 0.5,
      "skills_mastery_gte": {"count": 5, "threshold": 0.7}
    }

Achievements additionally report *progress* toward ``target`` so the UI can
show a bar rather than a binary lock.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.enums import RANK_ORDER, Rank


class _ProfileLike(Protocol):
    level: int
    rank: str
    total_xp: int
    current_streak: int
    longest_streak: int
    missions_completed: int
    challenges_passed: int
    questions_answered: int
    bosses_defeated: int
    incidents_resolved: int


class _SkillLike(Protocol):
    skill_slug: str
    mastery: float
    effective_mastery: float
    highest_tier_cleared: int
    attempts: int
    correct: int


class _SpecLike(Protocol):
    slug: str
    criteria: dict[str, Any]


NUMERIC_STATS = frozenset(
    {
        "total_xp",
        "level",
        "current_streak",
        "longest_streak",
        "missions_completed",
        "challenges_passed",
        "questions_answered",
        "bosses_defeated",
        "incidents_resolved",
        "reputation",
        "coins",
    }
)


def _measure(
    criteria: dict[str, Any],
    profile: _ProfileLike,
    skills: dict[str, _SkillLike],
) -> tuple[float, float]:
    """Return ``(current, required)`` for the criteria's primary numeric axis.

    Having a single "primary axis" is what lets an achievement render a
    progress bar. Criteria with no numeric axis (pure boolean gates) report
    ``(1, 1)`` when satisfied.
    """
    if "stat" in criteria and criteria["stat"] in NUMERIC_STATS:
        return float(getattr(profile, criteria["stat"], 0)), float(criteria.get("gte", 1))

    if "level_gte" in criteria:
        return float(profile.level), float(criteria["level_gte"])

    if "streak_gte" in criteria:
        return float(profile.longest_streak), float(criteria["streak_gte"])

    if "mastery_gte" in criteria and "skill" in criteria:
        row = skills.get(criteria["skill"])
        return float(row.mastery if row else 0.0), float(criteria["mastery_gte"])

    if "tier_cleared_gte" in criteria and "skill" in criteria:
        row = skills.get(criteria["skill"])
        return float(row.highest_tier_cleared if row else 0), float(criteria["tier_cleared_gte"])

    if "skills_mastery_gte" in criteria:
        spec = criteria["skills_mastery_gte"]
        threshold = float(spec.get("threshold", 0.7))
        count = sum(1 for s in skills.values() if s.mastery >= threshold)
        return float(count), float(spec.get("count", 1))

    if "all_skills_mastery_gte" in criteria:
        threshold = float(criteria["all_skills_mastery_gte"])
        from app.game.skills.registry import all_skill_slugs

        total = len(all_skill_slugs())
        met = sum(1 for s in skills.values() if s.mastery >= threshold)
        return float(met), float(total)

    return 1.0, 1.0


def evaluate_criteria(
    criteria: dict[str, Any],
    profile: _ProfileLike,
    skills: dict[str, _SkillLike],
) -> bool:
    if not criteria:
        return False

    if "stat" in criteria:
        stat = criteria["stat"]
        if stat not in NUMERIC_STATS:
            return False
        if float(getattr(profile, stat, 0)) < float(criteria.get("gte", 1)):
            return False

    if "level_gte" in criteria and profile.level < int(criteria["level_gte"]):
        return False

    if "streak_gte" in criteria and profile.longest_streak < int(criteria["streak_gte"]):
        return False

    if "rank_at_least" in criteria:
        try:
            needed = RANK_ORDER.index(Rank(criteria["rank_at_least"]))
            have = RANK_ORDER.index(Rank(profile.rank))
        except ValueError:
            return False
        if have < needed:
            return False

    skill_slug = criteria.get("skill")
    if "mastery_gte" in criteria:
        if skill_slug:
            row = skills.get(skill_slug)
            if row is None or row.mastery < float(criteria["mastery_gte"]):
                return False
        else:
            return False

    if "tier_cleared_gte" in criteria:
        tier_needed = int(criteria["tier_cleared_gte"])
        if skill_slug:
            row = skills.get(skill_slug)
            if row is None or row.highest_tier_cleared < tier_needed:
                return False
        elif not any(s.highest_tier_cleared >= tier_needed for s in skills.values()):
            return False

    if "skills_mastery_gte" in criteria:
        spec = criteria["skills_mastery_gte"]
        threshold = float(spec.get("threshold", 0.7))
        if sum(1 for s in skills.values() if s.mastery >= threshold) < int(spec.get("count", 1)):
            return False

    if "all_skills_mastery_gte" in criteria:
        from app.game.skills.registry import all_skill_slugs

        threshold = float(criteria["all_skills_mastery_gte"])
        wanted = set(all_skill_slugs())
        if any(skills.get(slug) is None or skills[slug].mastery < threshold for slug in wanted):
            return False

    return True


def evaluate_unlocks(
    *,
    profile: _ProfileLike,
    skills: list[_SkillLike],
    badges: list[_SpecLike],
    achievements: list[_SpecLike],
    earned_badge_slugs: set[str],
    achievement_progress: dict[str, int],
) -> tuple[list[str], dict[str, int]]:
    """Return ``(newly_earned_badge_slugs, achievement_slug -> progress)``."""
    skill_map = {s.skill_slug: s for s in skills}

    new_badges = [
        b.slug
        for b in badges
        if b.slug not in earned_badge_slugs and evaluate_criteria(b.criteria, profile, skill_map)
    ]

    progress: dict[str, int] = {}
    for spec in achievements:
        current, required = _measure(spec.criteria, profile, skill_map)
        satisfied = evaluate_criteria(spec.criteria, profile, skill_map)
        # Progress is the measured axis, capped; a satisfied boolean-only rule
        # reports full progress so the bar completes.
        value: int = int(current) if required > 1 else (1 if satisfied else 0)
        if satisfied and required > 1:
            value = max(value, int(required))
        if value != achievement_progress.get(spec.slug, 0):
            progress[spec.slug] = value
    return new_badges, progress
