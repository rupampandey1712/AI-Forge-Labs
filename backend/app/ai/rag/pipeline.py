"""The RAG pipeline — every stage independently observable and tunable.

DESIGN INTENT: this is not a RAG implementation that happens to be in a game.
It is a RAG implementation built so that a player can *break it on purpose* and
watch which metric moves.

Every stage emits a span. Every knob is a parameter, not a constant. Every
result carries the retrieved chunks and their scores, so a bad answer can always
be traced back to the retrieval that caused it — which is the whole diagnostic
skill the RAG Tower teaches.

    Documents ─► chunk ─► embed ─► store
                                     │
    Question ──► embed ──► retrieve ─┘─► rerank ─► build context ─► LLM ─► answer
                                                                            │
                                                                       evaluate
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import EmbeddingService, cosine_similarity, get_embedding_service
from app.ai.llm.client import LLMClient, get_llm_client
from app.core.logging import get_logger
from app.models.content import KnowledgeDocument

log = get_logger(__name__)


# ══ Chunking ═════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class Chunk:
    text: str
    index: int
    start_char: int
    end_char: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


#: Split priority: paragraph, then sentence, then word. Splitting mid-sentence
#: is what produces the classic "the answer was cut in half and neither chunk
#: retrieved" failure the Tower makes players diagnose.
_SPLIT_PATTERNS = (
    re.compile(r"\n\s*\n"),
    re.compile(r"(?<=[.!?])\s+"),
    re.compile(r"\s+"),
)


def chunk_text(
    text: str,
    *,
    chunk_size: int = 400,
    overlap: int = 50,
    respect_structure: bool = True,
) -> list[Chunk]:
    """Split text into overlapping chunks, preferring natural boundaries.

    ``chunk_size`` and ``overlap`` are in **characters**, not tokens, because
    that is what the player can see and reason about in the UI. The token
    estimate is derived, and the Tower explicitly teaches that ~4 chars/token is
    an approximation that breaks on code and non-English text.

    WHY overlap exists at all: without it, a fact spanning a boundary appears in
    neither chunk completely, so neither retrieves for it. WHY overlap is not
    free: duplicated text means near-identical chunks competing for the same
    top-k slots, crowding out genuinely different material.
    """
    text = text.strip()
    if not text:
        return []
    chunk_size = max(50, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 20))

    if not respect_structure:
        return _fixed_window(text, chunk_size, overlap)

    units = _split_into_units(text)
    chunks: list[Chunk] = []
    buffer = ""
    buffer_start = 0
    cursor = 0

    for unit in units:
        unit_start = text.find(unit, cursor)
        if unit_start == -1:
            unit_start = cursor
        cursor = unit_start + len(unit)

        if not buffer:
            buffer, buffer_start = unit, unit_start
            continue

        if len(buffer) + 1 + len(unit) <= chunk_size:
            buffer = f"{buffer} {unit}" if not buffer.endswith("\n") else buffer + unit
        else:
            chunks.append(
                Chunk(buffer.strip(), len(chunks), buffer_start, buffer_start + len(buffer))
            )
            tail = buffer[-overlap:] if overlap else ""
            buffer = f"{tail} {unit}".strip() if tail else unit
            buffer_start = max(buffer_start, unit_start - len(tail))

    if buffer.strip():
        chunks.append(Chunk(buffer.strip(), len(chunks), buffer_start, buffer_start + len(buffer)))
    return chunks


def _split_into_units(text: str) -> list[str]:
    for pattern in _SPLIT_PATTERNS:
        units = [u.strip() for u in pattern.split(text) if u.strip()]
        # Use the coarsest split that actually produces several units; falling
        # straight to words destroys every structural signal in the document.
        if len(units) > 1:
            return units
    return [text]


def _fixed_window(text: str, size: int, overlap: int) -> list[Chunk]:
    """Naive fixed-width splitting — the 'wrong' baseline, kept deliberately.

    The Tower asks players to compare this against structure-aware chunking on
    the same golden set. Seeing precision drop is more convincing than reading
    that boundaries matter.
    """
    chunks: list[Chunk] = []
    step = max(1, size - overlap)
    for i, start in enumerate(range(0, len(text), step)):
        window = text[start : start + size]
        if window.strip():
            chunks.append(Chunk(window.strip(), i, start, start + len(window)))
    return chunks


# ══ Retrieval ════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class RetrievedChunk:
    doc_slug: str
    title: str
    text: str
    score: float
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Populated when reranking runs, so the UI can show the reordering.
    rerank_score: float | None = None
    original_rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_slug": self.doc_slug,
            "title": self.title,
            "text": self.text,
            "score": round(self.score, 4),
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
            "rerank_score": round(self.rerank_score, 4) if self.rerank_score is not None else None,
            "original_rank": self.original_rank,
        }


@dataclass(slots=True)
class RAGConfig:
    """Every knob, in one object. This IS the lab's control panel."""

    corpus: str = "forge-docs"
    chunk_size: int = 400
    chunk_overlap: int = 50
    respect_structure: bool = True
    top_k: int = 4
    use_reranker: bool = False
    use_hybrid: bool = False
    #: Weight of lexical (BM25-ish) score when hybrid is on. 0 = pure vector.
    hybrid_alpha: float = 0.4
    metadata_filter: dict[str, Any] = field(default_factory=dict)
    max_context_chars: int = 6000
    prompt_template: str = ""
    temperature: float = 0.1
    #: Below this similarity a chunk is dropped entirely. Guards against the
    #: failure where nothing is relevant but top-k returns the least-bad four.
    min_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "respect_structure": self.respect_structure,
            "top_k": self.top_k,
            "use_reranker": self.use_reranker,
            "use_hybrid": self.use_hybrid,
            "hybrid_alpha": self.hybrid_alpha,
            "metadata_filter": self.metadata_filter,
            "max_context_chars": self.max_context_chars,
            "temperature": self.temperature,
            "min_score": self.min_score,
        }


