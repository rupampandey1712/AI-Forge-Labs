"""Missions, the daily mission, retention, interviews, analytics and the journal."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import (
    AnalyticsSvc,
    ContentSvc,
    CurrentProfile,
    DailySvc,
    DBSession,
    InterviewSvc,
    MissionSvc,
    RetentionSvc,
)
from app.schemas.analytics import ProgressAnalyticsOut, ReadinessBreakdown
from app.schemas.common import Message, Page
from app.schemas.content import (
    GradeOut,
    JournalEntryOut,
    JournalSubmission,
    MissionDetail,
    MissionStepSubmission,
    MissionSummary,
)
from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewReportOut,
    InterviewSessionOut,
    InterviewStartRequest,
)
from app.schemas.retention import (
    DailyMissionOut,
    MistakeOut,
    RetentionDashboardOut,
)

router = APIRouter(tags=["gameplay"])


# ── Missions ─────────────────────────────────────────────────────────────────
@router.get("/missions", response_model=Page[MissionSummary])
async def list_missions(
    profile: CurrentProfile,
    service: ContentSvc,
    building: str | None = None,
    category: str | None = None,
    kind: str | None = None,
    include_locked: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Page[MissionSummary]:
    items, total = await service.list_missions(
        profile,
        building=building,
        category=category,
        kind=kind,
        include_locked=include_locked,
        page=page,
        page_size=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/missions/{slug}", response_model=MissionDetail)
async def get_mission(slug: str, profile: CurrentProfile, service: ContentSvc) -> MissionDetail:
    return await service.get_mission(slug, profile)


@router.post("/missions/{slug}/start", response_model=MissionDetail)
async def start_mission(slug: str, profile: CurrentProfile, service: MissionSvc) -> MissionDetail:
    return await service.start(profile, slug)


@router.post("/missions/{slug}/step", response_model=GradeOut)
async def submit_step(
    slug: str,
    payload: MissionStepSubmission,
    profile: CurrentProfile,
    service: MissionSvc,
) -> GradeOut:
    return await service.submit_step(profile, slug, payload)


@router.post("/missions/{slug}/complete")
async def complete_mission(
    slug: str, profile: CurrentProfile, service: MissionSvc
) -> dict[str, Any]:
    """Finalise: score, XP, debrief and the journal prompts."""
    return await service.complete(profile, slug)


@router.post("/missions/{slug}/abandon", response_model=Message)
async def abandon_mission(slug: str, profile: CurrentProfile, service: MissionSvc) -> Message:
    await service.abandon(profile, slug)
    return Message(message="Mission abandoned. Progress on completed steps is kept.")


# ── Daily mission ────────────────────────────────────────────────────────────
@router.get("/daily-challenge", response_model=DailyMissionOut)
async def daily_challenge(profile: CurrentProfile, service: DailySvc) -> DailyMissionOut:
    """Today's plan. Generated once per day and then stable — no rerolls."""
    return await service.get_or_create(profile)


@router.post("/daily-challenge/submit", response_model=DailyMissionOut)
async def submit_daily_slot(
    payload: dict[str, Any], profile: CurrentProfile, service: DailySvc
) -> DailyMissionOut:
    return await service.mark_slot_complete(
        profile, int(payload.get("slot", 0)), float(payload.get("score", 0.0))
    )


@router.get("/daily-challenge/history")
async def daily_history(
    profile: CurrentProfile,
    service: DailySvc,
    limit: Annotated[int, Query(ge=1, le=90)] = 14,
) -> list[dict[str, Any]]:
    return await service.history(profile.id, limit=limit)


# ── Retention ────────────────────────────────────────────────────────────────
@router.get("/retention", response_model=RetentionDashboardOut)
async def retention_dashboard(
    profile: CurrentProfile, service: RetentionSvc
) -> RetentionDashboardOut:
    """Decay, due reviews, alerts and the 90-day forgetting forecast."""
    return await service.dashboard(profile.id)


