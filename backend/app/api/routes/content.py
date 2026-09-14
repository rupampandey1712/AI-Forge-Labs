"""Concepts, challenges, questions and code execution."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import ContentSvc, CurrentProfile, GradingSvc, OptionalProfile, SandboxSvc
from app.core.errors import ValidationFailedError
from app.schemas.common import Page
from app.schemas.content import (
    ChallengeOut,
    ChallengeSubmission,
    ConceptDetail,
    ConceptSummary,
    GradeOut,
    HintOut,
    QuestionOut,
    QuestionSubmission,
)

router = APIRouter(tags=["content"])


# ── Concepts ─────────────────────────────────────────────────────────────────
@router.get("/concepts", response_model=Page[ConceptSummary])
async def list_concepts(
    service: ContentSvc,
    profile: OptionalProfile,
    category: str | None = None,
    skill_slug: str | None = None,
    node_slug: str | None = None,
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Page[ConceptSummary]:
    items, total = await service.list_concepts(
        profile_id=profile.id if profile else None,
        category=category,
        skill_slug=skill_slug,
        node_slug=node_slug,
        search=search,
        page=page,
        page_size=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/concepts/{slug}", response_model=ConceptDetail)
async def get_concept(slug: str, service: ContentSvc, profile: OptionalProfile) -> ConceptDetail:
    return await service.get_concept(slug, profile_id=profile.id if profile else None)


# ── Challenges ───────────────────────────────────────────────────────────────
@router.get("/challenges", response_model=Page[dict])
async def list_challenges(
    service: ContentSvc,
    profile: OptionalProfile,
    category: str | None = None,
    skill_slug: str | None = None,
    tier: Annotated[int | None, Query(ge=1, le=10)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[dict]:
    items, total = await service.list_challenges(
        profile_id=profile.id if profile else None,
        category=category,
        skill_slug=skill_slug,
        tier=tier,
        page=page,
        page_size=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/challenges/{slug}", response_model=ChallengeOut)
async def get_challenge(slug: str, service: ContentSvc, profile: OptionalProfile) -> ChallengeOut:
    """Player-facing view. Hidden tests and the reference solution never appear."""
    return await service.get_challenge(slug, profile_id=profile.id if profile else None)


@router.post("/challenges/{slug}/submit", response_model=GradeOut)
async def submit_challenge(
    slug: str,
    payload: ChallengeSubmission,
    profile: CurrentProfile,
    content: ContentSvc,
    grading: GradingSvc,
) -> GradeOut:
    """Execute in the sandbox, grade, award XP and update the retention model."""
    challenge = await content.get_challenge_model(slug)
    return await grading.submit_challenge(profile, challenge, payload)


@router.get("/challenges/{slug}/hint", response_model=HintOut)
async def challenge_hint(
    slug: str,
    service: ContentSvc,
    profile: CurrentProfile,
    index: Annotated[int, Query(ge=0, le=20)] = 0,
) -> HintOut:
    """Hints escalate one at a time and cost coins — never free, never the answer."""
    text, remaining = await service.hint("challenge", slug, index)
    cost = 5 * (index + 1)
    if profile.coins < cost:
        raise ValidationFailedError("Not enough coins for another hint.")
    profile.coins -= cost
    return HintOut(index=index, text=text, remaining=remaining, cost_coins=cost)


# ── Questions ────────────────────────────────────────────────────────────────
@router.get("/questions/random", response_model=QuestionOut | None)
async def random_question(
    service: ContentSvc,
    profile: OptionalProfile,
    category: str | None = None,
    tier: Annotated[int | None, Query(ge=1, le=10)] = None,
    interview_level: str | None = None,
) -> QuestionOut | None:
    return await service.random_question(
        profile_id=profile.id if profile else None,
        category=category,
        tier=tier,
        interview_level=interview_level,
    )


@router.get("/questions/{slug}", response_model=QuestionOut)
async def get_question(slug: str, service: ContentSvc) -> QuestionOut:
    return service.to_question_out(await service.get_question_model(slug))


@router.post("/questions/{slug}/submit", response_model=GradeOut)
async def submit_question(
    slug: str,
    payload: QuestionSubmission,
    profile: CurrentProfile,
    content: ContentSvc,
    grading: GradingSvc,
) -> GradeOut:
    question = await content.get_question_model(slug)
    return await grading.submit_question(profile, question, payload)


@router.get("/questions/{slug}/hint", response_model=HintOut)
async def question_hint(
    slug: str,
    service: ContentSvc,
    profile: CurrentProfile,
    index: Annotated[int, Query(ge=0, le=20)] = 0,
) -> HintOut:
    text, remaining = await service.hint("question", slug, index)
    cost = 5 * (index + 1)
    if profile.coins < cost:
        raise ValidationFailedError("Not enough coins for another hint.")
    profile.coins -= cost
    return HintOut(index=index, text=text, remaining=remaining, cost_coins=cost)


# ── Free-form code execution (the Labs) ──────────────────────────────────────
@router.post("/code/execute")
async def execute_code(
    payload: dict[str, Any],
    profile: CurrentProfile,
    sandbox: SandboxSvc,
) -> dict[str, Any]:
    """Run arbitrary player code in the sandbox — the Data/ML/Transformer labs.

    Deliberately NOT graded and NOT recorded against the retention model:
    scratch experimentation must be free of consequences, or players stop
    experimenting.
    """
    code = str(payload.get("code", ""))
    if not code.strip():
        raise ValidationFailedError("No code supplied.")
    result = await sandbox.run(
        code,
        setup_code=str(payload.get("setup_code", "")),
        stdin=str(payload.get("stdin", "")),
        timeout_seconds=min(float(payload.get("timeout", 8)), 15.0),
    )
    return {
        "status": str(result.status),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
        "error_type": result.error_type,
        "error_message": result.error_message,
        "traceback": result.traceback,
        "benchmark_ms": result.benchmark_ms,
    }
