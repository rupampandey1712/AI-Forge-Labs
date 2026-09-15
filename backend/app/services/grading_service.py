"""End-to-end grading for code challenges and questions.

This is the spine of the game loop. One submission triggers, in order:

    sandbox execution -> test grading -> mistake detection -> explanation
    grading -> XP award -> retention update -> mistake database -> learning
    event -> failure-as-incident framing

Keeping it in one service (rather than scattering it across routes) is what
guarantees those steps always happen together. A challenge graded without a
retention update would silently break the forgetting model — the single most
important feature in the product — and it would break quietly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import AttemptStatus, DifficultyTier, Severity
from app.game.grading.mistakes import DetectedMistake, summarise
from app.game.grading.rubric import grade_free_text, grade_mcq
from app.game.xp.engine import AwardContext, compute_award
from app.models.content import Challenge, Question
from app.models.progress import (
    ChallengeAttempt,
    LearningEvent,
    MistakeRecord,
    QuestionAttempt,
)
from app.models.user import PlayerProfile
from app.repositories.player import ChallengeAttemptRepository, MistakeRepository
from app.sandbox.protocol import ExecStatus, ExecutionResult, TestCase
from app.sandbox.service import SandboxService, get_sandbox_service
from app.schemas.content import (
    ChallengeSubmission,
    GradeOut,
    QuestionSubmission,
    TestResultOut,
)
from app.services.progression_service import ProgressionService
from app.services.retention_service import RetentionService

log = get_logger(__name__)

#: Threshold at which a free-text answer counts as "you understand this" in a
#: LEARNING context. Deliberately lower than the interview hire bar (6.5 in
#: ``rubric.verdict_for_score``): a 5/10 answer has the right idea and is worth
#: crediting while still leaving room to grow. Conflating the two bars made
#: mission steps unpassable with genuinely good answers.
QUESTION_PASS_SCORE = 5.0

#: Consecutive clean attempts on a pattern before its mistake record closes.
MISTAKE_CLEAN_STREAK_TO_RESOLVE = 3
#: Reveal the reference solution only after this many genuine attempts, so the
#: player struggles productively first (spec §58) but never gets stuck forever.
REVEAL_SOLUTION_AFTER_ATTEMPTS = 4


class GradingService:
    def __init__(self, session: AsyncSession, sandbox: SandboxService | None = None) -> None:
        self.session = session
        self.sandbox = sandbox or get_sandbox_service()
        self.attempts = ChallengeAttemptRepository(session)
        self.mistakes = MistakeRepository(session)
        self.progression = ProgressionService(session)
        self.retention = RetentionService(session)

    # ── Code challenges ───────────────────────────────────────────────────
    async def run_challenge(
        self, challenge: Challenge, code: str, *, grade: bool
    ) -> ExecutionResult:
        """Execute a submission. ``grade=False`` runs only the visible tests."""
        raw_tests = (
            challenge.tests if grade else [t for t in challenge.tests if not t.get("hidden")]
        )
        tests = [TestCase.from_dict(t) for t in raw_tests]
        return await self.sandbox.run(
            code,
            tests=tests,
            setup_code=challenge.setup_code,
            timeout_seconds=challenge.time_limit_seconds,
            memory_mb=challenge.memory_limit_mb,
        )

    async def submit_challenge(
        self,
        profile: PlayerProfile,
        challenge: Challenge,
        payload: ChallengeSubmission,
        *,
        mission_attempt_id: uuid.UUID | None = None,
        is_daily: bool = False,
        is_retention_repair: bool = False,
        award_xp: bool = True,
    ) -> GradeOut:
        now = datetime.now(UTC)
        attempt_no = (await self.attempts.attempts_for(profile.id, challenge.slug)) + 1
        already_solved = await self.attempts.solved(profile.id, challenge.slug)

        result = await self.run_challenge(challenge, payload.code, grade=not payload.run_only)

        if payload.run_only:
            # A scratch run: feedback only, no attempt row, no XP, no retention
            # side effects. Players must be able to experiment without the
            # forgetting model concluding they failed.
            return self._grade_out_from_execution(result, challenge, scratch=True)

        mistakes = summarise(payload.code, category_hint=challenge.category)
        speedup = await self._measure_speedup(challenge, payload.code)

        passed = result.passed
        score = result.score if result.tests_total else (1.0 if passed else 0.0)

        explanation_score = None
        explanation_feedback = None
        missing_points: list[str] = []
        if payload.explanation:
            rubric = [
                p if isinstance(p, dict) else {"point": str(p)}
                for p in (challenge.explanation_prompts or [])
                if isinstance(p, dict)
            ]
            grade = grade_free_text(
                payload.explanation,
                rubric,
                tier=challenge.tier,
                expected_answer=challenge.solution_explanation,
            )
            explanation_score = round(grade.normalised, 4)
            missing_points = grade.missing_points
            explanation_feedback = _explanation_feedback(grade.score, grade.missing_points)

        # Complexity answers are graded strictly: "O(n)" vs "O(n log n)" is not
        # a matter of opinion, and partial credit here would teach vagueness.
        complexity_ok = None
        if payload.complexity and challenge.expected_complexity:
            complexity_ok = _normalise_complexity(payload.complexity) == _normalise_complexity(
                challenge.expected_complexity
            )

        attempt = ChallengeAttempt(
            profile_id=profile.id,
            challenge_slug=challenge.slug,
            mission_attempt_id=mission_attempt_id,
            attempt_number=attempt_no,
            status=AttemptStatus.PASSED.value if passed else AttemptStatus.FAILED.value,
            submitted_code=payload.code[:100_000],
            tests_passed=result.tests_passed,
            tests_total=result.tests_total,
            score=score,
            runtime_ms=result.duration_ms,
            stdout=result.stdout[:20_000],
            stderr=result.stderr[:20_000],
            test_results=[_outcome_dict(o) for o in result.outcomes],
            explanation=payload.explanation,
            explanation_score=explanation_score,
            complexity_answer=payload.complexity,
            code_quality_score=mistakes.code_quality_score,
            speedup_factor=speedup,
            hints_used=payload.hints_used,
            elapsed_seconds=payload.elapsed_seconds,
        )
        self.session.add(attempt)

        out = self._grade_out_from_execution(result, challenge)
        out.explanation_score = explanation_score
        out.explanation_feedback = explanation_feedback
        out.missing_points = missing_points
        out.speedup_factor = speedup
        out.detected_mistakes = [m.to_dict() for m in mistakes.detected]

        if not passed:
            out.reveal_solution = attempt_no >= REVEAL_SOLUTION_AFTER_ATTEMPTS
            if out.reveal_solution:
                out.solution = challenge.reference_solution
                out.solution_explanation = challenge.solution_explanation
            out.hint = _next_hint(challenge, payload.hints_used)

        await self._record_mistakes(profile, mistakes.detected, now=now, passed=passed)

        # ── side effects that make the game a game ────────────────────────
        # ORDER MATTERS: the denormalised counters must be updated *before*
        # `award()` runs, because award() evaluates badge/achievement criteria
        # against them. Incrementing afterwards made every count-based unlock
        # fire one submission late.
        if passed and not already_solved:
            profile.challenges_passed += 1
        profile.total_practice_seconds += min(payload.elapsed_seconds, 7200)

        if award_xp:
            ctx = AwardContext(
                tier=DifficultyTier(min(10, max(1, challenge.tier))),
                passed=passed,
                first_attempt=attempt_no == 1 and not already_solved,
                attempts=attempt_no,
                elapsed_seconds=payload.elapsed_seconds or None,
                par_seconds=float(challenge.par_seconds),
                explanation_score=explanation_score,
                code_quality_score=mistakes.code_quality_score if passed else None,
                optimization_factor=speedup,
                streak_days=profile.current_streak,
                is_boss=False,
                is_retention_repair=is_retention_repair,
            )
            progression = await self.progression.award(
                profile,
                compute_award(ctx),
                skill_slug=challenge.skill_slug,
                reference_type="challenge",
                reference_slug=challenge.slug,
                now=now,
            )
            out.progression = progression.model_dump()

        schedules = await self.retention.record_review(
            profile.id,
            challenge.concept_slugs or [],
            score=score,
            tier=challenge.tier,
            now=now,
            hints_used=payload.hints_used,
            confidence=payload.confidence,
            elapsed_seconds=payload.elapsed_seconds,
            par_seconds=challenge.par_seconds,
        )
        if schedules:
            out.next_review_at = min(s.due_at for s in schedules)
            out.mastery_delta = {
                s.concept_slug: {
                    "before": s.mastery_before,
                    "after": s.mastery_after,
                    "next_review_days": round(s.new_interval_days, 1),
                }
                for s in schedules
            }

        self.session.add(
            LearningEvent(
                profile_id=profile.id,
                event_type="challenge_submitted",
                skill_slug=challenge.skill_slug,
                category=challenge.category,
                tier=challenge.tier,
                score=score,
                elapsed_seconds=payload.elapsed_seconds,
                concept_slug=(challenge.concept_slugs or [None])[0],
                payload={
                    "challenge_slug": challenge.slug,
                    "passed": passed,
                    "attempt": attempt_no,
                    "hints_used": payload.hints_used,
                    "mistakes": [m.pattern for m in mistakes.detected],
                    "complexity_correct": complexity_ok,
                    "is_daily": is_daily,
                },
            )
        )
        return out

    async def _measure_speedup(self, challenge: Challenge, code: str) -> float | None:
        if not challenge.baseline_code:
            return None
        _base, _cand, speedup = await self.sandbox.benchmark_pair(
            challenge.baseline_code, code, repeat=3, setup_code=challenge.setup_code
        )
        return speedup

    def _grade_out_from_execution(
        self, result: ExecutionResult, challenge: Challenge, *, scratch: bool = False
    ) -> GradeOut:
        passed = result.passed
        headline, what_happened, root_cause = _frame_failure(result, challenge)
        return GradeOut(
            passed=passed,
            score=result.score if result.tests_total else (1.0 if passed else 0.0),
            points=result.points,
            max_points=result.max_points,
            tests_passed=result.tests_passed,
            tests_total=result.tests_total,
            test_results=[
                TestResultOut(
                    name=o.name,
                    passed=o.passed,
                    hidden=o.hidden,
                    expected=o.expected,
                    actual=o.actual,
                    message=o.message,
                    duration_ms=o.duration_ms,
                )
                for o in result.outcomes
            ],
            stdout=result.stdout,
            stderr=result.stderr,
            runtime_ms=result.duration_ms,
            timed_out=result.timed_out,
            headline="✅ All tests green" if passed else headline,
            what_happened="" if passed else what_happened,
            root_cause=None if passed else root_cause,
            can_retry=not scratch,
        )

    # ── Questions ─────────────────────────────────────────────────────────
    async def submit_question(
        self,
        profile: PlayerProfile,
        question: Question,
        payload: QuestionSubmission,
        *,
        mission_attempt_id: uuid.UUID | None = None,
        interview_session_id: uuid.UUID | None = None,
        award_xp: bool = True,
    ) -> GradeOut:
        now = datetime.now(UTC)
        is_choice = question.kind in ("mcq", "multi_select")

        if is_choice:
            correct, normalised, correct_ids = grade_mcq(
                payload.selected_option_ids, question.options
            )
            score_10 = round(normalised * 10, 2)
            dimension_scores: dict[str, float] = {"correctness": normalised}
            missing = [
                o["why"]
                for o in question.options
                if o.get("correct") and o["id"] not in payload.selected_option_ids and o.get("why")
            ]
            feedback = _mcq_feedback(question, payload.selected_option_ids, correct)
        else:
            grade = grade_free_text(
                payload.answer_text,
                question.rubric,
                tier=question.tier,
                expected_answer=question.expected_answer,
            )
            normalised = grade.normalised
            score_10 = grade.score
            correct = score_10 >= QUESTION_PASS_SCORE
            dimension_scores = grade.dimension_scores
            missing = grade.missing_points
            feedback = _explanation_feedback(score_10, grade.missing_points)
            correct_ids = []

        self.session.add(
            QuestionAttempt(
                profile_id=profile.id,
                question_slug=question.slug,
                interview_session_id=interview_session_id,
                mission_attempt_id=mission_attempt_id,
                answer_text=payload.answer_text[:20_000],
                selected_option_ids=payload.selected_option_ids,
                correct=correct,
                score=score_10,
                score_breakdown=dimension_scores,
                missing_points=missing,
                feedback=feedback,
                confidence=payload.confidence,
                hints_used=payload.hints_used,
                elapsed_seconds=payload.elapsed_seconds,
                graded_by="rubric",
            )
        )
        # Counters before the award, for the same reason as above.
        profile.questions_answered += 1
        profile.total_practice_seconds += min(payload.elapsed_seconds, 3600)

        out = GradeOut(
            passed=correct,
            score=normalised,
            headline="✅ Good answer"
            if correct
            else "🚨 That answer would not land in an interview",
            what_happened=feedback,
            missing_points=missing,
            explanation_score=normalised,
            explanation_feedback=feedback,
            solution=question.ideal_senior_answer or question.expected_answer,
            solution_explanation=question.common_wrong_answer or None,
            reveal_solution=True,  # questions always teach immediately
        )
        if is_choice:
            out.test_results = [
                TestResultOut(
                    name=o["text"][:80],
                    passed=o["id"] in correct_ids,
                    expected=o.get("why", ""),
                    actual="selected" if o["id"] in payload.selected_option_ids else "",
                )
                for o in question.options
            ]

        if award_xp:
            ctx = AwardContext(
                tier=DifficultyTier(min(10, max(1, question.tier))),
                passed=correct,
                attempts=1,
                elapsed_seconds=payload.elapsed_seconds or None,
                par_seconds=float(question.par_seconds),
                explanation_score=None if is_choice else normalised,
                architecture_score=(
                    dimension_scores.get("architecture_thinking") if not is_choice else None
                ),
                streak_days=profile.current_streak,
            )
            progression = await self.progression.award(
                profile,
                compute_award(ctx),
                skill_slug=question.skill_slug,
                reference_type="question",
                reference_slug=question.slug,
                now=now,
            )
            out.progression = progression.model_dump()

        schedules = await self.retention.record_review(
            profile.id,
            question.concept_slugs or [],
            score=normalised,
            tier=question.tier,
            now=now,
            hints_used=payload.hints_used,
            confidence=payload.confidence,
            elapsed_seconds=payload.elapsed_seconds,
            par_seconds=question.par_seconds,
        )
        if schedules:
            out.next_review_at = min(s.due_at for s in schedules)
            out.mastery_delta = {
                s.concept_slug: {"before": s.mastery_before, "after": s.mastery_after}
                for s in schedules
            }

        self.session.add(
            LearningEvent(
                profile_id=profile.id,
                event_type="question_answered",
                skill_slug=question.skill_slug,
                category=question.category,
                tier=question.tier,
                score=normalised,
                elapsed_seconds=payload.elapsed_seconds,
                concept_slug=(question.concept_slugs or [None])[0],
                payload={
                    "question_slug": question.slug,
                    "kind": question.kind,
                    "score_10": score_10,
                    "correct": correct,
                    "dimensions": dimension_scores,
                },
            )
        )
        return out

    # ── Mistake database ──────────────────────────────────────────────────
    async def _record_mistakes(
        self,
        profile: PlayerProfile,
        detected: list[DetectedMistake],
        *,
        now: datetime,
        passed: bool,
    ) -> None:
        """Upsert detected mistakes; close records the player has outgrown.

        The clean-streak mechanism matters: a mistake is only "resolved" after
        several clean submissions, not one. Getting it right once is luck;
        getting it right three times in a row is a changed habit.
        """
        found = {m.pattern for m in detected}
        for mistake in detected:
            record = await self.mistakes.get_pattern(profile.id, mistake.pattern)
            if record is None:
                self.session.add(
                    MistakeRecord(
                        profile_id=profile.id,
                        pattern=mistake.pattern,
                        concept_slug=mistake.concept_slug,
                        skill_slug=mistake.category,
                        category=mistake.category,
                        title=mistake.title,
                        description=mistake.description,
                        why_it_matters=mistake.why_it_matters,
                        correct_approach=mistake.correct_approach,
                        severity=mistake.severity.value,
                        first_seen_at=now,
                        last_seen_at=now,
                        evidence=[{"at": now.isoformat(), "line": mistake.line}],
                    )
                )
            else:
                record.occurrences += 1
                record.last_seen_at = now
                record.clean_streak = 0
                record.resolved = False
                record.resolved_at = None
                record.evidence = [
                    *record.evidence[-9:],
                    {"at": now.isoformat(), "line": mistake.line},
                ]

        if passed:
            for record in await self.mistakes.open_for_profile(profile.id, limit=50):
                if record.pattern in found:
                    continue
                record.clean_streak += 1
                if record.clean_streak >= MISTAKE_CLEAN_STREAK_TO_RESOLVE:
                    record.resolved = True
                    record.resolved_at = now
                    log.info("mistake.resolved", profile_id=str(profile.id), pattern=record.pattern)


# ── Failure framing (spec §64: failure should be fun) ────────────────────────
def _frame_failure(result: ExecutionResult, challenge: Challenge) -> tuple[str, str, str | None]:
    """Turn a failure into a postmortem card instead of the word 'Wrong'."""
    if result.status == ExecStatus.TIMEOUT:
        return (
            "🚨 Production incident: request timeout",
            result.error_message
            or "Your code did not finish inside the time limit, so the request was killed.",
            "Most likely an unbounded loop, runaway recursion, or an algorithm that is a "
            "complexity class too slow for this input size.",
        )
    if result.status == ExecStatus.MEMORY:
        return (
            "🚨 Out of memory",
            result.error_message or "The process exceeded its memory limit and was killed.",
            "Something is being materialised in full that should be streamed — a list where "
            "a generator belongs, or a copy inside a loop.",
        )
    if result.status == ExecStatus.ERROR:
        return (
            f"🚨 {result.error_type or 'Error'} at import time",
            result.error_message or "Your code raised before any test could run.",
            (result.traceback or "").splitlines()[-1] if result.traceback else None,
        )
    if result.status == ExecStatus.SANDBOX_ERROR:
        return (
            "⚠ The sandbox could not run this",
            result.error_message or "An infrastructure problem, not your code.",
            None,
        )

    failed = [o for o in result.outcomes if not o.passed]
    if not failed:
        return "🚨 No tests ran", "The grader found no test cases to execute.", None
    first = failed[0]
    detail = (
        f"`{first.name}` failed."
        if first.hidden
        else f"`{first.name}` expected {first.expected} but got {first.actual}."
    )
    return (
        f"🚨 {len(failed)} of {result.tests_total} checks failed",
        detail + (f"\n{first.message}" if first.message else ""),
        first.traceback.splitlines()[-1] if first.traceback else None,
    )


def _next_hint(challenge: Challenge, hints_used: int) -> str | None:
    hints = challenge.hints or []
    if hints_used >= len(hints):
        return None
    hint = hints[hints_used]
    return hint if isinstance(hint, str) else hint.get("text")


def _explanation_feedback(score_10: float, missing: list[str]) -> str:
    if score_10 >= 8.5:
        return "Strong explanation — you named the mechanism and the trade-off."
    if score_10 >= 6.5:
        base = "Solid, but not yet a senior answer."
    elif score_10 >= 4:
        base = "You have the shape of it, but the reasoning is thin."
    else:
        base = "This explains *what* happens, not *why*."
    if missing:
        shown = "; ".join(missing[:3])
        return f"{base} Still missing: {shown}."
    return base + " Go one level deeper: what breaks, and under what conditions?"


def _mcq_feedback(question: Question, selected: list[str], correct: bool) -> str:
    if correct:
        chosen = next((o for o in question.options if o["id"] in selected), None)
        why = (chosen or {}).get("why", "")
        return f"Correct. {why}".strip()
    wrong = [o for o in question.options if o["id"] in selected and not o.get("correct")]
    if wrong and wrong[0].get("why"):
        return f"Not quite — {wrong[0]['why']}"
    return "Not quite. Read the correct answer's reasoning below before moving on."


def _normalise_complexity(text: str) -> str:
    return (
        text.lower()
        .replace(" ", "")
        .replace("*", "")
        .replace("big-o", "")
        .replace("bigo", "")
        .replace("θ", "o")
        .replace("(", "(")
        .strip()
    )


def _outcome_dict(outcome: Any) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "passed": outcome.passed,
        "hidden": outcome.hidden,
        "points": outcome.points,
        "max_points": outcome.max_points,
        "message": outcome.message,
        "duration_ms": outcome.duration_ms,
    }


SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}
