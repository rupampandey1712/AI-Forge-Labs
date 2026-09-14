"""Content integrity — the CI gate that stops a broken mission reaching a player.

The most valuable test in this file is ``test_every_reference_solution_passes``:
it actually executes each authored solution against its own test suite in the
sandbox. Content that claims to be solvable but is not is the single worst bug
a learning product can ship, and it is invisible to every other kind of test.
"""

from __future__ import annotations

import pytest

from app.content.registry import all_packs
from app.content.schema import validate_pack
from app.domain.enums import Category, DifficultyTier, QuestionKind
from app.game.grading.rubric import grade_free_text
from app.game.skills.registry import BUILDING_BY_ID, SKILL_BY_SLUG, SKILL_TREES
from app.sandbox.protocol import TestCase
from app.sandbox.service import SandboxService

pytestmark = pytest.mark.integration

PACKS = all_packs()
ALL_CONCEPTS = [c for p in PACKS for c in p.concepts]
ALL_CHALLENGES = [c for p in PACKS for c in p.challenges]
ALL_QUESTIONS = [q for p in PACKS for q in p.questions]
ALL_MISSIONS = [m for p in PACKS for m in p.missions]
CONCEPT_SLUGS = {c.slug for c in ALL_CONCEPTS}


class TestStructure:
    def test_every_pack_validates(self):
        for pack in PACKS:
            validate_pack(pack, known_concepts=CONCEPT_SLUGS)

    def test_slugs_are_globally_unique(self):
        for label, items in (
            ("concept", ALL_CONCEPTS),
            ("challenge", ALL_CHALLENGES),
            ("question", ALL_QUESTIONS),
            ("mission", ALL_MISSIONS),
        ):
            slugs = [i.slug for i in items]
            duplicates = {s for s in slugs if slugs.count(s) > 1}
            assert not duplicates, f"duplicate {label} slugs: {duplicates}"

    def test_missions_reference_real_buildings(self):
        for mission in ALL_MISSIONS:
            assert mission.building in BUILDING_BY_ID, (
                f"{mission.slug} -> unknown building {mission.building}"
            )

    def test_concepts_reference_real_skill_nodes(self):
        valid = {n.slug for nodes in SKILL_TREES.values() for n in nodes}
        for concept in ALL_CONCEPTS:
            assert concept.skill_node in valid, f"{concept.slug} -> {concept.skill_node}"

    def test_every_category_maps_to_a_skill(self):
        from app.game.skills.registry import skill_for_category

        for category in Category:
            assert skill_for_category(category.value) in SKILL_BY_SLUG

    def test_knowledge_graph_has_no_cycles(self):
        """A prerequisite cycle would make content permanently unreachable."""
        edges: dict[str, list[str]] = {
            c.slug: [r for r in c.requires if r in CONCEPT_SLUGS] for c in ALL_CONCEPTS
        }
        state: dict[str, int] = {}

        def visit(node: str, path: list[str]) -> None:
            if state.get(node) == 2:
                return
            if state.get(node) == 1:
                raise AssertionError(f"prerequisite cycle: {' -> '.join([*path, node])}")
            state[node] = 1
            for child in edges.get(node, []):
                visit(child, [*path, node])
            state[node] = 2

        for slug in edges:
            visit(slug, [])

    def test_prerequisites_are_not_harder_than_their_dependents(self):
        by_slug = {c.slug: c for c in ALL_CONCEPTS}
        for concept in ALL_CONCEPTS:
            for prereq_slug in concept.requires:
                prereq = by_slug.get(prereq_slug)
                if prereq is None:
                    continue
                assert prereq.difficulty <= concept.difficulty, (
                    f"{concept.slug} (d{concept.difficulty}) requires "
                    f"{prereq.slug} (d{prereq.difficulty}) — a harder prerequisite"
                )

    def test_mission_prerequisites_exist(self):
        slugs = {m.slug for m in ALL_MISSIONS}
        for mission in ALL_MISSIONS:
            for required in mission.requires_missions:
                assert required in slugs, f"{mission.slug} -> unknown prerequisite {required}"


class TestConceptQuality:
    @pytest.mark.parametrize("concept", ALL_CONCEPTS, ids=lambda c: c.slug)
    def test_teaches_mechanism_not_just_syntax(self, concept):
        assert len(concept.explanation) > 400, "a concept needs a real explanation"
        assert concept.summary and len(concept.summary) < 200
        assert concept.examples, "every concept needs at least one worked example"
        assert concept.common_mistakes, "the mistakes are half the lesson"
        assert concept.real_world_usage, "concepts must connect to real systems"

    @pytest.mark.parametrize("concept", ALL_CONCEPTS, ids=lambda c: c.slug)
    def test_mistakes_carry_a_fix(self, concept):
        for mistake in concept.common_mistakes:
            assert mistake["why"], f"{concept.slug}: a mistake without a reason"
            assert mistake["fix"], f"{concept.slug}: a mistake without a fix"


