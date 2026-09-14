"""Read-side access to authored content, with player-relative gating.

The important rule enforced here: **secrets never leave this module**. Hidden
tests, reference solutions, rubrics and correct-option flags are stripped when
building the player-facing schema. A route that accidentally returns an ORM
object cannot leak them, because the response models do not have those fields —
but stripping here means even a debug dump is safe.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LockedError, NotFoundError
from app.domain.enums import RANK_ORDER, Rank
from app.models.content import Challenge, Concept, ConceptEdge, Mission, Question
from app.models.progress import ConceptProgress
from app.models.user import PlayerProfile
from app.repositories.player import (
    ChallengeAttemptRepository,
    MissionAttemptRepository,
    QuestionAttemptRepository,
)
from app.schemas.content import (
    ChallengeOut,
    ConceptDetail,
    ConceptSummary,
    MissionDetail,
    MissionStepOut,
    MissionSummary,
    QuestionOptionOut,
    QuestionOut,
    TestCaseOut,
)


class ContentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.challenge_attempts = ChallengeAttemptRepository(session)
        self.mission_attempts = MissionAttemptRepository(session)
        self.question_attempts = QuestionAttemptRepository(session)

    # ── Concepts ──────────────────────────────────────────────────────────
    async def list_concepts(
        self,
        *,
        profile_id: uuid.UUID | None = None,
        category: str | None = None,
        skill_slug: str | None = None,
        node_slug: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[list[ConceptSummary], int]:
        stmt: Select = select(Concept)
        if category:
            stmt = stmt.where(Concept.category == category)
        if skill_slug:
            stmt = stmt.where(Concept.skill_slug == skill_slug)
        if node_slug:
            stmt = stmt.where(Concept.skill_node_slug == node_slug)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(func.lower(Concept.title).like(like), func.lower(Concept.summary).like(like))
            )
        count = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(stmt.order_by(None).subquery())
                )
            ).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Concept.base_difficulty, Concept.title)
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        progress = await self._concept_progress(profile_id, [c.slug for c in rows])
        return [self._concept_summary(c, progress.get(c.slug)) for c in rows], count

    async def get_concept(self, slug: str, *, profile_id: uuid.UUID | None = None) -> ConceptDetail:
        concept = (
            await self.session.execute(select(Concept).where(Concept.slug == slug))
        ).scalar_one_or_none()
        if concept is None:
            raise NotFoundError(f"Concept '{slug}' not found.")

        # One query for both edge directions; the knowledge graph panel needs
        # prerequisites *and* what this leads to.
        edges = (
            (
                await self.session.execute(
                    select(ConceptEdge).where(
                        or_(
                            ConceptEdge.source_id == concept.id, ConceptEdge.target_id == concept.id
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        neighbour_ids = {e.source_id for e in edges} | {e.target_id for e in edges}
        neighbour_ids.discard(concept.id)
        neighbours = {
            c.id: c
            for c in (
                await self.session.execute(select(Concept).where(Concept.id.in_(neighbour_ids)))
            ).scalars()
        }

        prereqs, leads_to, related = [], [], []
        for edge in edges:
            other_id = edge.target_id if edge.source_id == concept.id else edge.source_id
            other = neighbours.get(other_id)
            if other is None:
                continue
            if edge.relation == "requires":
                (prereqs if edge.source_id == concept.id else leads_to).append(other)
            else:
                related.append(other)

        all_slugs = [concept.slug, *[c.slug for c in (*prereqs, *leads_to, *related)]]
        progress = await self._concept_progress(profile_id, all_slugs)

        challenge_slugs = [
            r[0]
            for r in (
                await self.session.execute(
                    select(Challenge.slug)
                    .where(
                        Challenge.concept_slugs.is_not(None), Challenge.category == concept.category
                    )
                    .limit(20)
                )
            ).all()
        ]
        question_slugs = [
            r[0]
            for r in (
                await self.session.execute(
                    select(Question.slug).where(Question.category == concept.category).limit(20)
                )
            ).all()
        ]

        detail = ConceptDetail(
            **self._concept_summary(concept, progress.get(concept.slug)).model_dump(),
            explanation=concept.explanation,
            examples=concept.examples,
            common_mistakes=concept.common_mistakes,
            real_world_usage=concept.real_world_usage,
            visualization=concept.visualization,
            max_tier=concept.max_tier,
            prerequisites=[self._concept_summary(c, progress.get(c.slug)) for c in prereqs],
            leads_to=[self._concept_summary(c, progress.get(c.slug)) for c in leads_to],
            related=[self._concept_summary(c, progress.get(c.slug)) for c in related],
            challenge_slugs=challenge_slugs,
            question_slugs=question_slugs,
        )
        return detail

    async def _concept_progress(
        self, profile_id: uuid.UUID | None, slugs: list[str]
    ) -> dict[str, ConceptProgress]:
        if not profile_id or not slugs:
            return {}
        rows = (
            await self.session.execute(
                select(ConceptProgress).where(
                    ConceptProgress.profile_id == profile_id,
                    ConceptProgress.concept_slug.in_(slugs),
                )
            )
        ).scalars()
        return {r.concept_slug: r for r in rows}

    @staticmethod
    def _concept_summary(concept: Concept, progress: ConceptProgress | None) -> ConceptSummary:
        from datetime import UTC, datetime

        from app.game.retention.model import decay_report
        from app.services.retention_service import to_state

        mastery = eff = 0.0
        due = decayed = False
        if progress and progress.attempts:
            report = decay_report(to_state(progress), datetime.now(UTC))
            mastery, eff = progress.mastery, report.effective_mastery
            due, decayed = report.is_due, report.is_decayed
        return ConceptSummary(
            slug=concept.slug,
            title=concept.title,
            category=concept.category,
            skill_slug=concept.skill_slug,
            base_difficulty=concept.base_difficulty,
            summary=concept.summary,
            estimated_minutes=concept.estimated_minutes,
            tags=concept.tags,
            mastery=round(mastery, 4),
            effective_mastery=round(eff, 4),
            due=due,
            decayed=decayed,
        )

    # ── Challenges ────────────────────────────────────────────────────────
    async def get_challenge_model(self, slug: str) -> Challenge:
        row = (
            await self.session.execute(select(Challenge).where(Challenge.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Challenge '{slug}' not found.")
        return row

    async def get_challenge(
        self, slug: str, *, profile_id: uuid.UUID | None = None
    ) -> ChallengeOut:
        challenge = await self.get_challenge_model(slug)
        visible = [t for t in challenge.tests if not t.get("hidden")]
        hidden_count = len(challenge.tests) - len(visible)
        return ChallengeOut(
            slug=challenge.slug,
            title=challenge.title,
            category=challenge.category,
            skill_slug=challenge.skill_slug,
            tier=challenge.tier,
            prompt=challenge.prompt,
            # DEBUG-tier challenges hand the player broken code, not a blank file.
            starter_code=challenge.broken_code or challenge.starter_code,
            hints_available=len(challenge.hints),
            visible_tests=[
                TestCaseOut(
                    name=t.get("name", "test"),
                    description=t.get("description", ""),
                    call=t.get("call"),
                    expect=t.get("expect"),
                    points=float(t.get("points", 1.0)),
                )
                for t in visible
            ],
            hidden_test_count=hidden_count,
            explanation_prompts=[
                p if isinstance(p, str) else p.get("prompt", "")
                for p in challenge.explanation_prompts
            ],
            requires_packages=challenge.requires_packages,
            par_seconds=challenge.par_seconds,
            time_limit_seconds=challenge.time_limit_seconds,
            concept_slugs=challenge.concept_slugs,
            expected_complexity=challenge.expected_complexity,
            target_speedup=challenge.target_speedup,
            baseline_code=challenge.baseline_code,
            attempts_made=(
                await self.challenge_attempts.attempts_for(profile_id, slug) if profile_id else 0
            ),
            solved=(await self.challenge_attempts.solved(profile_id, slug))
            if profile_id
            else False,
        )

    async def list_challenges(
        self,
        *,
        profile_id: uuid.UUID | None = None,
        category: str | None = None,
        skill_slug: str | None = None,
        tier: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt: Select = select(Challenge)
        if category:
            stmt = stmt.where(Challenge.category == category)
        if skill_slug:
            stmt = stmt.where(Challenge.skill_slug == skill_slug)
        if tier:
            stmt = stmt.where(Challenge.tier == tier)
        total = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(stmt.order_by(None).subquery())
                )
            ).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Challenge.tier, Challenge.title)
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        solved = await self.challenge_attempts.solved_slugs(profile_id) if profile_id else set()
        return (
            [
                {
                    "slug": c.slug,
                    "title": c.title,
                    "category": c.category,
                    "skill_slug": c.skill_slug,
                    "tier": c.tier,
                    "par_seconds": c.par_seconds,
                    "solved": c.slug in solved,
                    "concept_slugs": c.concept_slugs,
                }
                for c in rows
            ],
            total,
        )

    # ── Questions ─────────────────────────────────────────────────────────
    async def get_question_model(self, slug: str) -> Question:
        row = (
            await self.session.execute(select(Question).where(Question.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Question '{slug}' not found.")
        return row

    @staticmethod
    def to_question_out(question: Question) -> QuestionOut:
        return QuestionOut(
            slug=question.slug,
            kind=question.kind,
            category=question.category,
            skill_slug=question.skill_slug,
            tier=question.tier,
            interview_level=question.interview_level,
            prompt=question.prompt,
            context=question.context,
            # Note: only id and text survive. `correct` and `why` stay server-side.
            options=[QuestionOptionOut(id=o["id"], text=o["text"]) for o in question.options],
            hints_available=len(question.hints),
            par_seconds=question.par_seconds,
            concept_slugs=question.concept_slugs,
        )

    async def random_question(
        self,
        *,
        profile_id: uuid.UUID | None = None,
        category: str | None = None,
        tier: int | None = None,
        interview_level: str | None = None,
        exclude: set[str] | None = None,
    ) -> QuestionOut | None:
        stmt: Select = select(Question)
        if category:
            stmt = stmt.where(Question.category == category)
        if tier:
            stmt = stmt.where(Question.tier == tier)
        if interview_level:
            stmt = stmt.where(Question.interview_level == interview_level)

        seen = set(exclude or set())
        if profile_id:
            # Spec §40: never repeat a question the player has recently seen.
            seen |= await self.question_attempts.seen_slugs(profile_id, within_days=45)
        if seen:
            stmt = stmt.where(Question.slug.not_in(seen))

        row = (
            await self.session.execute(stmt.order_by(func.random()).limit(1))
        ).scalar_one_or_none()
        if row is None and seen:
            # Exhausted the unseen pool — fall back to the least-recently-seen
            # rather than returning nothing. Repetition beats a dead end.
            row = (
                await self.session.execute(
                    select(Question)
                    .where(Question.category == category if category else True)
                    .order_by(func.random())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return self.to_question_out(row) if row else None

    # ── Missions ──────────────────────────────────────────────────────────
    async def get_mission_model(self, slug: str) -> Mission:
        row = (
            await self.session.execute(select(Mission).where(Mission.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Mission '{slug}' not found.")
        return row

    async def list_missions(
        self,
        profile: PlayerProfile,
        *,
        building: str | None = None,
        category: str | None = None,
        kind: str | None = None,
        include_locked: bool = True,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[list[MissionSummary], int]:
        stmt: Select = select(Mission)
        if building:
            stmt = stmt.where(Mission.building == building)
        if category:
            stmt = stmt.where(Mission.category == category)
        if kind:
            stmt = stmt.where(Mission.kind == kind)
        total = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(stmt.order_by(None).subquery())
                )
            ).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Mission.tier, Mission.required_level, Mission.title)
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        completion = await self.mission_attempts.completion_map(profile.id)
        out = []
        for m in rows:
            locked, reason = self._lock_state(m, profile, completion)
            if locked and not include_locked:
                continue
            stats = completion.get(m.slug, {})
            out.append(
                MissionSummary(
                    slug=m.slug,
                    title=m.title,
                    kind=m.kind,
                    category=m.category,
                    building=m.building,
                    tier=m.tier,
                    skill_slug=m.skill_slug,
                    objective=m.objective,
                    estimated_minutes=m.estimated_minutes,
                    required_level=m.required_level,
                    is_boss=m.is_boss,
                    locked=locked,
                    lock_reason=reason,
                    completed=stats.get("completed", False),
                    best_score=stats.get("best_score"),
                    attempts=stats.get("attempts", 0),
                )
            )
        return out, total

    @staticmethod
    def _lock_state(
        mission: Mission, profile: PlayerProfile, completion: dict[str, dict[str, Any]]
    ) -> tuple[bool, str | None]:
        if profile.level < mission.required_level:
            return True, f"Reach level {mission.required_level}"
        if mission.required_rank:
            try:
                needed = RANK_ORDER.index(Rank(mission.required_rank))
                have = RANK_ORDER.index(Rank(profile.rank))
            except ValueError:
                needed = have = 0
            if have < needed:
                return True, f"Reach {mission.required_rank.replace('_', ' ').title()}"
        for prereq in mission.prerequisite_mission_slugs or []:
            if not completion.get(prereq, {}).get("completed"):
                return True, "Complete the prerequisite mission first"
        return False, None

    async def get_mission(self, slug: str, profile: PlayerProfile) -> MissionDetail:
        mission = await self.get_mission_model(slug)
        completion = await self.mission_attempts.completion_map(profile.id)
        locked, reason = self._lock_state(mission, profile, completion)
        if locked:
            raise LockedError(reason or "This mission is not unlocked yet.", details={"slug": slug})

        attempt = await self.mission_attempts.open_attempt(profile.id, slug)
        step_results = (attempt.step_results if attempt else {}) or {}
        stats = completion.get(slug, {})

        return MissionDetail(
            slug=mission.slug,
            title=mission.title,
            kind=mission.kind,
            category=mission.category,
            building=mission.building,
            tier=mission.tier,
            skill_slug=mission.skill_slug,
            objective=mission.objective,
            estimated_minutes=mission.estimated_minutes,
            required_level=mission.required_level,
            is_boss=mission.is_boss,
            locked=False,
            completed=stats.get("completed", False),
            best_score=stats.get("best_score"),
            attempts=stats.get("attempts", 0),
            briefing=mission.briefing,
            success_criteria=mission.success_criteria,
            artifacts=mission.artifacts,
            concept_slugs=mission.concept_slugs,
            par_seconds=mission.par_seconds,
            # The debrief is the teaching payload and is withheld until the
            # mission is passed — reading it first turns the mission into a quiz
            # with the answers printed underneath.
            debrief=mission.debrief if stats.get("completed") else None,
            attempt_id=attempt.id if attempt else None,
            steps=[
                MissionStepOut(
                    position=s.position,
                    step_type=s.step_type,
                    title=s.title,
                    prompt=s.prompt,
                    challenge_slug=s.challenge_slug,
                    question_slug=s.question_slug,
                    config=s.config,
                    required=s.required,
                    status=step_results.get(str(s.position), {}).get("status", "pending"),
                    score=step_results.get(str(s.position), {}).get("score"),
                )
                for s in mission.steps
            ],
        )

    async def hint(self, kind: str, slug: str, index: int) -> tuple[str, int]:
        """Return one hint and how many remain.

        Hints are served one at a time by index (spec §58: the mentor escalates
        rather than dumping the answer). Cost is applied by the caller.
        """
        source = (
            await self.get_challenge_model(slug)
            if kind == "challenge"
            else await self.get_question_model(slug)
        )
        hints = source.hints or []
        if not hints:
            return (
                "No hints are available for this one — try restating the problem in your own words first.",
                0,
            )
        idx = max(0, min(index, len(hints) - 1))
        text = hints[idx]
        return (text if isinstance(text, str) else text.get("text", "")), max(
            0, len(hints) - idx - 1
        )
