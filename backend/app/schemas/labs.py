"""Contracts for the interactive labs.

These endpoints are *instruments*, not CRUD. Each one returns every
intermediate value the visualiser needs, because the whole point is that the
player can see the mechanism rather than the result.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from app.schemas.common import Schema


# ══ Transformer Lab ══════════════════════════════════════════════════════════
class AttentionRequest(Schema):
    text: Annotated[str, Field(min_length=1, max_length=400)] = "The cat sat on the mat"
    n_heads: Annotated[int, Field(ge=1, le=8)] = 4
    d_model: Annotated[int, Field(ge=16, le=256)] = 64
    #: The three toggles that are the lab's entire pedagogy.
    causal: bool = False
    scaled: bool = True
    use_positional: bool = True


class TokenOut(Schema):
    text: str
    index: int
    id: int
    is_subword: bool
    of_word: str


class AttentionHeadOut(Schema):
    head: int
    weights: list[list[float]]
    raw_scores: list[list[float]]
    entropy: list[float]
    #: Which token each row attends to most — the readable summary of a head.
    argmax: list[int]


class AttentionResponse(Schema):
    tokens: list[TokenOut]
    d_model: int
    n_heads: int
    d_head: int
    causal: bool
    scaled: bool
    heads: list[AttentionHeadOut]
    vectors: dict[str, Any] | None = None
    #: Plain-language note on what the current toggles are demonstrating.
    insight: str = ""


class TokenizeRequest(Schema):
    text: Annotated[str, Field(min_length=1, max_length=20_000)]


class TokenizeResponse(Schema):
    tokens: list[TokenOut]
    stats: dict[str, Any]
    #: What this many tokens costs across providers, at today's prices.
    cost_estimates: list[dict[str, Any]] = Field(default_factory=list)


class SamplingRequest(Schema):
    temperature: Annotated[float, Field(ge=0.01, le=3.0)] = 1.0
    top_k: Annotated[int | None, Field(ge=1, le=50)] = None
    top_p: Annotated[float | None, Field(gt=0.0, le=1.0)] = None
    logits: list[float] | None = None
    labels: list[str] | None = None


class SamplingResponse(Schema):
    labels: list[str]
    logits: list[float]
    temperature: float
    scaled_logits: list[float]
    probabilities: list[float]
    final_probabilities: list[float]
    kept: list[bool]
    tokens_kept: int
    truncation: str
    entropy: float
    argmax: str
    insight: str = ""


# ══ RAG Tower ════════════════════════════════════════════════════════════════
class RAGConfigIn(Schema):
    corpus: str = "forge-docs"
    chunk_size: Annotated[int, Field(ge=50, le=4000)] = 400
    chunk_overlap: Annotated[int, Field(ge=0, le=1000)] = 50
    respect_structure: bool = True
    top_k: Annotated[int, Field(ge=1, le=20)] = 4
    use_reranker: bool = False
    use_hybrid: bool = False
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    max_context_chars: Annotated[int, Field(ge=200, le=32_000)] = 6000
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    min_score: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    prompt_template: Annotated[str, Field(max_length=4000)] = ""


class ChunkPreviewRequest(Schema):
    text: Annotated[str, Field(min_length=1, max_length=100_000)]
    chunk_size: Annotated[int, Field(ge=50, le=4000)] = 400
    chunk_overlap: Annotated[int, Field(ge=0, le=1000)] = 50
    respect_structure: bool = True


class ChunkOut(Schema):
    index: int
    text: str
    start_char: int
    end_char: int
    chars: int
    tokens: int


class ChunkPreviewResponse(Schema):
    chunks: list[ChunkOut]
    total_chunks: int
    avg_chars: float
    avg_tokens: float
    #: Chars duplicated across chunk boundaries — the cost of overlap.
    overlap_waste_chars: int
    insight: str = ""


class RetrievedChunkOut(Schema):
    doc_slug: str
    title: str
    text: str
    score: float
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    rerank_score: float | None = None
    original_rank: int | None = None


class StageOut(Schema):
    name: str
    duration_ms: float
    detail: dict[str, Any] = Field(default_factory=dict)


class RAGQueryRequest(Schema):
    question: Annotated[str, Field(min_length=3, max_length=2000)]
    config: RAGConfigIn = Field(default_factory=RAGConfigIn)
    #: Supplying this scores the run against a golden case immediately.
    expected_answer: str = ""
    relevant_doc_ids: list[str] = Field(default_factory=list)
    save_experiment: bool = True


class RAGQueryResponse(Schema):
    question: str
    answer: str
    retrieved: list[RetrievedChunkOut]
    config: dict[str, Any]
    stages: list[StageOut]
    prompt: str
    total_ms: float
    token_usage: dict[str, int]
    cost_usd: float
    simulated: bool
    metrics: dict[str, float] = Field(default_factory=dict)
    experiment_id: str | None = None
    #: What the numbers are telling you, in words.
    diagnosis: list[str] = Field(default_factory=list)


class RAGCorpusOut(Schema):
    corpus: str
    documents: int
    chunks: int
    embedding_model: str | None
    total_tokens: int
    titles: list[str] = Field(default_factory=list)


class RAGExperimentOut(Schema):
    id: str
    question: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    use_reranker: bool
    use_hybrid: bool
    embedding_model: str
    answer: str
    metrics: dict[str, Any]
    latency_ms: float
    created_at: str


class RAGCompareResponse(Schema):
    experiments: list[RAGExperimentOut]
    #: Metric deltas between the two most recent runs.
    delta: dict[str, float] = Field(default_factory=dict)
    verdict: str = "hold"
    reasons: list[str] = Field(default_factory=list)


# ══ Agent Factory ════════════════════════════════════════════════════════════
class GraphNodeOut(Schema):
    id: str
    label: str
    kind: str
    description: str = ""
    interrupt_before: bool = False
    is_entry: bool = False


class GraphEdgeOut(Schema):
    source: str
    target: str
    kind: str
    label: str = ""
    description: str = ""


class GraphDiagramOut(Schema):
    name: str
    entry: str | None
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    #: Every cycle. Not a bug — but every one needs a termination argument.
    cycles: list[list[str]] = Field(default_factory=list)
    info: dict[str, Any] = Field(default_factory=dict)


class AgentRunRequest(Schema):
    graph: str = "support_agent"
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    recursion_limit: Annotated[int, Field(ge=1, le=60)] = 25
    initial_state: dict[str, Any] = Field(default_factory=dict)
    save_run: bool = True


class StepOut(Schema):
    step: int
    node: str
    status: str
    duration_ms: float
    state_diff: dict[str, Any]
    state_after: dict[str, Any]
    edge_taken: str | None = None
    edge_reason: str | None = None
    error: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0


class AgentRunResponse(Schema):
    run_id: str | None = None
    graph: str
    status: str
    final_state: dict[str, Any]
    history: list[StepOut]
    halted_reason: str | None = None
    interrupted_at: str | None = None
    steps: int
    total_ms: float
    node_visits: dict[str, int]
    looped: bool
    diagnosis: list[str] = Field(default_factory=list)


class AgentResumeRequest(Schema):
    run_id: str
    approved: bool = True
    note: Annotated[str, Field(max_length=2000)] = ""


# ══ Mentor & content agent ═══════════════════════════════════════════════════
class MentorAskRequest(Schema):
    question: Annotated[str, Field(min_length=3, max_length=4000)]
    concept_slug: str | None = None
    challenge_slug: str | None = None
    code: Annotated[str | None, Field(max_length=20_000)] = None
    error: Annotated[str | None, Field(max_length=4000)] = None
    tier: Annotated[int, Field(ge=1, le=10)] = 5
    attempts: Annotated[int, Field(ge=0, le=100)] = 0
    hints_used: Annotated[int, Field(ge=0, le=20)] = 0
    persona: str = "senior_engineer"


class MentorResponseOut(Schema):
    level: str
    message: str
    question_back: str | None = None
    next_level: str | None = None
    reveals_answer: bool
    simulated: bool
    tokens: int = 0
    cost_usd: float = 0.0
    #: The mentor's own graph execution — the tool teaching its own mechanism.
    trace: list[dict[str, Any]] = Field(default_factory=list)


class SocraticRequest(Schema):
    concept_slug: str
    player_answer: Annotated[str, Field(min_length=1, max_length=20_000)]
    tier: Annotated[int, Field(ge=1, le=10)] = 5


class SocraticResponse(Schema):
    question: str
    targets_misconception: str
    good_answer_contains: list[str]
    tier: int
    simulated: bool


class GenerateQuestionRequest(Schema):
    concept_slug: str
    tier: Annotated[int, Field(ge=1, le=10)] = 5
    kind: str = "explain"
    count: Annotated[int, Field(ge=1, le=5)] = 1


class GeneratedQuestionOut(Schema):
    prompt: str
    kind: str
    tier: int
    context: str = ""
    options: list[dict[str, Any]] = Field(default_factory=list)
    expected_answer: str = ""
    ideal_senior_answer: str = ""
    common_wrong_answer: str = ""
    rubric: list[dict[str, Any]] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    #: Non-empty means this was rejected and must not be served as content.
    issues: list[str] = Field(default_factory=list)
    is_usable: bool = False
    simulated: bool = False


class GenerateQuestionResponse(Schema):
    concept_slug: str
    concept_title: str
    generated: list[GeneratedQuestionOut]
    accepted: int
    rejected: int
    #: Why generated content is held to the same bar as hand-authored content.
    validation_note: str = ""


# ══ Evaluation Lab ═══════════════════════════════════════════════════════════
class EvalCaseIn(Schema):
    question: str
    relevant_doc_ids: list[str] = Field(default_factory=list)
    expected_answer: str = ""


class EvalRunRequest(Schema):
    name: Annotated[str, Field(min_length=1, max_length=120)] = "experiment"
    config: RAGConfigIn = Field(default_factory=RAGConfigIn)
    cases: list[EvalCaseIn] = Field(default_factory=list)
    #: Use the built-in golden set when no cases are supplied.
    use_golden_set: bool = True
    use_llm_judge: bool = False
    baseline_evaluation_id: str | None = None


class EvalCaseResult(Schema):
    question: str
    answer: str
    passed: bool
    metrics: dict[str, float]
    retrieved_titles: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


class EvalRunResponse(Schema):
    evaluation_id: str | None = None
    name: str
    cases_total: int
    cases_passed: int
    metrics: dict[str, float]
    per_case: list[EvalCaseResult]
    verdict: str
    reasons: list[str] = Field(default_factory=list)
    baseline: dict[str, float] | None = None
    judged_by: str = "deterministic"