@router.get("/retention/due")
async def due_reviews(
    profile: CurrentProfile,
    service: RetentionSvc,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    pairs = await service.due_concepts(profile.id, limit=limit)
    return [
        {
            "concept_slug": row.concept_slug,
            "skill_slug": row.skill_slug,
            "category": row.category,
            "retrievability": rep.retrievability,
            "effective_mastery": rep.effective_mastery,
            "urgency": rep.urgency,
            "days_since_practice": rep.days_since_practice,
        }
        for row, rep in pairs
    ]


@router.get("/mistakes", response_model=list[MistakeOut])
async def mistakes(
    profile: CurrentProfile,
    session: DBSession,
    include_resolved: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[MistakeOut]:
    from sqlalchemy import select

    from app.models.progress import MistakeRecord

    stmt = select(MistakeRecord).where(MistakeRecord.profile_id == profile.id)
    if not include_resolved:
        stmt = stmt.where(MistakeRecord.resolved.is_(False))
    rows = (
        (await session.execute(stmt.order_by(MistakeRecord.occurrences.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [MistakeOut.model_validate(r) for r in rows]


# ── Interview Arena ──────────────────────────────────────────────────────────
@router.post("/interview/start", response_model=InterviewSessionOut)
async def start_interview(
    payload: InterviewStartRequest, profile: CurrentProfile, service: InterviewSvc
) -> InterviewSessionOut:
    return await service.start(profile, payload)


@router.get("/interview/{session_id}", response_model=InterviewSessionOut)
async def get_interview(
    session_id: uuid.UUID, profile: CurrentProfile, service: InterviewSvc
) -> InterviewSessionOut:
    return await service.get_session(session_id, profile.id)


@router.post("/interview/{session_id}/answer", response_model=InterviewAnswerResponse)
async def answer_interview(
    session_id: uuid.UUID,
    payload: InterviewAnswerRequest,
    profile: CurrentProfile,
    service: InterviewSvc,
) -> InterviewAnswerResponse:
    """Grade the answer and decide what the interviewer asks next."""
    return await service.answer(profile, session_id, payload)


@router.get("/interview/{session_id}/report", response_model=InterviewReportOut)
async def interview_report(
    session_id: uuid.UUID, profile: CurrentProfile, service: InterviewSvc
) -> InterviewReportOut:
    return await service.report(profile, session_id)


@router.post("/interview/{session_id}/end", response_model=Message)
async def end_interview(
    session_id: uuid.UUID, profile: CurrentProfile, service: InterviewSvc
) -> Message:
    await service.abandon(profile, session_id)
    return Message(message="Interview ended. Your report is ready.")


# ── Analytics ────────────────────────────────────────────────────────────────
@router.get("/analytics/progress", response_model=ProgressAnalyticsOut)
async def analytics_progress(
    profile: CurrentProfile, service: AnalyticsSvc
) -> ProgressAnalyticsOut:
    return await service.progress(profile)


@router.get("/analytics/readiness", response_model=ReadinessBreakdown)
async def analytics_readiness(profile: CurrentProfile, service: AnalyticsSvc) -> ReadinessBreakdown:
    """Interview readiness *with* the components that produced it."""
    return await service.interview_readiness(profile)


@router.get("/analytics/retention")
async def analytics_retention(profile: CurrentProfile, service: AnalyticsSvc) -> dict[str, Any]:
    return await service.retention_summary(profile)


# ── Engineering journal ──────────────────────────────────────────────────────
@router.post("/journal", response_model=JournalEntryOut)
async def add_journal_entry(
    payload: JournalSubmission, profile: CurrentProfile, service: MissionSvc
) -> JournalEntryOut:
    entry = await service.add_journal_entry(profile, payload)
    await service.session.flush()
    return JournalEntryOut.model_validate(entry)


@router.get("/journal", response_model=list[JournalEntryOut])
async def list_journal(
    profile: CurrentProfile,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[JournalEntryOut]:
    from app.repositories.player import JournalRepository

    rows = await JournalRepository(session).recent(profile.id, limit=limit)
    return [JournalEntryOut.model_validate(r) for r in rows]
