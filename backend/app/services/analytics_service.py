"""Analytics and readiness scoring (spec §46).

A rule applied throughout: **never show a composite score without its
components.** "Interview readiness: 62%" is a number; "62% — held back by
production awareness (0.31) and three decayed RAG concepts" is feedback. Every
gauge here ships with its breakdown.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game.skills.registry import SKILL_BY_SLUG
from app.game.xp.engine import experience_band_for_level
from app.models.progress import ConceptProgress, LearningEvent, QuestionAttempt
from app.models.user import PlayerProfile
from app.repositories.player import (
    LearningEventRepository,
    MistakeRepository,
    QuestionAttemptRepository,
    SkillProgressRepository,
    XPRepository,
)
from app.schemas.analytics import (
    MasteryRow,
    ProgressAnalyticsOut,
    ReadinessBreakdown,
    TimeSeriesPoint,
)
from app.services.retention_service import RetentionService

#: Which skills carry the most weight for interview readiness, and why.
READINESS_WEIGHTS: dict[str, float] = {
    "python": 0.18,
    "backend": 0.12,
    "database": 0.10,
    "system_design": 0.12,
    "architecture": 0.10,
    "debugging": 0.10,
    "ml": 0.05,
    "deep_learning": 0.04,
    "llm": 0.06,
    "rag": 0.05,
    "agents": 0.03,
    "testing": 0.03,
    "communication": 0.02,
}


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skills = SkillProgressRepository(session)
        self.xp = XPRepository(session)
        self.events = LearningEventRepository(session)
        self.questions = QuestionAttemptRepository(session)
        self.mistakes = MistakeRepository(session)
        self.retention = RetentionService(session)

    async def progress(self, profile: PlayerProfile) -> ProgressAnalyticsOut:
        now = datetime.now(UTC)
        skill_rows = await self.skills.for_profile(profile.id)

        mastery_by_skill = [
            MasteryRow(
                slug=s.skill_slug,
                name=SKILL_BY_SLUG[s.skill_slug].name
                if s.skill_slug in SKILL_BY_SLUG
                else s.skill_slug,
                mastery=s.mastery,
                effective_mastery=s.effective_mastery,
                peak_mastery=s.peak_mastery,
                attempts=s.attempts,
                accuracy=round(s.correct / s.attempts, 4) if s.attempts else 0.0,
                last_practiced_at=s.last_practiced_at,
            )
            for s in skill_rows
        ]

        cat_rows = (
            await self.session.execute(
                select(
                    ConceptProgress.category,
                    func.avg(ConceptProgress.mastery),
                    func.count(),
                )
                .where(ConceptProgress.profile_id == profile.id, ConceptProgress.attempts > 0)
                .group_by(ConceptProgress.category)
            )
        ).all()
        mastery_by_category = [
            MasteryRow(
                slug=r[0],
                name=r[0].replace("_", " ").title(),
                mastery=round(float(r[1] or 0), 4),
                effective_mastery=round(float(r[1] or 0), 4),
                peak_mastery=round(float(r[1] or 0), 4),
                attempts=int(r[2]),
            )
            for r in cat_rows
        ]
        mastery_by_category.sort(key=lambda m: -m.mastery)

        xp_daily = await self.xp.daily_totals(profile.id, days=30)
        activity = await self.events.active_days(profile.id, days=30)
        accuracy = await self.events.accuracy_trend(profile.id, days=30)

        tier_rows = (
            await self.session.execute(
                select(LearningEvent.tier, func.count())
                .where(LearningEvent.profile_id == profile.id, LearningEvent.tier.is_not(None))
                .group_by(LearningEvent.tier)
                .order_by(LearningEvent.tier)
            )
        ).all()

        decay = await self.retention.concept_decay(profile.id, now=now)
        forgotten = sorted(
            [(row, rep) for row, rep in decay if rep.is_decayed and row.attempts > 0],
            key=lambda p: -p[1].mastery_drop,
        )[:8]

        open_mistakes = await self.mistakes.open_for_profile(profile.id, limit=10)
        practice_7d, practice_30d = await self._practice_minutes(profile.id)
        readiness = await self.interview_readiness(profile)

        tracked = [s for s in mastery_by_skill if s.attempts > 0]
        return ProgressAnalyticsOut(
            generated_at=now,
            total_xp=profile.total_xp,
            level=profile.level,
            rank=profile.rank,
            experience_band=experience_band_for_level(profile.level).value,
            mastery_by_skill=mastery_by_skill,
            mastery_by_category=mastery_by_category,
            xp_over_time=[TimeSeriesPoint(date=d, value=float(v)) for d, v in xp_daily],
            activity_over_time=[TimeSeriesPoint(date=d, value=float(v)) for d, v in activity],
            accuracy_over_time=[TimeSeriesPoint(date=d, value=v) for d, v in accuracy],
            xp_by_source=[
                {"source": s, "amount": a} for s, a in await self.xp.sum_by_source(profile.id)
            ],
            tier_distribution=[{"tier": int(t), "count": int(c)} for t, c in tier_rows],
            strongest_skills=sorted(tracked, key=lambda m: -m.effective_mastery)[:5],
            weakest_skills=sorted(tracked, key=lambda m: m.effective_mastery)[:5],
            recently_forgotten=[
                {
                    "concept_slug": row.concept_slug,
                    "skill_slug": row.skill_slug,
                    "from": rep.peak_mastery,
                    "to": rep.effective_mastery,
                    "days": rep.days_since_practice,
                }
                for row, rep in forgotten
            ],
            most_common_mistakes=[
                {
                    "pattern": m.pattern,
                    "title": m.title,
                    "occurrences": m.occurrences,
                    "severity": m.severity,
                }
                for m in open_mistakes
            ],
            interview_readiness=readiness.overall,
            coding_speed_index=await self._coding_speed(profile.id),
            debugging_score=self._skill_value(skill_rows, "debugging"),
            architecture_score=self._skill_value(skill_rows, "architecture"),
            production_score=self._skill_value(skill_rows, "devops"),
            consistency_score=self._consistency(activity),
            practice_minutes_7d=practice_7d,
            practice_minutes_30d=practice_30d,
        )

    # ── Readiness ─────────────────────────────────────────────────────────
    async def interview_readiness(self, profile: PlayerProfile) -> ReadinessBreakdown:
        skill_rows = {s.skill_slug: s for s in await self.skills.for_profile(profile.id)}

        components: list[dict[str, Any]] = []
        weighted = 0.0
        for slug, weight in READINESS_WEIGHTS.items():
            row = skill_rows.get(slug)
            value = row.effective_mastery if row else 0.0
            weighted += value * weight
            components.append(
                {
                    "slug": slug,
                    "name": SKILL_BY_SLUG[slug].name if slug in SKILL_BY_SLUG else slug,
                    "weight": weight,
                    "value": round(value, 4),
                    "contribution": round(value * weight, 4),
                    # What this component *could* contribute if maxed — the
                    # honest way to show where the headroom actually is.
                    "headroom": round((1.0 - value) * weight, 4),
                }
            )

        # Interview *performance* is evidence that outranks self-study mastery,
        # so it is blended in once there is enough of it.
        avg_answer = await self.questions.average_score(profile.id)
        answered = await self.session.execute(
            select(func.count())
            .select_from(QuestionAttempt)
            .where(QuestionAttempt.profile_id == profile.id)
        )
        answer_count = int(answered.scalar_one())
        if answer_count >= 10:
            evidence_weight = min(0.35, 0.35 * (answer_count / 50))
            weighted = weighted * (1 - evidence_weight) + (avg_answer / 10.0) * evidence_weight
            components.append(
                {
                    "slug": "interview_evidence",
                    "name": "Interview answers to date",
                    "weight": round(evidence_weight, 4),
                    "value": round(avg_answer / 10.0, 4),
                    "contribution": round((avg_answer / 10.0) * evidence_weight, 4),
                    "headroom": round((1 - avg_answer / 10.0) * evidence_weight, 4),
                }
            )

        overall = round(min(1.0, weighted), 4)
        by_level = {
            "junior": round(min(1.0, overall / 0.35), 4),
            "mid": round(min(1.0, overall / 0.50), 4),
            "senior": round(min(1.0, overall / 0.68), 4),
            "staff": round(min(1.0, overall / 0.82), 4),
            "principal": round(min(1.0, overall / 0.92), 4),
        }
        blocking = sorted(components, key=lambda c: -c["headroom"])[:4]
        return ReadinessBreakdown(
            overall=overall,
            by_level=by_level,
            components=sorted(components, key=lambda c: -c["contribution"]),
            blocking_gaps=blocking,
            next_actions=[
                {
                    "kind": "skill",
                    "slug": g["slug"],
                    "title": f"Raise {g['name']}",
                    "reason": (
                        f"At {g['value']:.0%}. It carries {g['weight']:.0%} of readiness, "
                        f"so this is the largest single gain available."
                    ),
                }
                for g in blocking[:3]
            ],
        )

    # ── Helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _skill_value(rows: list, slug: str) -> float:
        row = next((r for r in rows if r.skill_slug == slug), None)
        return round(row.effective_mastery if row else 0.0, 4)

    @staticmethod
    def _consistency(activity: list[tuple]) -> float:
        """Fraction of the last 30 days with any activity.

        Consistency predicts long-term retention better than volume does, which
        is why it gets its own gauge rather than hiding inside XP.
        """
        return round(len(activity) / 30.0, 4) if activity else 0.0

    async def _practice_minutes(self, profile_id: uuid.UUID) -> tuple[int, int]:
        now = datetime.now(UTC)
        out = []
        for days in (7, 30):
            total = (
                await self.session.execute(
                    select(func.sum(LearningEvent.elapsed_seconds)).where(
                        LearningEvent.profile_id == profile_id,
                        LearningEvent.created_at >= now - timedelta(days=days),
                    )
                )
            ).scalar_one()
            out.append(int((total or 0) // 60))
        return out[0], out[1]

    async def _coding_speed(self, profile_id: uuid.UUID) -> float:
        """Median elapsed/par ratio, inverted so 1.0 means "at par or better"."""
        rows = (
            await self.session.execute(
                select(LearningEvent.elapsed_seconds, LearningEvent.tier)
                .where(
                    LearningEvent.profile_id == profile_id,
                    LearningEvent.event_type == "challenge_submitted",
                    LearningEvent.elapsed_seconds.is_not(None),
                )
                .order_by(LearningEvent.created_at.desc())
                .limit(50)
            )
        ).all()
        if not rows:
            return 0.0
        ratios = []
        for elapsed, tier in rows:
            par = 120 + 60 * (tier or 3)
            ratios.append(min(2.0, par / max(1, elapsed)))
        ratios.sort()
        median = ratios[len(ratios) // 2]
        return round(min(1.0, median / 1.5), 4)

    async def retention_summary(self, profile: PlayerProfile) -> dict[str, Any]:
        dashboard = await self.retention.dashboard(profile.id)
        return {
            "overall_retention": dashboard.overall_retention,
            "tracked": dashboard.concepts_tracked,
            "due": dashboard.concepts_due,
            "decayed": dashboard.concepts_decayed,
            "critical": dashboard.concepts_critical,
            "calibration_error": await self.retention.calibration(profile.id),
        }

    async def event_histogram(self, profile_id: uuid.UUID, days: int = 30) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(LearningEvent.event_type).where(
                    LearningEvent.profile_id == profile_id,
                    LearningEvent.created_at >= datetime.now(UTC) - timedelta(days=days),
                )
            )
        ).all()
        return dict(Counter(r[0] for r in rows))
