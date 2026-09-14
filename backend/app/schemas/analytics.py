"""Analytics contracts (spec §46)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.schemas.common import Schema


class MasteryRow(Schema):
    slug: str
    name: str
    mastery: float
    effective_mastery: float
    peak_mastery: float
    delta_30d: float = 0.0
    attempts: int = 0
    accuracy: float = 0.0
    last_practiced_at: datetime | None = None


class TimeSeriesPoint(Schema):
    date: date
    value: float
    label: str | None = None


class ProgressAnalyticsOut(Schema):
    generated_at: datetime
    total_xp: int
    level: int
    rank: str
    experience_band: str
    mastery_by_skill: list[MasteryRow]
    mastery_by_category: list[MasteryRow]
    xp_over_time: list[TimeSeriesPoint]
    activity_over_time: list[TimeSeriesPoint]
    accuracy_over_time: list[TimeSeriesPoint]
    xp_by_source: list[dict[str, Any]]
    tier_distribution: list[dict[str, Any]]
    strongest_skills: list[MasteryRow]
    weakest_skills: list[MasteryRow]
    recently_forgotten: list[dict[str, Any]]
    most_common_mistakes: list[dict[str, Any]]
    #: Composite readiness scores the dashboard shows as gauges.
    interview_readiness: float = 0.0
    coding_speed_index: float = 0.0
    debugging_score: float = 0.0
    architecture_score: float = 0.0
    production_score: float = 0.0
    consistency_score: float = 0.0
    practice_minutes_7d: int = 0
    practice_minutes_30d: int = 0


class ReadinessBreakdown(Schema):
    """Why a readiness number is what it is — never show a score without this."""

    overall: float
    by_level: dict[str, float]
    components: list[dict[str, Any]]
    blocking_gaps: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
