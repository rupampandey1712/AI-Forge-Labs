"""Typed authoring format for learning content.

WHY Python dataclasses instead of YAML/JSON files
--------------------------------------------------
Content is the largest and most error-prone part of this project. Authoring it
in Python buys three things a data file cannot:

1. **The type checker is the first proofreader.** A missing rubric, a tier of
   ``11``, a challenge pointing at a concept slug that does not exist — all of
   these are caught by ``validate_pack`` before a single row is written.
2. **Composition.** Ninety challenges share the same five test-case shapes;
   helpers like ``eq()`` and ``raises()`` remove the copy-paste where typos live.
3. **Refactorability.** Renaming a concept slug is a find-and-replace the tools
   understand, not a grep through JSON and a silently orphaned reference.

The cost is that content authors must write Python. For a project where the
author *is* an engineer, that is a trade worth making — and it is exactly the
kind of reasoning the Architecture Tower asks players to defend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.enums import Category, DifficultyTier, InterviewLevel, QuestionKind, Severity


# ── Small helpers for authoring test cases ───────────────────────────────────
def eq(
    name: str,
    call: str,
    expect: Any,
    *,
    hidden: bool = False,
    points: float = 1.0,
    description: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "equals",
        "call": call,
        "expect": expect,
        "hidden": hidden,
        "points": points,
        "description": description,
    }


def approx(
    name: str,
    call: str,
    expect: Any,
    *,
    tolerance: float = 1e-6,
    hidden: bool = False,
    points: float = 1.0,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "approx",
        "call": call,
        "expect": expect,
        "tolerance": tolerance,
        "hidden": hidden,
        "points": points,
    }


def raises(
    name: str, call: str, exception: str, *, hidden: bool = False, points: float = 1.0
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "raises",
        "call": call,
        "exception": exception,
        "hidden": hidden,
        "points": points,
    }


def predicate(
    name: str,
    call: str,
    condition: str,
    *,
    hidden: bool = False,
    points: float = 1.0,
    description: str = "",
) -> dict[str, Any]:
    """Assert a property of the result rather than an exact value.

    Essential for challenges where many answers are correct — "returns a
    generator", "is sorted", "did not mutate the input". Testing for an exact
    value there would grade style instead of correctness.
    """
    return {
        "name": name,
        "kind": "predicate",
        "call": call,
        "predicate": condition,
        "hidden": hidden,
        "points": points,
        "description": description,
    }


def script(
    name: str, code: str, *, hidden: bool = False, points: float = 1.0, description: str = ""
) -> dict[str, Any]:
    """Free-form assertions — for multi-step or stateful checks."""
    return {
        "name": name,
        "kind": "script",
        "script": code,
        "hidden": hidden,
        "points": points,
        "description": description,
    }


def prints(
    name: str, call: str, expected: str, *, hidden: bool = False, points: float = 1.0
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "stdout",
        "call": call,
        "expect_stdout": expected,
        "hidden": hidden,
        "points": points,
    }


def point(
    text: str,
    *keywords: str,
    weight: float = 1.0,
    dimension: str = "correctness",
    require_all: bool = False,
) -> dict[str, Any]:
    """One rubric point: what a good answer says, and how to recognise it."""
    return {
        "point": text,
        "keywords": list(keywords),
        "weight": weight,
        "dimension": dimension,
        "require_all": require_all,
    }


def opt(option_id: str, text: str, *, correct: bool = False, why: str = "") -> dict[str, Any]:
    """An MCQ option. ``why`` is mandatory in spirit: a distractor without an
    explanation teaches nothing when the player picks it."""
    return {"id": option_id, "text": text, "correct": correct, "why": why}


def example(title: str, code: str, *, output: str = "", note: str = "") -> dict[str, Any]:
    return {"title": title, "code": code.strip("\n"), "output": output, "note": note}


def mistake(text: str, why: str, fix: str, severity: Severity = Severity.MEDIUM) -> dict[str, Any]:
    return {"mistake": text, "why": why, "fix": fix, "severity": severity.value}


# ── Content records ──────────────────────────────────────────────────────────
@dataclass(slots=True)
class ConceptSpec:
    slug: str
    title: str
    category: Category
    skill_node: str
    difficulty: int
    summary: str
    explanation: str
    examples: list[dict[str, Any]] = field(default_factory=list)
    common_mistakes: list[dict[str, Any]] = field(default_factory=list)
    real_world_usage: list[str] = field(default_factory=list)
    #: Prerequisite concept slugs — hard gates in the knowledge graph.
    requires: list[str] = field(default_factory=list)
    #: Soft "see also" links that drive recommendations.
    related: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    estimated_minutes: int = 6
    max_tier: int = 10
    #: Spec for an animated frontend visualiser, e.g.
    #: {"type": "event_loop", "steps": [...]}.
    visualization: dict[str, Any] | None = None


@dataclass(slots=True)
class ChallengeSpec:
    slug: str
    title: str
    category: Category
    tier: DifficultyTier
    prompt: str
    tests: list[dict[str, Any]]
    concepts: list[str]
    starter_code: str = ""
    #: Present => this is a DEBUG challenge: the player receives broken code.
    broken_code: str | None = None
    reference_solution: str = ""
    solution_explanation: str = ""
    setup_code: str = ""
    requires_packages: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    #: Rubric points for the mandatory "explain your solution" step.
    explanation_prompts: list[dict[str, Any]] = field(default_factory=list)
    expected_complexity: str | None = None
    baseline_code: str | None = None
    target_speedup: float | None = None
    par_seconds: int = 420
    time_limit_seconds: int = 8
    memory_limit_mb: int = 256


@dataclass(slots=True)
class QuestionSpec:
    slug: str
    kind: QuestionKind
    category: Category
    tier: DifficultyTier
    level: InterviewLevel
    prompt: str
    concepts: list[str] = field(default_factory=list)
    context: str | None = None
    options: list[dict[str, Any]] = field(default_factory=list)
    expected_answer: str = ""
    ideal_senior_answer: str = ""
    common_wrong_answer: str = ""
    rubric: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    par_seconds: int = 180


@dataclass(slots=True)
class MissionStepSpec:
    step_type: Literal["challenge", "question", "explanation", "design", "review", "journal"]
    title: str = ""
    prompt: str = ""
    challenge: str | None = None
    question: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    required: bool = True


@dataclass(slots=True)
class MissionSpec:
    slug: str
    title: str
    kind: str
    category: Category
    building: str
    tier: DifficultyTier
    briefing: str
    objective: str
    steps: list[MissionStepSpec]
    concepts: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    #: Logs, metrics, stack traces, schemas — the evidence for debugging and
    #: incident missions. This is what makes them investigations, not quizzes.
    artifacts: dict[str, Any] = field(default_factory=dict)
    debrief: str = ""
    required_level: int = 1
    required_rank: str | None = None
    requires_missions: list[str] = field(default_factory=list)
    estimated_minutes: int = 15
    par_seconds: int = 900
    xp_multiplier: float = 1.0
    is_boss: bool = False


@dataclass(slots=True)
class BadgeSpec:
    slug: str
    name: str
    description: str
    tier: str
    criteria: dict[str, Any]
    icon: str = "award"
    xp_reward: int = 0
    secret: bool = False


@dataclass(slots=True)
class AchievementSpec:
    slug: str
    name: str
    description: str
    criteria: dict[str, Any]
    category: str = "general"
    icon: str = "trophy"
    xp_reward: int = 0
    coin_reward: int = 0
    target: int = 1
    secret: bool = False


@dataclass(slots=True)
class DocumentSpec:
    """A document for the in-game RAG corpora."""

    slug: str
    corpus: str
    title: str
    content: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectSpec:
    slug: str
    title: str
    summary: str
    brief: str
    milestones: list[dict[str, Any]]
    architecture: dict[str, Any] = field(default_factory=dict)
    defense_questions: list[str] = field(default_factory=list)
    required_level: int = 1
    required_rank: str | None = None
    xp_reward: int = 2000


@dataclass(slots=True)
class ContentPack:
    """One themed bundle of content, e.g. ``python_core`` or ``rag_tower``."""

    name: str
    concepts: list[ConceptSpec] = field(default_factory=list)
    challenges: list[ChallengeSpec] = field(default_factory=list)
    questions: list[QuestionSpec] = field(default_factory=list)
    missions: list[MissionSpec] = field(default_factory=list)
    badges: list[BadgeSpec] = field(default_factory=list)
    achievements: list[AchievementSpec] = field(default_factory=list)
    documents: list[DocumentSpec] = field(default_factory=list)
    projects: list[ProjectSpec] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "concepts": len(self.concepts),
            "challenges": len(self.challenges),
            "questions": len(self.questions),
            "missions": len(self.missions),
            "badges": len(self.badges),
            "achievements": len(self.achievements),
            "documents": len(self.documents),
            "projects": len(self.projects),
        }


class ContentError(ValueError):
    """A content bug. Raised at seed time so it can never reach a player."""


def validate_pack(pack: ContentPack, known_concepts: set[str] | None = None) -> list[str]:
    """Structural validation. Returns warnings; raises on anything fatal.

    This runs in CI (``tests/test_content_integrity.py``), which means a
    dangling concept reference or a challenge with no hidden tests fails the
    build rather than shipping a broken mission.
    """
    warnings: list[str] = []
    concept_slugs = (known_concepts or set()) | {c.slug for c in pack.concepts}
    challenge_slugs = {c.slug for c in pack.challenges}
    question_slugs = {q.slug for q in pack.questions}

    from app.game.skills.registry import SKILL_TREES

    valid_nodes = {n.slug for nodes in SKILL_TREES.values() for n in nodes}

    seen: set[str] = set()
    for concept in pack.concepts:
        if concept.slug in seen:
            raise ContentError(f"{pack.name}: duplicate concept slug '{concept.slug}'")
        seen.add(concept.slug)
        if not 1 <= concept.difficulty <= 10:
            raise ContentError(f"{concept.slug}: difficulty must be 1-10")
        if concept.skill_node and concept.skill_node not in valid_nodes:
            raise ContentError(f"{concept.slug}: unknown skill node '{concept.skill_node}'")
        if not concept.explanation.strip():
            raise ContentError(f"{concept.slug}: explanation is empty")
        if not concept.examples:
            warnings.append(f"{concept.slug}: no examples — concepts teach better with one")

    for challenge in pack.challenges:
        if not challenge.tests:
            raise ContentError(f"{challenge.slug}: has no tests")
        if not any(t.get("hidden") for t in challenge.tests):
            # Without a hidden case, a player can hard-code the visible answers
            # and the grade means nothing.
            warnings.append(f"{challenge.slug}: no hidden tests — solution can be hard-coded")
        for ref in challenge.concepts:
            if ref not in concept_slugs:
                raise ContentError(f"{challenge.slug}: references unknown concept '{ref}'")
        if not challenge.reference_solution.strip():
            warnings.append(f"{challenge.slug}: no reference solution to reveal after failures")

    for question in pack.questions:
        for ref in question.concepts:
            if ref not in concept_slugs:
                raise ContentError(f"{question.slug}: references unknown concept '{ref}'")
        if question.kind in (QuestionKind.MCQ, QuestionKind.MULTI_SELECT):
            if not question.options:
                raise ContentError(f"{question.slug}: MCQ with no options")
            if not any(o.get("correct") for o in question.options):
                raise ContentError(f"{question.slug}: MCQ with no correct option")
            missing_why = [o["id"] for o in question.options if not o.get("why")]
            if missing_why:
                warnings.append(f"{question.slug}: options {missing_why} have no explanation")
        elif not question.rubric:
            raise ContentError(
                f"{question.slug}: free-text question with no rubric cannot be graded"
            )

    for mission in pack.missions:
        if not mission.steps:
            raise ContentError(f"{mission.slug}: has no steps")
        for i, step in enumerate(mission.steps):
            if step.step_type == "challenge" and step.challenge not in challenge_slugs:
                raise ContentError(f"{mission.slug} step {i}: unknown challenge '{step.challenge}'")
            if step.step_type == "question" and step.question not in question_slugs:
                raise ContentError(f"{mission.slug} step {i}: unknown question '{step.question}'")
            if step.step_type in ("explanation", "design", "review") and not step.config.get(
                "rubric"
            ):
                warnings.append(f"{mission.slug} step {i}: free-form step with no rubric")

    return warnings
