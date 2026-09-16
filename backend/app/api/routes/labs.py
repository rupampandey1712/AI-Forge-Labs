"""Interactive lab endpoints: Transformer, RAG, Agents, Mentor, Evals.

These are instruments rather than CRUD. Each returns every intermediate value
the visualiser needs plus a plain-language diagnosis, because the skill being
taught is reading the numbers — not producing them.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentProfile, DBSession, OptionalProfile
from app.schemas.labs import (
    AgentResumeRequest,
    AgentRunRequest,
    AgentRunResponse,
    AttentionRequest,
    AttentionResponse,
    ChunkPreviewRequest,
    ChunkPreviewResponse,
    EvalRunRequest,
    EvalRunResponse,
    GenerateQuestionRequest,
    GenerateQuestionResponse,
    GraphDiagramOut,
    MentorAskRequest,
    MentorResponseOut,
    RAGCompareResponse,
    RAGCorpusOut,
    RAGQueryRequest,
    RAGQueryResponse,
    SamplingRequest,
    SamplingResponse,
    SocraticRequest,
    SocraticResponse,
    TokenizeRequest,
    TokenizeResponse,
)
from app.services.lab_service import GOLDEN_SET, EvalCase, LabService

router = APIRouter(prefix="/labs", tags=["labs"])


def lab_service(session: DBSession) -> LabService:
    return LabService(session)


LabSvc = Annotated[LabService, Depends(lab_service)]


# ══ Transformer Lab ══════════════════════════════════════════════════════════
@router.post("/transformer/attention", response_model=AttentionResponse)
async def attention(payload: AttentionRequest, service: LabSvc) -> dict[str, Any]:
    """Compute one multi-head self-attention block and return every intermediate.

    Every number is really computed — real embeddings, real positional encoding,
    real Q·Kᵀ/√d, real softmax. The projections are deterministic pseudo-random
    rather than trained, and the response says so: the mechanism is genuine, the
    learned behaviour is not.
    """
    return service.attention(payload)


@router.post("/transformer/tokenize", response_model=TokenizeResponse)
async def tokenize(payload: TokenizeRequest, service: LabSvc) -> dict[str, Any]:
    """Tokenize text and price it.

    Cost is reported per million requests as well as per request, because
    per-request pennies are exactly why token bloat goes unnoticed until the
    invoice arrives.
    """
    return service.tokenize(payload.text)


@router.post("/transformer/sampling", response_model=SamplingResponse)
async def sampling(payload: SamplingRequest, service: LabSvc) -> dict[str, Any]:
    """Show what temperature, top-k and top-p do to the same distribution."""
    return service.sampling(payload)


# ══ RAG Tower ════════════════════════════════════════════════════════════════
@router.get("/rag/corpora", response_model=list[RAGCorpusOut])
async def corpora(service: LabSvc) -> list[dict[str, Any]]:
    return await service.corpora()


@router.post("/rag/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview(payload: ChunkPreviewRequest, service: LabSvc) -> dict[str, Any]:
    """Preview chunking without embedding anything.

    Fast enough to drive a live slider, which is the point: seeing chunk
    boundaries move as you drag is how the trade-off becomes intuitive.
    """
    return service.preview_chunks(payload)


@router.post("/rag/query", response_model=RAGQueryResponse)
async def rag_query(
    payload: RAGQueryRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Run the full pipeline and return every stage, every score, and a diagnosis."""
    return await service.rag_query(payload, profile)


@router.get("/rag/experiments", response_model=RAGCompareResponse)
async def rag_experiments(
    profile: CurrentProfile,
    service: LabSvc,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Past runs, with the delta between the two most recent and a ship verdict."""
    return await service.experiments(profile.id, limit=limit)


@router.get("/rag/golden-set")
async def golden_set() -> list[EvalCase]:
    """The built-in evaluation cases.

    Deliberately readable: a golden set you cannot inspect and disagree with is
    one you should not be gating deploys on.
    """
    return GOLDEN_SET


# ══ Agent Factory ════════════════════════════════════════════════════════════
@router.get("/agents")
async def list_graphs(service: LabSvc) -> list[dict[str, Any]]:
    return service.list_graphs()


@router.get("/agents/{slug}", response_model=GraphDiagramOut)
async def graph_diagram(slug: str, service: LabSvc) -> dict[str, Any]:
    """The topology, **before** running anything.

    Inspecting a graph without executing it is the difference between debugging
    a diagram and debugging a stack trace. Cycles are reported — a cycle is not
    a bug, but every one needs a termination argument.
    """
    return service.graph_diagram(slug)


@router.post("/agents/run", response_model=AgentRunResponse)
async def run_agent(
    payload: AgentRunRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Execute a graph and return the state diff at every step."""
    return await service.run_agent(payload, profile)


@router.post("/agents/resume")
async def resume_agent(
    payload: AgentResumeRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Approve or reject a run paused at a human-in-the-loop checkpoint."""
    return await service.resume_agent(payload.run_id, payload.approved, payload.note)


# ══ AI Mentor ════════════════════════════════════════════════════════════════
@router.post("/mentor/ask", response_model=MentorResponseOut)
async def ask_mentor(
    payload: MentorAskRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Escalating help — never the answer before it is earned (spec §58).

    The response includes the mentor's own graph trace, so the tool that is
    helping you can be inspected in the same Agent Inspector it is built on.
    """
    return await service.ask_mentor(payload)


@router.post("/mentor/socratic", response_model=SocraticResponse)
async def socratic(
    payload: SocraticRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Ask the follow-up that reveals whether the player understood or pattern-matched."""
    return await service.socratic(payload)


@router.post("/mentor/generate", response_model=GenerateQuestionResponse)
async def generate_questions(
    payload: GenerateQuestionRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Generate practice questions from a concept — and validate them.

    Generated content is held to the *same* bar as hand-authored content,
    including the check that the generated ideal answer scores at least 0.6
    correctness against its own generated rubric. Rejected questions are
    returned with their reasons rather than hidden, because seeing what a model
    gets wrong about question design is itself instructive.
    """
    return await service.generate_questions(payload)


# ══ Evaluation Lab ═══════════════════════════════════════════════════════════
@router.post("/evals/run", response_model=EvalRunResponse)
async def run_evaluation(
    payload: EvalRunRequest, profile: CurrentProfile, service: LabSvc
) -> dict[str, Any]:
    """Run a configuration against a golden set and decide ship / hold / rollback.

    Regression against a baseline outranks absolute thresholds: a system that
    got worse is a rollback even when it still clears the gate, because the next
    change will make it worse again.
    """
    return await service.run_evaluation(payload, profile)


@router.get("/status")
async def lab_status(session: DBSession, profile: OptionalProfile) -> dict[str, Any]:
    """Which labs are fully live versus running on the offline stubs."""
    from app.ai.embeddings import get_embedding_service
    from app.ai.llm import get_llm_client
    from app.core.config import settings

    llm = get_llm_client()
    embeddings = get_embedding_service()
    return {
        "llm": {
            "provider": llm.provider_name,
            "simulated": llm.is_simulated,
            "configured": settings.llm_configured,
        },
        "embeddings": {
            "model": embeddings.model_name,
            "simulated": embeddings.is_simulated,
        },
        "note": (
            "Every lab works offline. The mock LLM is deterministic (seeded by a hash of the "
            "prompt), which is what makes the evaluation experiments reproducible. Configure "
            "a provider for real model behaviour — nothing unlocks, it just gets better."
        ),
    }
