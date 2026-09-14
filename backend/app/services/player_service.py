"""Dashboard, world map, skill trees and the leaderboard."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.domain.enums import RANK_ORDER, Rank
from app.game.skills.registry import (
    BUILDINGS,
    SKILL_BY_SLUG,
    SKILL_TREES,
    SkillId,
    building_unlock_state,
)
from app.models.content import Concept, Mission
from app.models.progress import ConceptProgress, MissionAttempt, SkillProgress
from app.models.user import PlayerProfile
from app.repositories.player import (
    AchievementProgressRepository,
    BadgeProgressRepository,
    LearningEventRepository,
    MistakeRepository,
    ProfileRepository,
    SkillProgressRepository,
)
from app.schemas.player import (
    BuildingOut,
    DashboardOut,
    LeaderboardRow,
    PlayerProfileOut,
    SkillNodeOut,
    SkillProgressOut,
    SkillTreeOut,
    WorldMapOut,
)
from app.services.progression_service import decorate_profile
from app.services.retention_service import RetentionService


class PlayerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profiles = ProfileRepository(session)
        self.skills = SkillProgressRepository(session)
        self.events = LearningEventRepository(session)
        self.badges = BadgeProgressRepository(session)
        self.achievements = AchievementProgressRepository(session)
        self.mistakes = MistakeRepository(session)
        self.retention = RetentionService(session)

    # ── Profile ───────────────────────────────────────────────────────────
    def to_profile_out(self, profile: PlayerProfile) -> PlayerProfileOut:
        base = PlayerProfileOut.model_validate(profile)
        for key, value in decorate_profile(profile).items():
            setattr(base, key, value)
        return base

    async def get_profile(self, profile_id: uuid.UUID) -> PlayerProfile:
        profile = await self.profiles.get(profile_id)
        if profile is None:
            raise NotFoundError("Player profile not found.")
        return profile

    # ── Skills ────────────────────────────────────────────────────────────
    async def skill_progress(self, profile_id: uuid.UUID) -> list[SkillProgressOut]:
        rows = await self.skills.for_profile(profile_id)
        counts = await self._concept_counts(profile_id)
        out: list[SkillProgressOut] = []
        for row in rows:
            sdef = SKILL_BY_SLUG.get(row.skill_slug)
            stats = counts.get(row.skill_slug, {})
            out.append(
                SkillProgressOut(
                    skill_slug=row.skill_slug,
                    name=sdef.name if sdef else row.skill_slug,
                    icon=sdef.icon if sdef else "sparkles",
                    color=sdef.color if sdef else "#38bdf8",
                    level=row.level,
                    xp=row.xp,
                    mastery=row.mastery,
                    effective_mastery=row.effective_mastery,
                    peak_mastery=row.peak_mastery,
                    confidence=row.confidence,
                    forgetting_score=row.forgetting_score,
                    highest_tier_cleared=row.highest_tier_cleared,
                    attempts=row.attempts,
                    correct=row.correct,
                    accuracy=round(row.correct / row.attempts, 4) if row.attempts else 0.0,
                    streak=row.streak,
                    last_practiced_at=row.last_practiced_at,
                    concepts_total=stats.get("total", 0),
                    concepts_started=stats.get("started", 0),
                    concepts_due=stats.get("due", 0),
                    concepts_decayed=stats.get("decayed", 0),
                )
            )
        out.sort(
            key=lambda s: (
                SKILL_BY_SLUG[s.skill_slug].display_order if s.skill_slug in SKILL_BY_SLUG else 99
            )
        )
        return out

    async def _concept_counts(self, profile_id: uuid.UUID) -> dict[str, dict[str, int]]:
        """Per-skill concept counts in two grouped queries, not 16 x N.

        The naive version of this panel (loop skills, count concepts, count
        progress) is 33 queries. This is 2.
        """
        now = datetime.now(UTC)
        totals = {
            row[0]: int(row[1])
            for row in (
                await self.session.execute(
                    select(Concept.skill_slug, func.count()).group_by(Concept.skill_slug)
                )
            ).all()
        }
        rows = (
            await self.session.execute(
                select(
                    ConceptProgress.skill_slug,
                    func.count(),
                    func.sum(
                        func.cast(
                            ConceptProgress.due_at <= now,
                            __import__("sqlalchemy").Integer,
                        )
                    ),
                )
                .where(ConceptProgress.profile_id == profile_id, ConceptProgress.attempts > 0)
                .group_by(ConceptProgress.skill_slug)
            )
        ).all()
        started = {r[0]: (int(r[1]), int(r[2] or 0)) for r in rows}

        out: dict[str, dict[str, int]] = {}
        for slug, total in totals.items():
            s, due = started.get(slug, (0, 0))
            out[slug] = {"total": total, "started": s, "due": due, "decayed": due}
        for slug, (s, due) in started.items():
            out.setdefault(slug, {"total": 0, "started": s, "due": due, "decayed": due})
        return out

    async def skill_tree(self, profile_id: uuid.UUID, skill_slug: str) -> SkillTreeOut:
        sdef = SKILL_BY_SLUG.get(skill_slug)
        if sdef is None:
            raise NotFoundError(f"Unknown skill '{skill_slug}'.")
        profile = await self.profiles.get(profile_id)
        if profile is None:
            raise NotFoundError("Player profile not found.")

        progress_rows = await self.skills.as_map(profile_id)
        progress = progress_rows.get(skill_slug)

        concepts = list(
            (
                await self.session.execute(
                    select(Concept.slug, Concept.skill_node_slug).where(
                        Concept.skill_slug == skill_slug
                    )
                )
            ).all()
        )
        by_node: dict[str, list[str]] = {}
        for slug, node in concepts:
            by_node.setdefault(node or "", []).append(slug)

        cp_rows = await self.session.execute(
            select(ConceptProgress.concept_slug, ConceptProgress.mastery).where(
                ConceptProgress.profile_id == profile_id,
                ConceptProgress.skill_slug == skill_slug,
            )
        )
        mastery_by_concept = {r[0]: r[1] for r in cp_rows.all()}

        nodes: list[SkillNodeOut] = []
        for i, node in enumerate(SKILL_TREES.get(SkillId(skill_slug), ())):
            node_concepts = by_node.get(node.slug, [])
            masteries = [mastery_by_concept.get(c, 0.0) for c in node_concepts]
            avg = round(sum(masteries) / len(masteries), 4) if masteries else 0.0
            nodes.append(
                SkillNodeOut(
                    slug=node.slug,
                    name=node.name,
                    summary=node.summary,
                    parent_slug=node.parent,
                    tier_range=list(node.tier_range),
                    unlock_level=node.unlock_level,
                    display_order=i,
                    unlocked=profile.level >= node.unlock_level,
                    mastery=avg,
                    concepts_total=len(node_concepts),
                    concepts_mastered=sum(1 for m in masteries if m >= 0.7),
                )
            )

        skill_out = (await self.skill_progress(profile_id)) if progress else []
        return SkillTreeOut(
            skill_slug=skill_slug,
            name=sdef.name,
            description=sdef.description,
            icon=sdef.icon,
            color=sdef.color,
            building=sdef.building.value,
            progress=next((s for s in skill_out if s.skill_slug == skill_slug), None),
            nodes=nodes,
        )

    # ── World map ─────────────────────────────────────────────────────────
    async def world_map(self, profile: PlayerProfile) -> WorldMapOut:
        rank_index = RANK_ORDER.index(Rank(profile.rank))
        skill_rows = await self.skills.as_map(profile.id)
        mission_counts = await self._mission_counts(profile.id)
        alerts = await self.retention.alerts(profile.id)
        alert_by_skill = {a.slug: a for a in alerts}

        buildings: list[BuildingOut] = []
        for b in BUILDINGS:
            state = building_unlock_state(b, profile.level, rank_index)
            skill_slugs = [s.value for s in b.skills]
            masteries = [skill_rows[s].effective_mastery for s in skill_slugs if s in skill_rows]
            alert = next((alert_by_skill[s] for s in skill_slugs if s in alert_by_skill), None)
            counts = mission_counts.get(b.id.value, {"total": 0, "done": 0})
            buildings.append(
                BuildingOut(
                    id=b.id.value,
                    name=b.name,
                    tagline=b.tagline,
                    description=b.description,
                    skill_slugs=skill_slugs,
                    categories=[c.value for c in b.categories],
                    required_level=b.required_level,
                    required_rank=b.required_rank.value if b.required_rank else None,
                    position={"x": b.position[0], "y": b.position[1]},
                    accent=b.accent,
                    icon=b.icon,
                    unlocked=state.unlocked,
                    mission_count=counts["total"],
                    missions_completed=counts["done"],
                    mastery=round(sum(masteries) / len(masteries), 4) if masteries else 0.0,
                    has_alert=alert is not None,
                    alert_text=alert.headline
                    if alert
                    else (state.reason if not state.unlocked else None),
                )
            )

        return WorldMapOut(
            profile=self.to_profile_out(profile),
            buildings=buildings,
            alerts=[a.model_dump() for a in alerts],
        )

    async def _mission_counts(self, profile_id: uuid.UUID) -> dict[str, dict[str, int]]:
        totals = {
            r[0]: int(r[1])
            for r in (
                await self.session.execute(
                    select(Mission.building, func.count()).group_by(Mission.building)
                )
            ).all()
        }
        done_rows = (
            await self.session.execute(
                select(Mission.building, func.count(func.distinct(MissionAttempt.mission_slug)))
                .join(MissionAttempt, MissionAttempt.mission_slug == Mission.slug)
                .where(MissionAttempt.profile_id == profile_id, MissionAttempt.status == "passed")
                .group_by(Mission.building)
            )
        ).all()
        done = {r[0]: int(r[1]) for r in done_rows}
        return {b: {"total": t, "done": done.get(b, 0)} for b, t in totals.items()}

    # ── Dashboard ─────────────────────────────────────────────────────────
    async def dashboard(self, profile: PlayerProfile) -> DashboardOut:
        now = datetime.now(UTC)
        skills = await self.skill_progress(profile.id)
        alerts = await self.retention.alerts(profile.id, now=now)
        due = await self.retention.due_concepts(profile.id, limit=50, now=now)
        events = await self.events.recent(profile.id, limit=12)
        open_mistakes = await self.mistakes.open_for_profile(profile.id, limit=5)
        unseen = await self.badges.unseen(profile.id)

        weakest = sorted([s for s in skills if s.attempts > 0], key=lambda s: s.effective_mastery)[
            :3
        ]
        recommended: list[dict[str, Any]] = [
            {
                "kind": "skill",
                "slug": s.skill_slug,
                "title": f"Strengthen {s.name}",
                "reason": f"Weakest tracked skill at {s.effective_mastery:.0%} mastery.",
            }
            for s in weakest
        ]
        for row, report in due[:3]:
            recommended.append(
                {
                    "kind": "review",
                    "slug": row.concept_slug,
                    "title": f"Review: {row.concept_slug}",
                    "reason": f"Recall probability has fallen to {report.retrievability:.0%}.",
                }
            )

        from app.models.content import Badge as BadgeModel
        from app.schemas.player import BadgeOut

        unseen_out: list[BadgeOut] = []
        if unseen:
            badge_rows = (
                await self.session.execute(
                    select(BadgeModel).where(BadgeModel.slug.in_([b.badge_slug for b in unseen]))
                )
            ).scalars()
            by_slug = {b.slug: b for b in badge_rows}
            for pb in unseen:
                spec = by_slug.get(pb.badge_slug)
                if spec:
                    unseen_out.append(
                        BadgeOut(
                            slug=spec.slug,
                            name=spec.name,
                            description=spec.description,
                            tier=spec.tier,
                            icon=spec.icon,
                            xp_reward=spec.xp_reward,
                            earned=True,
                            earned_at=pb.earned_at,
                        )
                    )

        return DashboardOut(
            profile=self.to_profile_out(profile),
            skills=skills,
            retention_alerts=[a.model_dump() for a in alerts],
            due_reviews=len(due),
            recent_events=[
                {
                    "type": e.event_type,
                    "concept_slug": e.concept_slug,
                    "skill_slug": e.skill_slug,
                    "score": e.score,
                    "tier": e.tier,
                    "at": e.created_at.isoformat(),
                    "payload": e.payload,
                }
                for e in events
            ],
            recommended=recommended,
            open_mistakes=[
                {
                    "pattern": m.pattern,
                    "title": m.title,
                    "severity": m.severity,
                    "occurrences": m.occurrences,
                    "why_it_matters": m.why_it_matters,
                }
                for m in open_mistakes
            ],
            unseen_badges=unseen_out,
            streak_calendar=await self._streak_calendar(profile.id),
        )

    async def _streak_calendar(self, profile_id: uuid.UUID, days: int = 84) -> list[dict[str, Any]]:
        active = dict(await self.events.active_days(profile_id, days=days))
        today = datetime.now(UTC).date()
        return [
            {
                "date": (today - timedelta(days=offset)).isoformat(),
                "count": active.get(today - timedelta(days=offset), 0),
            }
            for offset in range(days - 1, -1, -1)
        ]

    # ── Leaderboard ───────────────────────────────────────────────────────
    async def leaderboard(
        self, profile_id: uuid.UUID | None = None, limit: int = 25
    ) -> list[LeaderboardRow]:
        rows = await self.profiles.top_by_xp(limit=limit)
        return [
            LeaderboardRow(
                position=i + 1,
                display_name=r.display_name,
                xp=r.total_xp,
                level=r.level,
                rank=r.rank,
                is_me=r.id == profile_id,
            )
            for i, r in enumerate(rows)
        ]

    async def mark_badges_seen(self, profile_id: uuid.UUID) -> int:
        rows = await self.badges.unseen(profile_id)
        for row in rows:
            row.seen = True
        return len(rows)

    async def ensure_skill_rows(self, profile: PlayerProfile) -> None:
        """Backfill missing skill rows after a content update adds a skill."""
        existing = {s.skill_slug for s in await self.skills.for_profile(profile.id)}
        for sdef in SKILL_BY_SLUG.values():
            if sdef.slug.value not in existing:
                self.session.add(SkillProgress(profile_id=profile.id, skill_slug=sdef.slug.value))
