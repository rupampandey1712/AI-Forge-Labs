"""Model registry.

Importing every model here is not stylistic — SQLAlchemy resolves
``relationship()`` targets by class *name* at configure time, and Alembic's
autogenerate only sees tables that have been imported. One import site removes a
whole family of "table not found in metadata" and "expression 'X' failed to
locate a name" bugs.
"""

from app.db.base import Base
from app.models.ai import (
    AgentRun,
    CodeSubmission,
    Evaluation,
    RAGExperiment,
    Span,
    Trace,
)
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
from app.models.interview import InterviewSession, InterviewTurn
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
    ProjectProgress,
    QuestionAttempt,
    SkillProgress,
    XPTransaction,
)
from app.models.user import LeaderboardEntry, PlayerProfile, RefreshToken, User

__all__ = [
    "Achievement",
    "AgentRun",
    "Badge",
    "Base",
    "Challenge",
    "ChallengeAttempt",
    "CodeSubmission",
    "Concept",
    "ConceptEdge",
    "ConceptProgress",
    "DailyChallenge",
    "Evaluation",
    "InterviewSession",
    "InterviewTurn",
    "JournalEntry",
    "KnowledgeDocument",
    "LeaderboardEntry",
    "LearningEvent",
    "Mission",
    "MissionAttempt",
    "MissionStep",
    "MistakeRecord",
    "PlayerAchievement",
    "PlayerBadge",
    "PlayerProfile",
    "Project",
    "ProjectProgress",
    "Question",
    "QuestionAttempt",
    "RAGExperiment",
    "RefreshToken",
    "Skill",
    "SkillNode",
    "SkillProgress",
    "Span",
    "Trace",
    "User",
    "XPTransaction",
]
