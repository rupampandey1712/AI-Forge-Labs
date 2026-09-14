"""Player profile, progression and skill-tree contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import Field

from app.schemas.common import Schema


class XPGrantOut(Schema):
    source: str
    amount: int
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProgressionOut(Schema):
    """Everything the level-up animation needs in one payload.

    Deliberately includes the *previous* values: the client animates the delta,
    and re-deriving "what did it used to be" on the frontend would duplicate the
    XP curve in TypeScript — a classic source of the two drifting apart.
    """

    xp_gained: int
    total_xp: int
    previous_level: int
    new_level: int
    previous_rank: str
    new_rank: str
    leveled_up: bool
    ranked_up: bool
    xp_into_level: int
    xp_for_next_level: int
    progress_pct: float
    coins_gained: int = 0
    grants: list[XPGrantOut] = Field(default_factory=list)
    new_badges: list[str] = Field(default_factory=list)
    new_achievements: list[str] = Field(default_factory=list)
    unlocked_buildings: list[str] = Field(default_factory=list)


class PlayerProfileOut(Schema):
    id: uuid.UUID
    display_name: str
    avatar_seed: str
    title: str
    total_xp: int
    level: int
    rank: str
    experience_band: str = "0-1"
    coins: int
    reputation: int
    current_streak: int
    longest_streak: int
    last_active_date: date | None = None
    missions_completed: int
    challenges_passed: int
    questions_answered: int
    bosses_defeated: int
    incidents_resolved: int
    total_practice_seconds: int
    unlocked_buildings: list[str]
    preferred_mentor: str
    onboarding_completed: bool
    xp_into_level: int = 0
    xp_for_next_level: int = 0
    progress_pct: float = 0.0
    next_rank: str | None = None
    next_rank_level: int | None = None
    created_at: datetime


class ProfileUpdate(Schema):
    display_name: Annotated[str | None, Field(min_length=2, max_length=60)] = None
    avatar_seed: Annotated[str | None, Field(max_length=40)] = None
    preferred_mentor: str | None = None
    settings: dict[str, Any] | None = None


class SkillProgressOut(Schema):
    skill_slug: str
    name: str = ""
    icon: str = "sparkles"
    color: str = "#38bdf8"
    level: int
    xp: int
    mastery: float
    effective_mastery: float
    peak_mastery: float
    confidence: float
    forgetting_score: float
    highest_tier_cleared: int
    attempts: int
    correct: int
    accuracy: float = 0.0
    streak: int
    last_practiced_at: datetime | None = None
    concepts_total: int = 0
    concepts_started: int = 0
    concepts_due: int = 0
    concepts_decayed: int = 0


class SkillNodeOut(Schema):
    slug: str
    name: str
    summary: str
    parent_slug: str | None = None
    tier_range: list[int] = Field(default_factory=lambda: [1, 10])
    unlock_level: int = 1
    display_order: int = 0
    # Player-relative fields, filled in by the service.
    unlocked: bool = False
    mastery: float = 0.0
    concepts_total: int = 0
    concepts_mastered: int = 0


class SkillTreeOut(Schema):
    skill_slug: str
    name: str
    description: str
    icon: str
    color: str
    building: str | None = None
    progress: SkillProgressOut | None = None
    nodes: list[SkillNodeOut] = Field(default_factory=list)


class BuildingOut(Schema):
    """A world-map building plus this player's relationship to it."""

    id: str
    name: str
    tagline: str
    description: str
    skill_slugs: list[str]
    categories: list[str]
    required_level: int
    required_rank: str | None = None
    position: dict[str, float]
    accent: str
    icon: str
    unlocked: bool = False
    mission_count: int = 0
    missions_completed: int = 0
    mastery: float = 0.0
    has_alert: bool = False
    alert_text: str | None = None


class WorldMapOut(Schema):
    profile: PlayerProfileOut
    buildings: list[BuildingOut]
    alerts: list[dict[str, Any]] = Field(default_factory=list)


class BadgeOut(Schema):
    slug: str
    name: str
    description: str
    tier: str
    icon: str
    xp_reward: int
    earned: bool = False
    earned_at: datetime | None = None
    secret: bool = False


class AchievementOut(Schema):
    slug: str
    name: str
    description: str
    category: str
    icon: str
    xp_reward: int
    coin_reward: int
    target: int
    progress: int = 0
    completed: bool = False
    completed_at: datetime | None = None
    secret: bool = False


class XPTransactionOut(Schema):
    source: str
    amount: int
    reason: str
    skill_slug: str | None = None
    reference_type: str | None = None
    reference_slug: str | None = None
    balance_after: int
    created_at: datetime


class LeaderboardRow(Schema):
    position: int
    display_name: str
    xp: int
    level: int
    rank: str
    is_me: bool = False


class DashboardOut(Schema):
    """The single payload the game dashboard renders from.

    WHY one fat endpoint instead of six small ones: the dashboard needs all of
    it to draw a first frame, and six round-trips on a cold load is how a
    "fast" SPA ends up feeling slow. Each section is independently cacheable
    server-side; the client gets one coherent snapshot.
    """

    profile: PlayerProfileOut
    skills: list[SkillProgressOut]
    retention_alerts: list[dict[str, Any]] = Field(default_factory=list)
    due_reviews: int = 0
    daily: dict[str, Any] | None = None
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    recommended: list[dict[str, Any]] = Field(default_factory=list)
    open_mistakes: list[dict[str, Any]] = Field(default_factory=list)
    unseen_badges: list[BadgeOut] = Field(default_factory=list)
    streak_calendar: list[dict[str, Any]] = Field(default_factory=list)
