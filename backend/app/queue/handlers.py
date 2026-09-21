"""What the events actually do.

EVERY HANDLER HERE IS IDEMPOTENT, and that is not a style note — both backends
deliver at least once, so each of these will eventually run twice on the same
event. The technique differs per handler and is stated at each one, because
"make it idempotent" is easy to say and easy to get wrong.

These are the effects that used to run on a timer and nobody is waiting on:

  * the leaderboard was rebuilt every 15 minutes, so a player who overtook
    someone saw it up to 15 minutes later
  * concept decay snapshots were refreshed hourly for *every* tracked concept,
    when only the handful a player just touched had changed

WHAT IS DELIBERATELY *NOT* HERE: storing a submission's figures. That was an
event in the first version of this file and it was the wrong call — the grade
response carries the figure URLs, so the player is waiting on it. Deferring
work the response depends on is not asynchrony, it is a race. Figures are
written inline in `grading_service`, which costs about ten milliseconds.

Importing this module is what registers them, which is why `worker.py` and the
app factory both import it explicitly rather than relying on a side effect
somewhere in the package.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.progress import ConceptProgress
from app.models.user import LeaderboardEntry, PlayerProfile
from app.queue.base import Event, EventType
from app.queue.consumer import on

log = get_logger("handlers")


def _profile_id(event: Event) -> uuid.UUID | None:
    raw = event.payload.get("profile_id") or event.partition_key
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        log.warning("handler.bad_profile_id", value=str(raw)[:60])
        return None


# ── Leaderboard ──────────────────────────────────────────────────────────────
@on(EventType.SUBMISSION_GRADED)
@on(EventType.MISSION_COMPLETED)
@on(EventType.INTERVIEW_FINISHED)
async def refresh_leaderboard_position(event: Event) -> None:
    """Rebuild the leaderboard slice around the player whose XP just changed.

    IDEMPOTENT BY CONSTRUCTION: it deletes and re-inserts the period's rows
    from the current state of `player_profiles`, so running it twice produces
    the same table. It does not increment anything.

    WHY THE WHOLE PERIOD RATHER THAN ONE ROW: a player moving from 40th to 12th
    shifts everyone in between. A single-row update would leave 28 rows with
    stale positions, and reasoning about which ones is harder than rewriting a
    table of 100.
    """
    if _profile_id(event) is None:
        return

    now = datetime.now(UTC)
    period_key = now.strftime("%Y-%m")

    async with session_scope() as session:
        await session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.period == "all_time",
                LeaderboardEntry.period_key == period_key,
            )
        )
        rows = (
            (
                await session.execute(
                    select(PlayerProfile).order_by(PlayerProfile.total_xp.desc()).limit(100)
                )
            )
            .scalars()
            .all()
        )
        for position, profile in enumerate(rows, start=1):
            session.add(
                LeaderboardEntry(
                    period="all_time",
                    period_key=period_key,
                    profile_id=profile.id,
                    display_name=profile.display_name,
                    position=position,
                    xp=profile.total_xp,
                    level=profile.level,
                    rank=profile.rank,
                    extra={"streak": profile.current_streak},
                )
            )
    log.info("handler.leaderboard_refreshed", entries=len(rows))


# ── Decay snapshots ──────────────────────────────────────────────────────────
@on(EventType.CONCEPT_PRACTISED)
async def refresh_decay_for_touched_concepts(event: Event) -> None:
    """Recompute the cached decay snapshot for the concepts just practised.

    IDEMPOTENT BY CONSTRUCTION: the snapshot is a pure function of the stored
    review state and the clock, so recomputing it is a no-op beyond moving the
    timestamp.

    This is the case that most justifies the queue. The periodic job sweeps
    *every* tracked concept hourly to keep a handful fresh; this touches the
    two or three that actually changed, immediately.
    """
    from app.game.retention.model import decay_report
    from app.services.retention_service import to_state

    profile_id = _profile_id(event)
    slugs = [str(s) for s in event.payload.get("concept_slugs", []) if s]
    if profile_id is None or not slugs:
        return

    now = datetime.now(UTC)
    updated = 0
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(ConceptProgress).where(
                        ConceptProgress.profile_id == profile_id,
                        ConceptProgress.concept_slug.in_(slugs),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            report = decay_report(to_state(row), now)
            # Exactly the shape the periodic job writes. Two writers of one
            # field must agree on its shape, or the dashboard renders whichever
            # ran last and they silently disagree.
            row.last_decay_snapshot = {
                "retrievability": report.retrievability,
                "effective_mastery": report.effective_mastery,
                "urgency": report.urgency,
                "computed_at": now.isoformat(),
            }
            updated += 1

    log.info("handler.decay_refreshed", concepts=updated, profile_id=str(profile_id))
