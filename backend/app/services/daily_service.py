"""Daily Engineering Mission generator (spec §5).

THE SELECTION POLICY — the thing that makes the game work long-term
-------------------------------------------------------------------
A daily is not a random quiz. Slots are filled from prioritised pools so the
session always contains the *right* mix:

1. **Repair** (up to 3 slots) — concepts the retention engine says are decaying,
   highest urgency first. Non-negotiable: this is why the game is worth
   reopening after six months.
2. **Mistake targeting** (up to 2) — content exercising an open mistake pattern.
   Not the exact exercise they failed; the *pattern*.
3. **Frontier** (up to 2) — the next tier of a skill they are actively climbing.
   Adaptive difficulty lives here (spec §40): one tier above their demonstrated
   ceiling, never at it.
4. **Breadth** (1) — an unlocked area they have been neglecting, so the player
   does not tunnel into Python forever.
5. **Interview** (1) — always exactly one, at their current interview level.

Each slot records *why* it was chosen. Showing the reason is what turns a daily
from a chore into a training plan the player believes in.

The plan is persisted, so reopening the app shows the same mission. Rerolling
would let players dodge precisely the concepts they most need.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.domain.enums import XPSource
from app.game.skills.registry import BUILDING_BY_ID, SKILL_BY_SLUG
from app.game.xp.engine import XPGrant
from app.models.content import Challenge, Question
from app.models.progress import DailyChallenge, LearningEvent
from app.models.user import PlayerProfile
from app.repositories.player import (
    DailyChallengeRepository,
    MistakeRepository,
    SkillProgressRepository,
)
from app.schemas.retention import DailyMissionOut, DailySlotOut
from app.services.progression_service import ProgressionService
from app.services.retention_service import RetentionService

log = get_logger(__name__)

MAX_REPAIR_SLOTS = 3
MAX_MISTAKE_SLOTS = 2
MAX_FRONTIER_SLOTS = 2


class DailyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.dailies = DailyChallengeRepository(session)
        self.skills = SkillProgressRepository(session)
        self.mistakes = MistakeRepository(session)
        self.retention = RetentionService(session)
        self.progression = ProgressionService(session)

    async def get_or_create(
        self, profile: PlayerProfile, *, for_date: date | None = None
    ) -> DailyMissionOut:
        day = for_date or datetime.now(UTC).date()
        existing = await self.dailies.for_date(profile.id, day)
        if existing is None:
            existing = await self._generate(profile, day)
        return self._to_out(existing, profile)

    async def _generate(self, profile: PlayerProfile, day: date) -> DailyChallenge:
        size = settings.daily_mission_size
        # Seeded by (player, date) so regeneration after a crash is identical
        # and two players never get an obviously-shared "random" plan.
        rng = random.Random(f"{profile.id}:{day.isoformat()}")

        unlocked_categories = self._unlocked_categories(profile)
        slots: list[dict[str, Any]] = []
        used_refs: set[str] = set()
        reasons: dict[str, Any] = {"policy": "repair>mistake>frontier>breadth>interview"}

        # 1. Repair decayed knowledge
        decayed = await self.retention.due_concepts(profile.id, limit=20)
        repair_used = 0
        for row, report in decayed:
            if repair_used >= MAX_REPAIR_SLOTS or len(slots) >= size - 1:
                break
            ref = await self._content_for_concept(row.concept_slug, row.category, used_refs, rng)
            if ref is None:
                continue
            used_refs.add(ref["ref_slug"])
            slots.append(
                {
                    **ref,
                    "reason": (
                        f"Recall probability has fallen to {report.retrievability:.0%} "
                        f"({report.days_since_practice:.0f} days since practice). "
                        f"Mastery {report.peak_mastery:.0%} → {report.effective_mastery:.0%}."
                    ),
                    "pool": "repair",
                }
            )
            repair_used += 1
        reasons["repair_candidates"] = len(decayed)

        # 2. Target open mistake patterns
        open_mistakes = await self.mistakes.open_for_profile(profile.id, limit=6)
        mistake_used = 0
        for mistake in open_mistakes:
            if mistake_used >= MAX_MISTAKE_SLOTS or len(slots) >= size - 1:
                break
            ref = await self._content_for_category(
                mistake.category or "python", used_refs, rng, prefer_kind="challenge"
            )
            if ref is None:
                continue
            used_refs.add(ref["ref_slug"])
            slots.append(
                {
                    **ref,
                    "reason": (
                        f"You have hit “{mistake.title}” {mistake.occurrences}x. "
                        "This exercises the same pattern."
                    ),
                    "pool": "mistake",
                }
            )
            mistake_used += 1
        reasons["open_mistakes"] = len(open_mistakes)

        # 3. Frontier: one tier above demonstrated ceiling
        skill_rows = sorted(
            [s for s in await self.skills.for_profile(profile.id) if s.attempts > 0],
            key=lambda s: -s.mastery,
        )
        frontier_used = 0
        for skill in skill_rows:
            if frontier_used >= MAX_FRONTIER_SLOTS or len(slots) >= size - 1:
                break
            target_tier = min(10, max(2, skill.highest_tier_cleared + 1))
            ref = await self._content_for_skill(
                skill.skill_slug, target_tier, used_refs, rng, unlocked_categories
            )
            if ref is None:
                continue
            used_refs.add(ref["ref_slug"])
            name = (
                SKILL_BY_SLUG[skill.skill_slug].name
                if skill.skill_slug in SKILL_BY_SLUG
                else skill.skill_slug
            )
            slots.append(
                {
                    **ref,
                    "reason": (
                        f"{name}: you have cleared tier {skill.highest_tier_cleared}. "
                        f"This is tier {target_tier} — one step past your current ceiling."
                    ),
                    "pool": "frontier",
                }
            )
            frontier_used += 1

        # 4. Breadth: least-practised unlocked area
        neglected = sorted(
            await self.skills.for_profile(profile.id),
            key=lambda s: s.last_practiced_at or datetime.min.replace(tzinfo=UTC),
        )
        for skill in neglected:
            if len(slots) >= size - 1:
                break
            ref = await self._content_for_skill(
                skill.skill_slug,
                max(1, profile.level // 12 + 1),
                used_refs,
                rng,
                unlocked_categories,
            )
            if ref is None:
                continue
            used_refs.add(ref["ref_slug"])
            name = (
                SKILL_BY_SLUG[skill.skill_slug].name
                if skill.skill_slug in SKILL_BY_SLUG
                else skill.skill_slug
            )
            since = (
                f"not practised since {skill.last_practiced_at.date().isoformat()}"
                if skill.last_practiced_at
                else "never practised"
            )
            slots.append({**ref, "reason": f"Breadth: {name} — {since}.", "pool": "breadth"})
            break

        # 5. Fill any remaining space with level-appropriate variety
        while len(slots) < size - 1:
            ref = await self._content_for_category(
                rng.choice(unlocked_categories) if unlocked_categories else "python",
                used_refs,
                rng,
            )
            if ref is None:
                break
            used_refs.add(ref["ref_slug"])
            slots.append({**ref, "reason": "Keeping the rotation varied.", "pool": "variety"})

        # 6. Always exactly one interview question, last
        interview_ref = await self._interview_question(profile, used_refs, rng)
        if interview_ref:
            slots.append(
                {
                    **interview_ref,
                    "reason": "One senior-level interview question, every single day.",
                    "pool": "interview",
                }
            )

        for i, slot in enumerate(slots):
            slot["slot"] = i

        estimated = sum(s.get("estimated_minutes", 4) for s in slots)
        daily = DailyChallenge(
            profile_id=profile.id,
            for_date=day,
            slots=slots,
            generation_reason=reasons,
            estimated_minutes=estimated,
        )
        self.session.add(daily)
        await self.session.flush()
        log.info(
            "daily.generated",
            profile_id=str(profile.id),
            date=day.isoformat(),
            slots=len(slots),
            minutes=estimated,
        )
        return daily

    # ── Candidate lookups ─────────────────────────────────────────────────
    @staticmethod
    def _unlocked_categories(profile: PlayerProfile) -> list[str]:
        cats: list[str] = []
        for building_id in profile.unlocked_buildings or []:
            b = BUILDING_BY_ID.get(building_id)
            if b:
                cats.extend(c.value for c in b.categories)
        return cats or ["python"]

    async def _content_for_concept(
        self, concept_slug: str, category: str, used: set[str], rng: random.Random
    ) -> dict[str, Any] | None:
        challenge = (
            (
                await self.session.execute(
                    select(Challenge)
                    .where(Challenge.concept_slugs.contains([concept_slug]))
                    .order_by(func.random())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not settings.is_sqlite
            else None
        )

        if challenge is None:
            # SQLite cannot index into a JSON array, so fall back to category.
            # Correct either way; just less targeted on the zero-setup path.
            return await self._content_for_category(category, used, rng)
        if challenge.slug in used:
            return None
        return _challenge_ref(challenge)

    async def _content_for_category(
        self,
        category: str,
        used: set[str],
        rng: random.Random,
        *,
        prefer_kind: str | None = None,
    ) -> dict[str, Any] | None:
        want_challenge = prefer_kind == "challenge" or (prefer_kind is None and rng.random() < 0.6)
        for attempt_kind in [True, False] if want_challenge else [False, True]:
            if attempt_kind:
                row = (
                    await self.session.execute(
                        select(Challenge)
                        .where(Challenge.category == category, Challenge.slug.not_in(used or {""}))
                        .order_by(func.random())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    return _challenge_ref(row)
            else:
                row = (
                    await self.session.execute(
                        select(Question)
                        .where(Question.category == category, Question.slug.not_in(used or {""}))
                        .order_by(func.random())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    return _question_ref(row)
        return None

    async def _content_for_skill(
        self,
        skill_slug: str,
        tier: int,
        used: set[str],
        rng: random.Random,
        unlocked: list[str],
    ) -> dict[str, Any] | None:
        row = (
            await self.session.execute(
                select(Challenge)
                .where(
                    Challenge.skill_slug == skill_slug,
                    Challenge.tier.between(max(1, tier - 1), min(10, tier + 1)),
                    Challenge.category.in_(unlocked),
                    Challenge.slug.not_in(used or {""}),
                )
                .order_by(func.random())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row:
            return _challenge_ref(row)
        q = (
            await self.session.execute(
                select(Question)
                .where(
                    Question.skill_slug == skill_slug,
                    Question.tier.between(max(1, tier - 1), min(10, tier + 1)),
                    Question.slug.not_in(used or {""}),
                )
                .order_by(func.random())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _question_ref(q) if q else None

    async def _interview_question(
        self, profile: PlayerProfile, used: set[str], rng: random.Random
    ) -> dict[str, Any] | None:
        level = _interview_level_for(profile.level)
        row = (
            await self.session.execute(
                select(Question)
                .where(Question.interview_level == level, Question.slug.not_in(used or {""}))
                .order_by(func.random())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await self.session.execute(select(Question).order_by(func.random()).limit(1))
            ).scalar_one_or_none()
        return _question_ref(row, kind="interview") if row else None

    # ── Completion ────────────────────────────────────────────────────────
    async def mark_slot_complete(
        self, profile: PlayerProfile, slot_index: int, score: float
    ) -> DailyMissionOut:
        day = datetime.now(UTC).date()
        daily = await self.dailies.for_date(profile.id, day)
        if daily is None:
            raise NotFoundError("No daily mission for today.")

        completed = list(daily.completed_slots or [])
        if not any(c["slot"] == slot_index for c in completed):
            completed.append(
                {"slot": slot_index, "score": score, "at": datetime.now(UTC).isoformat()}
            )
            daily.completed_slots = completed

        if len(completed) >= len(daily.slots) and not daily.completed:
            daily.completed = True
            daily.completed_at = datetime.now(UTC)
            streak = self.progression.touch_streak(profile)
            avg = sum(c["score"] for c in completed) / len(completed)
            progression = await self.progression.award(
                profile,
                [
                    XPGrant(
                        XPSource.DAILY_COMPLETE,
                        int(120 + 180 * avg),
                        f"Daily mission complete ({avg:.0%} average)",
                    )
                ],
                reference_type="daily",
                reference_slug=day.isoformat(),
            )
            daily.xp_awarded = progression.xp_gained
            self.session.add(
                LearningEvent(
                    profile_id=profile.id,
                    event_type="daily_completed",
                    score=avg,
                    payload={"date": day.isoformat(), "streak": streak["streak"]},
                )
            )
            log.info("daily.completed", profile_id=str(profile.id), avg_score=round(avg, 3))

        return self._to_out(daily, profile)

    def _to_out(self, daily: DailyChallenge, profile: PlayerProfile) -> DailyMissionOut:
        done = {c["slot"]: c for c in (daily.completed_slots or [])}
        return DailyMissionOut(
            id=daily.id,
            for_date=daily.for_date,
            slots=[
                DailySlotOut(
                    slot=s.get("slot", i),
                    kind=s.get("kind", "coding"),
                    category=s.get("category", "python"),
                    title=s.get("title", ""),
                    reason=s.get("reason", ""),
                    tier=s.get("tier", 1),
                    ref_type=s.get("ref_type", "challenge"),
                    ref_slug=s.get("ref_slug", ""),
                    estimated_minutes=s.get("estimated_minutes", 4),
                    completed=s.get("slot", i) in done,
                    score=done.get(s.get("slot", i), {}).get("score"),
                )
                for i, s in enumerate(daily.slots or [])
            ],
            estimated_minutes=daily.estimated_minutes,
            completed=daily.completed,
            completed_at=daily.completed_at,
            xp_awarded=daily.xp_awarded,
            completed_count=len(done),
            streak=profile.current_streak,
            generation_reason=daily.generation_reason,
        )

    async def history(self, profile_id: uuid.UUID, limit: int = 14) -> list[dict[str, Any]]:
        rows = await self.dailies.recent(profile_id, limit=limit)
        return [
            {
                "date": r.for_date.isoformat(),
                "completed": r.completed,
                "slots": len(r.slots or []),
                "completed_slots": len(r.completed_slots or []),
                "xp_awarded": r.xp_awarded,
            }
            for r in rows
        ]


def _challenge_ref(c: Challenge) -> dict[str, Any]:
    return {
        "kind": "debugging" if c.broken_code else "coding",
        "category": c.category,
        "title": c.title,
        "tier": c.tier,
        "ref_type": "challenge",
        "ref_slug": c.slug,
        "estimated_minutes": max(2, c.par_seconds // 60),
    }


def _question_ref(q: Question, *, kind: str | None = None) -> dict[str, Any]:
    return {
        "kind": kind or ("concept" if q.tier <= 3 else "explain"),
        "category": q.category,
        "title": q.prompt[:90],
        "tier": q.tier,
        "ref_type": "question",
        "ref_slug": q.slug,
        "estimated_minutes": max(1, q.par_seconds // 60),
    }


def _interview_level_for(level: int) -> str:
    if level >= 84:
        return "principal"
    if level >= 52:
        return "staff"
    if level >= 22:
        return "senior"
    if level >= 8:
        return "mid"
    return "junior"
