"""AI-lab persistence: code submissions, evaluations, RAG experiments, agent runs
and the LangSmith-style trace store.

WHY traces live in Postgres rather than a real observability backend: the point
of the Observability Lab is to make the player *build and read* traces, so the
data model has to be inspectable, queryable and seedable. A span table with a
parent pointer is the same shape OpenTelemetry uses — the lesson transfers.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONB, UTCDateTime


class CodeSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every sandbox execution, whether graded or a scratch run.

    Kept separate from ``ChallengeAttempt`` because players run code far more
    often than they submit it, and because free-form runs from the Data Lab and
    PyTorch Lab have no challenge at all.
    """

    __tablename__ = "code_submissions"
    __table_args__ = (Index("ix_code_submissions_profile_time", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), index=True
    )
    challenge_slug: Mapped[str | None] = mapped_column(String(120), index=True)
    language: Mapped[str] = mapped_column(String(16), default="python", nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    #: run | grade | benchmark
    purpose: Mapped[str] = mapped_column(String(16), default="run", nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stderr: Mapped[str] = mapped_column(Text, default="", nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_memory_kb: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    test_results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    sandbox_mode: Mapped[str] = mapped_column(String(16), default="subprocess", nullable=False)


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A scored evaluation run (spec §20–§21): RAG, prompt, agent or model.

    One row per *run over a dataset*; per-case results live in ``results`` so an
    experiment is a single fetch. Aggregate metrics are hoisted into columns
    because the Evals dashboard charts them over time.
    """

    __tablename__ = "evaluations"
    __table_args__ = (Index("ix_evaluations_profile_target", "profile_id", "target_type"),)

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: rag | prompt | agent | model | retrieval
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_ref: Mapped[str | None] = mapped_column(String(120))
    dataset_slug: Mapped[str | None] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    #: The six headline metrics the Evals Lab teaches.
    retrieval_precision: Mapped[float | None] = mapped_column(Float)
    retrieval_recall: Mapped[float | None] = mapped_column(Float)
    context_relevance: Mapped[float | None] = mapped_column(Float)
    faithfulness: Mapped[float | None] = mapped_column(Float)
    answer_relevance: Mapped[float | None] = mapped_column(Float)
    groundedness: Mapped[float | None] = mapped_column(Float)
    extra_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    cases_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cases_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(24))  # ship | hold | rollback
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class RAGExperiment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One configuration of the RAG pipeline plus what it produced.

    The whole point of the RAG Tower is comparing configurations, so every knob
    the player can turn is a column or a key in ``config`` — chunk size, overlap,
    top-k, reranking, metadata filters — and the retrieved chunks are stored so a
    bad answer can be traced back to a bad retrieval.
    """

    __tablename__ = "rag_experiments"
    __table_args__ = (Index("ix_rag_experiments_profile", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), index=True
    )
    corpus: Mapped[str] = mapped_column(String(60), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)

    chunk_size: Mapped[int] = mapped_column(Integer, default=400, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(60), default="hash-tfidf", nullable=False)
    use_reranker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    use_hybrid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_filter: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, default="", nullable=False)

    retrieved: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("traces.id", ondelete="SET NULL"))
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    token_usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A LangGraph-style agent execution (spec §23).

    ``state_history`` is the teaching artefact: players step through how state
    mutated at each node, which is the only way graph debugging ever clicks.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_profile", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), index=True
    )
    graph_slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    input_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    final_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: [{"step","node","edge_taken","state_diff","duration_ms","tokens","error"}]
    state_history: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    node_visits: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Set when the recursion guard fired — the "infinite loop" boss.
    halted_reason: Mapped[str | None] = mapped_column(String(60))
    needs_human_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    human_decision: Mapped[str | None] = mapped_column(String(16))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("traces.id", ondelete="SET NULL"))
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    token_usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Trace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Root of an observability trace (spec §24/§50)."""

    __tablename__ = "traces"
    __table_args__ = (Index("ix_traces_profile_time", "profile_id", "started_at"),)

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="chain", nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    trace_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    spans: Mapped[list[Span]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="Span.started_at",
        lazy="selectin",
    )


class Span(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One unit of work inside a trace (retriever, llm, tool, node...)."""

    __tablename__ = "spans"
    __table_args__ = (Index("ix_spans_trace_parent", "trace_id", "parent_id"),)

    trace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("spans.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: llm | retriever | embedding | tool | node | chain | db | http
    span_type: Mapped[str] = mapped_column(String(24), default="chain", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    input_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    model: Mapped[str | None] = mapped_column(String(60))
    evaluation_score: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    span_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    trace: Mapped[Trace] = relationship(back_populates="spans")
    children: Mapped[list[Span]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[Span | None] = relationship(remote_side="Span.id", back_populates="children")
