"""Domain vocabulary.

Every enum here is a ``str`` enum so it serialises to readable JSON, stores as
readable text in the database, and stays greppable in logs. The DB columns use
native ``String`` + a CHECK-free application constraint rather than PG ENUM
types: adding a new rank or category should be a code change, not a migration
with an ``ALTER TYPE`` that cannot run inside a transaction on older Postgres.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Rank(StrEnum):
    """Career ladder at AI Forge Labs. Order matters — see ``RANK_ORDER``."""

    PYTHON_APPRENTICE = "python_apprentice"
    PYTHON_DEVELOPER = "python_developer"
    BACKEND_ENGINEER = "backend_engineer"
    SENIOR_PYTHON_ENGINEER = "senior_python_engineer"
    ML_ENGINEER = "ml_engineer"
    DEEP_LEARNING_ENGINEER = "deep_learning_engineer"
    AI_ENGINEER = "ai_engineer"
    LLM_ENGINEER = "llm_engineer"
    AI_PLATFORM_ENGINEER = "ai_platform_engineer"
    STAFF_AI_ENGINEER = "staff_ai_engineer"
    PRINCIPAL_AI_ENGINEER = "principal_ai_engineer"


RANK_ORDER: tuple[Rank, ...] = tuple(Rank)

RANK_TITLES: dict[Rank, str] = {
    Rank.PYTHON_APPRENTICE: "Python Apprentice",
    Rank.PYTHON_DEVELOPER: "Python Developer",
    Rank.BACKEND_ENGINEER: "Backend Engineer",
    Rank.SENIOR_PYTHON_ENGINEER: "Senior Python Engineer",
    Rank.ML_ENGINEER: "ML Engineer",
    Rank.DEEP_LEARNING_ENGINEER: "Deep Learning Engineer",
    Rank.AI_ENGINEER: "AI Engineer",
    Rank.LLM_ENGINEER: "LLM Engineer",
    Rank.AI_PLATFORM_ENGINEER: "AI Platform Engineer",
    Rank.STAFF_AI_ENGINEER: "Staff AI Engineer",
    Rank.PRINCIPAL_AI_ENGINEER: "Principal AI Engineer",
}


class SkillId(StrEnum):
    """The 16 player attributes. These are the axes of the radar chart."""

    PYTHON = "python"
    BACKEND = "backend"
    DATABASE = "database"
    DATA_ENGINEERING = "data_engineering"
    ML = "ml"
    DEEP_LEARNING = "deep_learning"
    LLM = "llm"
    RAG = "rag"
    AGENTS = "agents"
    ARCHITECTURE = "architecture"
    TESTING = "testing"
    DEVOPS = "devops"
    SYSTEM_DESIGN = "system_design"
    DEBUGGING = "debugging"
    COMMUNICATION = "communication"
    INTERVIEW_SKILLS = "interview_skills"


class Category(StrEnum):
    """Content taxonomy — maps 1:1 to the buildings on the world map."""

    PYTHON = "python"
    OOP = "oop"
    FASTAPI = "fastapi"
    PYDANTIC = "pydantic"
    SQLALCHEMY = "sqlalchemy"
    POSTGRESQL = "postgresql"
    NUMPY = "numpy"
    PANDAS = "pandas"
    MATPLOTLIB = "matplotlib"
    ML = "ml"
    PYTORCH = "pytorch"
    DEEP_LEARNING = "deep_learning"
    TRANSFORMERS = "transformers"
    LLM = "llm"
    RAG = "rag"
    EVALS = "evals"
    LANGCHAIN = "langchain"
    LANGGRAPH = "langgraph"
    LANGSMITH = "langsmith"
    SYSTEM_DESIGN = "system_design"
    ARCHITECTURE = "architecture"
    DEVOPS = "devops"
    TESTING = "testing"
    DEBUGGING = "debugging"
    PRODUCTION = "production"
    SECURITY = "security"
    CAREER = "career"


class DifficultyTier(IntEnum):
    """The 10-tier depth ladder (spec §56).

    This is the single most important design decision in the game: a concept is
    not "done" at tier 3. ``What is a decorator?`` (REMEMBER) and ``this
    decorator-heavy framework is unmaintainable — do you keep it?`` (PRINCIPAL)
    are the *same concept* at opposite ends of this ladder.
    """

    REMEMBER = 1
    UNDERSTAND = 2
    IMPLEMENT = 3
    DEBUG = 4
    OPTIMIZE = 5
    DESIGN = 6
    EXPLAIN = 7
    PRODUCTION = 8
    STAFF_TRADEOFF = 9
    PRINCIPAL_ARCHITECTURE = 10


TIER_LABELS: dict[DifficultyTier, str] = {
    DifficultyTier.REMEMBER: "Remember",
    DifficultyTier.UNDERSTAND: "Understand",
    DifficultyTier.IMPLEMENT: "Implement",
    DifficultyTier.DEBUG: "Debug",
    DifficultyTier.OPTIMIZE: "Optimize",
    DifficultyTier.DESIGN: "Design",
    DifficultyTier.EXPLAIN: "Explain to another engineer",
    DifficultyTier.PRODUCTION: "Production scenario",
    DifficultyTier.STAFF_TRADEOFF: "Staff-level tradeoff",
    DifficultyTier.PRINCIPAL_ARCHITECTURE: "Principal-level architecture",
}


class ExperienceBand(StrEnum):
    """Simulated seniority expectations (spec §42).

    NOTE: this models the *problems an engineer at that band is expected to
    solve*. It is explicitly not a claim that playing the game confers years of
    professional experience.
    """

    BAND_0_1 = "0-1"
    BAND_1_3 = "1-3"
    BAND_3_5 = "3-5"
    BAND_5_7 = "5-7"
    BAND_7_10 = "7-10"
    BAND_10_PLUS = "10+"


class MissionKind(StrEnum):
    CONCEPT = "concept"
    CODING = "coding"
    DEBUGGING = "debugging"
    REFACTOR = "refactor"
    DATA_LAB = "data_lab"
    ML_LAB = "ml_lab"
    VISUALIZATION = "visualization"
    RAG_LAB = "rag_lab"
    AGENT_LAB = "agent_lab"
    ARCHITECTURE = "architecture"
    CODE_REVIEW = "code_review"
    INCIDENT = "incident"
    INTERVIEW = "interview"
    BOSS = "boss"
    CAPSTONE = "capstone"


class QuestionKind(StrEnum):
    MCQ = "mcq"
    MULTI_SELECT = "multi_select"
    CODING = "coding"
    DEBUGGING = "debugging"
    EXPLAIN = "explain"
    DESIGN = "design"
    CODE_REVIEW = "code_review"
    SCENARIO = "scenario"
    TRADEOFF = "tradeoff"
    ARCHITECTURE = "architecture"
    BEHAVIORAL = "behavioral"
    PREDICT_OUTPUT = "predict_output"


class InterviewLevel(StrEnum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"


class AttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ABANDONED = "abandoned"


class XPSource(StrEnum):
    """Every XP grant is attributable. The ledger is append-only (spec §63)."""

    MISSION_COMPLETE = "mission_complete"
    CHALLENGE_PASSED = "challenge_passed"
    FIRST_ATTEMPT_BONUS = "first_attempt_bonus"
    SPEED_BONUS = "speed_bonus"
    CLEAN_CODE_BONUS = "clean_code_bonus"
    EXPLANATION_BONUS = "explanation_bonus"
    ARCHITECTURE_BONUS = "architecture_bonus"
    BUG_FOUND = "bug_found"
    TEST_WRITTEN = "test_written"
    OPTIMIZATION = "optimization"
    CODE_REVIEW = "code_review"
    DIFFICULTY_BONUS = "difficulty_bonus"
    STREAK_BONUS = "streak_bonus"
    BOSS_DEFEATED = "boss_defeated"
    DAILY_COMPLETE = "daily_complete"
    RETENTION_REPAIR = "retention_repair"
    INTERVIEW_ANSWER = "interview_answer"
    JOURNAL_ENTRY = "journal_entry"
    ACHIEVEMENT = "achievement"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BadgeTier(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    LEGENDARY = "legendary"


class BuildingId(StrEnum):
    """The 14 world-map buildings (spec §2)."""

    PYTHON_ACADEMY = "python_academy"
    BACKEND_CITY = "backend_city"
    DATA_SCIENCE_LAB = "data_science_lab"
    ML_ARENA = "ml_arena"
    DEEP_LEARNING_LAB = "deep_learning_lab"
    TRANSFORMER_CENTER = "transformer_center"
    RAG_TOWER = "rag_tower"
    AGENT_FACTORY = "agent_factory"
    PRODUCTION_CITY = "production_city"
    INTERVIEW_ARENA = "interview_arena"
    ARCHITECTURE_TOWER = "architecture_tower"
    DEBUGGING_DUNGEON = "debugging_dungeon"
    AI_WAR_ROOM = "ai_war_room"
    STAFF_HQ = "staff_hq"


class MentorPersona(StrEnum):
    SENIOR_ENGINEER = "senior_engineer"
    ML_RESEARCHER = "ml_researcher"
    BACKEND_ARCHITECT = "backend_architect"
    AI_ARCHITECT = "ai_architect"
    CODE_REVIEWER = "code_reviewer"
    INTERVIEWER = "interviewer"