DEFAULT_PROMPT = """You are a precise technical assistant for AI Forge Labs.

Answer the question using ONLY the context below. If the context does not
contain the answer, say exactly: "The provided context does not contain that
information." Do not use outside knowledge. Cite sources as [1], [2] etc.

Context:
{context}

Question: {question}

Answer:"""


@dataclass(slots=True)
class StageTiming:
    name: str
    duration_ms: float
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RAGResult:
    question: str
    answer: str
    retrieved: list[RetrievedChunk]
    config: RAGConfig
    stages: list[StageTiming] = field(default_factory=list)
    prompt: str = ""
    total_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    simulated: bool = False
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "retrieved": [c.to_dict() for c in self.retrieved],
            "config": self.config.to_dict(),
            "stages": [
                {"name": s.name, "duration_ms": round(s.duration_ms, 2), "detail": s.detail}
                for s in self.stages
            ],
            "prompt": self.prompt,
            "total_ms": round(self.total_ms, 2),
            "token_usage": self.token_usage,
            "cost_usd": round(self.cost_usd, 6),
            "simulated": self.simulated,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
        }


# ── Lexical scoring, for hybrid search ───────────────────────────────────────
_WORD_RE = re.compile(r"[a-z0-9_]+")


def bm25_scores(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25, written out rather than imported.

    The Tower's hybrid-search mission asks *why* combining lexical and vector
    retrieval helps — the answer is that they fail differently (BM25 misses
    paraphrase, vectors miss exact identifiers like error codes and API names).
    Seeing the formula makes that concrete.
    """
    query_terms = _WORD_RE.findall(query.lower())
    if not query_terms or not documents:
        return [0.0] * len(documents)

    tokenised = [_WORD_RE.findall(d.lower()) for d in documents]
    lengths = [len(t) for t in tokenised]
    avg_len = sum(lengths) / len(lengths) if lengths else 1.0
    n_docs = len(documents)

    scores = [0.0] * n_docs
    for term in set(query_terms):
        containing = sum(1 for tokens in tokenised if term in tokens)
        if containing == 0:
            continue
        idf = math.log(1 + (n_docs - containing + 0.5) / (containing + 0.5))
        for i, tokens in enumerate(tokenised):
            tf = tokens.count(term)
            if not tf:
                continue
            denom = tf + k1 * (1 - b + b * (lengths[i] / avg_len if avg_len else 1))
            scores[i] += idf * (tf * (k1 + 1)) / denom

    peak = max(scores) or 1.0
    return [s / peak for s in scores]


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Fuse several rankings by reciprocal rank.

    WHY RRF rather than normalising and adding the raw scores: cosine similarity
    and BM25 live on incomparable scales, and a linear blend of them is
    dominated by whichever happens to have more spread on that query. RRF uses
    only *position*, which is the one thing both rankings agree on the meaning
    of.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_index in enumerate(ranking):
            fused[doc_index] = fused.get(doc_index, 0.0) + 1.0 / (k + rank + 1)
    return fused


class Reranker:
    """Cross-encoder-style reranking, approximated offline.

    A real reranker scores (query, passage) *jointly*, which is why it beats
    bi-encoder retrieval — it can see interaction between the two. Offline we
    approximate that with term coverage plus proximity, which is crude but
    reproduces the useful property: it promotes passages that actually contain
    the answer over ones that are merely topically similar.
    """

    name = "heuristic-cross-encoder"

    def score(self, query: str, passage: str) -> float:
        query_terms = set(_WORD_RE.findall(query.lower()))
        if not query_terms:
            return 0.0
        passage_tokens = _WORD_RE.findall(passage.lower())
        passage_terms = set(passage_tokens)

        coverage = len(query_terms & passage_terms) / len(query_terms)

        # Proximity: query terms appearing close together is strong evidence the
        # passage is about the query rather than mentioning its words separately.
        positions = [i for i, tok in enumerate(passage_tokens) if tok in query_terms]
        proximity = 0.0
        if len(positions) > 1:
            span = positions[-1] - positions[0] + 1
            proximity = len(positions) / span
        elif positions:
            proximity = 0.5

        # Short passages that cover the query are better than long ones that
        # bury it — the classic "retrieved chunk is 90% irrelevant" problem.
        density = min(1.0, len(positions) / max(1, len(passage_tokens) / 40))

        return round(0.55 * coverage + 0.25 * proximity + 0.20 * density, 4)


# ══ The pipeline ═════════════════════════════════════════════════════════════
class RAGPipeline:
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingService | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.session = session
        self.embeddings = embeddings or get_embedding_service()
        self.llm = llm or get_llm_client()
        self.reranker = Reranker()

    # ── Ingestion ────────────────────────────────────────────────────────
    async def ingest(
        self,
        *,
        corpus: str,
        slug: str,
        title: str,
        content: str,
        config: RAGConfig,
        metadata: dict[str, Any] | None = None,
        source: str = "",
    ) -> list[KnowledgeDocument]:
        """Chunk, embed and store one document.

        Re-ingesting the same slug replaces its chunks. Chunking parameters are
        stored on each chunk so the lab can show *which* configuration produced
        the corpus currently being queried — comparing runs is meaningless
        otherwise.
        """
        from sqlalchemy import delete

        await self.session.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.chunk_of == slug)
        )

        chunks = chunk_text(
            content,
            chunk_size=config.chunk_size,
            overlap=config.chunk_overlap,
            respect_structure=config.respect_structure,
        )
        if not chunks:
            return []

        embedded = await self.embeddings.embed([c.text for c in chunks])
        rows: list[KnowledgeDocument] = []
        for chunk, vector in zip(chunks, embedded.vectors, strict=False):
            row = KnowledgeDocument(
                slug=f"{slug}#{chunk.index}",
                corpus=corpus,
                title=title,
                source=source,
                content=chunk.text,
                chunk_index=chunk.index,
                chunk_of=slug,
                doc_metadata={
                    **(metadata or {}),
                    "chunk_size": config.chunk_size,
                    "chunk_overlap": config.chunk_overlap,
                    "start_char": chunk.start_char,
                },
                embedding=vector,
                embedding_model=embedded.model,
                token_count=chunk.token_estimate,
            )
            self.session.add(row)
            rows.append(row)

        log.info(
            "rag.ingested",
            slug=slug,
            chunks=len(rows),
            model=embedded.model,
            chunk_size=config.chunk_size,
        )
        return rows

    # ── Retrieval ────────────────────────────────────────────────────────
    async def retrieve(
        self, question: str, config: RAGConfig
    ) -> tuple[list[RetrievedChunk], list[StageTiming]]:
        stages: list[StageTiming] = []

        started = time.perf_counter()
        query_vector = await self.embeddings.embed_query(question)
        stages.append(
            StageTiming(
                "embed_query",
                (time.perf_counter() - started) * 1000,
                {"model": self.embeddings.model_name, "dimensions": len(query_vector)},
            )
        )

        started = time.perf_counter()
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.corpus == config.corpus)
        rows = list((await self.session.execute(stmt)).scalars().all())

        # Metadata filtering happens BEFORE ranking. Applying it after would
        # silently shrink top-k and, in a multi-tenant corpus, would mean the
        # filter is a display concern rather than a security boundary.
        if config.metadata_filter:
            rows = [
                row
                for row in rows
                if all(row.doc_metadata.get(k) == v for k, v in config.metadata_filter.items())
            ]
        stages.append(
            StageTiming(
                "load_corpus",
                (time.perf_counter() - started) * 1000,
                {"candidates": len(rows), "filtered": bool(config.metadata_filter)},
            )
        )

        if not rows:
            return [], stages

        started = time.perf_counter()
        vector_scores = [cosine_similarity(query_vector, row.embedding or []) for row in rows]

        if config.use_hybrid:
            lexical = bm25_scores(question, [r.content for r in rows])
            vector_rank = sorted(range(len(rows)), key=lambda i: -vector_scores[i])
            lexical_rank = sorted(range(len(rows)), key=lambda i: -lexical[i])
            fused = reciprocal_rank_fusion([vector_rank, lexical_rank])
            peak = max(fused.values()) or 1.0
            combined = [fused.get(i, 0.0) / peak for i in range(len(rows))]
            detail = {"mode": "hybrid-rrf", "alpha": config.hybrid_alpha}
        else:
            combined = vector_scores
            detail = {"mode": "vector"}

        ordered = sorted(range(len(rows)), key=lambda i: -combined[i])
        # Over-fetch when reranking: a reranker can only promote what retrieval
        # already returned, so giving it 3x the candidates is what makes it
        # useful rather than cosmetic.
        fetch = config.top_k * 3 if config.use_reranker else config.top_k
        selected = [i for i in ordered[:fetch] if combined[i] >= config.min_score]

        results = [
            RetrievedChunk(
                doc_slug=rows[i].chunk_of or rows[i].slug,
                title=rows[i].title,
                text=rows[i].content,
                score=combined[i],
                chunk_index=rows[i].chunk_index,
                metadata=rows[i].doc_metadata,
                original_rank=rank,
            )
            for rank, i in enumerate(selected)
        ]
        stages.append(
            StageTiming(
                "retrieve",
                (time.perf_counter() - started) * 1000,
                {**detail, "returned": len(results), "fetched": fetch},
            )
        )

        if config.use_reranker and results:
            started = time.perf_counter()
            for chunk in results:
                chunk.rerank_score = self.reranker.score(question, chunk.text)
            results.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
            moved = sum(1 for new, c in enumerate(results) if c.original_rank != new)
            results = results[: config.top_k]
            stages.append(
                StageTiming(
                    "rerank",
                    (time.perf_counter() - started) * 1000,
                    {"model": self.reranker.name, "reordered": moved},
                )
            )

        return results[: config.top_k], stages

    # ── Generation ───────────────────────────────────────────────────────
    def build_context(self, chunks: list[RetrievedChunk], max_chars: int) -> tuple[str, int]:
        """Assemble the context window, truncating from the end.

        Returns the context and how many chunks actually made it. That count is
        the answer to "I retrieved 8 chunks but the model only saw 3" — a real
        and frequently-missed failure, because nothing errors when a prompt is
        silently truncated.
        """
        parts: list[str] = []
        used = 0
        included = 0
        for i, chunk in enumerate(chunks, start=1):
            block = f"[{i}] {chunk.title}\n{chunk.text}"
            if used + len(block) > max_chars and included:
                break
            parts.append(block)
            used += len(block)
            included += 1
        return "\n\n".join(parts), included

    async def query(self, question: str, config: RAGConfig) -> RAGResult:
        overall = time.perf_counter()
        retrieved, stages = await self.retrieve(question, config)

        started = time.perf_counter()
        context, included = self.build_context(retrieved, config.max_context_chars)
        template = config.prompt_template or DEFAULT_PROMPT
        prompt = template.format(context=context or "(no context retrieved)", question=question)
        stages.append(
            StageTiming(
                "build_context",
                (time.perf_counter() - started) * 1000,
                {
                    "chunks_included": included,
                    "chunks_dropped": len(retrieved) - included,
                    "context_chars": len(context),
                    "prompt_tokens_est": len(prompt) // 4,
                },
            )
        )

        started = time.perf_counter()
        response = await self.llm.complete(
            prompt,
            system="You answer strictly from the provided context.",
            temperature=config.temperature,
            max_tokens=700,
        )
        stages.append(
            StageTiming(
                "generate",
                (time.perf_counter() - started) * 1000,
                {
                    "model": response.model,
                    "provider": response.provider,
                    "simulated": response.simulated,
                },
            )
        )

        result = RAGResult(
            question=question,
            answer=response.text.strip(),
            retrieved=retrieved,
            config=config,
            stages=stages,
            prompt=prompt,
            total_ms=(time.perf_counter() - overall) * 1000,
            token_usage={
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
                "total": response.usage.total_tokens,
            },
            cost_usd=response.cost_usd,
            simulated=response.simulated,
        )
        log.info(
            "rag.query",
            chunks=len(retrieved),
            ms=round(result.total_ms, 1),
            hybrid=config.use_hybrid,
            rerank=config.use_reranker,
        )
        return result
