"""Operational CLI: ``aiforge <command>``.

WHY a CLI at all: seeding, schema creation and demo-player generation need to
run from Docker entrypoints, CI and a developer's terminal — three callers that
must not each reimplement the logic. The commands here are thin wrappers over
the same services the API uses, which is the point: if the CLI works, the
service layer is genuinely independent of HTTP.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_engine, session_scope

log = get_logger("cli")


async def _create_schema() -> None:
    """Create tables directly from metadata.

    For local SQLite only. Postgres deployments use Alembic — ``create_all``
    has no migration history, so a schema created this way cannot be upgraded.
    """
    from app.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ schema created")


async def _drop_schema() -> None:
    from app.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("✓ schema dropped")


async def _seed(strict: bool) -> None:
    from app.content.seeder import content_summary, seed_all

    summary = content_summary()
    print("Content packs:")
    for name, counts in summary["packs"].items():
        parts = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        print(f"  {name:<16} {parts or 'empty'}")

    async with session_scope() as session:
        result = await seed_all(session, strict=strict)

    print("\nSeed stats:")
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:<24} {value}")
    if result["warnings"]:
        print(f"\n⚠ {len(result['warnings'])} content warning(s):")
        for warning in result["warnings"][:20]:
            print(f"  - {warning}")
    print("\n✓ seed complete")


async def _demo_user(email: str, password: str, username: str, simulate_days: int) -> None:
    """Create a playable account, optionally with simulated practice history.

    ``--simulate-days`` back-dates activity so the retention dashboard, the
    decay alerts and the analytics charts have something real to show. Without
    it a fresh account renders an empty dashboard, which makes the single most
    important feature invisible on first run.
    """
    from app.schemas.auth import RegisterRequest
    from app.services.auth_service import AuthService

    async with session_scope() as session:
        service = AuthService(session)
        try:
            result = await service.register(
                RegisterRequest(email=email, username=username, password=password)
            )
            print(f"✓ created {username} <{email}>")
        except Exception as exc:
            print(f"· {username} already exists ({type(exc).__name__})")
            from app.schemas.auth import LoginRequest

            result = await service.login(LoginRequest(identifier=email, password=password))

        profile = await service.get_profile_for_user(result.user.id)

        if simulate_days:
            await _simulate_history(session, profile, simulate_days)
            print(f"✓ simulated {simulate_days} days of practice history")

    print(f"\n  access token: {result.tokens.access_token[:48]}…")
    print(f"  login with:   {email} / {password}")


async def _simulate_history(session, profile, days: int) -> None:
    """Replay realistic attempts through the real engines.

    Deliberately uses ``RetentionService.record_review`` rather than writing
    rows directly: simulated data that bypasses the engine would not exercise
    the engine, and the demo would show numbers the real game cannot produce.
    """
    import random

    from sqlalchemy import select

    from app.models.content import Concept
    from app.services.progression_service import ProgressionService
    from app.services.retention_service import RetentionService

    rng = random.Random(42)
    concepts = list((await session.execute(select(Concept))).scalars())
    if not concepts:
        print("  (no concepts seeded — run `aiforge seed` first)")
        return

    retention = RetentionService(session)
    progression = ProgressionService(session)
    now = datetime.now(UTC)

    for day_offset in range(days, 0, -1):
        at = now - timedelta(days=day_offset)
        # Skip ~30% of days so the streak and consistency metrics look human.
        if rng.random() < 0.3:
            continue
        for _ in range(rng.randint(1, 4)):
            concept = rng.choice(concepts)
            # Later days get harder tiers and better scores — a learning curve.
            progress = 1.0 - (day_offset / max(1, days))
            tier = min(10, max(1, int(2 + progress * 6 + rng.randint(-1, 1))))
            score = min(1.0, max(0.0, 0.45 + progress * 0.45 + rng.uniform(-0.2, 0.2)))
            await retention.record_review(
                profile.id,
                [concept.slug],
                score=score,
                tier=tier,
                now=at,
                confidence=min(1.0, score + rng.uniform(-0.15, 0.25)),
            )

    from app.domain.enums import XPSource
    from app.game.xp.engine import XPGrant

    await progression.award(
        profile,
        [XPGrant(XPSource.CHALLENGE_PASSED, 4200, "Simulated practice history")],
        skill_slug="python",
    )
    profile.current_streak = rng.randint(3, 12)
    profile.longest_streak = max(profile.current_streak, rng.randint(12, 40))
    profile.last_active_date = now.date()
    profile.challenges_passed = rng.randint(20, 60)
    profile.questions_answered = rng.randint(40, 120)
    profile.missions_completed = rng.randint(3, 12)
    await retention.recompute_all_skills(profile.id)


async def _content_check() -> None:
    """Validate every pack without touching a database. Used by CI."""
    from app.content.registry import all_packs
    from app.content.schema import ContentError, validate_pack

    known = {c.slug for pack in all_packs() for c in pack.concepts}
    total_warnings = 0
    failed = False
    for pack in all_packs():
        try:
            warnings = validate_pack(pack, known_concepts=known)
        except ContentError as exc:
            print(f"✗ {pack.name}: {exc}")
            failed = True
            continue
        counts = ", ".join(f"{v} {k}" for k, v in pack.counts().items() if v)
        print(f"✓ {pack.name:<16} {counts}")
        for warning in warnings:
            print(f"    ⚠ {warning}")
        total_warnings += len(warnings)

    print(f"\n{total_warnings} warning(s)")
    if failed:
        sys.exit(1)


async def _stats() -> None:
    from sqlalchemy import func, select

    from app.models.content import Challenge, Concept, Mission, Question
    from app.models.user import User

    async with session_scope() as session:
        rows = {}
        for label, model in (
            ("concepts", Concept),
            ("challenges", Challenge),
            ("questions", Question),
            ("missions", Mission),
            ("users", User),
        ):
            rows[label] = int(
                (await session.execute(select(func.count()).select_from(model))).scalar_one()
            )
    print(json.dumps(rows, indent=2))


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252, which cannot encode the status glyphs.

    Reconfiguring the stream (rather than dropping the glyphs) keeps the same
    output on every platform, and `errors="replace"` means an exotic terminal
    degrades to `?` instead of crashing the command.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(prog="aiforge", description="AI Forge Labs operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("create-schema", help="create tables from metadata (SQLite dev only)")
    sub.add_parser("drop-schema", help="DROP every table")
    sub.add_parser("stats", help="row counts")
    sub.add_parser("content-check", help="validate content packs without a database")

    seed = sub.add_parser("seed", help="seed skills and all content packs (idempotent)")
    seed.add_argument("--strict", action="store_true", help="fail on content warnings")

    demo = sub.add_parser("demo-user", help="create a playable account")
    demo.add_argument("--email", default="player@aiforge.dev")
    demo.add_argument("--username", default="player")
    demo.add_argument("--password", default="forge-me-2026")
    demo.add_argument(
        "--simulate-days",
        type=int,
        default=0,
        help="back-date practice history so the retention dashboard has data",
    )

    bootstrap = sub.add_parser(
        "bootstrap", help="create-schema + seed + demo-user, for a first run"
    )
    bootstrap.add_argument("--simulate-days", type=int, default=45)

    args = parser.parse_args()
    configure_logging(settings.log_level, settings.log_json)

    async def run() -> None:
        try:
            match args.command:
                case "create-schema":
                    await _create_schema()
                case "drop-schema":
                    await _drop_schema()
                case "seed":
                    await _seed(args.strict)
                case "demo-user":
                    await _demo_user(args.email, args.password, args.username, args.simulate_days)
                case "content-check":
                    await _content_check()
                case "stats":
                    await _stats()
                case "bootstrap":
                    await _create_schema()
                    await _seed(False)
                    await _demo_user(
                        "player@aiforge.dev",
                        "forge-me-2026",
                        "player",
                        args.simulate_days,
                    )
                    print("\n🎮 Ready. Start the API with: uvicorn app.main:app --reload")
        finally:
            await dispose_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
