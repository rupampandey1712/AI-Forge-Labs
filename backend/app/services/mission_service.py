"""Mission lifecycle: start, submit a step, complete, debrief, journal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.domain.enums import AttemptStatus, DifficultyTier, XPSource
from app.game.grading.rubric import grade_free_text
from app.game.xp.engine import AwardContext, XPGrant, compute_award
from app.models.content import Mission, MissionStep
from app.models.progress import JournalEntry, LearningEvent, MissionAttempt
from app.models.user import PlayerProfile
from app.repositories.player import MissionAttemptRepository
from app.schemas.content import (
    GradeOut,
    JournalSubmission,
    MissionDetail,
    MissionStepSubmission,
)
from app.services.content_service import ContentService
from app.services.grading_service import GradingService
from app.services.progression_service import ProgressionService
from app.services.retention_service import RetentionService

log = get_logger(__name__)

#: A mission passes on the MEAN of its required steps, not on every step being
#: binary-passed. Rubric-graded steps are continuous by nature, so an
#: all-or-nothing gate would fail a player who demonstrably understood the
#: material because one rubric point went unmentioned. The floor stops that
#: leniency from letting a completely missed step slide.
MISSION_PASS_MEAN = 0.6
MISSION_STEP_FLOOR = 0.3


class MissionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.attempts = MissionAttemptRepository(session)
        self.content = ContentService(session)
        self.grading = GradingService(session)
        self.progression = ProgressionService(session)
        self.retention = RetentionService(session)

    async def start(self, profile: PlayerProfile, slug: str) -> MissionDetail:
        detail = await self.content.get_mission(slug, profile)  # also enforces locking
        existing = await self.attempts.open_attempt(profile.id, slug)
        if existing is None:
            attempt = MissionAttempt(
                profile_id=profile.id,
                mission_slug=slug,
                attempt_number=await self.attempts.next_attempt_number(profile.id, slug),
                status=AttemptStatus.IN_PROGRESS.value,
                started_at=datetime.now(UTC),
            )
            self.session.add(attempt)
            await self.session.flush()
            detail.attempt_id = attempt.id

            # Introducing the concepts now (rather than on completion) means an
            # abandoned mission still schedules a first review — exposure counts.
            mission = await self.content.get_mission_model(slug)
            await self.retention.introduce(profile.id, mission.concept_slugs or [])
            self.session.add(
                LearningEvent(
                    profile_id=profile.id,
                    event_type="mission_started",
                    skill_slug=mission.skill_slug,
                    category=mission.category,
                    tier=mission.tier,
                    payload={"mission_slug": slug},
                )
            )
        else:
            detail.attempt_id = existing.id
        self.progression.touch_streak(profile)
        return detail

    async def submit_step(
        self, profile: PlayerProfile, slug: str, payload: MissionStepSubmission
    ) -> GradeOut:
        mission = await self.content.get_mission_model(slug)
        attempt = await self.attempts.open_attempt(profile.id, slug)
        if attempt is None:
            raise ConflictError("Start the mission before submitting a step.")

        step = next((s for s in mission.steps if s.position == payload.position), None)
        if step is None:
            raise NotFoundError(f"Mission '{slug}' has no step at position {payload.position}.")

        result = await self._grade_step(profile, mission, step, payload, attempt.id)

        # JSON columns need reassignment for SQLAlchemy to see the change.
        results = dict(attempt.step_results or {})
        results[str(step.position)] = {
            "status": "passed" if result.passed else "failed",
            "score": result.score,
            "at": datetime.now(UTC).isoformat(),
        }
        attempt.step_results = results
        attempt.hints_used += 0
        return result

    async def _grade_step(
        self,
        profile: PlayerProfile,
        mission: Mission,
        step: MissionStep,
        payload: MissionStepSubmission,
        attempt_id: uuid.UUID,
    ) -> GradeOut:
        """Dispatch on step type.

        Step XP is awarded at *mission* completion, not per step (``award_xp
        =False`` below). Otherwise a five-step mission would pay out five times
        and completing missions would be strictly worse than farming steps.
        """
        match step.step_type:
            case "challenge":
                if payload.challenge is None or not step.challenge_slug:
                    raise ValidationFailedError("This step expects a code submission.")
                challenge = await self.content.get_challenge_model(step.challenge_slug)
                return await self.grading.submit_challenge(
                    profile,
                    challenge,
                    payload.challenge,
                    mission_attempt_id=attempt_id,
                    award_xp=False,
                )
            case "question":
                if payload.question is None or not step.question_slug:
                    raise ValidationFailedError("This step expects an answer.")
                question = await self.content.get_question_model(step.question_slug)
                return await self.grading.submit_question(
                    profile,
                    question,
                    payload.question,
                    mission_attempt_id=attempt_id,
                    award_xp=False,
                )
            case "explanation" | "review" | "design":
                return await self._grade_free_form(profile, mission, step, payload)
            case "journal":
                return GradeOut(
                    passed=True,
                    score=1.0,
                    headline="Journal entry recorded",
                    what_happened="Reflection saved. You will see this again when it matters.",
                )
            case _:
                raise ValidationFailedError(f"Unsupported step type '{step.step_type}'.")

    async def _grade_free_form(
        self,
        profile: PlayerProfile,
        mission: Mission,
        step: MissionStep,
        payload: MissionStepSubmission,
    ) -> GradeOut:
        text = payload.free_text or ""
        if payload.design:
            # A design step submits a graph; we grade the written rationale plus
            # a flattened description of the components, so naming the right
            # pieces counts even when the prose is terse.
            text = f"{text}\n" + " ".join(
                str(n.get("type", "")) + " " + str(n.get("label", ""))
                for n in payload.design.get("nodes", [])
            )
        if payload.review_comments:
            text = f"{text}\n" + " ".join(c.get("comment", "") for c in payload.review_comments)

        rubric = step.config.get("rubric", [])
        grade = grade_free_text(text, rubric, tier=mission.tier)
        passed = grade.score >= float(step.config.get("pass_score", 5.5))

        await self.retention.record_review(
            profile.id,
            step.config.get("concept_slugs") or mission.concept_slugs or [],
            score=grade.normalised,
            tier=mission.tier,
            now=datetime.now(UTC),
        )
        return GradeOut(
            passed=passed,
            score=grade.normalised,
            headline="✅ Reasoning accepted" if passed else "Your reasoning needs more depth",
            what_happened=(
                "Strong: you covered the points that matter."
                if passed
                else "The graders look for mechanism, trade-offs and failure modes."
            ),
            missing_points=grade.missing_points,
            explanation_score=grade.normalised,
            explanation_feedback=None,
            reveal_solution=not passed,
            solution=step.config.get("model_answer"),
        )

    async def complete(self, profile: PlayerProfile, slug: str) -> dict[str, Any]:
        mission = await self.content.get_mission_model(slug)
        attempt = await self.attempts.open_attempt(profile.id, slug)
        if attempt is None:
            raise ConflictError("No mission in progress.")

        results = attempt.step_results or {}
        required = [s for s in mission.steps if s.required]
        graded = [results.get(str(s.position)) for s in required]
        missing = [s.position for s, r in zip(required, graded, strict=False) if r is None]
        if missing:
            raise ValidationFailedError(
                "Some required steps are not complete.", details={"missing_steps": missing}
            )

        scores = [float(r["score"]) for r in graded if r]
        score = round(sum(scores) / len(scores), 4) if scores else 0.0
        passed = bool(scores) and score >= MISSION_PASS_MEAN and min(scores) >= MISSION_STEP_FLOOR

        now = datetime.now(UTC)
        attempt.status = AttemptStatus.PASSED.value if passed else AttemptStatus.FAILED.value
        attempt.completed_at = now
        attempt.elapsed_seconds = int((now - attempt.started_at).total_seconds())
        attempt.score = score

        ctx = AwardContext(
            tier=DifficultyTier(min(10, max(1, mission.tier))),
            passed=passed,
            first_attempt=attempt.attempt_number == 1,
            attempts=attempt.attempt_number,
            elapsed_seconds=attempt.elapsed_seconds,
            par_seconds=float(mission.par_seconds),
            streak_days=profile.current_streak,
            is_boss=mission.is_boss,
            is_retention_repair=attempt.is_retention_repair,
        )
        grants = compute_award(ctx)
        if mission.xp_multiplier != 1.0:
            grants = [
                XPGrant(g.source, int(g.amount * mission.xp_multiplier), g.reason, g.metadata)
                for g in grants
            ]
        grants.append(
            XPGrant(XPSource.MISSION_COMPLETE, 0 if not passed else 25, f"Mission: {mission.title}")
        )

        progression = await self.progression.award(
            profile,
            grants,
            skill_slug=mission.skill_slug,
            reference_type="mission",
            reference_slug=mission.slug,
            now=now,
        )
        attempt.xp_awarded = progression.xp_gained
        attempt.coins_awarded = progression.coins_gained

        if passed:
            profile.missions_completed += 1
            if mission.is_boss:
                profile.bosses_defeated += 1
            if mission.kind == "incident":
                profile.incidents_resolved += 1

        self.session.add(
            LearningEvent(
                profile_id=profile.id,
                event_type="mission_completed",
                skill_slug=mission.skill_slug,
                category=mission.category,
                tier=mission.tier,
                score=score,
                elapsed_seconds=attempt.elapsed_seconds,
                payload={"mission_slug": slug, "passed": passed, "is_boss": mission.is_boss},
            )
        )
        log.info(
            "mission.completed",
            profile_id=str(profile.id),
            mission=slug,
            passed=passed,
            score=score,
            xp=progression.xp_gained,
        )
        return {
            "passed": passed,
            "score": score,
            "elapsed_seconds": attempt.elapsed_seconds,
            "progression": progression.model_dump(),
            "debrief": mission.debrief,
            "journal_prompt": {
                "what_i_learned": "What did you learn?",
                "mistake_made": "What mistake did you make?",
                "would_do_differently": "What would you do differently?",
            },
        }

    async def abandon(self, profile: PlayerProfile, slug: str) -> None:
        attempt = await self.attempts.open_attempt(profile.id, slug)
        if attempt:
            attempt.status = AttemptStatus.ABANDONED.value
            attempt.completed_at = datetime.now(UTC)

    # ── Engineering journal (spec §43) ────────────────────────────────────
    async def add_journal_entry(
        self, profile: PlayerProfile, payload: JournalSubmission
    ) -> JournalEntry:
        entry = JournalEntry(
            profile_id=profile.id,
            context_slug=payload.context_slug,
            what_i_learned=payload.what_i_learned,
            mistake_made=payload.mistake_made,
            would_do_differently=payload.would_do_differently,
            confidence=payload.confidence,
            concept_slugs=payload.concept_slugs,
        )
        self.session.add(entry)
        if any((payload.what_i_learned, payload.mistake_made, payload.would_do_differently)):
            await self.progression.award(
                profile,
                [XPGrant(XPSource.JOURNAL_ENTRY, 15, "Reflected on the work")],
                reference_type="journal",
            )
        return entry
