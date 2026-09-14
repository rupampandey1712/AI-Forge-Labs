"""Persists and queries the Knowledge Retention Engine.

Two responsibilities, kept strictly apart:

1. **Translation.** ``ConceptProgress`` (a row) <-> ``ReviewState`` (a value).
   The engine stays pure and the row stays dumb. Every rule lives in
   ``app/game/retention/model.py`` and is unit-tested without a database.
2. **Aggregation.** Rolling per-concept decay up into per-skill mastery, and
   turning "this decayed" into an actionable alert with a repair mission.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import DifficultyTier
from app.game.retention.model import (
    DecayReport,
    ReviewState,
    bootstrap,
    calibration_error,
    decay_report,
    effective_mastery,
    retrievability,
    review,
)
from app.game.skills.registry import SKILL_BY_SLUG, skill_for_category
from app.models.content import Concept
from app.models.progress import ConceptProgress, SkillProgress
from app.repositories.player import ConceptProgressRepository, SkillProgressRepository
from app.schemas.retention import (
    ConceptDecayOut,
    DecayAlertOut,
    RetentionDashboardOut,
    ReviewScheduleOut,
)

log = get_logger(__name__)

#: How many days of "silence" before a decayed concept earns an emergency
#: mission rather than a quiet nudge. Tuned so the spec's scenarios fire:
#: 30+ days on a mid-strength memory, 45+ on a strong one.
EMERGENCY_AFTER_DAYS = 21


def to_state(row: ConceptProgress) -> ReviewState:
    return ReviewState(
        stability_days=row.stability_days,
        ease=row.ease,
        interval_days=row.interval_days,
        repetitions=row.repetitions,
        lapses=row.lapses,
        attempts=row.attempts,
        correct=row.correct,
        mastery=row.mastery,
        peak_mastery=row.peak_mastery,
        confidence=row.confidence,
        last_seen=row.last_seen,
        last_correct=row.last_correct,
        last_incorrect=row.last_incorrect,
        due_at=row.due_at,
        highest_tier_cleared=row.highest_tier_cleared,
    )


def apply_state(row: ConceptProgress, state: ReviewState, *, now: datetime) -> None:
    row.stability_days = state.stability_days
    row.ease = state.ease
    row.interval_days = state.interval_days
    row.repetitions = state.repetitions
    row.lapses = state.lapses
    row.attempts = state.attempts
    row.correct = state.correct
    row.mastery = state.mastery
    row.peak_mastery = state.peak_mastery
    row.confidence = state.confidence
    row.last_seen = state.last_seen
    row.last_correct = state.last_correct
    row.last_incorrect = state.last_incorrect
    row.due_at = state.due_at
    row.highest_tier_cleared = state.highest_tier_cleared
    report = decay_report(state, now)
    row.last_decay_snapshot = {
        "retrievability": report.retrievability,
        "effective_mastery": report.effective_mastery,
        "urgency": report.urgency,
        "computed_at": now.isoformat(),
    }


class RetentionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.concepts = ConceptProgressRepository(session)
        self.skills = SkillProgressRepository(session)

    # ── Recording ─────────────────────────────────────────────────────────
    async def record_review(
        self,
        profile_id: uuid.UUID,
        concept_slugs: list[str],
        *,
        score: float,
        tier: DifficultyTier | int,
        now: datetime | None = None,
        hints_used: int = 0,
        confidence: float | None = None,
        elapsed_seconds: int | None = None,
        par_seconds: int | None = None,
    ) -> list[ReviewScheduleOut]:
        """Fold one graded attempt into every concept it exercised.

        A challenge usually touches 2-4 concepts. Crediting all of them is what
        makes the retention model track *understanding* rather than a per-exercise
        score — solving an async challenge should refresh ``python.asyncio``
        even though the player never opened that concept page.
        """
        if not concept_slugs:
            return []
        now = now or datetime.now(UTC)
        time_pressure = 1.0
        if elapsed_seconds and par_seconds and par_seconds > 0:
            time_pressure = max(1.0, elapsed_seconds / par_seconds)

        existing = await self.concepts.get_many(profile_id, concept_slugs)
        meta = await self._concept_meta(concept_slugs)
        out: list[ReviewScheduleOut] = []

        for slug in concept_slugs:
            info = meta.get(slug)
            if info is None:
                # A challenge referencing an unseeded concept is a content bug,
                # not a player-facing failure: log it and keep grading.
                log.warning("retention.unknown_concept", concept_slug=slug)
                continue
            row = existing.get(slug)
            if row is None:
                row = ConceptProgress(
                    profile_id=profile_id,
                    concept_slug=slug,
                    skill_slug=info["skill_slug"],
                    category=info["category"],
                )
                self.session.add(row)
                await self.session.flush()

            before = to_state(row)
            after = review(
                before,
                score=score,
                tier=tier,
                now=now,
                hints_used=hints_used,
                confidence=confidence,
                time_pressure=time_pressure,
            )
            apply_state(row, after, now=now)
            out.append(
                ReviewScheduleOut(
                    concept_slug=slug,
                    previous_interval_days=round(before.interval_days, 2),
                    new_interval_days=round(after.interval_days, 2),
                    due_at=after.due_at or now,
                    stability_days=round(after.stability_days, 2),
                    ease=round(after.ease, 3),
                    mastery_before=round(effective_mastery(before, now), 4),
                    mastery_after=round(after.mastery, 4),
                    repetitions=after.repetitions,
                    lapses=after.lapses,
                )
            )

        await self._recompute_skills(profile_id, {meta[s]["skill_slug"] for s in meta}, now=now)
        return out

    async def introduce(
        self, profile_id: uuid.UUID, concept_slugs: list[str], *, now: datetime | None = None
    ) -> None:
        """Mark concepts as *seen but not tested* — schedules a first review."""
        now = now or datetime.now(UTC)
        existing = await self.concepts.get_many(profile_id, concept_slugs)
        meta = await self._concept_meta(concept_slugs)
        for slug in concept_slugs:
            if slug in existing or slug not in meta:
                continue
            row = ConceptProgress(
                profile_id=profile_id,
                concept_slug=slug,
                skill_slug=meta[slug]["skill_slug"],
                category=meta[slug]["category"],
            )
            apply_state(row, bootstrap(now), now=now)
            self.session.add(row)

    async def _concept_meta(self, slugs: list[str]) -> dict[str, dict[str, str]]:
        if not slugs:
            return {}
        stmt = select(Concept.slug, Concept.skill_slug, Concept.category, Concept.title).where(
            Concept.slug.in_(slugs)
        )
        rows = (await self.session.execute(stmt)).all()
        return {
            r[0]: {
                "skill_slug": r[1] or skill_for_category(r[2]),
                "category": r[2],
                "title": r[3],
            }
            for r in rows
        }

    # ── Aggregation ───────────────────────────────────────────────────────
    async def _recompute_skills(
        self, profile_id: uuid.UUID, skill_slugs: set[str], *, now: datetime
    ) -> None:
        """Roll concept mastery up into skill mastery.

        WHY the top-quartile weighting: a plain mean punishes breadth — someone
        who has touched 40 Python concepts at varying depth would score lower
        than someone who did 3 perfectly. We blend the mean (breadth) with the
        mean of the strongest quarter (depth) so both count.
        """
        for skill_slug in skill_slugs:
            rows = await self.concepts.for_skill(profile_id, skill_slug)
            if not rows:
                continue
            states = [to_state(r) for r in rows]
            masteries = sorted((s.mastery for s in states), reverse=True)
            effectives = [effective_mastery(s, now) for s in states]
            top_n = max(1, len(masteries) // 4)
            blended = 0.5 * (sum(masteries) / len(masteries)) + 0.5 * (
                sum(masteries[:top_n]) / top_n
            )
            eff_blend = blended * (
                (sum(effectives) / len(effectives)) / (sum(masteries) / len(masteries))
                if sum(masteries) > 0
                else 0.0
            )

            row = await self.skills.get_or_none(profile_id, skill_slug)
            if row is None:
                row = SkillProgress(profile_id=profile_id, skill_slug=skill_slug)
                self.session.add(row)
                await self.session.flush()

            row.mastery = round(min(1.0, blended), 4)
            row.effective_mastery = round(min(1.0, eff_blend), 4)
            row.peak_mastery = round(max(row.peak_mastery, row.mastery), 4)
            row.forgetting_score = round(max(0.0, row.mastery - row.effective_mastery), 4)
            row.attempts = sum(s.attempts for s in states)
            row.correct = sum(s.correct for s in states)
            row.highest_tier_cleared = max((s.highest_tier_cleared for s in states), default=0)
            row.confidence = round(
                sum(s.confidence for s in states) / len(states) if states else 0.0, 4
            )
            row.last_practiced_at = max(
                (s.last_seen for s in states if s.last_seen), default=row.last_practiced_at
            )

    async def recompute_all_skills(self, profile_id: uuid.UUID) -> None:
        rows = await self.concepts.for_profile(profile_id)
        await self._recompute_skills(
            profile_id, {r.skill_slug for r in rows}, now=datetime.now(UTC)
        )

    # ── Reading ───────────────────────────────────────────────────────────
    async def concept_decay(
        self, profile_id: uuid.UUID, *, now: datetime | None = None
    ) -> list[tuple[ConceptProgress, DecayReport]]:
        now = now or datetime.now(UTC)
        rows = await self.concepts.for_profile(profile_id)
        return [(r, decay_report(to_state(r), now)) for r in rows]

    async def dashboard(
        self, profile_id: uuid.UUID, *, now: datetime | None = None
    ) -> RetentionDashboardOut:
        now = now or datetime.now(UTC)
        pairs = await self.concept_decay(profile_id, now=now)
        titles = await self._titles([r.concept_slug for r, _ in pairs])

        items = [
            _to_decay_out(row, rep, titles.get(row.concept_slug, row.concept_slug))
            for row, rep in pairs
        ]
        tracked = [i for i in items if i.attempts > 0]

        due = sorted([i for i in tracked if i.is_due], key=lambda i: -i.urgency)
        decayed = [i for i in tracked if i.is_decayed]
        critical = [i for i in tracked if i.is_critical]
        upcoming = sorted(
            [i for i in tracked if not i.is_due and i.due_at],
            key=lambda i: i.due_at or now,
        )[:12]
        strongest = sorted(tracked, key=lambda i: -i.effective_mastery)[:8]
        weakest = sorted(
            [i for i in tracked if i.attempts >= 2], key=lambda i: i.effective_mastery
        )[:8]
        recently_forgotten = sorted(decayed, key=lambda i: -i.mastery_drop)[:8]

        overall = (
            round(sum(i.retrievability for i in tracked) / len(tracked), 4) if tracked else 0.0
        )

        by_skill: list[dict[str, Any]] = []
        grouped: dict[str, list[ConceptDecayOut]] = defaultdict(list)
        for item in tracked:
            grouped[item.skill_slug].append(item)
        for slug, group in grouped.items():
            sdef = SKILL_BY_SLUG.get(slug)
            by_skill.append(
                {
                    "skill_slug": slug,
                    "name": sdef.name if sdef else slug,
                    "color": sdef.color if sdef else "#38bdf8",
                    "concepts": len(group),
                    "due": sum(1 for i in group if i.is_due),
                    "decayed": sum(1 for i in group if i.is_decayed),
                    "mastery": round(sum(i.mastery for i in group) / len(group), 4),
                    "effective_mastery": round(
                        sum(i.effective_mastery for i in group) / len(group), 4
                    ),
                }
            )
        by_skill.sort(key=lambda d: d["effective_mastery"])

        return RetentionDashboardOut(
            generated_at=now,
            overall_retention=overall,
            concepts_tracked=len(tracked),
            concepts_due=len(due),
            concepts_decayed=len(decayed),
            concepts_critical=len(critical),
            alerts=await self.alerts(profile_id, now=now, precomputed=pairs, titles=titles),
            due_now=due[:20],
            upcoming=upcoming,
            strongest=strongest,
            weakest=weakest,
            recently_forgotten=recently_forgotten,
            by_skill=by_skill,
            forecast=_forecast(pairs, now),
        )

    async def alerts(
        self,
        profile_id: uuid.UUID,
        *,
        now: datetime | None = None,
        precomputed: list[tuple[ConceptProgress, DecayReport]] | None = None,
        titles: dict[str, str] | None = None,
        limit: int = 5,
    ) -> list[DecayAlertOut]:
        """Turn decay into the banner the player sees on the dashboard.

        Alerts are grouped **by skill**, not per concept: "12 separate concepts
        decayed" is noise the player will dismiss; "your RAG knowledge fell from
        84% to 61% — here is the repair mission" is something they will act on.
        """
        now = now or datetime.now(UTC)
        pairs = (
            precomputed
            if precomputed is not None
            else await self.concept_decay(profile_id, now=now)
        )
        titles = titles or await self._titles([r.concept_slug for r, _ in pairs])

        by_skill: dict[str, list[tuple[ConceptProgress, DecayReport]]] = defaultdict(list)
        for row, rep in pairs:
            if row.attempts > 0 and rep.is_decayed and rep.days_since_practice >= 7:
                by_skill[row.skill_slug].append((row, rep))

        alerts: list[DecayAlertOut] = []
        for skill_slug, group in by_skill.items():
            sdef = SKILL_BY_SLUG.get(skill_slug)
            name = sdef.name if sdef else skill_slug
            peak = sum(r.peak_mastery for _, r in group) / len(group)
            eff = sum(r.effective_mastery for _, r in group) / len(group)
            worst_days = max(r.days_since_practice for _, r in group)
            critical = any(r.is_critical for _, r in group)
            emergency = worst_days >= EMERGENCY_AFTER_DAYS or critical

            concept_slugs = [
                row.concept_slug for row, _ in sorted(group, key=lambda p: -p[1].urgency)
            ][:6]
            headline_concept = (
                titles.get(concept_slugs[0], concept_slugs[0]) if concept_slugs else name
            )

            alerts.append(
                DecayAlertOut(
                    severity="critical" if critical else ("warning" if emergency else "info"),
                    scope="skill",
                    slug=skill_slug,
                    title=name,
                    headline=(
                        f"⚠ {name.upper()} KNOWLEDGE DECAY DETECTED"
                        if emergency
                        else f"{name} is starting to fade"
                    ),
                    detail=(
                        f"Your {name} mastery dropped from {peak:.0%} → {eff:.0%}. "
                        f"{len(group)} concept{'s' if len(group) > 1 else ''} including "
                        f"“{headline_concept}” have not been practised for "
                        f"{worst_days:.0f} days."
                    ),
                    from_mastery=round(peak, 4),
                    to_mastery=round(eff, 4),
                    days_since_practice=round(worst_days, 1),
                    repair_mission_slug=None,  # filled in by MissionService
                    repair_kind="emergency" if emergency else "review",
                    concept_slugs=concept_slugs,
                )
            )

        alerts.sort(
            key=lambda a: (
                a.severity != "critical",
                a.severity != "warning",
                -a.days_since_practice,
            )
        )
        return alerts[:limit]

    async def due_concepts(
        self, profile_id: uuid.UUID, *, limit: int = 20, now: datetime | None = None
    ) -> list[tuple[ConceptProgress, DecayReport]]:
        now = now or datetime.now(UTC)
        rows = await self.concepts.due_before(profile_id, now, limit=limit * 3)
        scored = [(r, decay_report(to_state(r), now)) for r in rows]
        scored.sort(key=lambda p: -p[1].urgency)
        return scored[:limit]

    async def _titles(self, slugs: list[str]) -> dict[str, str]:
        if not slugs:
            return {}
        stmt = select(Concept.slug, Concept.title).where(Concept.slug.in_(slugs))
        return {r[0]: r[1] for r in (await self.session.execute(stmt)).all()}

    async def calibration(self, profile_id: uuid.UUID) -> float:
        """Mean confidence-vs-accuracy gap across tracked concepts."""
        rows = await self.concepts.for_profile(profile_id)
        errors = [calibration_error(to_state(r)) for r in rows if r.attempts >= 3]
        return round(sum(errors) / len(errors), 4) if errors else 0.0


def _to_decay_out(row: ConceptProgress, rep: DecayReport, title: str) -> ConceptDecayOut:
    return ConceptDecayOut(
        concept_slug=row.concept_slug,
        title=title,
        category=row.category,
        skill_slug=row.skill_slug,
        mastery=round(row.mastery, 4),
        peak_mastery=rep.peak_mastery,
        effective_mastery=rep.effective_mastery,
        retrievability=rep.retrievability,
        forgetting_probability=rep.forgetting_probability,
        mastery_drop=rep.mastery_drop,
        days_since_practice=rep.days_since_practice,
        urgency=rep.urgency,
        is_due=rep.is_due,
        is_decayed=rep.is_decayed,
        is_critical=rep.is_critical,
        due_at=row.due_at,
        lapses=row.lapses,
        attempts=row.attempts,
        accuracy=round(row.correct / row.attempts, 4) if row.attempts else 0.0,
    )


def _forecast(
    pairs: list[tuple[ConceptProgress, DecayReport]], now: datetime, days: int = 90
) -> list[dict[str, Any]]:
    """Project average retention forward if the player does nothing.

    Rendering this as a falling line next to a flat "if you keep practising"
    line is the most persuasive thing the dashboard does — it makes an abstract
    forgetting curve personal.
    """
    states = [to_state(row) for row, _ in pairs if row.attempts > 0]
    if not states:
        return []
    points: list[dict[str, Any]] = []
    for offset in range(0, days + 1, 5):
        at = now + timedelta(days=offset)
        avg_r = sum(retrievability(s, at) for s in states) / len(states)
        avg_m = sum(effective_mastery(s, at) for s in states) / len(states)
        points.append(
            {
                "day": offset,
                "date": at.date().isoformat(),
                "retention": round(avg_r, 4),
                "effective_mastery": round(avg_m, 4),
            }
        )
    return points
