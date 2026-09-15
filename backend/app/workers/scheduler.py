"""Background scheduler.

WHY a plain asyncio loop rather than Celery/APScheduler: there are four
periodic jobs, none of them fan out, none need a result backend, and none need
to survive a restart mid-run (every job is idempotent). A broker, a worker pool
and a beat process would be three moving parts added to run four functions on a
timer — the exact "enterprise architecture for its own sake" the spec warns
against. When a job genuinely needs retries, isolation or fan-out, that is the
moment to introduce a queue, and the Architecture Tower missions argue that
threshold explicitly.

Every job is:
  * idempotent — safe to run twice, safe to kill mid-run
  * self-contained — its own session, its own transaction
  * fault-isolated — one failing job never stops the others or the loop
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, session_scope
from app.models.progress import ConceptProgress
from app.models.user import LeaderboardEntry, PlayerProfile

log = get_logger("worker")

JobFn = Callable[[], Awaitable[dict[str, int]]]


@dataclass(slots=True)
class Job:
    name: str
    interval_seconds: float
    fn: JobFn
    #: Delay before the first run, so a restart does not fire everything at once.
    jitter_seconds: float = 0.0


# ── Jobs ─────────────────────────────────────────────────────────────────────
async def refresh_decay_snapshots() -> dict[str, int]:
    """Recompute the cached decay snapshot on every tracked concept.

    The snapshot is purely a cache — ``decay_report`` can always recompute it
    from the stored review state — so this job is free to be interrupted, and a
    stale snapshot degrades the dashboard's freshness, never its correctness.
    """
    from app.game.retention.model import decay_report
    from app.services.retention_service import to_state

    now = datetime.now(UTC)
    updated = 0

    async with session_scope() as session:
        rows = (
            (await session.execute(select(ConceptProgress).where(ConceptProgress.attempts > 0)))
            .scalars()
            .all()
        )
        for row in rows:
            report = decay_report(to_state(row), now)
            row.last_decay_snapshot = {
                "retrievability": report.retrievability,
                "effective_mastery": report.effective_mastery,
                "urgency": report.urgency,
                "computed_at": now.isoformat(),
            }
            updated += 1

    return {"concepts": updated}


async def recompute_skill_rollups() -> dict[str, int]:
    """Rebuild per-skill mastery from per-concept state.

    The skill row is denormalised for the dashboard. It is written on every
    submission, so it should already be correct; this job exists because
    "derived data that is only ever written incrementally" always drifts
    eventually, and a cheap nightly reconciliation is worth more than the
    confidence that it will not.
    """
    from app.services.retention_service import RetentionService

    profiles = 0
    async with session_scope() as session:
        ids = (await session.execute(select(PlayerProfile.id))).scalars().all()
        service = RetentionService(session)
        for profile_id in ids:
            await service.recompute_all_skills(profile_id)
            profiles += 1
    return {"profiles": profiles}


async def snapshot_leaderboard() -> dict[str, int]:
    """Materialise the all-time leaderboard.

    WHY snapshot rather than query live: `ORDER BY total_xp LIMIT 25` is a
    sequential scan once the table is large, and it cannot express weekly or
    monthly boards at all. The snapshot is rebuilt wholesale because it is
    small and a partial update would be harder to reason about than a rewrite.
    """
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
    return {"entries": len(rows)}


async def purge_expired_tokens() -> dict[str, int]:
    """Delete refresh tokens that have expired.

    They are already rejected at verification time, so this is hygiene rather
    than security — an unbounded table is a slow-motion outage.
    """
    from app.services.auth_service import AuthService

    async with session_scope() as session:
        removed = await AuthService(session).purge_expired_tokens()
    return {"tokens": removed}


async def report_stats() -> dict[str, int]:
    """One structured heartbeat line, so the log proves the worker is alive."""
    async with session_scope() as session:
        players = int(
            (await session.execute(select(func.count()).select_from(PlayerProfile))).scalar_one()
        )
        due = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ConceptProgress)
                    .where(
                        ConceptProgress.due_at.is_not(None),
                        ConceptProgress.due_at <= datetime.now(UTC),
                    )
                )
            ).scalar_one()
        )
    return {"players": players, "concepts_due": due}


JOBS: tuple[Job, ...] = (
    Job(
        "decay_snapshots", settings.retention_decay_check_hours * 3600, refresh_decay_snapshots, 30
    ),
    Job("skill_rollups", 24 * 3600, recompute_skill_rollups, 90),
    Job("leaderboard", 15 * 60, snapshot_leaderboard, 15),
    Job("purge_tokens", 6 * 3600, purge_expired_tokens, 120),
    Job("heartbeat", 5 * 60, report_stats, 5),
)


# ── Loop ─────────────────────────────────────────────────────────────────────
async def run_job(job: Job, stop: asyncio.Event) -> None:
    """Run one job forever. A failure logs and waits — it never kills the loop."""
    if job.jitter_seconds:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=job.jitter_seconds)

    while not stop.is_set():
        started = asyncio.get_running_loop().time()
        try:
            result = await job.fn()
            duration_ms = (asyncio.get_running_loop().time() - started) * 1000
            log.info("worker.job_ok", job=job.name, duration_ms=round(duration_ms, 1), **result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # one bad job must not stop the rest
            log.exception("worker.job_failed", job=job.name, error=str(exc)[:300])

        # Waiting on the stop event rather than sleeping means Ctrl-C and
        # SIGTERM are honoured immediately instead of after the full interval.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=job.interval_seconds)


async def main() -> None:
    configure_logging(settings.log_level, settings.log_json)
    log.info("worker.starting", jobs=[j.name for j in JOBS])

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, AttributeError):
            # Windows' proactor loop has no add_signal_handler; KeyboardInterrupt
            # still propagates there, which is good enough for local dev.
            loop.add_signal_handler(sig, stop.set)

    tasks = [asyncio.create_task(run_job(job, stop), name=job.name) for job in JOBS]
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop.set()
    finally:
        log.info("worker.stopping")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispose_engine()
        log.info("worker.stopped")


def _next_run_hint(job: Job) -> datetime:
    """Used by the observability panel to show when each job fires next."""
    return datetime.now(UTC) + timedelta(seconds=job.interval_seconds)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
