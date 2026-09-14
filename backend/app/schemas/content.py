"""Contracts for missions, challenges, questions and concepts.

SECURITY NOTE that shaped this module: ``ChallengeOut`` must never contain
``reference_solution`` or hidden tests. The split between ``ChallengeOut``
(player-facing) and ``ChallengeAdminOut`` is the enforcement mechanism — if the
secret is not on the response model, Pydantic drops it even when the service
hands over a full ORM object.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from app.schemas.common import Schema


class ConceptSummary(Schema):
    slug: str
    title: str
    category: str
    skill_slug: str
    base_difficulty: int
    summary: str
    estimated_minutes: int
    tags: list[str] = Field(default_factory=list)
    mastery: float = 0.0
    effective_mastery: float = 0.0
    due: bool = False
    decayed: bool = False


class ConceptDetail(ConceptSummary):
    explanation: str
    examples: list[dict[str, Any]] = Field(default_factory=list)
    common_mistakes: list[dict[str, Any]] = Field(default_factory=list)
    real_world_usage: list[str] = Field(default_factory=list)
    visualization: dict[str, Any] | None = None
    max_tier: int = 10
    prerequisites: list[ConceptSummary] = Field(default_factory=list)
    leads_to: list[ConceptSummary] = Field(default_factory=list)
    related: list[ConceptSummary] = Field(default_factory=list)
    challenge_slugs: list[str] = Field(default_factory=list)
    question_slugs: list[str] = Field(default_factory=list)


class TestCaseOut(Schema):
    """A *visible* test case. Hidden cases are filtered out by the service."""

    name: str
    description: str = ""
    call: str | None = None
    expect: Any = None
    points: float = 1.0


class ChallengeOut(Schema):
    slug: str
    title: str
    category: str
    skill_slug: str
    tier: int
    prompt: str
    starter_code: str
    hints_available: int = 0
    visible_tests: list[TestCaseOut] = Field(default_factory=list)
    hidden_test_count: int = 0
    explanation_prompts: list[str] = Field(default_factory=list)
    requires_packages: list[str] = Field(default_factory=list)
    par_seconds: int
    time_limit_seconds: int
    concept_slugs: list[str] = Field(default_factory=list)
    expected_complexity: str | None = None
    target_speedup: float | None = None
    baseline_code: str | None = None
    attempts_made: int = 0
    solved: bool = False


class MissionStepOut(Schema):
    position: int
    step_type: str
    title: str
    prompt: str
    challenge_slug: str | None = None
    question_slug: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    status: str = "pending"
    score: float | None = None


class MissionSummary(Schema):
    slug: str
    title: str
    kind: str
    category: str
    building: str
    tier: int
    skill_slug: str
    objective: str
    estimated_minutes: int
    required_level: int
    is_boss: bool
    locked: bool = False
    lock_reason: str | None = None
    completed: bool = False
    best_score: float | None = None
    attempts: int = 0


class MissionDetail(MissionSummary):
    briefing: str
    success_criteria: list[str] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    concept_slugs: list[str] = Field(default_factory=list)
    par_seconds: int = 900
    steps: list[MissionStepOut] = Field(default_factory=list)
    attempt_id: uuid.UUID | None = None
    debrief: str | None = None


class QuestionOptionOut(Schema):
    id: str
    text: str


class QuestionOut(Schema):
    """Player-facing question. Note what is absent: ``expected_answer``,
    ``rubric`` and which option is correct."""

    slug: str
    kind: str
    category: str
    skill_slug: str
    tier: int
    interview_level: str
    prompt: str
    context: str | None = None
    options: list[QuestionOptionOut] = Field(default_factory=list)
    hints_available: int = 0
    par_seconds: int
    concept_slugs: list[str] = Field(default_factory=list)


class HintOut(Schema):
    index: int
    text: str
    remaining: int
    cost_coins: int = 0


# ── Submissions ─────────────────────────────────────────────────────────────
class ExplanationPayload(Schema):
    """Spec §41 — passing tests is not enough; the player must justify."""

    explanation: Annotated[str | None, Field(max_length=8000)] = None
    complexity: Annotated[str | None, Field(max_length=80)] = None
    tradeoffs: Annotated[str | None, Field(max_length=8000)] = None
    confidence: Annotated[float | None, Field(ge=0, le=1)] = None


class ChallengeSubmission(ExplanationPayload):
    code: Annotated[str, Field(min_length=1, max_length=100_000)]
    elapsed_seconds: Annotated[int, Field(ge=0, le=86_400)] = 0
    hints_used: Annotated[int, Field(ge=0, le=20)] = 0
    run_only: bool = False


class QuestionSubmission(ExplanationPayload):
    answer_text: Annotated[str, Field(max_length=20_000)] = ""
    selected_option_ids: list[str] = Field(default_factory=list)
    elapsed_seconds: Annotated[int, Field(ge=0, le=86_400)] = 0
    hints_used: Annotated[int, Field(ge=0, le=20)] = 0


class MissionStepSubmission(Schema):
    position: int
    challenge: ChallengeSubmission | None = None
    question: QuestionSubmission | None = None
    free_text: Annotated[str | None, Field(max_length=20_000)] = None
    design: dict[str, Any] | None = None
    review_comments: list[dict[str, Any]] | None = None


class TestResultOut(Schema):
    name: str
    passed: bool
    hidden: bool = False
    expected: Any = None
    actual: Any = None
    message: str = ""
    duration_ms: float = 0.0


class GradeOut(Schema):
    """Uniform grading envelope for every gradeable interaction.

    Failure is framed as an incident, not a buzzer (spec §64): ``headline``,
    ``what_happened`` and ``root_cause`` are populated on failure so the UI can
    render a postmortem card instead of the word "Wrong".
    """

    passed: bool
    score: float  # 0..1 normalised
    points: float = 0.0
    max_points: float = 0.0
    tests_passed: int = 0
    tests_total: int = 0
    test_results: list[TestResultOut] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    runtime_ms: float = 0.0
    timed_out: bool = False

    headline: str = ""
    what_happened: str = ""
    root_cause: str | None = None
    hint: str | None = None
    explanation_score: float | None = None
    explanation_feedback: str | None = None
    missing_points: list[str] = Field(default_factory=list)
    detected_mistakes: list[dict[str, Any]] = Field(default_factory=list)
    speedup_factor: float | None = None

    progression: dict[str, Any] | None = None
    mastery_delta: dict[str, Any] | None = None
    next_review_at: datetime | None = None
    can_retry: bool = True
    reveal_solution: bool = False
    solution: str | None = None
    solution_explanation: str | None = None


class JournalSubmission(Schema):
    what_i_learned: Annotated[str, Field(max_length=8000)] = ""
    mistake_made: Annotated[str, Field(max_length=8000)] = ""
    would_do_differently: Annotated[str, Field(max_length=8000)] = ""
    confidence: Annotated[float | None, Field(ge=0, le=1)] = None
    context_slug: str | None = None
    concept_slugs: list[str] = Field(default_factory=list)


class JournalEntryOut(Schema):
    id: uuid.UUID
    context_slug: str | None
    what_i_learned: str
    mistake_made: str
    would_do_differently: str
    confidence: float | None
    concept_slugs: list[str]
    created_at: datetime
