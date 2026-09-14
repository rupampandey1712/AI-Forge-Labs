"""Badges, achievements and the capstone project.

These are cross-cutting: they reference progress across every other pack, so
they live in their own module rather than being scattered.

DESIGN NOTE on reward design. Badges are *milestones* (a single moment: "you
did the thing"); achievements are *journeys* with a progress bar. Mixing the two
makes both feel arbitrary. Every criteria object below is interpreted by
``app/game/achievements/rules.py`` — there is no bespoke unlock code anywhere.
"""

from __future__ import annotations

from app.content.schema import AchievementSpec, BadgeSpec, ContentPack, ProjectSpec

BADGES = [
    # ── Journey starters ─────────────────────────────────────────────────
    BadgeSpec(
        slug="first-commit",
        name="First Commit",
        description="Passed your first coding challenge at AI Forge Labs.",
        tier="bronze",
        icon="git-commit",
        criteria={"stat": "challenges_passed", "gte": 1},
        xp_reward=25,
    ),
    BadgeSpec(
        slug="shipped-it",
        name="Shipped It",
        description="Completed your first mission end to end.",
        tier="bronze",
        icon="rocket",
        criteria={"stat": "missions_completed", "gte": 1},
        xp_reward=40,
    ),
    # ── Craft ─────────────────────────────────────────────────────────────
    BadgeSpec(
        slug="python-master",
        name="Python Master",
        description="Python mastery above 85% — including the object model, not just syntax.",
        tier="gold",
        icon="code",
        criteria={"skill": "python", "mastery_gte": 0.85, "tier_cleared_gte": 8},
        xp_reward=600,
    ),
    BadgeSpec(
        slug="async-ninja",
        name="Async Ninja",
        description="Cleared a tier-8 asyncio problem without blocking the event loop.",
        tier="gold",
        icon="zap",
        criteria={"skill": "python", "tier_cleared_gte": 8, "mastery_gte": 0.7},
        xp_reward=450,
    ),
    BadgeSpec(
        slug="api-architect",
        name="API Architect",
        description="Backend mastery above 80%.",
        tier="gold",
        icon="server",
        criteria={"skill": "backend", "mastery_gte": 0.8},
        xp_reward=500,
    ),
    BadgeSpec(
        slug="data-wizard",
        name="Data Wizard",
        description="Data engineering mastery above 80%.",
        tier="gold",
        icon="layers",
        criteria={"skill": "data_engineering", "mastery_gte": 0.8},
        xp_reward=500,
    ),
    BadgeSpec(
        slug="ml-engineer",
        name="ML Engineer",
        description="Machine learning mastery above 75%.",
        tier="gold",
        icon="scatter-chart",
        criteria={"skill": "ml", "mastery_gte": 0.75},
        xp_reward=500,
    ),
    BadgeSpec(
        slug="tensor-tactician",
        name="Tensor Tactician",
        description="Deep learning mastery above 75% — including debugging a training run.",
        tier="gold",
        icon="brain-circuit",
        criteria={"skill": "deep_learning", "mastery_gte": 0.75, "tier_cleared_gte": 7},
        xp_reward=550,
    ),
    BadgeSpec(
        slug="transformer-master",
        name="Transformer Master",
        description="LLM mastery above 80% — attention from first principles.",
        tier="platinum",
        icon="atom",
        criteria={"skill": "llm", "mastery_gte": 0.8, "tier_cleared_gte": 8},
        xp_reward=700,
    ),
    BadgeSpec(
        slug="rag-detective",
        name="RAG Detective",
        description="Diagnosed retrieval failures at tier 8 and above.",
        tier="platinum",
        icon="search",
        criteria={"skill": "rag", "mastery_gte": 0.78, "tier_cleared_gte": 8},
        xp_reward=700,
    ),
    BadgeSpec(
        slug="agent-architect",
        name="Agent Architect",
        description="Agent mastery above 78% — state, loops and human-in-the-loop.",
        tier="platinum",
        icon="workflow",
        criteria={"skill": "agents", "mastery_gte": 0.78},
        xp_reward=700,
    ),
    # ── Operational ───────────────────────────────────────────────────────
    BadgeSpec(
        slug="debugging-legend",
        name="Debugging Legend",
        description="Debugging mastery above 85% at production tier.",
        tier="platinum",
        icon="bug",
        criteria={"skill": "debugging", "mastery_gte": 0.85, "tier_cleared_gte": 8},
        xp_reward=800,
    ),
    BadgeSpec(
        slug="production-hero",
        name="Production Hero",
        description="Resolved 10 production incidents.",
        tier="platinum",
        icon="siren",
        criteria={"stat": "incidents_resolved", "gte": 10},
        xp_reward=800,
    ),
    BadgeSpec(
        slug="interview-crusher",
        name="Interview Crusher",
        description="Interview skills above 80%.",
        tier="gold",
        icon="mic",
        criteria={"skill": "interview_skills", "mastery_gte": 0.8},
        xp_reward=600,
    ),
    BadgeSpec(
        slug="boss-slayer",
        name="Boss Slayer",
        description="Defeated five boss battles.",
        tier="platinum",
        icon="swords",
        criteria={"stat": "bosses_defeated", "gte": 5},
        xp_reward=900,
    ),
    # ── Endgame ───────────────────────────────────────────────────────────
    BadgeSpec(
        slug="staff-engineer",
        name="Staff Engineer",
        description="Reached Staff AI Engineer with breadth across eight skills.",
        tier="legendary",
        icon="crown",
        criteria={
            "rank_at_least": "staff_ai_engineer",
            "skills_mastery_gte": {"count": 8, "threshold": 0.7},
        },
        xp_reward=2000,
    ),
    BadgeSpec(
        slug="principal-engineer",
        name="Principal Engineer",
        description="Reached Principal AI Engineer with 60%+ mastery in every skill.",
        tier="legendary",
        icon="gem",
        criteria={"rank_at_least": "principal_ai_engineer", "all_skills_mastery_gte": 0.6},
        xp_reward=5000,
    ),
    # ── Habit ─────────────────────────────────────────────────────────────
    BadgeSpec(
        slug="thirty-day-streak",
        name="Consistency",
        description="A 30-day practice streak.",
        tier="gold",
        icon="flame",
        criteria={"streak_gte": 30},
        xp_reward=750,
    ),
    BadgeSpec(
        slug="hundred-day-streak",
        name="Relentless",
        description="A 100-day practice streak.",
        tier="legendary",
        icon="flame",
        criteria={"streak_gte": 100},
        xp_reward=2500,
    ),
    # ── Secret ────────────────────────────────────────────────────────────
    BadgeSpec(
        slug="the-long-game",
        name="The Long Game",
        description="Came back and repaired knowledge that had decayed below 45%.",
        tier="silver",
        icon="clock",
        criteria={"stat": "challenges_passed", "gte": 100},
        xp_reward=300,
        secret=True,
    ),
]