class TestChallengeQuality:
    @pytest.mark.parametrize("challenge", ALL_CHALLENGES, ids=lambda c: c.slug)
    def test_has_hidden_tests_and_a_solution(self, challenge):
        assert any(t.get("hidden") for t in challenge.tests), (
            "without a hidden test the visible answers can be hard-coded"
        )
        assert challenge.reference_solution.strip()
        assert challenge.solution_explanation.strip(), "revealing a solution must also teach"

    @pytest.mark.parametrize("challenge", ALL_CHALLENGES, ids=lambda c: c.slug)
    def test_hints_escalate_without_giving_the_answer(self, challenge):
        assert challenge.hints, "a player who is stuck needs a ladder, not a wall"
        for hint in challenge.hints:
            assert len(hint) > 15

    @pytest.mark.parametrize("challenge", ALL_CHALLENGES, ids=lambda c: c.slug)
    def test_debug_challenges_ship_broken_code(self, challenge):
        if challenge.tier is DifficultyTier.DEBUG:
            assert challenge.broken_code, (
                f"{challenge.slug} is a DEBUG challenge but has nothing to debug"
            )

    @pytest.mark.parametrize("challenge", ALL_CHALLENGES, ids=lambda c: c.slug)
    def test_concepts_are_declared(self, challenge):
        assert challenge.concepts, "a challenge with no concepts cannot feed the retention engine"
        for slug in challenge.concepts:
            assert slug in CONCEPT_SLUGS


class TestQuestionQuality:
    @pytest.mark.parametrize("question", ALL_QUESTIONS, ids=lambda q: q.slug)
    def test_is_gradable_and_teaches_on_answer(self, question):
        if question.kind in (QuestionKind.MCQ, QuestionKind.MULTI_SELECT):
            assert question.options
            assert sum(1 for o in question.options if o.get("correct")) >= 1
            for option in question.options:
                assert option.get("why"), (
                    f"{question.slug}: option {option['id']} has no explanation — "
                    "a distractor teaches nothing without one"
                )
        else:
            assert question.rubric, f"{question.slug}: free text with no rubric is ungradable"

        assert question.ideal_senior_answer, (
            f"{question.slug}: without an ideal answer the player cannot see the gap"
        )

    @pytest.mark.parametrize("question", ALL_QUESTIONS, ids=lambda q: q.slug)
    def test_rubric_keywords_are_matchable(self, question):
        """A keyword that survives normalisation is one that can actually match."""
        from app.game.grading.rubric import RubricPoint

        for raw in question.rubric:
            rubric_point = RubricPoint.from_dict(raw)
            assert rubric_point.point, f"{question.slug}: a rubric point with no description"
            assert rubric_point.keywords, (
                f"{question.slug}: '{rubric_point.point}' has no matchable keywords"
            )

    @pytest.mark.parametrize(
        "question",
        [q for q in ALL_QUESTIONS if q.kind not in (QuestionKind.MCQ, QuestionKind.MULTI_SELECT)],
        ids=lambda q: q.slug,
    )
    def test_the_ideal_answer_scores_well_against_its_own_rubric(self, question):
        """If the model answer cannot pass the grader, the rubric is wrong."""
        grade = grade_free_text(
            question.ideal_senior_answer,
            question.rubric,
            tier=int(question.tier),
            expected_answer=question.expected_answer,
        )
        assert grade.dimension_scores["correctness"] >= 0.6, (
            f"{question.slug}: the ideal answer only scored "
            f"{grade.dimension_scores['correctness']:.2f} on correctness. "
            f"Missing: {grade.missing_points}"
        )

    @pytest.mark.parametrize(
        "question",
        [q for q in ALL_QUESTIONS if q.kind not in (QuestionKind.MCQ, QuestionKind.MULTI_SELECT)],
        ids=lambda q: q.slug,
    )
    def test_a_junior_answer_scores_below_the_ideal_one(self, question):
        """The grader must discriminate, not just match keywords."""
        ideal = grade_free_text(
            question.ideal_senior_answer, question.rubric, tier=int(question.tier)
        )
        naive = grade_free_text(
            "It depends. I would look it up.", question.rubric, tier=int(question.tier)
        )
        assert naive.score < ideal.score - 2.0, f"{question.slug}: grader does not discriminate"

    def test_interview_levels_span_the_ladder(self):
        levels = {q.level for q in ALL_QUESTIONS}
        assert len(levels) >= 3, "content must cover more than one seniority band"


