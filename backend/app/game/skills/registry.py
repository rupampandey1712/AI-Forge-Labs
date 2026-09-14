"""Static definitions of the 16 skills, the skill trees and the 14 buildings.

WHY in Python rather than the database: this is *structure*, not content. The
world map, the skill axes and the tree shape change only when the game design
changes, and they are referenced by name from seeds, services and tests. Keeping
them as typed module constants means a typo is an ``ImportError`` at startup
rather than an empty panel at runtime. They are mirrored into the database by
the seeder so that joins and FKs still work.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import BuildingId, Category, Rank, SkillId


@dataclass(frozen=True, slots=True)
class SkillDef:
    slug: SkillId
    name: str
    description: str
    icon: str
    color: str
    building: BuildingId
    categories: tuple[Category, ...]
    display_order: int


@dataclass(frozen=True, slots=True)
class SkillNodeDef:
    slug: str
    name: str
    summary: str
    parent: str | None = None
    tier_range: tuple[int, int] = (1, 10)
    unlock_level: int = 1


@dataclass(frozen=True, slots=True)
class BuildingDef:
    id: BuildingId
    name: str
    tagline: str
    description: str
    skills: tuple[SkillId, ...]
    categories: tuple[Category, ...]
    required_level: int
    required_rank: Rank | None
    #: Normalised 0..1 coordinates on the map canvas — the frontend scales them.
    position: tuple[float, float]
    accent: str
    icon: str
    unlock_hint: str = ""


SKILLS: tuple[SkillDef, ...] = (
    SkillDef(
        SkillId.PYTHON,
        "Python",
        "The language itself — from syntax to the object model.",
        "code",
        "#3b82f6",
        BuildingId.PYTHON_ACADEMY,
        (Category.PYTHON, Category.OOP),
        1,
    ),
    SkillDef(
        SkillId.BACKEND,
        "Backend",
        "HTTP services, APIs, contracts and request lifecycles.",
        "server",
        "#22d3ee",
        BuildingId.BACKEND_CITY,
        (Category.FASTAPI, Category.PYDANTIC),
        2,
    ),
    SkillDef(
        SkillId.DATABASE,
        "Database",
        "Modelling, querying and not bringing production down.",
        "database",
        "#a78bfa",
        BuildingId.BACKEND_CITY,
        (Category.SQLALCHEMY, Category.POSTGRESQL),
        3,
    ),
    SkillDef(
        SkillId.DATA_ENGINEERING,
        "Data Engineering",
        "Moving, cleaning and reshaping data at volume.",
        "layers",
        "#34d399",
        BuildingId.DATA_SCIENCE_LAB,
        (Category.NUMPY, Category.PANDAS, Category.MATPLOTLIB),
        4,
    ),
    SkillDef(
        SkillId.ML,
        "Machine Learning",
        "Classical modelling, evaluation and the bias/variance trade.",
        "scatter-chart",
        "#f59e0b",
        BuildingId.ML_ARENA,
        (Category.ML,),
        5,
    ),
    SkillDef(
        SkillId.DEEP_LEARNING,
        "Deep Learning",
        "Tensors, autograd, training loops and why they diverge.",
        "brain",
        "#fb7185",
        BuildingId.DEEP_LEARNING_LAB,
        (Category.PYTORCH, Category.DEEP_LEARNING),
        6,
    ),
    SkillDef(
        SkillId.LLM,
        "LLMs",
        "Tokens, sampling, context, cost and hallucination.",
        "message-square",
        "#e879f9",
        BuildingId.TRANSFORMER_CENTER,
        (Category.TRANSFORMERS, Category.LLM),
        7,
    ),
    SkillDef(
        SkillId.RAG,
        "RAG",
        "Retrieval-augmented generation and why it returns the wrong doc.",
        "search",
        "#38bdf8",
        BuildingId.RAG_TOWER,
        (Category.RAG, Category.EVALS),
        8,
    ),
    SkillDef(
        SkillId.AGENTS,
        "Agents",
        "Graphs, state, tools, loops and human-in-the-loop.",
        "workflow",
        "#818cf8",
        BuildingId.AGENT_FACTORY,
        (Category.LANGCHAIN, Category.LANGGRAPH),
        9,
    ),
    SkillDef(
        SkillId.ARCHITECTURE,
        "Architecture",
        "Boundaries, coupling, and abstractions that earn their keep.",
        "blocks",
        "#94a3b8",
        BuildingId.ARCHITECTURE_TOWER,
        (Category.ARCHITECTURE,),
        10,
    ),
    SkillDef(
        SkillId.TESTING,
        "Testing",
        "What to test, what to mock, and what that costs you.",
        "flask-conical",
        "#4ade80",
        BuildingId.PRODUCTION_CITY,
        (Category.TESTING,),
        11,
    ),
    SkillDef(
        SkillId.DEVOPS,
        "DevOps",
        "Containers, pipelines, config and the path to production.",
        "container",
        "#fbbf24",
        BuildingId.PRODUCTION_CITY,
        (Category.DEVOPS, Category.SECURITY),
        12,
    ),
    SkillDef(
        SkillId.SYSTEM_DESIGN,
        "System Design",
        "Scaling from one box to a global system.",
        "network",
        "#60a5fa",
        BuildingId.ARCHITECTURE_TOWER,
        (Category.SYSTEM_DESIGN,),
        13,
    ),
    SkillDef(
        SkillId.DEBUGGING,
        "Debugging",
        "Reading evidence and finding root cause under pressure.",
        "bug",
        "#ef4444",
        BuildingId.DEBUGGING_DUNGEON,
        (Category.DEBUGGING, Category.PRODUCTION),
        14,
    ),
    SkillDef(
        SkillId.COMMUNICATION,
        "Communication",
        "Explaining decisions so other engineers can act on them.",
        "megaphone",
        "#f472b6",
        BuildingId.STAFF_HQ,
        (Category.CAREER,),
        15,
    ),
    SkillDef(
        SkillId.INTERVIEW_SKILLS,
        "Interview Skills",
        "Structuring answers and defending trade-offs.",
        "mic",
        "#c084fc",
        BuildingId.INTERVIEW_ARENA,
        (Category.CAREER,),
        16,
    ),
)

SKILL_BY_SLUG: dict[str, SkillDef] = {s.slug.value: s for s in SKILLS}


# ── Skill trees ──────────────────────────────────────────────────────────────
# Flat lists with parent pointers; the API assembles the tree. Flat is easier to
# diff in review than a nested literal, and the seeder inserts it in one pass.
SKILL_TREES: dict[SkillId, tuple[SkillNodeDef, ...]] = {
    SkillId.PYTHON: (
        SkillNodeDef(
            "python.syntax",
            "Syntax & Types",
            "Variables, primitives, strings, control flow.",
            None,
            (1, 4),
        ),
        SkillNodeDef(
            "python.collections",
            "Collections",
            "list, tuple, set, dict — and when each is wrong.",
            "python.syntax",
            (1, 6),
        ),
        SkillNodeDef(
            "python.functions",
            "Functions",
            "Arguments, *args/**kwargs, scope, closures.",
            "python.syntax",
            (1, 7),
        ),
        SkillNodeDef(
            "python.comprehensions",
            "Comprehensions",
            "Comprehensions, generator expressions, readability limits.",
            "python.collections",
            (2, 6),
        ),
        SkillNodeDef(
            "python.errors",
            "Exceptions",
            "Raising, catching, custom hierarchies, and EAFP.",
            "python.functions",
            (2, 8),
        ),
        SkillNodeDef(
            "python.modules",
            "Modules & Packaging",
            "Imports, packages, venvs, dependency hygiene.",
            "python.syntax",
            (2, 8),
        ),
        SkillNodeDef(
            "python.typing",
            "Typing",
            "Hints, generics, protocols, and what mypy can prove.",
            "python.functions",
            (3, 9),
        ),
        SkillNodeDef(
            "python.oop",
            "OOP",
            "Classes, inheritance, composition, SOLID.",
            "python.functions",
            (3, 10),
            4,
        ),
        SkillNodeDef(
            "python.dunder",
            "Object Model",
            "__new__, __call__, __eq__/__hash__, MRO.",
            "python.oop",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "python.iterators",
            "Iterators",
            "The iterator protocol and StopIteration.",
            "python.collections",
            (3, 8),
            4,
        ),
        SkillNodeDef(
            "python.generators",
            "Generators",
            "Lazy evaluation, send/throw, pipelines.",
            "python.iterators",
            (4, 10),
            5,
        ),
        SkillNodeDef(
            "python.decorators",
            "Decorators",
            "Closures, functools.wraps, parameterised decorators.",
            "python.functions",
            (4, 10),
            5,
        ),
        SkillNodeDef(
            "python.context",
            "Context Managers",
            "with, __enter__/__exit__, contextlib, cleanup guarantees.",
            "python.errors",
            (4, 9),
            5,
        ),
        SkillNodeDef(
            "python.dataclasses",
            "Dataclasses & Records",
            "dataclass vs NamedTuple vs TypedDict vs Pydantic.",
            "python.typing",
            (3, 9),
            4,
        ),
        SkillNodeDef(
            "python.descriptors",
            "Descriptors & Properties",
            "property, __get__/__set__, and where ORMs use them.",
            "python.dunder",
            (6, 10),
            10,
        ),
        SkillNodeDef(
            "python.metaclasses",
            "Metaclasses",
            "type, __init_subclass__, and why you probably shouldn't.",
            "python.dunder",
            (7, 10),
            14,
        ),
        SkillNodeDef(
            "python.memory",
            "Memory & GC",
            "Refcounting, cycles, weakrefs, __slots__.",
            "python.dunder",
            (6, 10),
            12,
        ),
        SkillNodeDef(
            "python.concurrency",
            "Concurrency",
            "GIL, threads, processes — and choosing between them.",
            "python.functions",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "python.asyncio",
            "Asyncio",
            "Event loop, coroutines, tasks, cancellation.",
            "python.concurrency",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "python.performance",
            "Performance",
            "Profiling, caching, algorithmic vs constant factors.",
            "python.concurrency",
            (5, 10),
            10,
        ),
    ),
    SkillId.BACKEND: (
        SkillNodeDef(
            "fastapi.routing", "Routing", "Paths, methods, params, routers.", None, (1, 6)
        ),
        SkillNodeDef(
            "fastapi.validation",
            "Validation",
            "Pydantic models, response_model, error shapes.",
            "fastapi.routing",
            (2, 7),
        ),
        SkillNodeDef(
            "fastapi.di",
            "Dependency Injection",
            "Depends, scopes, overrides, lifetimes.",
            "fastapi.routing",
            (3, 10),
            5,
        ),
        SkillNodeDef(
            "fastapi.async",
            "Async Endpoints",
            "async def, blocking calls, thread pools.",
            "fastapi.routing",
            (4, 10),
            6,
        ),
        SkillNodeDef(
            "fastapi.middleware",
            "Middleware & Lifecycle",
            "Middleware, lifespan, exception handlers.",
            "fastapi.routing",
            (3, 9),
            5,
        ),
        SkillNodeDef(
            "fastapi.auth",
            "Auth",
            "JWT, OAuth2 flows, RBAC, token hygiene.",
            "fastapi.di",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "fastapi.performance",
            "API Performance",
            "Caching, pagination, N+1, rate limiting.",
            "fastapi.async",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "fastapi.realtime",
            "WebSockets & Streaming",
            "Long-lived connections, backpressure.",
            "fastapi.async",
            (5, 10),
            10,
        ),
    ),
    SkillId.DATABASE: (
        SkillNodeDef(
            "db.models", "Models & Schema", "Tables, columns, constraints, naming.", None, (1, 6)
        ),
        SkillNodeDef(
            "db.sessions",
            "Sessions & Transactions",
            "Unit of work, commit boundaries, rollback.",
            "db.models",
            (2, 9),
            4,
        ),
        SkillNodeDef(
            "db.relationships",
            "Relationships",
            "1:1, 1:N, M:N, association objects.",
            "db.models",
            (2, 8),
            4,
        ),
        SkillNodeDef(
            "db.loading",
            "Loading Strategies",
            "lazy, selectin, joined — and the N+1 trap.",
            "db.relationships",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "db.indexing",
            "Indexes & Query Plans",
            "B-trees, covering indexes, EXPLAIN ANALYZE.",
            "db.models",
            (4, 10),
            8,
        ),
        SkillNodeDef(
            "db.migrations",
            "Migrations",
            "Alembic, reversibility, zero-downtime changes.",
            "db.models",
            (3, 10),
            6,
        ),
        SkillNodeDef(
            "db.concurrency",
            "Isolation & Concurrency",
            "Isolation levels, locks, optimistic concurrency.",
            "db.sessions",
            (6, 10),
            11,
        ),
    ),
    SkillId.DATA_ENGINEERING: (
        SkillNodeDef("numpy.arrays", "ndarray", "Shape, dtype, memory layout.", None, (1, 6)),
        SkillNodeDef(
            "numpy.indexing",
            "Indexing & Slicing",
            "Views vs copies, fancy indexing, masks.",
            "numpy.arrays",
            (2, 8),
        ),
        SkillNodeDef(
            "numpy.broadcasting",
            "Broadcasting",
            "The rules, and the silent bugs they cause.",
            "numpy.arrays",
            (3, 9),
            4,
        ),
        SkillNodeDef(
            "numpy.vectorization",
            "Vectorization",
            "Replacing loops; when it does not help.",
            "numpy.broadcasting",
            (4, 10),
            5,
        ),
        SkillNodeDef(
            "pandas.basics", "DataFrames", "Selection, filtering, dtypes, indexes.", None, (1, 6)
        ),
        SkillNodeDef(
            "pandas.groupby",
            "Group & Aggregate",
            "groupby, agg, transform, window functions.",
            "pandas.basics",
            (3, 9),
            5,
        ),
        SkillNodeDef(
            "pandas.joins",
            "Joins & Reshaping",
            "merge, concat, pivot, melt.",
            "pandas.basics",
            (3, 9),
            5,
        ),
        SkillNodeDef(
            "pandas.cleaning",
            "Cleaning",
            "Missing values, duplicates, types, datetimes.",
            "pandas.basics",
            (2, 9),
            4,
        ),
        SkillNodeDef(
            "pandas.performance",
            "Pandas at Scale",
            "apply vs vectorised, memory, chunking.",
            "pandas.groupby",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "viz.charts",
            "Visualization",
            "Choosing the right chart; matplotlib mechanics.",
            None,
            (2, 8),
            4,
        ),
        SkillNodeDef(
            "viz.model_metrics",
            "Model Diagnostics",
            "Loss curves, confusion matrices, ROC/PR.",
            "viz.charts",
            (4, 10),
            7,
        ),
    ),
    SkillId.ML: (
        SkillNodeDef(
            "ml.foundations",
            "Foundations",
            "Supervised vs unsupervised; the learning setup.",
            None,
            (1, 6),
        ),
        SkillNodeDef(
            "ml.evaluation",
            "Evaluation",
            "Splits, cross-validation, leakage, metric choice.",
            "ml.foundations",
            (2, 10),
            4,
        ),
        SkillNodeDef(
            "ml.features",
            "Feature Engineering",
            "Encoding, scaling, leakage, feature stores.",
            "ml.foundations",
            (3, 9),
            5,
        ),
        SkillNodeDef(
            "ml.linear",
            "Linear Models",
            "Regression, logistic regression, regularisation.",
            "ml.foundations",
            (2, 8),
            4,
        ),
        SkillNodeDef(
            "ml.trees",
            "Trees & Ensembles",
            "Decision trees, random forests, boosting.",
            "ml.linear",
            (3, 9),
            6,
        ),
        SkillNodeDef(
            "ml.unsupervised",
            "Clustering",
            "k-means, DBSCAN, choosing k, evaluating clusters.",
            "ml.foundations",
            (3, 8),
            6,
        ),
        SkillNodeDef(
            "ml.biasvariance",
            "Bias & Variance",
            "Over/underfitting, learning curves, capacity.",
            "ml.evaluation",
            (4, 10),
            7,
        ),
    ),
    SkillId.DEEP_LEARNING: (
        SkillNodeDef(
            "torch.tensors", "Tensors", "Shapes, dtypes, devices, broadcasting.", None, (1, 7)
        ),
        SkillNodeDef(
            "torch.autograd",
            "Autograd",
            "The computation graph, backward, detach.",
            "torch.tensors",
            (3, 10),
            5,
        ),
        SkillNodeDef(
            "torch.data",
            "Dataset & DataLoader",
            "Batching, shuffling, collate, workers.",
            "torch.tensors",
            (2, 8),
            4,
        ),
        SkillNodeDef(
            "torch.modules",
            "nn.Module",
            "Parameters, forward, initialisation.",
            "torch.autograd",
            (3, 9),
            6,
        ),
        SkillNodeDef(
            "torch.training",
            "Training Loop",
            "Loss, optimiser, zero_grad, scheduling.",
            "torch.modules",
            (3, 10),
            6,
        ),
        SkillNodeDef(
            "torch.debugging",
            "Training Pathologies",
            "Exploding/vanishing gradients, NaNs, overfitting.",
            "torch.training",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "torch.deployment",
            "Checkpoints & Inference",
            "eval(), no_grad, saving, serving, GPU memory.",
            "torch.training",
            (4, 10),
            8,
        ),
    ),
    SkillId.LLM: (
        SkillNodeDef(
            "tf.tokenization",
            "Tokenization",
            "BPE, vocabulary, token counting and cost.",
            None,
            (1, 8),
        ),
        SkillNodeDef(
            "tf.embeddings",
            "Embeddings",
            "Vector semantics, similarity, dimensionality.",
            "tf.tokenization",
            (2, 9),
            4,
        ),
        SkillNodeDef(
            "tf.positional",
            "Positional Encoding",
            "Why order needs to be injected.",
            "tf.embeddings",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "tf.attention",
            "Self-Attention",
            "Q/K/V, scaled dot product, masking.",
            "tf.embeddings",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "tf.multihead",
            "Multi-Head Attention",
            "Heads, projections, what each head learns.",
            "tf.attention",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "tf.block",
            "Transformer Block",
            "Residuals, layer norm, feed-forward.",
            "tf.multihead",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "llm.sampling",
            "Sampling",
            "Logits, temperature, top-k, top-p.",
            "tf.tokenization",
            (3, 9),
            5,
        ),
        SkillNodeDef(
            "llm.context",
            "Context & Cost",
            "Context window, truncation, token economics.",
            "llm.sampling",
            (3, 10),
            6,
        ),
        SkillNodeDef(
            "llm.structured",
            "Structured Output",
            "Schema-constrained output and tool calling.",
            "llm.sampling",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "llm.tuning",
            "Adaptation",
            "Prompting vs RAG vs fine-tuning vs LoRA.",
            "llm.context",
            (6, 10),
            10,
        ),
    ),
    SkillId.RAG: (
        SkillNodeDef(
            "rag.pipeline",
            "The Pipeline",
            "Load → chunk → embed → store → retrieve → generate.",
            None,
            (2, 8),
            3,
        ),
        SkillNodeDef(
            "rag.chunking",
            "Chunking",
            "Size, overlap, structure-aware splitting.",
            "rag.pipeline",
            (3, 10),
            5,
        ),
        SkillNodeDef(
            "rag.retrieval",
            "Retrieval",
            "Similarity, top-k, hybrid search, filters.",
            "rag.pipeline",
            (3, 10),
            5,
        ),
        SkillNodeDef(
            "rag.reranking",
            "Reranking",
            "Two-stage retrieval and when it pays.",
            "rag.retrieval",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "rag.grounding",
            "Grounding",
            "Prompt construction, citations, refusals.",
            "rag.retrieval",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "rag.evaluation",
            "RAG Evaluation",
            "Precision/recall, faithfulness, answer relevance.",
            "rag.grounding",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "evals.method",
            "Evaluation Method",
            "Golden sets, LLM-as-judge, regression gates.",
            "rag.evaluation",
            (5, 10),
            9,
        ),
    ),
    SkillId.AGENTS: (
        SkillNodeDef(
            "lc.primitives",
            "LangChain Primitives",
            "Prompts, models, parsers, composition.",
            None,
            (2, 8),
            3,
        ),
        SkillNodeDef(
            "lc.tools",
            "Tools",
            "Tool definitions, schemas, error handling.",
            "lc.primitives",
            (3, 9),
            6,
        ),
        SkillNodeDef(
            "lg.state",
            "Graph State",
            "Typed state, reducers, immutability.",
            "lc.tools",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "lg.edges",
            "Nodes & Edges",
            "Conditional routing, branching, fan-out.",
            "lg.state",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "lg.control",
            "Loops & Guards",
            "Recursion limits, retries, termination.",
            "lg.edges",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "lg.hitl",
            "Human-in-the-Loop",
            "Checkpoints, interrupts, approvals, persistence.",
            "lg.control",
            (6, 10),
            10,
        ),
        SkillNodeDef(
            "obs.tracing",
            "Tracing",
            "Traces, spans, latency and token attribution.",
            "lg.edges",
            (4, 10),
            8,
        ),
    ),
    SkillId.ARCHITECTURE: (
        SkillNodeDef(
            "arch.solid",
            "SOLID & Cohesion",
            "Responsibilities, coupling, dependency direction.",
            None,
            (3, 10),
            4,
        ),
        SkillNodeDef(
            "arch.patterns",
            "Design Patterns",
            "Factory, Strategy, Repository, Unit of Work.",
            "arch.solid",
            (3, 10),
            5,
        ),
        SkillNodeDef(
            "arch.layers",
            "Layering",
            "Domain, service, transport — and leaks between them.",
            "arch.solid",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "arch.tradeoffs",
            "Trade-offs",
            "Abstraction cost, reversibility, YAGNI.",
            "arch.layers",
            (6, 10),
            10,
        ),
    ),
    SkillId.TESTING: (
        SkillNodeDef(
            "test.unit", "Unit Tests", "pytest, assertions, parametrize.", None, (2, 7), 3
        ),
        SkillNodeDef(
            "test.fixtures", "Fixtures", "Scope, factories, teardown.", "test.unit", (3, 8), 5
        ),
        SkillNodeDef(
            "test.mocking",
            "Mocking",
            "What to mock — and what never to.",
            "test.fixtures",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "test.integration",
            "Integration & API Tests",
            "Test DBs, dependency overrides, async tests.",
            "test.fixtures",
            (4, 10),
            8,
        ),
    ),
    SkillId.DEVOPS: (
        SkillNodeDef(
            "ops.containers", "Containers", "Images, layers, multi-stage builds.", None, (3, 9), 5
        ),
        SkillNodeDef(
            "ops.compose",
            "Local Orchestration",
            "Compose, healthchecks, dependencies.",
            "ops.containers",
            (3, 9),
            6,
        ),
        SkillNodeDef(
            "ops.cicd",
            "CI/CD",
            "Pipelines, gates, artefacts, rollbacks.",
            "ops.containers",
            (4, 10),
            8,
        ),
        SkillNodeDef(
            "ops.observability",
            "Observability",
            "Structured logs, metrics, traces, alerting.",
            "ops.cicd",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "ops.security",
            "Security",
            "Secrets, least privilege, input validation, sandboxing.",
            "ops.containers",
            (4, 10),
            8,
        ),
    ),
    SkillId.SYSTEM_DESIGN: (
        SkillNodeDef(
            "sd.basics", "Building Blocks", "Load balancer, cache, queue, storage.", None, (4, 9), 7
        ),
        SkillNodeDef(
            "sd.scaling",
            "Scaling",
            "Vertical, horizontal, sharding, read replicas.",
            "sd.basics",
            (5, 10),
            9,
        ),
        SkillNodeDef(
            "sd.consistency",
            "Consistency",
            "CAP in practice, idempotency, exactly-once myths.",
            "sd.scaling",
            (7, 10),
            12,
        ),
        SkillNodeDef(
            "sd.ai_platform",
            "AI Platform Design",
            "Serving, vector stores, evaluation, cost control.",
            "sd.scaling",
            (7, 10),
            14,
        ),
    ),
    SkillId.DEBUGGING: (
        SkillNodeDef(
            "dbg.method", "Method", "Reproduce, bisect, form and test hypotheses.", None, (3, 10), 4
        ),
        SkillNodeDef(
            "dbg.evidence",
            "Reading Evidence",
            "Logs, stack traces, metrics, query plans.",
            "dbg.method",
            (3, 10),
            5,
        ),
        SkillNodeDef(
            "dbg.performance",
            "Performance Debugging",
            "Profiling, latency budgets, tail latency.",
            "dbg.evidence",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "dbg.concurrency",
            "Concurrency Bugs",
            "Races, deadlocks, blocked event loops.",
            "dbg.evidence",
            (6, 10),
            10,
        ),
        SkillNodeDef(
            "dbg.ai",
            "AI System Debugging",
            "Hallucination, retrieval failure, agent loops.",
            "dbg.evidence",
            (5, 10),
            9,
        ),
    ),
    SkillId.COMMUNICATION: (
        SkillNodeDef(
            "comm.explain",
            "Explaining",
            "Audience, altitude, and leading with the point.",
            None,
            (4, 10),
            6,
        ),
        SkillNodeDef(
            "comm.review",
            "Code Review",
            "Actionable comments and reviewing for design.",
            "comm.explain",
            (4, 10),
            7,
        ),
        SkillNodeDef(
            "comm.incident",
            "Incident Communication",
            "Status updates, blameless postmortems.",
            "comm.explain",
            (6, 10),
            10,
        ),
    ),
    SkillId.INTERVIEW_SKILLS: (
        SkillNodeDef(
            "iv.structure",
            "Structuring Answers",
            "Signal first, then depth; bounded answers.",
            None,
            (3, 10),
            4,
        ),
        SkillNodeDef(
            "iv.depth",
            "Going Deep",
            "Following up your own answer before they do.",
            "iv.structure",
            (5, 10),
            8,
        ),
        SkillNodeDef(
            "iv.design",
            "Design Interviews",
            "Requirements, estimation, trade-offs, failure modes.",
            "iv.structure",
            (6, 10),
            10,
        ),
        SkillNodeDef(
            "iv.leadership",
            "Staff+ Signals",
            "Scope, influence, ownership, mentoring.",
            "iv.depth",
            (8, 10),
            14,
        ),
    ),
}


BUILDINGS: tuple[BuildingDef, ...] = (
    BuildingDef(
        BuildingId.PYTHON_ACADEMY,
        "Python Academy",
        "Where every engineer at the Forge starts.",
        "Language fundamentals through the object model, generators, decorators and asyncio.",
        (SkillId.PYTHON,),
        (Category.PYTHON, Category.OOP),
        1,
        None,
        (0.14, 0.68),
        "#3b82f6",
        "graduation-cap",
    ),
    BuildingDef(
        BuildingId.BACKEND_CITY,
        "Backend City",
        "APIs that survive contact with real traffic.",
        "FastAPI, Pydantic, SQLAlchemy and PostgreSQL — routing to query plans.",
        (SkillId.BACKEND, SkillId.DATABASE),
        (Category.FASTAPI, Category.PYDANTIC, Category.SQLALCHEMY, Category.POSTGRESQL),
        5,
        Rank.PYTHON_DEVELOPER,
        (0.32, 0.55),
        "#22d3ee",
        "building-2",
        "Reach Python Developer (level 5).",
    ),
    BuildingDef(
        BuildingId.DATA_SCIENCE_LAB,
        "Data Science Lab",
        "Ten million rows, forty minutes, one bad apply().",
        "NumPy, pandas and matplotlib against realistic, dirty business data.",
        (SkillId.DATA_ENGINEERING,),
        (Category.NUMPY, Category.PANDAS, Category.MATPLOTLIB),
        10,
        None,
        (0.50, 0.74),
        "#34d399",
        "flask-round",
        "Reach level 10.",
    ),
    BuildingDef(
        BuildingId.ML_ARENA,
        "ML Arena",
        "Your model scored 0.99. That is the bad news.",
        "Supervised and unsupervised learning, evaluation, leakage and the bias/variance trade.",
        (SkillId.ML,),
        (Category.ML,),
        16,
        None,
        (0.66, 0.60),
        "#f59e0b",
        "swords",
        "Reach level 16.",
    ),
    BuildingDef(
        BuildingId.DEEP_LEARNING_LAB,
        "Deep Learning Lab",
        "Tensors, gradients, and loss that becomes NaN at epoch 3.",
        "PyTorch from tensors and autograd to a training loop you can debug.",
        (SkillId.DEEP_LEARNING,),
        (Category.PYTORCH, Category.DEEP_LEARNING),
        24,
        None,
        (0.80, 0.72),
        "#fb7185",
        "brain-circuit",
        "Reach level 24.",
    ),
    BuildingDef(
        BuildingId.TRANSFORMER_CENTER,
        "Transformer Research Center",
        "Attention, from Q·Kᵀ to a working block.",
        "Tokenization, embeddings, positional encoding and multi-head attention — built, not recited.",
        (SkillId.LLM,),
        (Category.TRANSFORMERS, Category.LLM),
        34,
        Rank.ML_ENGINEER,
        (0.88, 0.45),
        "#e879f9",
        "atom",
        "Reach ML Engineer (level 32).",
    ),
    BuildingDef(
        BuildingId.RAG_TOWER,
        "RAG Tower",
        "The chatbot is confidently wrong. Find out why.",
        "Chunking, embeddings, retrieval, reranking, grounding and evaluation.",
        (SkillId.RAG,),
        (Category.RAG, Category.EVALS),
        42,
        None,
        (0.74, 0.30),
        "#38bdf8",
        "tower-control",
        "Reach level 42.",
    ),
    BuildingDef(
        BuildingId.AGENT_FACTORY,
        "Agent Factory",
        "Graphs, state and the agent that will not stop.",
        "LangChain primitives and LangGraph state machines with real control flow.",
        (SkillId.AGENTS,),
        (Category.LANGCHAIN, Category.LANGGRAPH),
        50,
        None,
        (0.58, 0.22),
        "#818cf8",
        "factory",
        "Reach level 50.",
    ),
    BuildingDef(
        BuildingId.PRODUCTION_CITY,
        "Production City",
        "Where code meets consequences.",
        "Testing, Docker, CI/CD, observability and the deployment path.",
        (SkillId.TESTING, SkillId.DEVOPS),
        (Category.TESTING, Category.DEVOPS, Category.SECURITY),
        12,
        None,
        (0.42, 0.40),
        "#fbbf24",
        "building",
        "Reach level 12.",
    ),
    BuildingDef(
        BuildingId.INTERVIEW_ARENA,
        "Interview Arena",
        "An interviewer who follows up.",
        "Junior through Principal interviews, scored across seven dimensions.",
        (SkillId.INTERVIEW_SKILLS,),
        (Category.CAREER,),
        6,
        None,
        (0.20, 0.32),
        "#c084fc",
        "mic-vocal",
        "Reach level 6.",
    ),
    BuildingDef(
        BuildingId.ARCHITECTURE_TOWER,
        "Architecture Tower",
        "Draw the system. Then defend every box.",
        "System design from one box to global, plus the abstractions worth their cost.",
        (SkillId.ARCHITECTURE, SkillId.SYSTEM_DESIGN),
        (Category.ARCHITECTURE, Category.SYSTEM_DESIGN),
        28,
        None,
        (0.36, 0.12),
        "#94a3b8",
        "landmark",
        "Reach level 28.",
    ),
    BuildingDef(
        BuildingId.DEBUGGING_DUNGEON,
        "Debugging Dungeon",
        "Broken systems, real evidence, no hints until you ask.",
        "Memory leaks, races, deadlocks, N+1, blocked event loops, GPU OOM, retrieval failure.",
        (SkillId.DEBUGGING,),
        (Category.DEBUGGING,),
        8,
        None,
        (0.08, 0.44),
        "#ef4444",
        "bug",
        "Reach level 8.",
    ),
    BuildingDef(
        BuildingId.AI_WAR_ROOM,
        "AI War Room",
        "02:13. Latency went from 200ms to 8s.",
        "Timed production incidents across the whole stack, scored on root cause and fix quality.",
        (SkillId.DEBUGGING, SkillId.DEVOPS),
        (Category.PRODUCTION,),
        56,
        Rank.AI_ENGINEER,
        (0.62, 0.06),
        "#f97316",
        "siren",
        "Reach AI Engineer (level 52).",
    ),
    BuildingDef(
        BuildingId.STAFF_HQ,
        "Staff Engineer HQ",
        "Scope beyond your own keyboard.",
        "Platform design, trade-off defence, mentoring and the capstone build.",
        (SkillId.COMMUNICATION, SkillId.ARCHITECTURE),
        (Category.CAREER, Category.ARCHITECTURE),
        84,
        Rank.STAFF_AI_ENGINEER,
        (0.88, 0.12),
        "#facc15",
        "crown",
        "Reach Staff AI Engineer (level 84).",
    ),
)

BUILDING_BY_ID: dict[str, BuildingDef] = {b.id.value: b for b in BUILDINGS}

#: Which skill a category trains. Every piece of content declares a category;
#: this is the one place that mapping is defined.
CATEGORY_TO_SKILL: dict[str, str] = {}
for _skill in SKILLS:
    for _cat in _skill.categories:
        CATEGORY_TO_SKILL.setdefault(_cat.value, _skill.slug.value)
# Categories that legitimately train more than one skill get an explicit winner.
CATEGORY_TO_SKILL.update(
    {
        Category.DEBUGGING.value: SkillId.DEBUGGING.value,
        Category.PRODUCTION.value: SkillId.DEBUGGING.value,
        Category.SECURITY.value: SkillId.DEVOPS.value,
        Category.EVALS.value: SkillId.RAG.value,
        Category.LANGSMITH.value: SkillId.AGENTS.value,
        Category.DEEP_LEARNING.value: SkillId.DEEP_LEARNING.value,
        Category.OOP.value: SkillId.PYTHON.value,
    }
)


def skill_for_category(category: str) -> str:
    return CATEGORY_TO_SKILL.get(category, SkillId.PYTHON.value)


def all_skill_slugs() -> list[str]:
    return [s.slug.value for s in SKILLS]


@dataclass(frozen=True, slots=True)
class UnlockState:
    unlocked: bool
    reason: str | None = None


def building_unlock_state(building: BuildingDef, level: int, rank_index: int) -> UnlockState:
    from app.domain.enums import RANK_ORDER

    if level < building.required_level:
        return UnlockState(False, f"Requires level {building.required_level}")
    if building.required_rank is not None:
        needed = RANK_ORDER.index(building.required_rank)
        if rank_index < needed:
            return UnlockState(
                False, building.unlock_hint or f"Requires {building.required_rank.value}"
            )
    return UnlockState(True)


DEFAULT_UNLOCKED_BUILDINGS: tuple[str, ...] = tuple(
    b.id.value for b in BUILDINGS if b.required_level <= 1 and b.required_rank is None
)