ACHIEVEMENTS = [
    AchievementSpec(
        slug="century-of-challenges",
        name="Century",
        description="Pass 100 coding challenges.",
        category="craft",
        icon="target",
        criteria={"stat": "challenges_passed", "gte": 100},
        target=100,
        xp_reward=800,
        coin_reward=200,
    ),
    AchievementSpec(
        slug="thousand-questions",
        name="A Thousand Questions",
        description="Answer 1,000 questions.",
        category="craft",
        icon="help-circle",
        criteria={"stat": "questions_answered", "gte": 1000},
        target=1000,
        xp_reward=2000,
        coin_reward=500,
    ),
    AchievementSpec(
        slug="fifty-missions",
        name="Fifty Missions Deep",
        description="Complete 50 missions.",
        category="craft",
        icon="flag",
        criteria={"stat": "missions_completed", "gte": 50},
        target=50,
        xp_reward=1200,
        coin_reward=300,
    ),
    AchievementSpec(
        slug="incident-commander",
        name="Incident Commander",
        description="Resolve 25 production incidents.",
        category="operations",
        icon="siren",
        criteria={"stat": "incidents_resolved", "gte": 25},
        target=25,
        xp_reward=2500,
        coin_reward=600,
    ),
    AchievementSpec(
        slug="full-spectrum",
        name="Full Spectrum",
        description="Reach 50% mastery in all 16 skills.",
        category="breadth",
        icon="radar",
        criteria={"all_skills_mastery_gte": 0.5},
        target=16,
        xp_reward=3000,
        coin_reward=800,
    ),
    AchievementSpec(
        slug="deep-diver",
        name="Deep Diver",
        description="Clear a tier-10 principal-level problem.",
        category="depth",
        icon="anchor",
        criteria={"tier_cleared_gte": 10},
        target=1,
        xp_reward=2500,
        coin_reward=700,
    ),
    AchievementSpec(
        slug="level-fifty",
        name="Halfway to Principal",
        description="Reach level 50.",
        category="progression",
        icon="trending-up",
        criteria={"level_gte": 50},
        target=50,
        xp_reward=1500,
        coin_reward=400,
    ),
    AchievementSpec(
        slug="year-one",
        name="Year One",
        description="Maintain a 365-day streak.",
        category="habit",
        icon="calendar",
        criteria={"streak_gte": 365},
        target=365,
        xp_reward=10000,
        coin_reward=3000,
        secret=True,
    ),
]


