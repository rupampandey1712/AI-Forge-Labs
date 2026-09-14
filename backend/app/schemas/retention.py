"""Knowledge-retention and daily-mission contracts (spec §4, §5, §45)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.schemas.common import Schema


class ConceptDecayOut(Schema):
    concept_slug: str
    title: str
    category: str
    skill_slug: str
    mastery: float
    peak_mastery: float
    effective_mastery: float
    retrievability: float
    forgetting_probability: float
    mastery_drop: float
    days_since_practice: float
    urgency: float
    is_due: bool
    is_decayed: bool
    is_critical: bool
    due_at: datetime | None = None
    lapses: int = 0
    attempts: int = 0
    accuracy: float = 0.0


class DecayAlertOut(Schema):
    """The dashboard banner: "⚠ GENERATOR KNOWLEDGE DECAY DETECTED"."""

    severity: str  # info | warning | critical
    scope: str  # concept | skill
    slug: str
    title: str
    headline: str
    detail: str
    from_mastery: float
    to_mastery: float
    days_since_practice: float
    repair_mission_slug: str | None = None
    repair_kind: str = "mission"
    concept_slugs: list[str] = Field(default_factory=list)


class RetentionDashboardOut(Schema):
    generated_at: datetime
    overall_retention: float
    concepts_tracked: int
    concepts_due: int
    concepts_decayed: int
    concepts_critical: int
    alerts: list[DecayAlertOut] = Field(default_factory=list)
    due_now: list[ConceptDecayOut] = Field(default_factory=list)
    upcoming: list[ConceptDecayOut] = Field(default_factory=list)
    strongest: list[ConceptDecayOut] = Field(default_factory=list)
    weakest: list[ConceptDecayOut] = Field(default_factory=list)
    recently_forgotten: list[ConceptDecayOut] = Field(default_factory=list)
    by_skill: list[dict[str, Any]] = Field(default_factory=list)
    #: 90-day projection so the player can *see* the forgetting curve bend.
    forecast: list[dict[str, Any]] = Field(default_factory=list)


class ReviewScheduleOut(Schema):
    concept_slug: str
    previous_interval_days: float
    new_interval_days: float
    due_at: datetime
    stability_days: float
    ease: float
    mastery_before: float
    mastery_after: float
    repetitions: int
    lapses: int


class DailySlotOut(Schema):
    slot: int
    kind: str  # coding | debugging | concept | interview | data_lab | ...
    category: str
    title: str
    #: Why the generator picked this — shown to the player, because a training
    #: plan you understand is one you trust.
    reason: str
    tier: int
    ref_type: str  # challenge | question | mission | concept
    ref_slug: str
    estimated_minutes: int
    completed: bool = False
    score: float | None = None


class DailyMissionOut(Schema):
    id: uuid.UUID
    for_date: date
    slots: list[DailySlotOut]
    estimated_minutes: int
    completed: bool
    completed_at: datetime | None = None
    xp_awarded: int = 0
    completed_count: int = 0
    streak: int = 0
    generation_reason: dict[str, Any] = Field(default_factory=dict)


class MistakeOut(Schema):
    pattern: str
    title: str
    description: str
    why_it_matters: str
    correct_approach: str
    severity: str
    category: str | None = None
    skill_slug: str | None = None
    concept_slug: str | None = None
    occurrences: int
    clean_streak: int
    resolved: bool
    first_seen_at: datetime
    last_seen_at: datetime
