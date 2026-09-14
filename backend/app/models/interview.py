"""Interview Arena persistence (spec §29–§31).

An interview is a *stateful conversation*, not a quiz run: the next question
depends on how the last one was answered. That is why the session stores an
explicit ``adaptive_state`` blob — the interviewer's working memory — alongside
the turn log.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONB, UTCDateTime


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (Index("ix_interview_sessions_profile", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), default="mid", nullable=False)
    focus_categories: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    persona: Mapped[str] = mapped_column(String(32), default="interviewer", nullable=False)
    #: standard | pressure — pressure mode enforces a per-question clock and
    #: escalates follow-ups regardless of answer quality.
    mode: Mapped[str] = mapped_column(String(16), default="standard", nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="in_progress", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    planned_questions: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    overall_score: Mapped[float | None] = mapped_column(Float)  # 0..10
    #: {"correctness":..,"depth":..,"practical":..,"tradeoffs":..,"clarity":..,
    #:  "architecture":..,"production":..}
    dimension_scores: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(32))  # strong_hire .. no_hire
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    strengths: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    gaps: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Interviewer working memory: difficulty pressure, covered concepts,
    #: which thread is still open, asked-slug set (prevents repeats).
    adaptive_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    turns: Mapped[list[InterviewTurn]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewTurn.position",
        lazy="selectin",
    )


class InterviewTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question/answer exchange, including dynamically generated follow-ups."""

    __tablename__ = "interview_turns"
    __table_args__ = (Index("ix_interview_turns_session_pos", "session_id", "position"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_slug: Mapped[str | None] = mapped_column(String(120))
    #: A follow-up has no seeded slug — it is generated from the parent question.
    parent_position: Mapped[int | None] = mapped_column(Integer)
    is_followup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))

    answer_text: Mapped[str | None] = mapped_column(Text)
    selected_option_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    score: Mapped[float | None] = mapped_column(Float)  # 0..10
    dimension_scores: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    missing_points: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    interviewer_reaction: Mapped[str] = mapped_column(Text, default="", nullable=False)
    graded_by: Mapped[str] = mapped_column(String(16), default="rubric", nullable=False)

    session: Mapped[InterviewSession] = relationship(back_populates="turns")
