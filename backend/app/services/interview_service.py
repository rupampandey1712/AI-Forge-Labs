"""Interview Arena: an interviewer that adapts, follows up and writes a debrief.

WHAT MAKES THIS AN INTERVIEW RATHER THAN A QUIZ
-----------------------------------------------
* **It follows up.** A strong answer earns a harder follow-up on the same
  thread ("okay, but how does a decorator preserve function metadata?"). A weak
  one earns a scaffolded retry at a lower tier. The next question is a function
  of the last answer, which is the entire difference from a question list.
* **It keeps pressure.** ``mode="pressure"`` enforces a per-question clock and
  escalates regardless of how well it is going — because real interviews do.
* **It scores seven dimensions** (spec §57) and tells you what a Staff answer
  would have added, which is the part players actually learn from.

Follow-ups are generated from the question's authored ``followups`` list, so
the arena works with no LLM. When one is configured, ``_llm_followup`` produces
a bespoke probe from the player's actual words.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.domain.enums import DifficultyTier, InterviewLevel, XPSource
from app.game.grading.rubric import (
    DIMENSIONS,
    grade_free_text,
    grade_mcq,
    level_gap_feedback,
    verdict_for_score,
)
from app.game.xp.engine import AwardContext, compute_award
from app.models.content import Question
from app.models.interview import InterviewSession, InterviewTurn
from app.models.progress import LearningEvent, QuestionAttempt
from app.models.user import PlayerProfile
from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewFeedbackOut,
    InterviewReportOut,
    InterviewSessionOut,
    InterviewStartRequest,
    InterviewTurnOut,
)
from app.services.progression_service import ProgressionService
from app.services.retention_service import RetentionService

log = get_logger(__name__)

#: Per-question clock in pressure mode, by tier. Tight enough to be
#: uncomfortable, generous enough that thinking is still possible.
PRESSURE_SECONDS = {1: 60, 2: 75, 3: 90, 4: 120, 5: 150, 6: 180, 7: 210, 8: 240, 9: 300, 10: 360}

LEVEL_TIER_RANGE: dict[str, tuple[int, int]] = {
    "junior": (1, 3),
    "mid": (2, 5),
    "senior": (4, 8),
    "staff": (6, 9),
    "principal": (8, 10),
}

#: A strong answer at/above this score earns a deeper follow-up.
FOLLOWUP_THRESHOLD = 6.5
MAX_FOLLOWUPS_PER_THREAD = 2


class InterviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.progression = ProgressionService(session)
        self.retention = RetentionService(session)

    # ── Session lifecycle ─────────────────────────────────────────────────
    async def start(
        self, profile: PlayerProfile, payload: InterviewStartRequest
    ) -> InterviewSessionOut:
        level = payload.level if payload.level in LEVEL_TIER_RANGE else "mid"
        session = InterviewSession(
            profile_id=profile.id,
            level=level,
            focus_categories=payload.focus_categories,
            persona=payload.persona,
            mode=payload.mode,
            started_at=datetime.now(UTC),
            planned_questions=payload.question_count,
            adaptive_state={
                "asked_slugs": [],
                # Pressure starts at the middle of the band and moves with the
                # candidate: nail two and it climbs, miss two and it backs off.
                "difficulty": sum(LEVEL_TIER_RANGE[level]) // 2,
                "followups_on_thread": 0,
                "consecutive_strong": 0,
                "consecutive_weak": 0,
            },
        )
        self.session.add(session)
        await self.session.flush()

        turn = await self._next_question(session, profile)
        if turn is None:
            raise NotFoundError("No interview questions are available for that configuration.")
        return await self.get_session(session.id, profile.id)

    async def get_session(
        self, session_id: uuid.UUID, profile_id: uuid.UUID
    ) -> InterviewSessionOut:
        row = (
            await self.session.execute(
                select(InterviewSession).where(
                    InterviewSession.id == session_id, InterviewSession.profile_id == profile_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Interview session not found.")

        turns = [self._turn_out(t, row) for t in row.turns]
        current = next((t for t in turns if not t.answered), None)
        return InterviewSessionOut(
            id=row.id,
            level=row.level,
            mode=row.mode,
            persona=row.persona,
            status=row.status,
            focus_categories=row.focus_categories,
            planned_questions=row.planned_questions,
            questions_asked=row.questions_asked,
            started_at=row.started_at,
            completed_at=row.completed_at,
            current_turn=current,
            turns=turns,
        )

    def _turn_out(self, turn: InterviewTurn, session: InterviewSession) -> InterviewTurnOut:
        return InterviewTurnOut(
            position=turn.position,
            prompt=turn.prompt,
            context=turn.context,
            options=[{"id": o["id"], "text": o["text"]} for o in (turn.options or [])],
            kind="mcq" if turn.options else "explain",
            tier=turn.tier,
            category=turn.category,
            is_followup=turn.is_followup,
            parent_position=turn.parent_position,
            time_limit_seconds=(
                PRESSURE_SECONDS.get(turn.tier, 180) if session.mode == "pressure" else None
            ),
            answered=turn.answered_at is not None,
            score=turn.score,
            interviewer_reaction=turn.interviewer_reaction,
        )

    # ── Question selection ────────────────────────────────────────────────
    async def _next_question(
        self, session: InterviewSession, profile: PlayerProfile
    ) -> InterviewTurn | None:
        state = dict(session.adaptive_state or {})
        asked: list[str] = list(state.get("asked_slugs", []))
        difficulty = int(state.get("difficulty", 5))
        lo, hi = LEVEL_TIER_RANGE[session.level]
        tier = max(lo, min(hi, difficulty))

        stmt = select(Question).where(
            Question.tier.between(max(1, tier - 1), min(10, tier + 1)),
            Question.slug.not_in(asked or {""}),
        )
        if session.focus_categories:
            stmt = stmt.where(Question.category.in_(session.focus_categories))

        question = (
            await self.session.execute(stmt.order_by(func.random()).limit(1))
        ).scalar_one_or_none()
        if question is None:
            # Widen before giving up: a narrow focus should not end the
            # interview after three questions.
            question = (
                await self.session.execute(
                    select(Question)
                    .where(Question.slug.not_in(asked or {""}))
                    .order_by(func.random())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if question is None:
            return None

        turn = InterviewTurn(
            session_id=session.id,
            position=session.questions_asked,
            question_slug=question.slug,
            prompt=question.prompt,
            context=question.context,
            options=[{"id": o["id"], "text": o["text"]} for o in question.options],
            tier=question.tier,
            category=question.category,
        )
        self.session.add(turn)
        session.questions_asked += 1
        state["asked_slugs"] = [*asked, question.slug]
        state["followups_on_thread"] = 0
        session.adaptive_state = state
        await self.session.flush()
        return turn

    async def _make_followup(
        self, session: InterviewSession, parent: InterviewTurn, question: Question, score: float
    ) -> InterviewTurn | None:
        state = dict(session.adaptive_state or {})
        if state.get("followups_on_thread", 0) >= MAX_FOLLOWUPS_PER_THREAD:
            return None
        followups = question.followups or []
        idx = int(state.get("followups_on_thread", 0))
        if idx >= len(followups):
            return None
        spec = followups[idx]
        prompt = spec if isinstance(spec, str) else spec.get("prompt", "")
        if not prompt:
            return None

        turn = InterviewTurn(
            session_id=session.id,
            position=session.questions_asked,
            question_slug=question.slug,
            parent_position=parent.position,
            is_followup=True,
            prompt=prompt,
            tier=min(10, parent.tier + 1),
            category=parent.category,
        )
        self.session.add(turn)
        session.questions_asked += 1
        state["followups_on_thread"] = idx + 1
        session.adaptive_state = state
        await self.session.flush()
        return turn

    # ── Answering ─────────────────────────────────────────────────────────
    async def answer(
        self, profile: PlayerProfile, session_id: uuid.UUID, payload: InterviewAnswerRequest
    ) -> InterviewAnswerResponse:
        session = (
            await self.session.execute(
                select(InterviewSession).where(
                    InterviewSession.id == session_id, InterviewSession.profile_id == profile.id
                )
            )
        ).scalar_one_or_none()
        if session is None:
            raise NotFoundError("Interview session not found.")
        if session.status != "in_progress":
            raise ConflictError("This interview has already finished.")

        turn = next((t for t in session.turns if t.position == payload.position), None)
        if turn is None:
            raise NotFoundError(f"No question at position {payload.position}.")
        if turn.answered_at is not None:
            raise ConflictError("That question has already been answered.")

        question = None
        if turn.question_slug:
            question = (
                await self.session.execute(
                    select(Question).where(Question.slug == turn.question_slug)
                )
            ).scalar_one_or_none()

        feedback = self._grade_turn(turn, question, payload)

        turn.answer_text = payload.answer_text[:20_000]
        turn.selected_option_ids = payload.selected_option_ids
        turn.answered_at = datetime.now(UTC)
        turn.elapsed_seconds = payload.elapsed_seconds
        turn.score = feedback.score
        turn.dimension_scores = feedback.dimension_scores
        turn.missing_points = feedback.missing_points
        turn.interviewer_reaction = feedback.interviewer_reaction
        turn.graded_by = feedback.graded_by

        if question is not None:
            self.session.add(
                QuestionAttempt(
                    profile_id=profile.id,
                    question_slug=question.slug,
                    interview_session_id=session.id,
                    answer_text=payload.answer_text[:20_000],
                    selected_option_ids=payload.selected_option_ids,
                    correct=feedback.score >= 6.0,
                    score=feedback.score,
                    score_breakdown=feedback.dimension_scores,
                    missing_points=feedback.missing_points,
                    feedback=feedback.interviewer_reaction,
                    confidence=payload.confidence,
                    elapsed_seconds=payload.elapsed_seconds,
                    graded_by=feedback.graded_by,
                )
            )
            await self.retention.record_review(
                profile.id,
                question.concept_slugs or [],
                score=feedback.score / 10.0,
                tier=question.tier,
                now=datetime.now(UTC),
                confidence=payload.confidence,
            )

        # ── adapt ─────────────────────────────────────────────────────────
        state = dict(session.adaptive_state or {})
        if feedback.score >= FOLLOWUP_THRESHOLD:
            state["consecutive_strong"] = int(state.get("consecutive_strong", 0)) + 1
            state["consecutive_weak"] = 0
        else:
            state["consecutive_weak"] = int(state.get("consecutive_weak", 0)) + 1
            state["consecutive_strong"] = 0
        if state["consecutive_strong"] >= 2:
            state["difficulty"] = min(10, int(state.get("difficulty", 5)) + 1)
            state["consecutive_strong"] = 0
        elif state["consecutive_weak"] >= 2:
            state["difficulty"] = max(1, int(state.get("difficulty", 5)) - 1)
            state["consecutive_weak"] = 0
        session.adaptive_state = state

        next_turn: InterviewTurn | None = None
        complete = False
        if session.questions_asked >= session.planned_questions:
            complete = True
        elif (
            question is not None
            and feedback.score >= FOLLOWUP_THRESHOLD
            and not turn.is_followup
            and (question.followups or [])
        ):
            next_turn = await self._make_followup(session, turn, question, feedback.score)

        if next_turn is None and not complete:
            next_turn = await self._next_question(session, profile)
            complete = next_turn is None

        progression = None
        if question is not None:
            grants = compute_award(
                AwardContext(
                    tier=DifficultyTier(min(10, max(1, turn.tier))),
                    passed=feedback.score >= 6.0,
                    elapsed_seconds=payload.elapsed_seconds or None,
                    par_seconds=float(question.par_seconds),
                    explanation_score=feedback.dimension_scores.get("depth"),
                    architecture_score=feedback.dimension_scores.get("architecture_thinking"),
                    streak_days=profile.current_streak,
                )
            )
            result = await self.progression.award(
                profile,
                grants,
                skill_slug="interview_skills",
                reference_type="interview",
                reference_slug=str(session.id),
            )
            progression = result.model_dump()
            profile.questions_answered += 1

        if complete:
            await self._finalise(session, profile)

        return InterviewAnswerResponse(
            feedback=feedback,
            next_turn=self._turn_out(next_turn, session) if next_turn else None,
            session_complete=complete,
            progression=progression,
        )

    def _grade_turn(
        self, turn: InterviewTurn, question: Question | None, payload: InterviewAnswerRequest
    ) -> InterviewFeedbackOut:
        if turn.options:
            _correct, normalised, _ids = grade_mcq(
                payload.selected_option_ids, question.options if question else []
            )
            score = round(normalised * 10, 2)
            dims = dict.fromkeys(DIMENSIONS, normalised)
            missing = [
                o.get("why", "")
                for o in (question.options if question else [])
                if o.get("correct") and o["id"] not in payload.selected_option_ids
            ]
        else:
            rubric = (question.rubric if question else []) or []
            grade = grade_free_text(
                payload.answer_text,
                rubric,
                tier=turn.tier,
                expected_answer=question.expected_answer if question else "",
            )
            score = grade.score
            dims = grade.dimension_scores
            missing = grade.missing_points

        return InterviewFeedbackOut(
            score=score,
            dimension_scores=dims,
            hit_points=[],
            missing_points=[m for m in missing if m],
            interviewer_reaction=_reaction(score, turn.is_followup),
            ideal_answer=question.ideal_senior_answer if question else None,
            common_wrong_answer=question.common_wrong_answer if question else None,
            level_gap=level_gap_feedback(score, turn.tier),
            graded_by="rubric",
        )

    # ── Debrief ───────────────────────────────────────────────────────────
    async def _finalise(self, session: InterviewSession, profile: PlayerProfile) -> None:
        answered = [t for t in session.turns if t.score is not None]
        if not answered:
            session.status = "abandoned"
            session.completed_at = datetime.now(UTC)
            return

        overall = round(sum(t.score or 0 for t in answered) / len(answered), 2)
        dims: dict[str, float] = {}
        for dim in DIMENSIONS:
            values = [t.dimension_scores.get(dim) for t in answered if t.dimension_scores]
            values = [v for v in values if v is not None]
            dims[dim] = round(sum(values) / len(values), 4) if values else 0.0

        strengths = [d for d, v in sorted(dims.items(), key=lambda kv: -kv[1])[:2] if v >= 0.6]
        gaps = [d for d, v in sorted(dims.items(), key=lambda kv: kv[1])[:3] if v < 0.6]

        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        session.overall_score = overall
        session.dimension_scores = dims
        session.verdict = verdict_for_score(overall)
        session.strengths = [_dim_label(d) for d in strengths]
        session.gaps = [_dim_label(d) for d in gaps]
        session.summary = _summary(overall, session.level, dims)

        await self.progression.award(
            profile,
            self._session_grants(overall, session.level),
            skill_slug="interview_skills",
            reference_type="interview_session",
            reference_slug=str(session.id),
        )
        self.session.add(
            LearningEvent(
                profile_id=profile.id,
                event_type="interview_completed",
                skill_slug="interview_skills",
                score=overall / 10.0,
                payload={
                    "level": session.level,
                    "verdict": session.verdict,
                    "questions": len(answered),
                    "dimensions": dims,
                },
            )
        )
        log.info(
            "interview.completed",
            profile_id=str(profile.id),
            level=session.level,
            score=overall,
            verdict=session.verdict,
        )

    @staticmethod
    def _session_grants(overall: float, level: str) -> list:
        from app.game.xp.engine import XPGrant

        level_bonus = {"junior": 1.0, "mid": 1.3, "senior": 1.8, "staff": 2.4, "principal": 3.0}
        base = int(80 * level_bonus.get(level, 1.0) * (overall / 10.0))
        return [
            XPGrant(
                XPSource.INTERVIEW_ANSWER,
                max(20, base),
                f"{level.title()} interview complete — {overall:.1f}/10",
            )
        ]

    async def report(self, profile: PlayerProfile, session_id: uuid.UUID) -> InterviewReportOut:
        row = (
            await self.session.execute(
                select(InterviewSession).where(
                    InterviewSession.id == session_id, InterviewSession.profile_id == profile.id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Interview session not found.")
        if row.status == "in_progress":
            raise ValidationFailedError("This interview is still in progress.")

        answered = [t for t in row.turns if t.score is not None]
        # Categories the candidate scored below the hire bar in become the
        # study plan attached to the report — a debrief without next steps is
        # just a number.
        weak_categories = sorted(
            {t.category for t in answered if (t.score or 0) < 6.0 and t.category}
        )
        recommended_concepts = await self._concepts_for_categories(weak_categories)
        return InterviewReportOut(
            session_id=row.id,
            level=row.level,
            overall_score=row.overall_score or 0.0,
            verdict=row.verdict or "no_hire",
            dimension_scores=row.dimension_scores,
            summary=row.summary,
            strengths=row.strengths,
            gaps=row.gaps,
            per_question=[
                {
                    "position": t.position,
                    "prompt": t.prompt,
                    "tier": t.tier,
                    "category": t.category,
                    "is_followup": t.is_followup,
                    "score": t.score,
                    "elapsed_seconds": t.elapsed_seconds,
                    "missing_points": t.missing_points,
                    "reaction": t.interviewer_reaction,
                    "answer": t.answer_text,
                }
                for t in sorted(row.turns, key=lambda x: x.position)
            ],
            recommended_concepts=recommended_concepts,
            recommended_missions=weak_categories,
            interview_readiness=round((row.overall_score or 0) / 10.0, 4),
            progression=None,
        )

    async def _concepts_for_categories(self, categories: list[str]) -> list[str]:
        if not categories:
            return []
        from app.models.content import Concept

        rows = (
            await self.session.execute(
                select(Concept.slug)
                .where(Concept.category.in_(categories))
                .order_by(Concept.base_difficulty)
                .limit(8)
            )
        ).all()
        return [r[0] for r in rows]

    async def abandon(self, profile: PlayerProfile, session_id: uuid.UUID) -> None:
        row = (
            await self.session.execute(
                select(InterviewSession).where(
                    InterviewSession.id == session_id, InterviewSession.profile_id == profile.id
                )
            )
        ).scalar_one_or_none()
        if row and row.status == "in_progress":
            await self._finalise(row, profile)


def _reaction(score: float, is_followup: bool) -> str:
    """What the interviewer says next. Tone matters: an interviewer who says
    'wrong' teaches nothing, and one who says 'great!' to everything is noise."""
    if score >= 8.5:
        return (
            "That is the answer I was looking for — mechanism, trade-off and a concrete case."
            if not is_followup
            else "Good. You went deeper without being pushed. Let's move on."
        )
    if score >= 6.5:
        return "Solid. I'd like to push on one part of that."
    if score >= 4.5:
        return "You're circling the right idea, but I'm not hearing the mechanism yet."
    if score >= 2:
        return "Hmm. Let me reframe, because I don't think we're talking about the same thing."
    return "Let's take a step back — I'd rather you say you don't know than guess."


def _dim_label(dim: str) -> str:
    return dim.replace("_", " ").title()


def _summary(overall: float, level: str, dims: dict[str, float]) -> str:
    verdict = verdict_for_score(overall).replace("_", " ")
    weakest = min(dims.items(), key=lambda kv: kv[1])[0] if dims else "depth"
    strongest = max(dims.items(), key=lambda kv: kv[1])[0] if dims else "correctness"
    return (
        f"{overall:.1f}/10 at {level} level — {verdict}. "
        f"Strongest signal: {_dim_label(strongest)}. "
        f"Weakest: {_dim_label(weakest)}. "
        f"{'Focus your next sessions there.' if overall < 8 else 'Keep the bar where it is.'}"
    )


def level_for_profile(level: int) -> InterviewLevel:
    if level >= 84:
        return InterviewLevel.PRINCIPAL
    if level >= 52:
        return InterviewLevel.STAFF
    if level >= 22:
        return InterviewLevel.SENIOR
    if level >= 8:
        return InterviewLevel.MID
    return InterviewLevel.JUNIOR