class TestMissionQuality:
    @pytest.mark.parametrize("mission", ALL_MISSIONS, ids=lambda m: m.slug)
    def test_has_briefing_criteria_and_debrief(self, mission):
        assert len(mission.briefing) > 100, "a mission needs in-fiction framing"
        assert mission.objective
        assert mission.success_criteria
        assert len(mission.debrief) > 150, "the debrief is where the learning lands"

    @pytest.mark.parametrize("mission", ALL_MISSIONS, ids=lambda m: m.slug)
    def test_debugging_and_incident_missions_provide_evidence(self, mission):
        if mission.kind in ("debugging", "incident"):
            assert mission.artifacts, (
                f"{mission.slug}: a debugging mission without logs/metrics is a quiz"
            )

    @pytest.mark.parametrize("mission", ALL_MISSIONS, ids=lambda m: m.slug)
    def test_asks_for_an_explanation_somewhere(self, mission):
        """Spec §41: passing tests is never enough."""
        kinds = {s.step_type for s in mission.steps}
        assert kinds & {"explanation", "design", "review", "question"}, (
            f"{mission.slug}: no step asks the player to justify anything"
        )


@pytest.mark.slow
class TestSolvability:
    """Execute every authored solution against its own suite."""

    @pytest.mark.parametrize("challenge", ALL_CHALLENGES, ids=lambda c: c.slug)
    async def test_every_reference_solution_passes(self, challenge):
        sandbox = SandboxService()
        result = await sandbox.run(
            challenge.reference_solution,
            tests=[TestCase.from_dict(t) for t in challenge.tests],
            setup_code=challenge.setup_code,
            timeout_seconds=max(challenge.time_limit_seconds, 10),
        )
        assert result.passed, (
            f"{challenge.slug}: the authored solution does not pass its own tests.\n"
            f"status={result.status} {result.tests_passed}/{result.tests_total}\n"
            f"stderr={result.stderr[:500]}\n"
            f"failures={[(o.name, o.message) for o in result.outcomes if not o.passed]}"
        )

    @pytest.mark.parametrize(
        "challenge",
        [c for c in ALL_CHALLENGES if c.broken_code],
        ids=lambda c: c.slug,
    )
    async def test_broken_code_actually_fails(self, challenge):
        """A 'debug this' challenge whose starting code already passes is pointless."""
        sandbox = SandboxService()
        result = await sandbox.run(
            challenge.broken_code,
            tests=[TestCase.from_dict(t) for t in challenge.tests],
            setup_code=challenge.setup_code,
            timeout_seconds=max(challenge.time_limit_seconds, 10),
        )
        assert not result.passed, f"{challenge.slug}: the 'broken' code passes all tests"


class TestVolume:
    """Guards against content silently shrinking. Raise these as packs land."""

    def test_pack_counts(self):
        totals = {
            "concepts": len(ALL_CONCEPTS),
            "challenges": len(ALL_CHALLENGES),
            "questions": len(ALL_QUESTIONS),
            "missions": len(ALL_MISSIONS),
        }
        assert totals["concepts"] >= 12, totals
        assert totals["challenges"] >= 8, totals
        assert totals["questions"] >= 8, totals
        assert totals["missions"] >= 3, totals

    def test_difficulty_spans_the_full_ladder(self):
        """The game must not stop at 'what is a decorator?'."""
        tiers = {int(c.tier) for c in ALL_CHALLENGES} | {int(q.tier) for q in ALL_QUESTIONS}
        assert min(tiers) <= 2, "content must include entry-level material"
        assert max(tiers) >= 8, "content must reach production/staff tiers"

    def test_badges_and_achievements_have_interpretable_criteria(self):
        from app.game.achievements.rules import NUMERIC_STATS

        known_keys = {
            "stat",
            "gte",
            "skill",
            "mastery_gte",
            "tier_cleared_gte",
            "level_gte",
            "rank_at_least",
            "streak_gte",
            "all_skills_mastery_gte",
            "skills_mastery_gte",
        }
        for pack in PACKS:
            for spec in [*pack.badges, *pack.achievements]:
                assert spec.criteria, f"{spec.slug}: no criteria — it can never unlock"
                unknown = set(spec.criteria) - known_keys
                assert not unknown, (
                    f"{spec.slug}: criteria keys the rules engine ignores: {unknown}"
                )
                if "stat" in spec.criteria:
                    assert spec.criteria["stat"] in NUMERIC_STATS, (
                        f"{spec.slug}: unknown stat '{spec.criteria['stat']}'"
                    )
