"""Per-player progress, attempts, the XP ledger and the mistake database.

Design rule applied throughout: *attempts are append-only facts, progress rows
are derived state.* If a progress row is ever wrong we can rebuild it by
replaying attempts. That property is what makes it safe to denormalise
aggressively for the dashboard.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONB, UTCDateTime

if TYPE_CHECKING:
    from app.models.user import PlayerProfile


class SkillProgress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (player, skill) — the radar chart and skill tree read this."""

    __tablename__ = "skill_progress"
    __table_args__ = (
        UniqueConstraint("profile_id", "skill_slug", name="uq_skill_progress_profile_skill"),
        Index("ix_skill_progress_mastery", "profile_id", "mastery"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_slug: Mapped[str] = mapped_column(String(40), nullable=False)

    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Rolled up from the player's ConceptProgress rows for this skill.
    mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    effective_mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    forgetting_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    highest_tier_cleared: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_practiced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    unlocked_nodes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    profile: Mapped[PlayerProfile] = relationship(back_populates="skill_progress")


class ConceptProgress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The persisted ``ReviewState`` (app/game/retention/model.py).

    The column set mirrors that dataclass exactly and on purpose: the engine
    stays pure and testable, and this row is only its storage format. See
    ``app/services/retention_service.py`` for the two conversion functions.
    """

    __tablename__ = "concept_progress"
    __table_args__ = (
        UniqueConstraint("profile_id", "concept_slug", name="uq_concept_progress"),
        # The retention scan's hot query: "what is due for this player?"
        Index("ix_concept_progress_due", "profile_id", "due_at"),
        Index("ix_concept_progress_skill", "profile_id", "skill_slug"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concept_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_slug: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)

    # --- ReviewState mirror ---------------------------------------------
    stability_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ease: Mapped[float] = mapped_column(Float, default=2.35, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    highest_tier_cleared: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_correct: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_incorrect: Mapped[datetime | None] = mapped_column(UTCDateTime)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    #: Cached decay snapshot so the dashboard needs no recomputation per row.
    #: Refreshed by the retention scan; always safe to recompute from the mirror.
    last_decay_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    decay_alert_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    profile: Mapped[PlayerProfile] = relationship(back_populates="concept_progress")


class MissionAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mission_attempts"
    __table_args__ = (
        Index("ix_mission_attempts_profile_status", "profile_id", "status"),
        Index("ix_mission_attempts_mission", "mission_slug", "profile_id"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mission_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="in_progress", nullable=False)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coins_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: {step_position: {"status","score","payload",...}}
    step_results: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_daily: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_retention_repair: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feedback: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ChallengeAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "challenge_attempts"
    __table_args__ = (Index("ix_challenge_attempts_profile", "profile_id", "challenge_slug"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    challenge_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    mission_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mission_attempts.id", ondelete="SET NULL")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="failed", nullable=False)

    submitted_code: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tests_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    runtime_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stdout: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stderr: Mapped[str] = mapped_column(Text, default="", nullable=False)
    test_results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    explanation: Mapped[str | None] = mapped_column(Text)
    explanation_score: Mapped[float | None] = mapped_column(Float)
    complexity_answer: Mapped[str | None] = mapped_column(String(80))
    code_quality_score: Mapped[float | None] = mapped_column(Float)
    speedup_factor: Mapped[float | None] = mapped_column(Float)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class QuestionAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "question_attempts"
    __table_args__ = (
        Index("ix_question_attempts_profile", "profile_id", "question_slug"),
        Index("ix_question_attempts_recent", "profile_id", "created_at"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    interview_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="SET NULL")
    )
    mission_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mission_attempts.id", ondelete="SET NULL")
    )

    answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    selected_option_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0..10
    #: Per-criterion breakdown (correctness, depth, tradeoffs, ... — spec §57)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    missing_points: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    graded_by: Mapped[str] = mapped_column(String(16), default="rubric", nullable=False)


class XPTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only XP ledger.

    WHY a ledger rather than just incrementing ``total_xp``: it makes progression
    auditable and reversible, it powers the "where did my XP come from" chart,
    and it is the single source of truth if the denormalised counter drifts.
    """

    __tablename__ = "xp_transactions"
    __table_args__ = (Index("ix_xp_transactions_profile_time", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    skill_slug: Mapped[str | None] = mapped_column(String(40), index=True)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_slug: Mapped[str | None] = mapped_column(String(120))
    balance_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    profile: Mapped[PlayerProfile] = relationship(back_populates="xp_transactions")


class PlayerBadge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_badges"
    __table_args__ = (UniqueConstraint("profile_id", "badge_slug", name="uq_player_badge"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    badge_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    earned_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    profile: Mapped[PlayerProfile] = relationship(back_populates="badges")


class PlayerAchievement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_achievements"
    __table_args__ = (
        UniqueConstraint("profile_id", "achievement_slug", name="uq_player_achievement"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    achievement_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    profile: Mapped[PlayerProfile] = relationship(back_populates="achievements")


class DailyChallenge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The generated daily mission for one player on one day (spec §5).

    Stored rather than regenerated so that reopening the app mid-session shows
    the *same* mission — a regenerated daily would let players reroll away from
    the concepts the retention engine deliberately chose for them.
    """

    __tablename__ = "daily_challenges"
    __table_args__ = (UniqueConstraint("profile_id", "for_date", name="uq_daily_per_day"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    for_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: [{"slot","kind","category","ref_type","ref_slug","title","reason","tier"}]
    slots: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    generation_reason: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    completed_slots: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LearningEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only stream of everything the player did.

    This is the raw material for analytics, adaptive difficulty and the
    "you struggled with async generators three months ago" callbacks. Kept
    deliberately generic — a new event type is a new ``event_type`` string, not
    a migration.
    """

    __tablename__ = "learning_events"
    __table_args__ = (
        Index("ix_learning_events_profile_time", "profile_id", "created_at"),
        Index("ix_learning_events_type", "profile_id", "event_type"),
        Index("ix_learning_events_concept", "profile_id", "concept_slug"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    concept_slug: Mapped[str | None] = mapped_column(String(120))
    skill_slug: Mapped[str | None] = mapped_column(String(40), index=True)
    category: Mapped[str | None] = mapped_column(String(32))
    tier: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    profile: Mapped[PlayerProfile] = relationship(back_populates="learning_events")


class MistakeRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The Mistake Database (spec §44).

    Every mistake is classified into a reusable ``pattern`` (e.g.
    ``blocking_call_in_async``) so that the mission generator can target the
    *pattern*, not the one-off question the player got wrong. ``occurrences``
    makes a repeated mistake louder without creating duplicate rows.
    """

    __tablename__ = "mistake_records"
    __table_args__ = (
        UniqueConstraint("profile_id", "pattern", name="uq_mistake_profile_pattern"),
        Index("ix_mistake_records_open", "profile_id", "resolved"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pattern: Mapped[str] = mapped_column(String(80), nullable=False)
    concept_slug: Mapped[str | None] = mapped_column(String(120), index=True)
    skill_slug: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, default="", nullable=False)
    correct_approach: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)

    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    #: Consecutive clean attempts on this pattern; N in a row closes it.
    clean_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    profile: Mapped[PlayerProfile] = relationship(back_populates="mistakes")


class JournalEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Engineering Journal (spec §43) — reflection after each mission."""

    __tablename__ = "journal_entries"
    __table_args__ = (Index("ix_journal_profile_time", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mission_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mission_attempts.id", ondelete="SET NULL")
    )
    context_slug: Mapped[str | None] = mapped_column(String(120))
    what_i_learned: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mistake_made: Mapped[str] = mapped_column(Text, default="", nullable=False)
    would_do_differently: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    concept_slugs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Set when the entry has been replayed back to the player as a callback.
    resurfaced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    profile: Mapped[PlayerProfile] = relationship(back_populates="journal_entries")


class ProjectProgress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_progress"
    __table_args__ = (UniqueConstraint("profile_id", "project_slug", name="uq_project_progress"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="in_progress", nullable=False)
    #: {milestone_slug: {"status","score","notes","submitted_at","artifacts"}}
    milestone_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    defense_score: Mapped[float | None] = mapped_column(Float)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
