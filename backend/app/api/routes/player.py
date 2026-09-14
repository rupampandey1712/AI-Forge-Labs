"""Player profile, world map, skill trees, badges and the leaderboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentProfile, DBSession, PlayerSvc
from app.models.content import Achievement, Badge
from app.schemas.common import Message
from app.schemas.player import (
    AchievementOut,
    BadgeOut,
    DashboardOut,
    LeaderboardRow,
    PlayerProfileOut,
    ProfileUpdate,
    SkillProgressOut,
    SkillTreeOut,
    WorldMapOut,
    XPTransactionOut,
)

router = APIRouter(prefix="/player", tags=["player"])


@router.get("/profile", response_model=PlayerProfileOut)
async def get_profile(profile: CurrentProfile, service: PlayerSvc) -> PlayerProfileOut:
    return service.to_profile_out(profile)


@router.patch("/profile", response_model=PlayerProfileOut)
async def update_profile(
    payload: ProfileUpdate, profile: CurrentProfile, service: PlayerSvc
) -> PlayerProfileOut:
    if payload.display_name:
        profile.display_name = payload.display_name
    if payload.avatar_seed:
        profile.avatar_seed = payload.avatar_seed
    if payload.preferred_mentor:
        profile.preferred_mentor = payload.preferred_mentor
    if payload.settings is not None:
        profile.settings = {**(profile.settings or {}), **payload.settings}
    return service.to_profile_out(profile)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(profile: CurrentProfile, service: PlayerSvc) -> DashboardOut:
    """Everything the game dashboard needs, in one round trip."""
    await service.ensure_skill_rows(profile)
    return await service.dashboard(profile)


@router.get("/world", response_model=WorldMapOut)
async def world_map(profile: CurrentProfile, service: PlayerSvc) -> WorldMapOut:
    return await service.world_map(profile)


@router.get("/skills", response_model=list[SkillProgressOut])
async def skills(profile: CurrentProfile, service: PlayerSvc) -> list[SkillProgressOut]:
    return await service.skill_progress(profile.id)


@router.get("/skills/{skill_slug}", response_model=SkillTreeOut)
async def skill_tree(skill_slug: str, profile: CurrentProfile, service: PlayerSvc) -> SkillTreeOut:
    return await service.skill_tree(profile.id, skill_slug)


@router.get("/badges", response_model=list[BadgeOut])
async def badges(profile: CurrentProfile, session: DBSession) -> list[BadgeOut]:
    from app.models.progress import PlayerBadge

    specs = list((await session.execute(select(Badge).order_by(Badge.tier))).scalars())
    earned = {
        r.badge_slug: r
        for r in (
            await session.execute(select(PlayerBadge).where(PlayerBadge.profile_id == profile.id))
        ).scalars()
    }
    return [
        BadgeOut(
            slug=b.slug,
            name=b.name,
            # A secret badge that is not yet earned shows as a locked silhouette
            # rather than revealing what it is for.
            description=b.description if (b.slug in earned or not b.secret) else "???",
            tier=b.tier,
            icon=b.icon,
            xp_reward=b.xp_reward,
            earned=b.slug in earned,
            earned_at=earned[b.slug].earned_at if b.slug in earned else None,
            secret=b.secret,
        )
        for b in specs
    ]


@router.get("/achievements", response_model=list[AchievementOut])
async def achievements(profile: CurrentProfile, session: DBSession) -> list[AchievementOut]:
    from app.models.progress import PlayerAchievement

    specs = list((await session.execute(select(Achievement))).scalars())
    progress = {
        r.achievement_slug: r
        for r in (
            await session.execute(
                select(PlayerAchievement).where(PlayerAchievement.profile_id == profile.id)
            )
        ).scalars()
    }
    return [
        AchievementOut(
            slug=a.slug,
            name=a.name,
            description=a.description if (a.slug in progress or not a.secret) else "???",
            category=a.category,
            icon=a.icon,
            xp_reward=a.xp_reward,
            coin_reward=a.coin_reward,
            target=a.target,
            progress=progress[a.slug].progress if a.slug in progress else 0,
            completed=bool(a.slug in progress and progress[a.slug].completed_at),
            completed_at=progress[a.slug].completed_at if a.slug in progress else None,
            secret=a.secret,
        )
        for a in specs
    ]


@router.post("/badges/seen", response_model=Message)
async def mark_badges_seen(profile: CurrentProfile, service: PlayerSvc) -> Message:
    count = await service.mark_badges_seen(profile.id)
    return Message(message=f"{count} badge(s) marked as seen.")


@router.get("/xp", response_model=list[XPTransactionOut])
async def xp_history(
    profile: CurrentProfile,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[XPTransactionOut]:
    from app.repositories.player import XPRepository

    rows = await XPRepository(session).recent(profile.id, limit=limit)
    return [XPTransactionOut.model_validate(r) for r in rows]


@router.get("/leaderboard", response_model=list[LeaderboardRow])
async def leaderboard(
    profile: CurrentProfile,
    service: PlayerSvc,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[LeaderboardRow]:
    return await service.leaderboard(profile.id, limit=limit)
