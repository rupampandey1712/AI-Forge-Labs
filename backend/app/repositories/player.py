"""Repositories for identity, progression and progress rows."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import selectinload

from app.models.progress import (
    ChallengeAttempt,
    ConceptProgress,
    DailyChallenge,
    JournalEntry,
    LearningEvent,
    MissionAttempt,
    MistakeRecord,
    PlayerAchievement,
    PlayerBadge,
    QuestionAttempt,
    SkillProgress,
    XPTransaction,
)
from app.models.user import PlayerProfile, RefreshToken, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self.get_by(email=email.lower().strip())

    async def get_by_username(self, username: str) -> User | None:
        return await self.get_by(username=username.strip())

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Accept an email or a username in the same login field.

        One query with an OR rather than two sequential lookups: the second
        lookup would also leak, via timing, which of the two matched.
        """
        ident = identifier.strip()
        stmt = (
            select(User)
            .where(or_(User.email == ident.lower(), User.username == ident))
            .options(selectinload(User.profile))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def touch_login(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(last_login_at=datetime.now(UTC))
        )


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_jti(self, jti: str) -> RefreshToken | None:
        return await self.get_by(jti=jti)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        return int(result.rowcount or 0)

    async def purge_expired(self) -> int:
        result = await self.session.execute(
            sa_delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
        )
        return int(result.rowcount or 0)


class ProfileRepository(BaseRepository[PlayerProfile]):
    model = PlayerProfile

    async def get_for_user(self, user_id: uuid.UUID) -> PlayerProfile | None:
        return await self.get_by(user_id=user_id)

    async def top_by_xp(self, limit: int = 50) -> list[PlayerProfile]:
        stmt = select(PlayerProfile).order_by(PlayerProfile.total_xp.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def rank_of(self, profile_id: uuid.UUID) -> int:
        """1-based leaderboard position.

        A COUNT of players with more XP is O(n) but index-only on
        ``ix_player_profiles_total_xp``, and it avoids materialising a window
        function over the whole table just to read one row's rank.
        """
        me = await self.get(profile_id)
        if me is None:
            return 0
        stmt = (
            select(func.count())
            .select_from(PlayerProfile)
            .where(PlayerProfile.total_xp > me.total_xp)
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1


class SkillProgressRepository(BaseRepository[SkillProgress]):
    model = SkillProgress

    async def for_profile(self, profile_id: uuid.UUID) -> list[SkillProgress]:
        return await self.list_by(profile_id=profile_id, order_by=SkillProgress.skill_slug)

    async def get_or_none(self, profile_id: uuid.UUID, skill_slug: str) -> SkillProgress | None:
        return await self.get_by(profile_id=profile_id, skill_slug=skill_slug)

    async def as_map(self, profile_id: uuid.UUID) -> dict[str, SkillProgress]:
        return {sp.skill_slug: sp for sp in await self.for_profile(profile_id)}


class ConceptProgressRepository(BaseRepository[ConceptProgress]):
    model = ConceptProgress

    async def for_profile(self, profile_id: uuid.UUID) -> list[ConceptProgress]:
        return await self.list_by(profile_id=profile_id)

    async def get_one(self, profile_id: uuid.UUID, concept_slug: str) -> ConceptProgress | None:
        return await self.get_by(profile_id=profile_id, concept_slug=concept_slug)

    async def get_many(
        self, profile_id: uuid.UUID, concept_slugs: list[str]
    ) -> dict[str, ConceptProgress]:
        if not concept_slugs:
            return {}
        stmt = select(ConceptProgress).where(
            ConceptProgress.profile_id == profile_id,
            ConceptProgress.concept_slug.in_(concept_slugs),
        )
        return {cp.concept_slug: cp for cp in (await self.session.execute(stmt)).scalars()}

    async def due_before(
        self, profile_id: uuid.UUID, cutoff: datetime, limit: int = 100
    ) -> list[ConceptProgress]:
        """Hits ``ix_concept_progress_due`` — the retention scan's hot path."""
        stmt = (
            select(ConceptProgress)
            .where(
                ConceptProgress.profile_id == profile_id,
                ConceptProgress.due_at.is_not(None),
                ConceptProgress.due_at <= cutoff,
            )
            .order_by(ConceptProgress.due_at)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_skill(self, profile_id: uuid.UUID, skill_slug: str) -> list[ConceptProgress]:
        return await self.list_by(profile_id=profile_id, skill_slug=skill_slug)


class XPRepository(BaseRepository[XPTransaction]):
    model = XPTransaction

    async def recent(self, profile_id: uuid.UUID, limit: int = 50) -> list[XPTransaction]:
        return await self.list_by(
            profile_id=profile_id, order_by=XPTransaction.created_at.desc(), limit=limit
        )

    async def sum_by_source(self, profile_id: uuid.UUID) -> list[tuple[str, int]]:
        stmt = (
            select(XPTransaction.source, func.sum(XPTransaction.amount))
            .where(XPTransaction.profile_id == profile_id)
            .group_by(XPTransaction.source)
            .order_by(func.sum(XPTransaction.amount).desc())
        )
        return [(row[0], int(row[1] or 0)) for row in (await self.session.execute(stmt)).all()]

    async def daily_totals(self, profile_id: uuid.UUID, days: int = 30) -> list[tuple[date, int]]:
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date(XPTransaction.created_at)
        stmt = (
            select(day, func.sum(XPTransaction.amount))
            .where(XPTransaction.profile_id == profile_id, XPTransaction.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(_as_date(r[0]), int(r[1] or 0)) for r in rows]


def _as_date(value: Any) -> date:
    """SQLite returns ``date()`` as a string; Postgres returns a real date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


class LearningEventRepository(BaseRepository[LearningEvent]):
    model = LearningEvent

    async def recent(self, profile_id: uuid.UUID, limit: int = 25) -> list[LearningEvent]:
        return await self.list_by(
            profile_id=profile_id, order_by=LearningEvent.created_at.desc(), limit=limit
        )

    async def active_days(self, profile_id: uuid.UUID, days: int = 90) -> list[tuple[date, int]]:
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date(LearningEvent.created_at)
        stmt = (
            select(day, func.count())
            .where(LearningEvent.profile_id == profile_id, LearningEvent.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
        return [(_as_date(r[0]), int(r[1])) for r in (await self.session.execute(stmt)).all()]

    async def accuracy_trend(
        self, profile_id: uuid.UUID, days: int = 30
    ) -> list[tuple[date, float]]:
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date(LearningEvent.created_at)
        stmt = (
            select(day, func.avg(LearningEvent.score))
            .where(
                LearningEvent.profile_id == profile_id,
                LearningEvent.created_at >= since,
                LearningEvent.score.is_not(None),
            )
            .group_by(day)
            .order_by(day)
        )
        return [
            (_as_date(r[0]), round(float(r[1] or 0), 4))
            for r in (await self.session.execute(stmt)).all()
        ]


class MistakeRepository(BaseRepository[MistakeRecord]):
    model = MistakeRecord

    async def get_pattern(self, profile_id: uuid.UUID, pattern: str) -> MistakeRecord | None:
        return await self.get_by(profile_id=profile_id, pattern=pattern)

    async def open_for_profile(self, profile_id: uuid.UUID, limit: int = 20) -> list[MistakeRecord]:
        stmt = (
            select(MistakeRecord)
            .where(MistakeRecord.profile_id == profile_id, MistakeRecord.resolved.is_(False))
            .order_by(MistakeRecord.occurrences.desc(), MistakeRecord.last_seen_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class MissionAttemptRepository(BaseRepository[MissionAttempt]):
    model = MissionAttempt

    async def latest_for(self, profile_id: uuid.UUID, mission_slug: str) -> MissionAttempt | None:
        rows = await self.list_by(
            profile_id=profile_id,
            mission_slug=mission_slug,
            order_by=MissionAttempt.created_at.desc(),
            limit=1,
        )
        return rows[0] if rows else None

    async def next_attempt_number(self, profile_id: uuid.UUID, mission_slug: str) -> int:
        return (await self.count(profile_id=profile_id, mission_slug=mission_slug)) + 1

    async def open_attempt(self, profile_id: uuid.UUID, mission_slug: str) -> MissionAttempt | None:
        return await self.get_by(
            profile_id=profile_id, mission_slug=mission_slug, status="in_progress"
        )

    async def completion_map(self, profile_id: uuid.UUID) -> dict[str, dict[str, Any]]:
        """``{mission_slug: {"completed": bool, "best_score": float, "attempts": int}}``

        One grouped query instead of one per mission — the mission list renders
        60+ cards, and the per-card version of this is a textbook N+1.
        """
        stmt = (
            select(
                MissionAttempt.mission_slug,
                func.count(),
                func.max(MissionAttempt.score),
                func.sum(case((MissionAttempt.status == "passed", 1), else_=0)),
            )
            .where(MissionAttempt.profile_id == profile_id)
            .group_by(MissionAttempt.mission_slug)
        )
        out: dict[str, dict[str, Any]] = {}
        for slug, attempts, best, passed in (await self.session.execute(stmt)).all():
            out[slug] = {
                "attempts": int(attempts or 0),
                "best_score": float(best or 0.0),
                "completed": bool(passed),
            }
        return out


class ChallengeAttemptRepository(BaseRepository[ChallengeAttempt]):
    model = ChallengeAttempt

    async def attempts_for(self, profile_id: uuid.UUID, challenge_slug: str) -> int:
        return await self.count(profile_id=profile_id, challenge_slug=challenge_slug)

    async def solved(self, profile_id: uuid.UUID, challenge_slug: str) -> bool:
        return await self.exists(
            profile_id=profile_id, challenge_slug=challenge_slug, status="passed"
        )

    async def solved_slugs(self, profile_id: uuid.UUID) -> set[str]:
        stmt = (
            select(ChallengeAttempt.challenge_slug)
            .where(ChallengeAttempt.profile_id == profile_id, ChallengeAttempt.status == "passed")
            .distinct()
        )
        return {row[0] for row in (await self.session.execute(stmt)).all()}


class QuestionAttemptRepository(BaseRepository[QuestionAttempt]):
    model = QuestionAttempt

    async def seen_slugs(self, profile_id: uuid.UUID, within_days: int | None = None) -> set[str]:
        stmt = select(QuestionAttempt.question_slug).where(QuestionAttempt.profile_id == profile_id)
        if within_days:
            stmt = stmt.where(
                QuestionAttempt.created_at >= datetime.now(UTC) - timedelta(days=within_days)
            )
        return {row[0] for row in (await self.session.execute(stmt.distinct())).all()}

    async def average_score(self, profile_id: uuid.UUID) -> float:
        """Mean 0..10 score across every answered question."""
        stmt = select(func.avg(QuestionAttempt.score)).where(
            QuestionAttempt.profile_id == profile_id
        )
        return float((await self.session.execute(stmt)).scalar_one() or 0.0)


class DailyChallengeRepository(BaseRepository[DailyChallenge]):
    model = DailyChallenge

    async def for_date(self, profile_id: uuid.UUID, day: date) -> DailyChallenge | None:
        return await self.get_by(profile_id=profile_id, for_date=day)

    async def recent(self, profile_id: uuid.UUID, limit: int = 14) -> list[DailyChallenge]:
        return await self.list_by(
            profile_id=profile_id, order_by=DailyChallenge.for_date.desc(), limit=limit
        )


class BadgeProgressRepository(BaseRepository[PlayerBadge]):
    model = PlayerBadge

    async def earned_slugs(self, profile_id: uuid.UUID) -> set[str]:
        stmt = select(PlayerBadge.badge_slug).where(PlayerBadge.profile_id == profile_id)
        return {row[0] for row in (await self.session.execute(stmt)).all()}

    async def unseen(self, profile_id: uuid.UUID) -> list[PlayerBadge]:
        return await self.list_by(profile_id=profile_id, seen=False)


class AchievementProgressRepository(BaseRepository[PlayerAchievement]):
    model = PlayerAchievement

    async def as_map(self, profile_id: uuid.UUID) -> dict[str, PlayerAchievement]:
        rows = await self.list_by(profile_id=profile_id)
        return {r.achievement_slug: r for r in rows}


class JournalRepository(BaseRepository[JournalEntry]):
    model = JournalEntry

    async def recent(self, profile_id: uuid.UUID, limit: int = 20) -> list[JournalEntry]:
        return await self.list_by(
            profile_id=profile_id, order_by=JournalEntry.created_at.desc(), limit=limit
        )

    async def oldest_unresurfaced(
        self, profile_id: uuid.UUID, older_than_days: int = 30
    ) -> JournalEntry | None:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = (
            select(JournalEntry)
            .where(
                JournalEntry.profile_id == profile_id,
                JournalEntry.created_at <= cutoff,
                JournalEntry.resurfaced_at.is_(None),
                JournalEntry.mistake_made != "",
            )
            .order_by(JournalEntry.created_at)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
