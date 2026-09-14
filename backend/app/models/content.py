"""Authored learning content.

Everything in this module is *seeded from code* (``app/content/**``) rather than
entered by users. Consequences that shaped the schema:

* every row carries a stable ``slug`` — re-seeding must never orphan progress;
* rows are versioned (``content_version``) so a changed challenge can invalidate
  cached results without losing history;
* the knowledge graph lives in a dedicated edge table, not in a JSON blob, so we
  can traverse it in SQL (recursive CTE) for prerequisite checks.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SlugMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONB

if TYPE_CHECKING:
    pass


class Skill(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """One of the 16 player attributes (``SkillId``), plus its tree nodes."""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(40), default="sparkles", nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#38bdf8", nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Which world-map building this attribute is trained in.
    building: Mapped[str | None] = mapped_column(String(40))

    nodes: Mapped[list[SkillNode]] = relationship(
        back_populates="skill", cascade="all, delete-orphan", order_by="SkillNode.display_order"
    )


class SkillNode(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """A node in the animated skill tree (e.g. Python -> Decorators).

    Self-referential parent link gives an arbitrary-depth tree without a second
    table; the frontend renders it as a radial/force graph.
    """

    __tablename__ = "skill_nodes"
    __table_args__ = (Index("ix_skill_nodes_skill_parent", "skill_id", "parent_id"),)

    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_nodes.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tier_range: Mapped[list] = mapped_column(JSONB, default=lambda: [1, 10], nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unlock_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    skill: Mapped[Skill] = relationship(back_populates="nodes")
    parent: Mapped[SkillNode | None] = relationship(
        remote_side="SkillNode.id", back_populates="children"
    )
    children: Mapped[list[SkillNode]] = relationship(back_populates="parent")


class Concept(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """An atomic teachable idea — the unit the retention engine schedules.

    Spec §62: a concept carries not just an explanation but the *whole ladder*
    of ways to engage with it. Rich text lives in JSON columns because it is
    read as a whole document and never queried field-by-field.
    """

    __tablename__ = "concepts"
    __table_args__ = (
        Index("ix_concepts_category_difficulty", "category", "base_difficulty"),
        CheckConstraint("base_difficulty BETWEEN 1 AND 10", name="base_difficulty_range"),
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill_slug: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    skill_node_slug: Mapped[str | None] = mapped_column(String(80), index=True)
    base_difficulty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_tier: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: [{"title": ..., "code": ..., "output": ..., "note": ...}]
    examples: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: [{"mistake": ..., "why": ..., "fix": ..., "severity": ...}]
    common_mistakes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    real_world_usage: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Optional structured spec for an animated visualisation component.
    visualization: Mapped[dict | None] = mapped_column(JSONB)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    outgoing_edges: Mapped[list[ConceptEdge]] = relationship(
        back_populates="source",
        foreign_keys="ConceptEdge.source_id",
        cascade="all, delete-orphan",
    )


class ConceptEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A directed edge of the knowledge graph (spec §39).

    ``relation`` distinguishes a hard prerequisite (gates content) from a soft
    "leads to" link (drives recommendations) — conflating them would either
    over-gate the game or under-teach the dependencies.
    """

    __tablename__ = "concept_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation", name="uq_concept_edge"),
        Index("ix_concept_edges_target", "target_id", "relation"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(24), default="requires", nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    source: Mapped[Concept] = relationship(
        foreign_keys=[source_id], back_populates="outgoing_edges"
    )
    target: Mapped[Concept] = relationship(foreign_keys=[target_id])


class Mission(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """A playable unit: briefing + one or more steps.

    A mission is the *container*; the actual work lives in ``MissionStep`` rows
    that point at challenges or questions. That indirection is what lets the
    daily-mission generator assemble a bespoke mission from existing content
    without duplicating it.
    """

    __tablename__ = "missions"
    __table_args__ = (
        Index("ix_missions_building_tier", "building", "tier"),
        CheckConstraint("tier BETWEEN 1 AND 10", name="tier_range"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    building: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    tier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    skill_slug: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    #: In-fiction framing: who filed the ticket, what is on fire.
    briefing: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    success_criteria: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Artefacts handed to the player: logs, metrics, stack traces, schemas.
    artifacts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    debrief: Mapped[str] = mapped_column(Text, default="", nullable=False)

    required_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    required_rank: Mapped[str | None] = mapped_column(String(40))
    prerequisite_mission_slugs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    concept_slugs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    estimated_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    par_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    xp_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_boss: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_daily_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    steps: Mapped[list[MissionStep]] = relationship(
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="MissionStep.position",
        lazy="selectin",
    )


class MissionStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mission_steps"
    __table_args__ = (UniqueConstraint("mission_id", "position", name="uq_mission_step_position"),)

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    #: challenge | question | explanation | design | review | journal
    step_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    challenge_slug: Mapped[str | None] = mapped_column(String(120), index=True)
    question_slug: Mapped[str | None] = mapped_column(String(120), index=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    mission: Mapped[Mission] = relationship(back_populates="steps")


class Challenge(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """A code challenge executed in the sandbox.

    ``tests`` is the grading contract. It is never sent to the client in full —
    ``visible_tests`` is. Hidden tests are what stop a player from special-casing
    the examples, exactly like a real test suite they cannot see in CI.
    """

    __tablename__ = "challenges"
    __table_args__ = (Index("ix_challenges_category_tier", "category", "tier"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill_slug: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    tier: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    concept_slugs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    starter_code: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Deliberately broken code for DEBUG-tier challenges.
    broken_code: Mapped[str | None] = mapped_column(Text)
    reference_solution: Mapped[str] = mapped_column(Text, default="", nullable=False)
    solution_explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)

    #: [{"name","call","expect","hidden","points","timeout"}] — see sandbox/runner.py
    tests: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Extra modules the sandbox must import (numpy, pandas, ...).
    requires_packages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    setup_code: Mapped[str] = mapped_column(Text, default="", nullable=False)

    hints: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Graded free-text follow-ups (spec §41: explain WHY, complexity, tradeoffs)
    explanation_prompts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    expected_complexity: Mapped[str | None] = mapped_column(String(40))
    #: Optimisation challenges compare against this baseline.
    baseline_code: Mapped[str | None] = mapped_column(Text)
    target_speedup: Mapped[float | None] = mapped_column(Float)

    par_seconds: Mapped[int] = mapped_column(Integer, default=420, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Question(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """An interview / quiz question at a specific tier (spec §30).

    Note the fields beyond the answer: ``ideal_senior_answer``,
    ``common_wrong_answer`` and ``followups`` are what turn a quiz into an
    interview. The scoring rubric is stored with the question so grading stays
    deterministic and explainable even when no LLM is configured.
    """

    __tablename__ = "questions"
    __table_args__ = (
        Index("ix_questions_category_tier_kind", "category", "tier", "kind"),
        Index("ix_questions_level", "interview_level"),
    )

    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    skill_slug: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    tier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    interview_level: Mapped[str] = mapped_column(String(16), default="junior", nullable=False)
    concept_slugs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)  # code snippet / logs / schema
    #: [{"id":"a","text":...,"correct":bool,"why":...}] for MCQ kinds
    options: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ideal_senior_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    common_wrong_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: [{"keyword": "...", "weight": 0.2, "aliases": [...]}] — deterministic rubric
    rubric: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    hints: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    followups: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    par_seconds: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Badge(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    __tablename__ = "badges"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String(16), default="bronze", nullable=False)
    icon: Mapped[str] = mapped_column(String(40), default="award", nullable=False)
    #: Declarative unlock rule evaluated by app/game/achievements/rules.py
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    xp_reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Achievement(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    __tablename__ = "achievements"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    xp_reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coin_reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    icon: Mapped[str] = mapped_column(String(40), default="trophy", nullable=False)
    #: Multi-step achievements track progress toward this target.
    target: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class KnowledgeDocument(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """Source documents for the in-game RAG tower.

    Embeddings are stored as a JSON float array rather than pgvector so the game
    runs identically on SQLite. The RAG missions teach *why* that is the wrong
    choice at scale, and the vector-store abstraction (app/ai/rag/store.py) has a
    pgvector backend behind the same interface.
    """

    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_knowledge_documents_corpus_chunk", "corpus", "chunk_index"),)

    corpus: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_of: Mapped[str | None] = mapped_column(String(120), index=True)
    doc_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSONB)
    embedding_model: Mapped[str | None] = mapped_column(String(60))
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Project(UUIDPrimaryKeyMixin, SlugMixin, TimestampMixin, Base):
    """Long-form build (spec §33/§59) — the capstone and its milestones."""

    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    required_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    required_rank: Mapped[str | None] = mapped_column(String(40))
    architecture: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: [{"slug","title","description","acceptance":[...],"concepts":[...],"xp":N}]
    milestones: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    defense_question_slugs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    xp_reward: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)