PROJECTS = [
    ProjectSpec(
        slug="ai-enterprise-catalogue",
        title="AI-Powered Enterprise Catalogue Platform",
        summary=(
            "The capstone. Build and defend a production AI platform end to end — "
            "catalogue, semantic search, RAG assistant, agent workflows, evaluation "
            "and observability."
        ),
        brief="""
You are the founding engineer on a new product at AI Forge Labs.

**The ask:** a catalogue platform for enterprise customers, with an AI assistant
that answers questions about products using the customer's own documents.

**What makes this the capstone:** every milestone forces you to use something
you learned earlier, and the final step is not a deployment — it is defending
every architectural decision to a Staff and a Principal engineer who will ask
why, what breaks at 10x, and what you would do differently.

You may not answer "because the tutorial said so". There is no tutorial.
""",
        architecture={
            "layers": [
                {
                    "id": "web",
                    "label": "React + TypeScript",
                    "tech": ["vite", "tailwind", "framer-motion"],
                },
                {"id": "api", "label": "FastAPI", "tech": ["pydantic", "jwt", "async"]},
                {
                    "id": "cache",
                    "label": "Redis",
                    "tech": ["session", "read-through", "rate-limit"],
                },
                {"id": "db", "label": "PostgreSQL", "tech": ["sqlalchemy", "alembic", "indexes"]},
                {"id": "queue", "label": "Background workers", "tech": ["ingestion", "embeddings"]},
                {"id": "storage", "label": "Object storage", "tech": ["documents", "images"]},
                {"id": "embed", "label": "Embedding service", "tech": ["batching", "caching"]},
                {"id": "vector", "label": "Vector store", "tech": ["pgvector", "metadata filters"]},
                {
                    "id": "rag",
                    "label": "RAG service",
                    "tech": ["chunking", "retrieval", "reranking"],
                },
                {
                    "id": "llm",
                    "label": "LLM gateway",
                    "tech": ["provider abstraction", "cost control"],
                },
                {"id": "agent", "label": "LangGraph agent", "tech": ["state", "tools", "hitl"]},
                {
                    "id": "evals",
                    "label": "Evaluation pipeline",
                    "tech": ["golden set", "regression gate"],
                },
                {"id": "obs", "label": "Observability", "tech": ["traces", "spans", "token cost"]},
            ],
            "edges": [
                ["web", "api"],
                ["api", "cache"],
                ["api", "db"],
                ["api", "queue"],
                ["queue", "storage"],
                ["queue", "embed"],
                ["embed", "vector"],
                ["api", "rag"],
                ["rag", "vector"],
                ["rag", "llm"],
                ["api", "agent"],
                ["agent", "llm"],
                ["agent", "rag"],
                ["rag", "evals"],
                ["agent", "obs"],
                ["rag", "obs"],
                ["api", "obs"],
            ],
        },
        milestones=[
            {
                "slug": "m1-foundation",
                "title": "Foundation: schema, API, auth",
                "description": (
                    "PostgreSQL schema for products, categories and tenants. FastAPI CRUD with "
                    "Pydantic contracts. JWT auth with refresh rotation. Alembic migrations."
                ),
                "acceptance": [
                    "Migrations run forward and backward cleanly",
                    "Auth rejects expired, malformed and wrong-type tokens",
                    "Every endpoint has a response_model that excludes internal fields",
                ],
                "concepts": ["python-dataclass-vs-pydantic"],
                "xp": 400,
            },
            {
                "slug": "m2-search",
                "title": "Search: filtering, pagination, indexes",
                "description": (
                    "Faceted filtering and pagination over 1M products. Prove your indexes are "
                    "used with EXPLAIN ANALYZE, and prove the endpoint has no N+1."
                ),
                "acceptance": [
                    "p95 under 150ms on 1M rows",
                    "EXPLAIN ANALYZE shows index scans, not sequential",
                    "A query-count assertion in the test suite guards against N+1",
                ],
                "concepts": [],
                "xp": 500,
            },
            {
                "slug": "m3-async-ingestion",
                "title": "Ingestion: background workers and object storage",
                "description": (
                    "Document upload goes to object storage; a worker chunks and embeds it. "
                    "The API returns immediately. Failures are retryable and observable."
                ),
                "acceptance": [
                    "Upload returns in under 200ms regardless of document size",
                    "A worker crash mid-document does not lose or duplicate chunks",
                    "Ingestion progress is visible to the user",
                ],
                "concepts": ["python-generators"],
                "xp": 600,
            },
            {
                "slug": "m4-rag",
                "title": "RAG: chunking, retrieval, grounding",
                "description": (
                    "Semantic search and a grounded assistant. Tune chunk size and overlap "
                    "against a golden set — and justify the values you land on with numbers."
                ),
                "acceptance": [
                    "Retrieval precision@5 above 0.8 on the golden set",
                    "The assistant cites its sources and refuses when context is insufficient",
                    "Chunking parameters are justified by measurement, not by default values",
                ],
                "concepts": [],
                "xp": 800,
            },
            {
                "slug": "m5-agent",
                "title": "Agent: LangGraph with human-in-the-loop",
                "description": (
                    "A support agent that classifies, retrieves, answers, self-evaluates and "
                    "escalates to a human when confidence is low. With a recursion guard."
                ),
                "acceptance": [
                    "The graph terminates on every path, provably",
                    "Low-confidence answers route to human approval",
                    "State transitions are inspectable after the fact",
                ],
                "concepts": [],
                "xp": 900,
            },
            {
                "slug": "m6-evals",
                "title": "Evaluation: golden sets and a regression gate",
                "description": (
                    "An evaluation pipeline that blocks a deploy when faithfulness or retrieval "
                    "quality regresses. Include the decision rule, not just the metrics."
                ),
                "acceptance": [
                    "CI fails on a faithfulness regression beyond the threshold",
                    "You can explain what threshold you chose and why",
                    "The golden set has documented provenance",
                ],
                "concepts": [],
                "xp": 800,
            },
            {
                "slug": "m7-observability",
                "title": "Observability: traces, tokens and cost",
                "description": (
                    "Every AI request produces a trace with per-span latency, token usage and "
                    "cost. Build the dashboard you would actually use at 3am."
                ),
                "acceptance": [
                    "A slow request can be attributed to a specific span in under a minute",
                    "Cost per request is visible and attributable to a tenant",
                    "Alerts fire on latency and error-rate thresholds you can defend",
                ],
                "concepts": [],
                "xp": 700,
            },
            {
                "slug": "m8-hardening",
                "title": "Hardening: security, load, cost control",
                "description": (
                    "Rate limiting, tenant isolation, prompt-injection defence, load testing and "
                    "an LLM spend cap. Then break your own system and write the postmortem."
                ),
                "acceptance": [
                    "Tenant A cannot retrieve tenant B's documents — proven by a test",
                    "A malicious document cannot exfiltrate the system prompt",
                    "The system degrades gracefully when the LLM provider is down",
                ],
                "concepts": [],
                "xp": 1000,
            },
            {
                "slug": "m9-defense",
                "title": "The Defence",
                "description": (
                    "A Staff and a Principal engineer interview you on the system you built. "
                    "Every box on the diagram is fair game."
                ),
                "acceptance": [
                    "You justify each component choice with a trade-off, not a preference",
                    "You can describe what breaks at 10x and at 100x",
                    "You name at least one decision you would reverse, and why",
                ],
                "concepts": [],
                "xp": 1500,
            },
        ],
        defense_questions=[
            "q-py-dataclass-vs-pydantic-choice",
        ],
        required_level=72,
        required_rank="ai_platform_engineer",
        xp_reward=8000,
    ),
]


PACK = ContentPack(
    name="meta",
    badges=BADGES,
    achievements=ACHIEVEMENTS,
    projects=PROJECTS,
)
