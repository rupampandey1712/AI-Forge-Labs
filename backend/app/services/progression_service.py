"""Applies XP, levels, ranks, coins, streaks, badges and achievements.

This is the one place allowed to mutate ``PlayerProfile.total_xp``. Every other
service produces ``XPGrant`` objects and hands them here. Centralising it means
the ledger can never disagree with the counter, and the level-up/rank-up events
fire exactly once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import RANK_ORDER, Rank, XPSource
from app.game.achievements.rules import evaluate_unlocks
from app.game.skills.registry import BUILDINGS, building_unlock_state
from app.game.xp.engine import (
    ProgressionResult,
    XPGrant,
    apply_xp,
    coins_for_grants,
    experience_band_for_level,
    next_rank,
    rank_for_level,
    total_xp_for_level,
    xp_to_next_level,
)
from app.models.content import Achievement, Badge
from app.models.progress import (
    LearningEvent,
    PlayerAchievement,
    PlayerBadge,
    SkillProgress,
    XPTransaction,
)
from app.models.user import PlayerProfile
from app.repositories.player import (
    AchievementProgressRepository,
    BadgeProgressRepository,
    LearningEventRepository,
    ProfileRepository,
    SkillProgressRepository,
    XPRepository,
)
from app.schemas.player import ProgressionOut, XPGrantOut

log = get_logger(__name__)

#: A streak survives one missed day. Rewarding perfection punishes the player
#: who gets sick on day 40, and losing a long streak is the single most common
#: reason people abandon a daily-practice app for good.
STREAK_GRACE_DAYS = 1


class ProgressionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profiles = ProfileRepository(session)
        self.skills = SkillProgressRepository(session)
        self.xp = XPRepository(session)
        self.badges = BadgeProgressRepository(session)
        self.achievements = AchievementProgressRepository(session)
        self.events = LearningEventRepository(session)

    # ── XP ────────────────────────────────────────────────────────────────
    async def award(
        self,
        profile: PlayerProfile,
        grants: list[XPGrant],
        *,
        skill_slug: str | None = None,
        reference_type: str | None = None,
        reference_slug: str | None = None,
        now: datetime | None = None,
    ) -> ProgressionOut:
        """Apply grants, write the ledger, and return the animation payload."""
        now = now or datetime.now(UTC)
        result: ProgressionResult = apply_xp(profile.total_xp, grants)
        coins = coins_for_grants(grants)

        running = profile.total_xp
        for grant in grants:
            running += grant.amount
            self.session.add(
                XPTransaction(
                    profile_id=profile.id,
                    source=grant.source.value,
                    amount=grant.amount,
                    reason=grant.reason[:255],
                    skill_slug=skill_slug,
                    reference_type=reference_type,
                    reference_slug=reference_slug,
                    balance_after=running,
                    extra=dict(grant.metadata),
                )
            )

        profile.total_xp = result.total_xp
        profile.level = result.new_level
        profile.rank = result.new_rank.value
        profile.coins += coins
        # Reputation tracks *depth* rather than volume: only boss wins,
        # incidents and staff-tier work move it, so it stays a meaningful signal.
        profile.reputation += sum(
            g.amount
            for g in grants
            if g.source in (XPSource.BOSS_DEFEATED, XPSource.ARCHITECTURE_BONUS)
        )

        if skill_slug:
            await self._add_skill_xp(profile.id, skill_slug, result.xp_gained)

        newly_unlocked = self._refresh_unlocked_buildings(profile)
        if result.ranked_up:
            profile.title = _rank_title(result.new_rank)
            log.info(
                "progression.rank_up",
                profile_id=str(profile.id),
                from_rank=result.previous_rank.value,
                to_rank=result.new_rank.value,
            )
            self.session.add(
                LearningEvent(
                    profile_id=profile.id,
                    event_type="rank_up",
                    payload={"from": result.previous_rank.value, "to": result.new_rank.value},
                )
            )
        if result.leveled_up:
            self.session.add(
                LearningEvent(
                    profile_id=profile.id,
                    event_type="level_up",
                    payload={"from": result.previous_level, "to": result.new_level},
                )
            )

        badges, achievements = await self.check_unlocks(profile, now=now)

        return ProgressionOut(
            xp_gained=result.xp_gained,
            total_xp=result.total_xp,
            previous_level=result.previous_level,
            new_level=result.new_level,
            previous_rank=result.previous_rank.value,
            new_rank=result.new_rank.value,
            leveled_up=result.leveled_up,
            ranked_up=result.ranked_up,
            xp_into_level=result.xp_into_level,
            xp_for_next_level=result.xp_for_next_level,
            progress_pct=result.progress_pct,
            coins_gained=coins,
            grants=[
                XPGrantOut(
                    source=g.source.value,
                    amount=g.amount,
                    reason=g.reason,
                    metadata=dict(g.metadata),
                )
                for g in result.grants
            ],
            new_badges=badges,
            new_achievements=achievements,
            unlocked_buildings=newly_unlocked,
        )

    async def _add_skill_xp(self, profile_id: uuid.UUID, skill_slug: str, amount: int) -> None:
        row = await self.skills.get_or_none(profile_id, skill_slug)
        if row is None:
            row = SkillProgress(profile_id=profile_id, skill_slug=skill_slug)
            self.session.add(row)
            await self.session.flush()
        row.xp += amount
        # Skill levels use a gentler curve than the account level: a skill level
        # is a *legibility* device ("Python 7"), not a second progression system.
        row.level = max(1, int((row.xp / 220) ** 0.6) + 1)
        row.last_practiced_at = datetime.now(UTC)

    def _refresh_unlocked_buildings(self, profile: PlayerProfile) -> list[str]:
        current = set(profile.unlocked_buildings or [])
        rank_index = RANK_ORDER.index(Rank(profile.rank))
        newly: list[str] = []
        for building in BUILDINGS:
            if building.id.value in current:
                continue
            if building_unlock_state(building, profile.level, rank_index).unlocked:
                current.add(building.id.value)
                newly.append(building.id.value)
        if newly:
            # Reassign (not mutate) so SQLAlchemy's change detection fires on a
            # JSON column — mutating the list in place would silently not save.
            profile.unlocked_buildings = sorted(current)
        return newly

    # ── Streaks ───────────────────────────────────────────────────────────
    def touch_streak(self, profile: PlayerProfile, today: date | None = None) -> dict[str, Any]:
        today = today or datetime.now(UTC).date()
        last = profile.last_active_date
        if last == today:
            return {"streak": profile.current_streak, "changed": False}

        if last is None:
            profile.current_streak = 1
        else:
            gap = (today - last).days
            if gap <= 1:
                profile.current_streak += 1
            elif gap <= 1 + STREAK_GRACE_DAYS:
                profile.current_streak += 1  # grace day: the chain holds
            else:
                profile.current_streak = 1
        profile.longest_streak = max(profile.longest_streak, profile.current_streak)
        profile.last_active_date = today
        return {"streak": profile.current_streak, "changed": True}

    # ── Badges & achievements ─────────────────────────────────────────────
    async def check_unlocks(
        self, profile: PlayerProfile, *, now: datetime | None = None
    ) -> tuple[list[str], list[str]]:
        """Evaluate every declarative unlock rule against the current profile.

        Runs on each award. That is a handful of indexed reads and is far
        simpler to reason about than an event-driven unlock system — and unlock
        rules that silently stop firing are a worse bug than a few extra
        queries.
        """
        now = now or datetime.now(UTC)
        skill_rows = await self.skills.for_profile(profile.id)
        earned_badges = await self.badges.earned_slugs(profile.id)
        achievement_map = await self.achievements.as_map(profile.id)

        all_badges = list((await self.session.execute(select(Badge))).scalars())
        all_achievements = list((await self.session.execute(select(Achievement))).scalars())

        new_badges, achievement_updates = evaluate_unlocks(
            profile=profile,
            skills=skill_rows,
            badges=all_badges,
            achievements=all_achievements,
            earned_badge_slugs=earned_badges,
            achievement_progress={k: v.progress for k, v in achievement_map.items()},
        )

        bonus: list[XPGrant] = []
        for slug in new_badges:
            self.session.add(
                PlayerBadge(profile_id=profile.id, badge_slug=slug, earned_at=now, seen=False)
            )
            badge = next((b for b in all_badges if b.slug == slug), None)
            if badge and badge.xp_reward:
                bonus.append(XPGrant(XPSource.ACHIEVEMENT, badge.xp_reward, f"Badge: {badge.name}"))

        completed: list[str] = []
        for slug, progress in achievement_updates.items():
            spec = next((a for a in all_achievements if a.slug == slug), None)
            if spec is None:
                continue
            row = achievement_map.get(slug)
            if row is None:
                row = PlayerAchievement(
                    profile_id=profile.id, achievement_slug=slug, target=spec.target
                )
                self.session.add(row)
            was_complete = row.completed_at is not None
            row.progress = min(progress, spec.target)
            if not was_complete and row.progress >= spec.target:
                row.completed_at = now
                completed.append(slug)
                if spec.xp_reward:
                    bonus.append(
                        XPGrant(XPSource.ACHIEVEMENT, spec.xp_reward, f"Achievement: {spec.name}")
                    )
                profile.coins += spec.coin_reward

        if bonus:
            # Applied directly, without recursing into ``award`` — an unlock
            # bonus must never be able to trigger another unlock check and loop.
            extra = apply_xp(profile.total_xp, bonus)
            running = profile.total_xp
            for grant in bonus:
                running += grant.amount
                self.session.add(
                    XPTransaction(
                        profile_id=profile.id,
                        source=grant.source.value,
                        amount=grant.amount,
                        reason=grant.reason[:255],
                        reference_type="unlock",
                        balance_after=running,
                    )
                )
            profile.total_xp = extra.total_xp
            profile.level = extra.new_level
            profile.rank = extra.new_rank.value
            self._refresh_unlocked_buildings(profile)

        return new_badges, completed


def _rank_title(rank: Rank) -> str:
    from app.domain.enums import RANK_TITLES

    return RANK_TITLES[rank]


def decorate_profile(profile: PlayerProfile) -> dict[str, Any]:
    """Derived fields the client needs but we refuse to store (they would drift)."""
    level = profile.level
    floor_xp = total_xp_for_level(level)
    span = xp_to_next_level(level)
    nxt = next_rank(Rank(profile.rank))
    from app.game.xp.engine import RANK_LEVEL_THRESHOLDS

    return {
        "xp_into_level": profile.total_xp - floor_xp,
        "xp_for_next_level": span,
        "progress_pct": round(100.0 * (profile.total_xp - floor_xp) / span, 2) if span else 100.0,
        "experience_band": experience_band_for_level(level).value,
        "next_rank": nxt.value if nxt else None,
        "next_rank_level": RANK_LEVEL_THRESHOLDS[nxt] if nxt else None,
        "rank": rank_for_level(level).value,
    }
