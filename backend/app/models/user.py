"""Identity and the player's headline progression row."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONB, UTCDateTime
from app.domain.enums import MentorPersona, Rank

if TYPE_CHECKING:
    from app.models.progress import (
        ConceptProgress,
        JournalEntry,
        LearningEvent,
        MistakeRecord,
        PlayerAchievement,
        PlayerBadge,
        SkillProgress,
        XPTransaction,
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    profile: Mapped[PlayerProfile] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Server-side refresh-token records.

    WHY store them at all when JWTs are stateless: logout and "revoke all
    sessions" are impossible with a pure stateless refresh token. We store only
    the ``jti`` and a revocation flag — the token itself never touches the DB,
    so a database leak does not hand over live sessions.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_revoked", "user_id", "revoked"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_valid(self) -> bool:
        return not self.revoked and self.expires_at > datetime.now(UTC)


class PlayerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The RPG sheet: XP, rank, streak, avatar, world state.

    WHY separate from ``User``: identity and gameplay change at completely
    different rates and for different reasons. Every mission submission writes
    this row; nothing writes ``users``. Splitting them keeps the hot row narrow
    and keeps auth logic free of game concerns.
    """

    __tablename__ = "player_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    avatar_seed: Mapped[str] = mapped_column(String(40), default="forge-01", nullable=False)
    title: Mapped[str] = mapped_column(String(80), default="Python Apprentice", nullable=False)

    total_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    rank: Mapped[str] = mapped_column(
        String(40), default=Rank.PYTHON_APPRENTICE.value, nullable=False
    )
    coins: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    reputation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Streaks ---------------------------------------------------------
    current_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_date: Mapped[date | None] = mapped_column(Date)

    # --- Aggregates (denormalised for the dashboard) ---------------------
    # WHY denormalise: the dashboard is the single most-hit endpoint and these
    # counters would otherwise need five COUNT(*) queries over growing tables.
    # They are derived, so a nightly reconciliation job can rebuild them if a
    # bug ever drifts them — see app/services/analytics_service.py.
    missions_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenges_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    questions_answered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bosses_defeated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    incidents_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_practice_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- World state -----------------------------------------------------
    unlocked_buildings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    preferred_mentor: Mapped[str] = mapped_column(
        String(32), default=MentorPersona.SENIOR_ENGINEER.value, nullable=False
    )
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")
    skill_progress: Mapped[list[SkillProgress]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    concept_progress: Mapped[list[ConceptProgress]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    xp_transactions: Mapped[list[XPTransaction]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    badges: Mapped[list[PlayerBadge]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    achievements: Mapped[list[PlayerAchievement]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    learning_events: Mapped[list[LearningEvent]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    mistakes: Mapped[list[MistakeRecord]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    journal_entries: Mapped[list[JournalEntry]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class LeaderboardEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Materialised leaderboard snapshot.

    WHY a table instead of ``ORDER BY total_xp LIMIT 50``: that query is cheap
    today and a sequential scan at 100k players. Snapshotting on a schedule also
    gives us weekly/monthly boards for free, which a live query cannot express.
    """

    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        UniqueConstraint("period", "period_key", "profile_id", name="uq_leaderboard_slot"),
        Index("ix_leaderboard_rank", "period", "period_key", "position"),
    )

    period: Mapped[str] = mapped_column(String(16), nullable=False)  # all_time | weekly | monthly
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. 2026-W07
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[str] = mapped_column(String(40), nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
