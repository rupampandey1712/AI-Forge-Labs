"""Orchestration for the interactive labs.

The recurring job of this layer is **turning numbers into diagnosis**. Every lab
endpoint returns not just its measurements but a short list of plain-language
observations — because a player staring at `precision@5 = 0.42` does not yet
know that the fix is chunk size rather than the prompt. Teaching that mapping is
the entire point of the RAG Tower, and the diagnosis text is the scaffolding
that gets them there before they can do it unaided.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import GRAPH_INFO, build_graph
from app.ai.evaluation.metrics import (
    aggregate,
    answer_metrics,
    answer_similarity,
    decide_verdict,
    llm_judge,
    retrieval_metrics,
)
from app.ai.llm.client import LLMClient, get_llm_client
from app.ai.llm.pricing import estimate_cost
from app.ai.rag.pipeline import RAGConfig, RAGPipeline, chunk_text
from app.ai.transformer.attention import (
    DEMO_LOGITS,
    compute_attention,
    count_tokens,
    sampling_demo,
    tokenize,
)
from app.ai.tutor.agent import ContentAgent, MentorAgent, MentorRequest, SocraticAgent
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.ai import AgentRun, Evaluation, RAGExperiment
from app.models.content import Challenge, Concept, KnowledgeDocument
from app.models.user import PlayerProfile
from app.schemas.labs import (
    AgentRunRequest,
    AttentionRequest,
    ChunkPreviewRequest,
    EvalRunRequest,
    GenerateQuestionRequest,
    MentorAskRequest,
    RAGConfigIn,
    RAGQueryRequest,
    SamplingRequest,
    SocraticRequest,
)

log = get_logger(__name__)


def _to_rag_config(payload: RAGConfigIn) -> RAGConfig:
    return RAGConfig(
        corpus=payload.corpus,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        respect_structure=payload.respect_structure,
        top_k=payload.top_k,
        use_reranker=payload.use_reranker,
        use_hybrid=payload.use_hybrid,
        metadata_filter=payload.metadata_filter,
        max_context_chars=payload.max_context_chars,
        temperature=payload.temperature,
        min_score=payload.min_score,
        prompt_template=payload.prompt_template,
    )


class LabService:
    def __init__(self, session: AsyncSession, llm: LLMClient | None = None) -> None:
        self.session = session
        self.llm = llm or get_llm_client()
        self.rag = RAGPipeline(session, llm=self.llm)
        self.mentor_agent = MentorAgent(self.llm)
        self.socratic_agent = SocraticAgent(self.llm)
        self.content_agent = ContentAgent(self.llm)

    # ══ Transformer Lab ══════════════════════════════════════════════════
    def attention(self, payload: AttentionRequest) -> dict[str, Any]:
        result = compute_attention(
            payload.text,
            d_model=payload.d_model,
            n_heads=payload.n_heads,
            causal=payload.causal,
            scaled=payload.scaled,
            use_positional=payload.use_positional,
        )
        data = result.to_dict()
        data["insight"] = self._attention_insight(payload, result)
        return data

    @staticmethod
    def _attention_insight(payload: AttentionRequest, result: Any) -> str:
        """Say what the current toggle combination is demonstrating.

        Without this the toggles are three checkboxes that change a heatmap.
        With it, each one is a claim the player can check against the picture.
        """
        if not result.tokens:
            return "Type a sentence to see attention computed over its tokens."

        notes: list[str] = []
        if not payload.scaled:
            peak = max(float(h.weights.max()) for h in result.heads)
            notes.append(
                f"Scaling is OFF. The largest attention weight is {peak:.2f} — without "
                f"dividing by √{result.d_head}, logits grow with dimension, softmax "
                "saturates toward one-hot, and gradients through it vanish. Turn it back on "
                "and watch the distribution flatten."
            )
        if payload.causal:
            notes.append(
                "Causal masking is ON, so the matrix is lower-triangular: token i cannot "
                "attend to anything after it. This is the entire difference between an "
                "encoder (bidirectional) and a decoder (autoregressive)."
            )
        if not payload.use_positional:
            notes.append(
                "Positional encoding is OFF. Self-attention is permutation-equivariant, so "
                "the model now cannot tell 'dog bites man' from 'man bites dog'. Repeat a "
                "word in your sentence and compare its rows — they are now identical."
            )
        if not notes:
            entropies = [e for h in result.heads for e in h.entropy()]
            mean_entropy = sum(entropies) / len(entropies) if entropies else 0.0
            import math

            uniform = math.log(len(result.tokens)) if len(result.tokens) > 1 else 1.0
            notes.append(
                f"Mean attention entropy is {mean_entropy:.2f} against a uniform maximum of "
                f"{uniform:.2f}. These projections are random rather than trained, so heads "
                "spread their attention. A trained head would be far sharper — low entropy "
                "means 'this token knows exactly what it is looking at'."
            )
        return " ".join(notes)

    def tokenize(self, text: str) -> dict[str, Any]:
        tokens = tokenize(text, max_tokens=100_000)
        stats = count_tokens(text)
        # Cost at realistic volume: per-request pennies hide the problem, and
        # "per million requests" is the number that actually changes decisions.
        estimates = [
            {
                "model": model,
                "input_cost_per_1m_requests": round(
                    estimate_cost(model, stats["tokens"], 0) * 1_000_000, 2
                ),
                "cost_per_request": estimate_cost(model, stats["tokens"], 200),
            }
            for model in ("gemini-2.5-flash", "gemini-2.5-pro", "claude-sonnet-5", "gpt-4o-mini")
        ]
        return {
            "tokens": [t.to_dict() for t in tokens[:500]],
            "stats": stats,
            "cost_estimates": estimates,
        }

    def sampling(self, payload: SamplingRequest) -> dict[str, Any]:
        logits: list[float] = payload.logits or list(DEMO_LOGITS["logits"])
        labels: list[str] = payload.labels or list(DEMO_LOGITS["labels"])
        if len(logits) != len(labels):
            raise ValidationFailedError("logits and labels must be the same length")

        result = sampling_demo(
            logits,
            labels,
            temperature=payload.temperature,
            top_k=payload.top_k,
            top_p=payload.top_p,
        )
        result["insight"] = self._sampling_insight(result)
        return result

    @staticmethod
    def _sampling_insight(result: dict[str, Any]) -> str:
        temperature = result["temperature"]
        entropy = result["entropy"]
        if temperature <= 0.2:
            body = (
                f"At T={temperature} the distribution has collapsed (entropy {entropy:.2f}). "
                "This is effectively greedy decoding: the same prompt gives the same answer "
                "every time. Right for extraction and structured output, wrong for anything "
                "that should vary."
            )
        elif temperature >= 1.3:
            body = (
                f"At T={temperature} the distribution is flat (entropy {entropy:.2f}) and "
                "low-probability tokens become genuinely reachable. This is where "
                "'creative' turns into 'incoherent' — and where hallucination rates climb."
            )
        else:
            body = (
                f"T={temperature} keeps the top token dominant while leaving real probability "
                f"on the alternatives (entropy {entropy:.2f}). This is the usual production "
                "range for conversational output."
            )
        if result["tokens_kept"] < len(result["labels"]):
            body += (
                f" Truncation ({result['truncation']}) removed "
                f"{len(result['labels']) - result['tokens_kept']} tokens from consideration "
                "entirely — note that temperature is applied BEFORE truncation, so changing "
                "it changes which tokens survive."
            )
        return body

    # ══ RAG Tower ════════════════════════════════════════════════════════
    def preview_chunks(self, payload: ChunkPreviewRequest) -> dict[str, Any]:
        chunks = chunk_text(
            payload.text,
            chunk_size=payload.chunk_size,
            overlap=payload.chunk_overlap,
            respect_structure=payload.respect_structure,
        )
        if not chunks:
            return {
                "chunks": [],
                "total_chunks": 0,
                "avg_chars": 0.0,
                "avg_tokens": 0.0,
                "overlap_waste_chars": 0,
                "insight": "Nothing to chunk.",
            }

        total_chars = sum(len(c.text) for c in chunks)
        waste = max(0, total_chars - len(payload.text.strip()))
        avg_chars = total_chars / len(chunks)
        avg_tokens = sum(c.token_estimate for c in chunks) / len(chunks)

        notes = []
        if payload.chunk_size < 150:
            notes.append(
                "Chunks this small frequently split a single fact across two of them, so "
                "neither retrieves confidently for it."
            )
        if payload.chunk_size > 1500:
            notes.append(
                "Large chunks dilute relevance: the matching sentence is a small fraction of "
                "what gets sent, so precision drops and you pay for the rest."
            )
        if waste > len(payload.text) * 0.4:
            notes.append(
                f"Overlap is duplicating {waste} characters ({waste / total_chars:.0%} of the "
                "corpus). Near-identical chunks compete for the same top-k slots and crowd "
                "out genuinely different material."
            )
        if payload.chunk_overlap == 0:
            notes.append(
                "Zero overlap means any answer spanning a boundary is lost. Watch what "
                "happens to recall when you raise it."
            )
        if not notes:
            notes.append(
                f"{len(chunks)} chunks averaging {avg_tokens:.0f} tokens. Tune against a "
                "golden set rather than by eye — there is no universal right answer."
            )

        return {
            "chunks": [
                {
                    "index": c.index,
                    "text": c.text,
                    "start_char": c.start_char,
                    "end_char": c.end_char,
                    "chars": len(c.text),
                    "tokens": c.token_estimate,
                }
                for c in chunks
            ],
            "total_chunks": len(chunks),
            "avg_chars": round(avg_chars, 1),
            "avg_tokens": round(avg_tokens, 1),
            "overlap_waste_chars": waste,
            "insight": " ".join(notes),
        }

    async def rag_query(
        self, payload: RAGQueryRequest, profile: PlayerProfile | None = None
    ) -> dict[str, Any]:
        config = _to_rag_config(payload.config)
        result = await self.rag.query(payload.question, config)
        data = result.to_dict()

        metrics: dict[str, float] = {}
        if payload.relevant_doc_ids:
            retrieval = retrieval_metrics(
                [c.doc_slug for c in result.retrieved], payload.relevant_doc_ids
            )
            metrics.update({k: float(v) for k, v in retrieval.to_dict().items()})
        answer = answer_metrics(payload.question, result.answer, [c.text for c in result.retrieved])
        metrics.update(
            {
                "faithfulness": answer.faithfulness,
                "answer_relevance": answer.answer_relevance,
                "context_relevance": answer.context_relevance,
                "groundedness": answer.groundedness,
            }
        )
        if payload.expected_answer:
            metrics["answer_similarity"] = answer_similarity(result.answer, payload.expected_answer)

        data["metrics"] = {k: round(v, 4) for k, v in metrics.items()}
        data["diagnosis"] = self._rag_diagnosis(result, answer, metrics)

        experiment_id = None
        if payload.save_experiment and profile is not None:
            experiment = RAGExperiment(
                profile_id=profile.id,
                corpus=config.corpus,
                question=payload.question,
                expected_answer=payload.expected_answer or None,
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
                top_k=config.top_k,
                embedding_model=self.rag.embeddings.model_name,
                use_reranker=config.use_reranker,
                use_hybrid=config.use_hybrid,
                metadata_filter=config.metadata_filter,
                prompt_template=config.prompt_template or "",
                retrieved=[c.to_dict() for c in result.retrieved],
                answer=result.answer,
                metrics=data["metrics"],
                latency_ms=result.total_ms,
                token_usage=result.token_usage,
            )
            self.session.add(experiment)
            await self.session.flush()
            experiment_id = str(experiment.id)
        data["experiment_id"] = experiment_id
        return data

    @staticmethod
    def _rag_diagnosis(result: Any, answer: Any, metrics: dict[str, float]) -> list[str]:
        """Walk the debugging ladder from RAG.md and report where it breaks.

        Ordered deliberately: corpus → retrieval → chunking → context → generation.
        Most people start at the prompt. It is almost never the prompt.
        """
        notes: list[str] = []

        if not result.retrieved:
            notes.append(
                "❌ Nothing retrieved. Before touching the prompt: is the answer in the corpus "
                "at all? Then check whether min_score or a metadata filter excluded everything."
            )
            return notes

        precision = metrics.get("precision_at_k")
        if precision is not None and precision < 0.5:
            notes.append(
                f"❌ Retrieval precision {precision:.0%} — most of what was retrieved is "
                "irrelevant. This is step 2 of the ladder, and it is where the fix usually is. "
                "Try hybrid search (lexical catches exact identifiers vectors miss) or "
                "reranking."
            )

        recall = metrics.get("recall_at_k")
        if recall is not None and recall < 0.6:
            notes.append(
                f"⚠ Retrieval recall {recall:.0%} — relevant material exists and was not "
                "returned. Raise top_k, or check whether chunking split the answer so that "
                "neither half scores well."
            )

        context_stage = next((s for s in result.stages if s.name == "build_context"), None)
        if context_stage and context_stage.detail.get("chunks_dropped", 0) > 0:
            dropped = context_stage.detail["chunks_dropped"]
            notes.append(
                f"⚠ {dropped} retrieved chunk(s) never reached the model — the context window "
                "truncated them. Nothing errors when this happens, which is why it goes "
                "unnoticed. Raise max_context_chars or lower top_k."
            )

        if answer.refused:
            notes.append(
                "✓ The model correctly refused rather than inventing an answer. That is the "
                "behaviour you want when retrieval fails — a confident wrong answer is far "
                "worse than an honest gap."
            )
        elif answer.faithfulness < 0.6:
            notes.append(
                f"❌ Faithfulness {answer.faithfulness:.0%} — {len(answer.unsupported_claims)} "
                "claim(s) are not supported by the retrieved context. This is hallucination, "
                "and at this point it IS the prompt (or the temperature). Everything above "
                "this line is retrieval; this line is generation."
            )
        elif answer.faithfulness >= 0.9 and not answer.cited_sources:
            notes.append(
                "⚠ The answer is grounded but cites nothing. Citations are what make "
                "groundedness auditable by a user rather than only by you."
            )

        if result.config.temperature > 0.5:
            notes.append(
                f"⚠ Temperature {result.config.temperature} is high for a grounded-answering "
                "task. RAG usually wants near-deterministic output — creativity here means "
                "drifting from the source."
            )

        rerank = next((s for s in result.stages if s.name == "rerank"), None)
        if rerank and rerank.detail.get("reordered", 0) > 0:
            notes.append(
                f"· Reranking moved {rerank.detail['reordered']} chunk(s). When that number is "
                "consistently zero, the reranker is costing latency for nothing."
            )

        if not notes:
            notes.append(
                "✓ Retrieval and grounding both look healthy. Change one knob and re-run to "
                "see which metric it actually moves — that mapping is the skill."
            )
        return notes

    async def corpora(self) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(
                    KnowledgeDocument.corpus,
                    func.count().label("chunks"),
                    func.count(func.distinct(KnowledgeDocument.chunk_of)).label("documents"),
                    func.sum(KnowledgeDocument.token_count).label("tokens"),
                ).group_by(KnowledgeDocument.corpus)
            )
        ).all()

        out: list[dict[str, Any]] = []
        for corpus, chunks, documents, tokens in rows:
            titles = [
                r[0]
                for r in (
                    await self.session.execute(
                        select(KnowledgeDocument.title)
                        .where(KnowledgeDocument.corpus == corpus)
                        .distinct()
                        .limit(25)
                    )
                ).all()
            ]
            model = (
                await self.session.execute(
                    select(KnowledgeDocument.embedding_model)
                    .where(KnowledgeDocument.corpus == corpus)
                    .limit(1)
                )
            ).scalar_one_or_none()
            out.append(
                {
                    "corpus": corpus,
                    "documents": int(documents or 0),
                    "chunks": int(chunks or 0),
                    "embedding_model": model,
                    "total_tokens": int(tokens or 0),
                    "titles": titles,
                }
            )
        return out

    async def experiments(self, profile_id: uuid.UUID, limit: int = 20) -> dict[str, Any]:
        rows = (
            (
                await self.session.execute(
                    select(RAGExperiment)
                    .where(RAGExperiment.profile_id == profile_id)
                    .order_by(RAGExperiment.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        experiments: list[dict[str, Any]] = [
            {
                "id": str(r.id),
                "question": r.question,
                "chunk_size": r.chunk_size,
                "chunk_overlap": r.chunk_overlap,
                "top_k": r.top_k,
                "use_reranker": r.use_reranker,
                "use_hybrid": r.use_hybrid,
                "embedding_model": r.embedding_model,
                "answer": r.answer,
                "metrics": r.metrics,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

        delta: dict[str, float] = {}
        verdict, reasons = "hold", ["Run at least two experiments to compare."]
        if len(experiments) >= 2:
            latest, previous = experiments[0]["metrics"], experiments[1]["metrics"]
            delta = {
                key: round(float(latest[key]) - float(previous.get(key, 0.0)), 4)
                for key in latest
                if isinstance(latest.get(key), (int, float))
            }
            verdict, reasons = decide_verdict(
                {k: float(v) for k, v in latest.items() if isinstance(v, (int, float))},
                baseline={k: float(v) for k, v in previous.items() if isinstance(v, (int, float))},
            )
        return {"experiments": experiments, "delta": delta, "verdict": verdict, "reasons": reasons}

    # ══ Agent Factory ════════════════════════════════════════════════════
    def graph_diagram(self, slug: str) -> dict[str, Any]:
        try:
            graph = build_graph(slug)
        except KeyError as exc:
            raise NotFoundError(f"Unknown graph '{slug}'") from exc
        diagram = graph.to_diagram()
        diagram["cycles"] = graph.find_cycles()
        diagram["info"] = GRAPH_INFO.get(slug, {})
        return diagram

    def list_graphs(self) -> list[dict[str, Any]]:
        out = []
        for slug, info in GRAPH_INFO.items():
            graph = build_graph(slug)
            diagram = graph.to_diagram()
            out.append(
                {
                    "slug": slug,
                    **info,
                    "nodes": len(diagram["nodes"]) - 1,
                    "edges": len(diagram["edges"]),
                    "cycles": len(graph.find_cycles()),
                }
            )
        return out

    async def run_agent(
        self, payload: AgentRunRequest, profile: PlayerProfile | None = None
    ) -> dict[str, Any]:
        try:
            graph = build_graph(payload.graph)
        except KeyError as exc:
            raise NotFoundError(f"Unknown graph '{payload.graph}'") from exc

        state = {"question": payload.question, **payload.initial_state}
        run = await graph.run(state, recursion_limit=payload.recursion_limit)
        data = run.to_dict()
        data["graph"] = payload.graph
        data["diagnosis"] = self._agent_diagnosis(payload.graph, run)

        run_id = None
        if payload.save_run and profile is not None:
            row = AgentRun(
                profile_id=profile.id,
                graph_slug=payload.graph,
                input_payload={"question": payload.question},
                # `interrupted_at` lives in config rather than its own column: it
                # is meaningless except while a run is paused, and adding a
                # column for it would mean a migration for a transient field.
                config={
                    "recursion_limit": payload.recursion_limit,
                    "interrupted_at": run.interrupted_at,
                },
                status=run.status,
                final_state=data["final_state"],
                output=str(run.final_state.get("final_answer", ""))[:5000],
                state_history=data["history"],
                node_visits=run.node_visits,
                steps=run.steps,
                halted_reason=run.halted_reason[:60] if run.halted_reason else None,
                needs_human_approval=run.status == "interrupted",
                latency_ms=run.total_ms,
                token_usage={"total": sum(r.tokens for r in run.history)},
            )
            self.session.add(row)
            await self.session.flush()
            run_id = str(row.id)
        data["run_id"] = run_id
        return data

    @staticmethod
    def _agent_diagnosis(slug: str, run: Any) -> list[str]:
        notes: list[str] = []

        if run.status == "halted":
            worst = max(run.node_visits.items(), key=lambda kv: kv[1], default=("", 0))
            notes.append(
                f"🚨 The graph hit its recursion limit. '{worst[0]}' ran {worst[1]} times. "
                "Find the conditional edge that never routes to END — the fix is a termination "
                "condition, NOT a higher limit. Raising the limit turns a fast failure into a "
                "slow, expensive one."
            )
            notes.append(
                "Compare this with `reflection_agent`: nearly identical topology, but its "
                "`revise` node increments a counter that its router checks. That one line is "
                "the entire difference."
            )
        elif run.status == "interrupted":
            notes.append(
                f"⏸ Paused before '{run.interrupted_at}' — a human-in-the-loop checkpoint. "
                "The state is durable, so the run can resume after approval. This is what "
                "separates an agent you would deploy from a demo."
            )
        elif run.status == "error":
            notes.append(
                f"❌ A node raised: {run.halted_reason}. Note the run stopped cleanly with "
                "full state history rather than losing everything — which is why nodes catch "
                "rather than propagate."
            )
        elif run.looped:
            notes.append(
                f"⚠ Completed, but node visits {run.node_visits} show a loop ran several "
                "times. Bounded, so it terminated — worth checking the bound is deliberate "
                "rather than lucky."
            )
        else:
            notes.append(
                f"✓ Completed in {run.steps} steps. Path: "
                f"{' → '.join(r.node for r in run.history)}."
            )

        if slug == "support_agent" and run.final_state.get("escalated"):
            notes.append(
                f"The self-evaluation scored confidence "
                f"{run.final_state.get('confidence', 0):.2f} and escalated. An agent that "
                "answers without scoring itself has no idea when it is wrong."
            )
        return notes

    async def resume_agent(self, run_id: str, approved: bool, note: str) -> dict[str, Any]:
        """Continue a paused run, or close it out as rejected.

        WHY THIS ACTUALLY RE-EXECUTES: an approval that only records a decision
        teaches the wrong lesson. The entire point of `interrupt_before` is that
        the state is *durable* — the graph stops, a human decides, and execution
        picks up from exactly where it paused with the decision folded into
        state. If approving ran nothing, the lab would be demonstrating a
        confirmation dialog, not human-in-the-loop.

        The returned shape is a full run response, and its history is the
        original steps plus the resumed ones, renumbered into one sequence. The
        player scrubbing the replay should see the whole story, not the tail.
        """
        row = (
            await self.session.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(run_id)))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Agent run not found.")
        if not row.needs_human_approval:
            raise ValidationFailedError("This run is not waiting for approval.")

        decision = "approved" if approved else "rejected"
        resolved_state = {
            **row.final_state,
            "human_decision": decision,
            "human_note": note,
            "resolved_at": datetime.now(UTC).isoformat(),
        }
        prior: list[dict[str, Any]] = list(row.state_history)
        paused_at = (row.config or {}).get("interrupted_at")

        if approved and paused_at:
            graph = build_graph(row.graph_slug)
            # `resume_at` both restarts at the paused node and suppresses *that*
            # node's own interrupt — a later gate in the same graph still stops.
            resumed = await graph.run(
                {},
                recursion_limit=int((row.config or {}).get("recursion_limit", 25)),
                resume_from=resolved_state,
                resume_at=paused_at,
            )
            data = resumed.to_dict()
            # Graph step numbers are 0-indexed and restart at 0 on a resumed
            # run, so they are rebased onto the end of the prior history. Off by
            # one here leaves a gap in the replay scrubber.
            offset = len(prior)
            for index, record in enumerate(data["history"]):
                record["step"] = offset + index
            merged = prior + data["history"]
            visits = dict(row.node_visits)
            for node, count in resumed.node_visits.items():
                visits[node] = visits.get(node, 0) + count

            row.status = resumed.status
            row.final_state = data["final_state"]
            row.output = str(resumed.final_state.get("final_answer", ""))[:5000]
            row.state_history = merged
            row.node_visits = visits
            row.steps = row.steps + resumed.steps
            row.latency_ms = row.latency_ms + resumed.total_ms
            row.halted_reason = resumed.halted_reason[:60] if resumed.halted_reason else None
            # A second gate in the same graph leaves the run paused again.
            row.needs_human_approval = resumed.status == "interrupted"
            row.config = {**(row.config or {}), "interrupted_at": resumed.interrupted_at}
            payload = {
                **data,
                "history": merged,
                "node_visits": visits,
                "steps": row.steps,
                "total_ms": row.latency_ms,
            }
        else:
            # A rejection is a terminal outcome, not a failure: the graph did its
            # job by asking. Nothing further executes.
            row.status = "rejected" if not approved else "completed"
            row.final_state = resolved_state
            row.needs_human_approval = False
            payload = {
                "status": row.status,
                "final_state": resolved_state,
                "history": prior,
                "halted_reason": None,
                "interrupted_at": None,
                "steps": row.steps,
                "total_ms": row.latency_ms,
                "node_visits": dict(row.node_visits),
                "looped": False,
            }

        row.human_decision = decision
        payload["run_id"] = run_id
        payload["graph"] = row.graph_slug
        payload["diagnosis"] = self._resume_diagnosis(decision, str(paused_at or ""), row.status)
        return payload

    @staticmethod
    def _resume_diagnosis(decision: str, paused_at: str, status: str) -> list[str]:
        if decision == "rejected":
            return [
                f"✋ Rejected at '{paused_at}'. The graph stopped without acting, which is the "
                "outcome the checkpoint exists to make possible. Note that the agent had already "
                "decided what to do — the gate is what turned that decision into a proposal.",
            ]
        notes = [
            f"▶ Resumed from '{paused_at}' with the approval folded into state. The steps after "
            "this point are the ones the checkpoint was holding back.",
        ]
        if status == "interrupted":
            notes.append(
                "⏸ And it paused again: this graph has more than one gate. Approving once does "
                "not grant blanket permission, which is the correct default for anything that "
                "spends money or touches production."
            )
        return notes

    # ══ Mentor ═══════════════════════════════════════════════════════════
    async def ask_mentor(self, payload: MentorAskRequest) -> dict[str, Any]:
        concept_title = concept_summary = ""
        if payload.concept_slug:
            concept = (
                await self.session.execute(
                    select(Concept).where(Concept.slug == payload.concept_slug)
                )
            ).scalar_one_or_none()
            if concept:
                concept_title, concept_summary = concept.title, concept.summary

        authored: list[str] = []
        if payload.challenge_slug:
            challenge = (
                await self.session.execute(
                    select(Challenge).where(Challenge.slug == payload.challenge_slug)
                )
            ).scalar_one_or_none()
            if challenge:
                authored = [h if isinstance(h, str) else h.get("text", "") for h in challenge.hints]

        response = await self.mentor_agent.help(
            MentorRequest(
                question=payload.question,
                concept_slug=payload.concept_slug,
                concept_title=concept_title,
                concept_summary=concept_summary,
                code=payload.code,
                error=payload.error,
                tier=payload.tier,
                attempts=payload.attempts,
                hints_used=payload.hints_used,
                persona=payload.persona,
                authored_hints=authored,
            )
        )
        return response.to_dict()

    async def socratic(self, payload: SocraticRequest) -> dict[str, Any]:
        concept = (
            await self.session.execute(select(Concept).where(Concept.slug == payload.concept_slug))
        ).scalar_one_or_none()
        if concept is None:
            raise NotFoundError(f"Concept '{payload.concept_slug}' not found.")
        return await self.socratic_agent.probe(
            concept_title=concept.title,
            concept_summary=concept.summary,
            player_answer=payload.player_answer,
            tier=payload.tier,
        )

    async def generate_questions(self, payload: GenerateQuestionRequest) -> dict[str, Any]:
        concept = (
            await self.session.execute(select(Concept).where(Concept.slug == payload.concept_slug))
        ).scalar_one_or_none()
        if concept is None:
            raise NotFoundError(f"Concept '{payload.concept_slug}' not found.")

        from app.models.content import Question

        existing = [
            r[0]
            for r in (
                await self.session.execute(
                    select(Question.prompt).where(Question.category == concept.category).limit(10)
                )
            ).all()
        ]

        generated = []
        for _ in range(payload.count):
            question = await self.content_agent.generate_question(
                concept_title=concept.title,
                concept_summary=concept.summary,
                concept_explanation=concept.explanation,
                tier=payload.tier,
                kind=payload.kind,
                avoid=existing,
            )
            generated.append(question.to_dict())
            if question.prompt:
                existing.append(question.prompt)

        accepted = sum(1 for g in generated if g["is_usable"])
        return {
            "concept_slug": concept.slug,
            "concept_title": concept.title,
            "generated": generated,
            "accepted": accepted,
            "rejected": len(generated) - accepted,
            "validation_note": (
                "Generated questions run through the same validator as hand-authored content: "
                "every MCQ distractor needs an explanation, every free-text question needs a "
                "rubric, and the generated ideal answer must score at least 0.6 correctness "
                "against its own rubric. A model that writes a rubric its own answer fails has "
                "produced an unscoreable question, and no downstream prompting fixes that."
            ),
        }

    # ══ Evaluation Lab ═══════════════════════════════════════════════════
    async def run_evaluation(
        self, payload: EvalRunRequest, profile: PlayerProfile | None = None
    ) -> dict[str, Any]:
        cases: list[EvalCase] = [
            EvalCase(
                question=c.question,
                relevant=list(c.relevant_doc_ids or []),
                expected=c.expected_answer or "",
            )
            for c in payload.cases
        ]
        if not cases and payload.use_golden_set:
            cases = GOLDEN_SET
        if not cases:
            raise ValidationFailedError("No evaluation cases supplied.")

        config = _to_rag_config(payload.config)
        per_case: list[dict[str, Any]] = []

        for case in cases:
            result = await self.rag.query(case["question"], config)
            retrieval = retrieval_metrics([c.doc_slug for c in result.retrieved], case["relevant"])
            answer = answer_metrics(
                case["question"], result.answer, [c.text for c in result.retrieved]
            )
            metrics = {
                **{
                    k: float(v)
                    for k, v in retrieval.to_dict().items()
                    if isinstance(v, (int, float))
                },
                "faithfulness": answer.faithfulness,
                "answer_relevance": answer.answer_relevance,
                "context_relevance": answer.context_relevance,
                "groundedness": answer.groundedness,
            }
            if case["expected"]:
                metrics["answer_similarity"] = answer_similarity(result.answer, case["expected"])

            if payload.use_llm_judge:
                judged = await llm_judge(
                    self.llm,
                    question=case["question"],
                    answer=result.answer,
                    context_chunks=[c.text for c in result.retrieved],
                    expected=case["expected"] or None,
                )
                metrics["judge_faithfulness"] = judged["faithfulness"]
                metrics["judge_relevance"] = judged["answer_relevance"]

            passed = metrics["faithfulness"] >= 0.7 and metrics.get("precision_at_k", 1.0) >= 0.5
            per_case.append(
                {
                    "question": case["question"],
                    "answer": result.answer,
                    "passed": passed,
                    "metrics": {k: round(v, 4) for k, v in metrics.items()},
                    "retrieved_titles": [c.title for c in result.retrieved],
                    "unsupported_claims": answer.unsupported_claims,
                }
            )

        summary = aggregate([c["metrics"] for c in per_case])

        baseline = None
        if payload.baseline_evaluation_id:
            row = (
                await self.session.execute(
                    select(Evaluation).where(
                        Evaluation.id == uuid.UUID(payload.baseline_evaluation_id)
                    )
                )
            ).scalar_one_or_none()
            if row:
                baseline = {
                    k: float(v)
                    for k, v in (row.extra_metrics or {}).items()
                    if isinstance(v, (int, float))
                }

        verdict, reasons = decide_verdict(summary, baseline)

        evaluation_id = None
        if profile is not None:
            row = Evaluation(
                profile_id=profile.id,
                name=payload.name,
                target_type="rag",
                target_ref=config.corpus,
                config=config.to_dict(),
                retrieval_precision=summary.get("precision_at_k"),
                retrieval_recall=summary.get("recall_at_k"),
                context_relevance=summary.get("context_relevance"),
                faithfulness=summary.get("faithfulness"),
                answer_relevance=summary.get("answer_relevance"),
                groundedness=summary.get("groundedness"),
                extra_metrics={k: round(v, 4) for k, v in summary.items()},
                cases_total=len(per_case),
                cases_passed=sum(1 for c in per_case if c["passed"]),
                results=per_case,
                verdict=verdict,
                notes=" | ".join(reasons),
            )
            self.session.add(row)
            await self.session.flush()
            evaluation_id = str(row.id)

        return {
            "evaluation_id": evaluation_id,
            "name": payload.name,
            "cases_total": len(per_case),
            "cases_passed": sum(1 for c in per_case if c["passed"]),
            "metrics": {k: round(v, 4) for k, v in summary.items()},
            "per_case": per_case,
            "verdict": verdict,
            "reasons": reasons,
            "baseline": baseline,
            "judged_by": "llm" if payload.use_llm_judge else "deterministic",
        }


#: The built-in golden set for the Evals Lab, over the seeded `forge-docs`
#: corpus. Small and hand-labelled — a golden set you cannot read and verify
#: yourself is a golden set you should not trust.
class EvalCase(TypedDict):
    """One golden-set row.

    WHY a TypedDict rather than a bare dict: mypy widens a dict literal whose
    values mix ``str`` and ``list[str]`` to ``Sequence[str]``, so every later
    ``case["question"]`` looked like a sequence of strings and the real contract
    was invisible. This costs nothing at runtime — it is still a plain dict —
    and it is the shape a player writing their own eval set must produce.
    """

    question: str
    relevant: list[str]
    expected: str


GOLDEN_SET: list[EvalCase] = [
    {
        "question": "How long is a password reset link valid?",
        "relevant": ["forge-security-policy"],
        "expected": "The reset link expires after 15 minutes.",
    },
    {
        "question": "What happens when a refresh token is reused?",
        "relevant": ["forge-security-policy"],
        "expected": "Reuse is treated as theft: every session for that user is revoked.",
    },
    {
        "question": "Why does the sandbox run player code in a separate process?",
        "relevant": ["forge-sandbox-design"],
        "expected": "Python cannot sandbox itself; isolation requires a process or container boundary.",
    },
    {
        "question": "How is mastery capped?",
        "relevant": ["forge-retention-model"],
        "expected": "By the deepest difficulty tier the player has cleared.",
    },
    {
        "question": "What is the company's holiday policy?",
        "relevant": [],
        "expected": "The provided context does not contain that information.",
    },
]
