"""Idempotent content seeding.

WHY upsert-by-slug rather than truncate-and-insert: players' progress rows
reference content by slug. A destructive re-seed would either orphan every
``ConceptProgress`` row or cascade-delete months of practice history. Seeding
must therefore be safe to run on every deploy, against a database with real
players in it.

The seeder is also the last line of content QA: ``validate_pack`` runs first, so
a dangling reference or an ungradeable question fails the seed rather than
reaching a player as a broken mission.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import all_packs
from app.content.schema import (
    AchievementSpec,
    BadgeSpec,
    ChallengeSpec,
    ConceptSpec,
    ContentPack,
    DocumentSpec,
    MissionSpec,
    ProjectSpec,
    QuestionSpec,
    validate_pack,
)
from app.core.logging import get_logger
from app.game.skills.registry import SKILL_BY_SLUG, SKILL_TREES, skill_for_category
from app.models.content import (
    Achievement,
    Badge,
    Challenge,
    Concept,
    ConceptEdge,
    KnowledgeDocument,
    Mission,
    MissionStep,
    Project,
    Question,
    Skill,
    SkillNode,
)

log = get_logger(__name__)


class Seeder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stats: dict[str, int] = {}

    def _bump(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    # ── Structure (skills + trees) ────────────────────────────────────────
    async def seed_skills(self) -> None:
        """Mirror the code-defined skill registry into the database."""
        existing = {s.slug: s for s in (await self.session.execute(select(Skill))).scalars()}
        for sdef in SKILL_BY_SLUG.values():
            row = existing.get(sdef.slug.value)
            if row is None:
                row = Skill(slug=sdef.slug.value)
                self.session.add(row)
                self._bump("skills_created")
            else:
                self._bump("skills_updated")
            row.name = sdef.name
            row.description = sdef.description
            row.icon = sdef.icon
            row.color = sdef.color
            row.display_order = sdef.display_order
            row.building = sdef.building.value
        await self.session.flush()

        skills = {s.slug: s for s in (await self.session.execute(select(Skill))).scalars()}
        nodes = {n.slug: n for n in (await self.session.execute(select(SkillNode))).scalars()}

        # Two passes: create every node, then wire parents. A single pass would
        # fail whenever a child is defined before its parent.
        for skill_id, defs in SKILL_TREES.items():
            skill = skills[skill_id.value]
            for order, ndef in enumerate(defs):
                row = nodes.get(ndef.slug)
                if row is None:
                    row = SkillNode(slug=ndef.slug)
                    self.session.add(row)
                    nodes[ndef.slug] = row
                    self._bump("skill_nodes_created")
                row.skill_id = skill.id
                row.name = ndef.name
                row.summary = ndef.summary
                row.tier_range = list(ndef.tier_range)
                row.display_order = order
                row.unlock_level = ndef.unlock_level
        await self.session.flush()

        for defs in SKILL_TREES.values():
            for ndef in defs:
                if ndef.parent:
                    nodes[ndef.slug].parent_id = nodes[ndef.parent].id
        await self.session.flush()

    # ── Content ───────────────────────────────────────────────────────────
    async def seed_pack(self, pack: ContentPack, *, strict: bool = False) -> list[str]:
        warnings = validate_pack(pack, known_concepts=await self._known_concept_slugs())
        for warning in warnings:
            log.warning("content.warning", pack=pack.name, detail=warning)
        if strict and warnings:
            from app.content.schema import ContentError

            raise ContentError(f"{pack.name}: {len(warnings)} content warning(s) in strict mode")

        await self._seed_concepts(pack.concepts)
        await self._seed_challenges(pack.challenges)
        await self._seed_questions(pack.questions)
        await self._seed_missions(pack.missions)
        await self._seed_badges(pack.badges)
        await self._seed_achievements(pack.achievements)
        await self._seed_documents(pack.documents)
        await self._seed_projects(pack.projects)
        await self.session.flush()
        return warnings

    async def _known_concept_slugs(self) -> set[str]:
        return {r[0] for r in (await self.session.execute(select(Concept.slug))).all()} | {
            c.slug for pack in all_packs() for c in pack.concepts
        }

    async def _seed_concepts(self, specs: list[ConceptSpec]) -> None:
        if not specs:
            return
        existing = {
            c.slug: c
            for c in (
                await self.session.execute(
                    select(Concept).where(Concept.slug.in_([s.slug for s in specs]))
                )
            ).scalars()
        }
        for spec in specs:
            row = existing.get(spec.slug)
            if row is None:
                row = Concept(slug=spec.slug)
                self.session.add(row)
                self._bump("concepts_created")
            else:
                self._bump("concepts_updated")
            row.title = spec.title
            row.category = spec.category.value
            row.skill_slug = skill_for_category(spec.category.value)
            row.skill_node_slug = spec.skill_node
            row.base_difficulty = spec.difficulty
            row.max_tier = spec.max_tier
            row.summary = spec.summary
            row.explanation = spec.explanation.strip()
            row.examples = spec.examples
            row.common_mistakes = spec.common_mistakes
            row.real_world_usage = spec.real_world_usage
            row.visualization = spec.visualization
            row.tags = spec.tags
            row.estimated_minutes = spec.estimated_minutes
            row.content_version = row.content_version + 1 if spec.slug in existing else 1
        await self.session.flush()
        await self._seed_edges(specs)

    async def _seed_edges(self, specs: list[ConceptSpec]) -> None:
        """Rebuild the knowledge graph edges for the given concepts.

        Edges are deleted and recreated rather than diffed: they carry no
        player state, the set is small, and a diff would have to handle
        relation changes anyway.
        """
        slugs = [s.slug for s in specs]
        referenced = {r for s in specs for r in (*s.requires, *s.related)}
        all_slugs = set(slugs) | referenced
        rows = {
            c.slug: c
            for c in (
                await self.session.execute(select(Concept).where(Concept.slug.in_(all_slugs)))
            ).scalars()
        }

        source_ids = [rows[s].id for s in slugs if s in rows]
        if source_ids:
            from sqlalchemy import delete

            await self.session.execute(
                delete(ConceptEdge).where(ConceptEdge.source_id.in_(source_ids))
            )

        for spec in specs:
            source = rows.get(spec.slug)
            if source is None:
                continue
            for target_slug in spec.requires:
                target = rows.get(target_slug)
                if target is None:
                    # A forward reference to a concept in a pack not yet seeded.
                    # Not fatal: the next full seed pass creates it.
                    log.warning("content.edge_target_missing", source=spec.slug, target=target_slug)
                    continue
                self.session.add(
                    ConceptEdge(source_id=source.id, target_id=target.id, relation="requires")
                )
                self._bump("edges")
            for target_slug in spec.related:
                target = rows.get(target_slug)
                if target is None:
                    continue
                self.session.add(
                    ConceptEdge(
                        source_id=source.id, target_id=target.id, relation="related", weight=0.5
                    )
                )
                self._bump("edges")

    async def _seed_challenges(self, specs: list[ChallengeSpec]) -> None:
        if not specs:
            return
        existing = {
            c.slug: c
            for c in (
                await self.session.execute(
                    select(Challenge).where(Challenge.slug.in_([s.slug for s in specs]))
                )
            ).scalars()
        }
        for spec in specs:
            row = existing.get(spec.slug)
            if row is None:
                row = Challenge(slug=spec.slug)
                self.session.add(row)
                self._bump("challenges_created")
            else:
                self._bump("challenges_updated")
            row.title = spec.title
            row.category = spec.category.value
            row.skill_slug = skill_for_category(spec.category.value)
            row.tier = int(spec.tier)
            row.concept_slugs = spec.concepts
            row.prompt = spec.prompt.strip()
            row.starter_code = spec.starter_code.strip("\n")
            row.broken_code = spec.broken_code.strip("\n") if spec.broken_code else None
            row.reference_solution = spec.reference_solution.strip("\n")
            row.solution_explanation = spec.solution_explanation
            row.tests = spec.tests
            row.requires_packages = spec.requires_packages
            row.setup_code = spec.setup_code.strip("\n")
            row.hints = spec.hints
            row.explanation_prompts = spec.explanation_prompts
            row.expected_complexity = spec.expected_complexity
            row.baseline_code = spec.baseline_code
            row.target_speedup = spec.target_speedup
            row.par_seconds = spec.par_seconds
            row.time_limit_seconds = spec.time_limit_seconds
            row.memory_limit_mb = spec.memory_limit_mb

    async def _seed_questions(self, specs: list[QuestionSpec]) -> None:
        if not specs:
            return
        existing = {
            q.slug: q
            for q in (
                await self.session.execute(
                    select(Question).where(Question.slug.in_([s.slug for s in specs]))
                )
            ).scalars()
        }
        for spec in specs:
            row = existing.get(spec.slug)
            if row is None:
                row = Question(slug=spec.slug)
                self.session.add(row)
                self._bump("questions_created")
            else:
                self._bump("questions_updated")
            row.kind = spec.kind.value
            row.category = spec.category.value
            row.skill_slug = skill_for_category(spec.category.value)
            row.tier = int(spec.tier)
            row.interview_level = spec.level.value
            row.concept_slugs = spec.concepts
            row.prompt = spec.prompt.strip()
            row.context = spec.context.strip("\n") if spec.context else None
            row.options = spec.options
            row.expected_answer = spec.expected_answer
            row.ideal_senior_answer = spec.ideal_senior_answer
            row.common_wrong_answer = spec.common_wrong_answer
            row.rubric = spec.rubric
            row.hints = spec.hints
            row.followups = spec.followups
            row.tags = spec.tags
            row.par_seconds = spec.par_seconds

    async def _seed_missions(self, specs: list[MissionSpec]) -> None:
        if not specs:
            return
        existing = {
            m.slug: m
            for m in (
                await self.session.execute(
                    select(Mission).where(Mission.slug.in_([s.slug for s in specs]))
                )
            ).scalars()
        }
        for spec in specs:
            row = existing.get(spec.slug)
            if row is None:
                row = Mission(slug=spec.slug)
                self.session.add(row)
                self._bump("missions_created")
            else:
                self._bump("missions_updated")
            row.title = spec.title
            row.kind = spec.kind
            row.category = spec.category.value
            row.building = spec.building
            row.tier = int(spec.tier)
            row.skill_slug = skill_for_category(spec.category.value)
            row.briefing = spec.briefing.strip()
            row.objective = spec.objective
            row.success_criteria = spec.success_criteria
            row.artifacts = spec.artifacts
            row.debrief = spec.debrief.strip()
            row.required_level = spec.required_level
            row.required_rank = spec.required_rank
            row.prerequisite_mission_slugs = spec.requires_missions
            row.concept_slugs = spec.concepts
            row.estimated_minutes = spec.estimated_minutes
            row.par_seconds = spec.par_seconds
            row.xp_multiplier = spec.xp_multiplier
            row.is_boss = spec.is_boss
            await self.session.flush()

            # Steps are positional and carry no player state of their own
            # (results live on MissionAttempt), so replacing them wholesale is
            # both correct and simpler than diffing.
            from sqlalchemy import delete

            await self.session.execute(delete(MissionStep).where(MissionStep.mission_id == row.id))
            for position, step in enumerate(spec.steps):
                self.session.add(
                    MissionStep(
                        mission_id=row.id,
                        position=position,
                        step_type=step.step_type,
                        title=step.title,
                        prompt=step.prompt.strip(),
                        challenge_slug=step.challenge,
                        question_slug=step.question,
                        config=step.config,
                        required=step.required,
                    )
                )

    async def _seed_badges(self, specs: list[BadgeSpec]) -> None:
        await self._seed_simple(specs, Badge, "badges", _badge_fields)

    async def _seed_achievements(self, specs: list[AchievementSpec]) -> None:
        await self._seed_simple(specs, Achievement, "achievements", _achievement_fields)

    async def _seed_projects(self, specs: list[ProjectSpec]) -> None:
        await self._seed_simple(specs, Project, "projects", _project_fields)

    async def _seed_documents(self, specs: list[DocumentSpec]) -> None:
        if not specs:
            return
        existing = {
            d.slug: d
            for d in (
                await self.session.execute(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.slug.in_([s.slug for s in specs])
                    )
                )
            ).scalars()
        }
        for spec in specs:
            row = existing.get(spec.slug)
            if row is None:
                row = KnowledgeDocument(slug=spec.slug)
                self.session.add(row)
                self._bump("documents_created")
            row.corpus = spec.corpus
            row.title = spec.title
            row.content = spec.content.strip()
            row.source = spec.source
            row.doc_metadata = spec.metadata
            row.token_count = max(1, len(spec.content) // 4)

    async def _seed_simple(self, specs: list, model: Any, label: str, mapper) -> None:
        if not specs:
            return
        existing = {
            r.slug: r
            for r in (
                await self.session.execute(
                    select(model).where(model.slug.in_([s.slug for s in specs]))
                )
            ).scalars()
        }
        for spec in specs:
            row = existing.get(spec.slug)
            if row is None:
                row = model(slug=spec.slug)
                self.session.add(row)
                self._bump(f"{label}_created")
            for field, value in mapper(spec).items():
                setattr(row, field, value)


def _badge_fields(spec: BadgeSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "tier": spec.tier,
        "icon": spec.icon,
        "criteria": spec.criteria,
        "xp_reward": spec.xp_reward,
        "secret": spec.secret,
    }


def _achievement_fields(spec: AchievementSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "icon": spec.icon,
        "criteria": spec.criteria,
        "xp_reward": spec.xp_reward,
        "coin_reward": spec.coin_reward,
        "target": spec.target,
        "secret": spec.secret,
    }


def _project_fields(spec: ProjectSpec) -> dict[str, Any]:
    return {
        "title": spec.title,
        "summary": spec.summary,
        "brief": spec.brief.strip(),
        "milestones": spec.milestones,
        "architecture": spec.architecture,
        "defense_question_slugs": spec.defense_questions,
        "required_level": spec.required_level,
        "required_rank": spec.required_rank,
        "xp_reward": spec.xp_reward,
    }


async def seed_all(session: AsyncSession, *, strict: bool = False) -> dict[str, Any]:
    """Seed structure + every registered pack. Safe to run repeatedly."""
    seeder = Seeder(session)
    await seeder.seed_skills()

    all_warnings: list[str] = []
    for pack in all_packs():
        warnings = await seeder.seed_pack(pack, strict=strict)
        all_warnings.extend(f"[{pack.name}] {w}" for w in warnings)
        log.info("content.pack_seeded", pack=pack.name, **pack.counts())

    log.info("content.seed_complete", **seeder.stats)
    return {"stats": seeder.stats, "warnings": all_warnings}


def content_summary() -> dict[str, Any]:
    """Totals across every registered pack — used by the CLI and by CI."""
    totals: dict[str, int] = {}
    per_pack: dict[str, dict[str, int]] = {}
    for pack in all_packs():
        counts = pack.counts()
        per_pack[pack.name] = counts
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return {"totals": totals, "packs": per_pack}


def _spec_dict(spec: Any) -> dict[str, Any]:
    return asdict(spec)
