"""Interview Arena contracts (spec §29–§31, §57)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from app.schemas.common import Schema

#: The seven scoring dimensions from spec §57. Kept as a constant rather than a
#: free-form dict so the radar chart and the rubric can never drift apart.
SCORE_DIMENSIONS = (
    "correctness",
    "depth",
    "practical_experience",
    "tradeoff_awareness",
    "clarity",
    "architecture_thinking",
    "production_awareness",
)


class InterviewStartRequest(Schema):
    level: str = "mid"
    focus_categories: list[str] = Field(default_factory=list)
    mode: str = "standard"  # standard | pressure
    persona: str = "interviewer"
    question_count: Annotated[int, Field(ge=3, le=25)] = 8


class InterviewTurnOut(Schema):
    position: int
    prompt: str
    context: str | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)
    kind: str = "explain"
    tier: int
    category: str | None = None
    is_followup: bool = False
    parent_position: int | None = None
    time_limit_seconds: int | None = None
    answered: bool = False
    score: float | None = None
    interviewer_reaction: str = ""


class InterviewAnswerRequest(Schema):
    position: int
    answer_text: Annotated[str, Field(max_length=20_000)] = ""
    selected_option_ids: list[str] = Field(default_factory=list)
    elapsed_seconds: Annotated[int, Field(ge=0, le=7200)] = 0
    confidence: Annotated[float | None, Field(ge=0, le=1)] = None


class InterviewFeedbackOut(Schema):
    score: float  # 0..10
    dimension_scores: dict[str, float]
    hit_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    interviewer_reaction: str
    ideal_answer: str | None = None
    common_wrong_answer: str | None = None
    #: What a Senior / Staff / Principal answer would have added on top.
    level_gap: dict[str, str] = Field(default_factory=dict)
    graded_by: str = "rubric"


class InterviewAnswerResponse(Schema):
    feedback: InterviewFeedbackOut
    next_turn: InterviewTurnOut | None = None
    session_complete: bool = False
    progression: dict[str, Any] | None = None


class InterviewSessionOut(Schema):
    id: uuid.UUID
    level: str
    mode: str
    persona: str
    status: str
    focus_categories: list[str]
    planned_questions: int
    questions_asked: int
    started_at: datetime
    completed_at: datetime | None = None
    current_turn: InterviewTurnOut | None = None
    turns: list[InterviewTurnOut] = Field(default_factory=list)


class InterviewReportOut(Schema):
    """The post-interview debrief — the thing players actually learn from."""

    session_id: uuid.UUID
    level: str
    overall_score: float
    verdict: str
    dimension_scores: dict[str, float]
    summary: str
    strengths: list[str]
    gaps: list[str]
    per_question: list[dict[str, Any]]
    recommended_concepts: list[str] = Field(default_factory=list)
    recommended_missions: list[str] = Field(default_factory=list)
    interview_readiness: float = 0.0
    progression: dict[str, Any] | None = None
