"""Embeddings, with an offline provider that is genuinely useful.

WHY the offline provider matters: the RAG Tower is about *debugging retrieval*.
A player must be able to change chunk size, watch precision move, and reason
about why — none of which requires a real embedding model. A deterministic
local embedder makes the whole lab reproducible, testable and free.

THE OFFLINE MODEL: hashed character n-grams + word unigrams, TF weighted,
L2-normalised. It is a bag-of-n-grams model, so it captures lexical overlap and
nothing else.

That limitation is a *feature* for teaching. The Tower's central lesson is that
lexical retrieval fails on paraphrase — "how do I reset my password" vs "account
recovery steps" share almost no tokens. Players hit that wall with the offline
model, and then switching to a real embedding provider *visibly* fixes it. Being
told semantic search is better teaches nothing; watching precision jump from
0.42 to 0.87 on the same golden set teaches it permanently.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimensions: int
    tokens: int = 0
    cost_usd: float = 0.0
    simulated: bool = False


class EmbeddingProvider(ABC):
    name: str = "abstract"
    dimensions: int = 256

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text])).vectors[0]


# ── Offline ──────────────────────────────────────────────────────────────────
class HashingEmbeddings(EmbeddingProvider):
    """Deterministic, dependency-free, ~0.1ms per document.

    Uses both word unigrams and character 4-grams: the character grams give it
    partial robustness to morphology ("retry"/"retries") that pure word hashing
    lacks, which keeps the lab's baseline from being uselessly bad.
    """

    name = "hash-tfidf"

    def __init__(self, dimensions: int = 256, char_ngram: int = 4) -> None:
        self.dimensions = dimensions
        self.char_ngram = char_ngram

    def _features(self, text: str) -> Counter[str]:
        lowered = text.lower()
        words = TOKEN_RE.findall(lowered)
        features: Counter[str] = Counter(words)
        # Word bigrams capture a little word order — enough that "not safe"
        # and "safe" are not identical vectors.
        features.update(f"{a}_{b}" for a, b in pairwise(words))
        compact = re.sub(r"\s+", " ", lowered)
        n = self.char_ngram
        features.update(f"#{compact[i : i + n]}" for i in range(max(0, len(compact) - n + 1)))
        return features

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for feature, count in self._features(text).items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            # The sign bit halves collision cancellation error — two colliding
            # features are as likely to cancel as to reinforce, which keeps a
            # hashed space usable at 256 dimensions.
            sign = 1.0 if digest[4] & 1 else -1.0
            # Sublinear TF: a word repeated 50 times is not 50x as meaningful.
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._vector(t) for t in texts],
            model=self.name,
            dimensions=self.dimensions,
            tokens=sum(len(t) // 4 for t in texts),
            simulated=True,
        )


# ── Hosted ───────────────────────────────────────────────────────────────────
class GeminiEmbeddings(EmbeddingProvider):
    """Google `text-embedding-004` via the Generative Language REST API."""

    name = "gemini-embedding"
    dimensions = 768
    URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = "text-embedding-004") -> None:
        self.api_key = api_key
        self.model = model

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.model, self.dimensions)
        # Gemini has a dedicated batch endpoint; one request for N documents
        # instead of N requests is the difference between a 2s ingest and a 40s
        # one, and it is the most common thing people leave on the table.
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text[:20000]}]},
                    "taskType": "RETRIEVAL_DOCUMENT",
                }
                for text in texts
            ]
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.URL}/{self.model}:batchEmbedContents",
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            raise EmbeddingUnavailable(
                f"gemini embeddings {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        vectors = [e["values"] for e in data.get("embeddings", [])]
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            dimensions=len(vectors[0]) if vectors else self.dimensions,
            tokens=sum(len(t) // 4 for t in texts),
        )


class OpenAIEmbeddings(EmbeddingProvider):
    name = "openai-embedding"
    dimensions = 1536
    URL = "https://api.openai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self.api_key = api_key
        self.model = model

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.model, self.dimensions)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": [t[:20000] for t in texts]},
            )
        if response.status_code >= 400:
            raise EmbeddingUnavailable(
                f"openai embeddings {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"])]
        usage = data.get("usage", {})
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            dimensions=len(vectors[0]) if vectors else self.dimensions,
            tokens=usage.get("total_tokens", 0),
            cost_usd=round(usage.get("total_tokens", 0) * 0.02 / 1_000_000, 8),
        )


class EmbeddingUnavailable(RuntimeError):
    """The configured embedding provider could not be reached."""


# ── Similarity ───────────────────────────────────────────────────────────────
def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity, robust to unnormalised input.

    Written out rather than using NumPy so the RAG Tower can show the player
    the actual arithmetic — "what IS a similarity score" is a tier-2 question
    that a `np.dot` hides.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def top_k_similar(
    query: list[float], candidates: list[tuple[Any, list[float]]], k: int = 5
) -> list[tuple[Any, float]]:
    """Brute-force nearest neighbours.

    O(n·d) per query with no index. Correct, and deliberately so for a few
    thousand chunks — the RAG missions make the player *measure* where this
    stops being acceptable rather than asserting a threshold up front.
    """
    scored = [(item, cosine_similarity(query, vector)) for item, vector in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]


class EmbeddingService:
    """Facade with automatic fallback to the offline model."""

    def __init__(
        self, provider: EmbeddingProvider | None = None, cfg: Settings | None = None
    ) -> None:
        self.cfg = cfg or get_settings()
        self.provider = provider or build_embedding_provider(self.cfg)
        self._fallback = HashingEmbeddings()

    @property
    def model_name(self) -> str:
        return self.provider.name

    @property
    def is_simulated(self) -> bool:
        return isinstance(self.provider, HashingEmbeddings)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        try:
            return await self.provider.embed(texts)
        except (EmbeddingUnavailable, httpx.HTTPError) as exc:
            log.warning("embeddings.fallback", provider=self.provider.name, error=str(exc)[:200])
            return await self._fallback.embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text])).vectors[0]


def build_embedding_provider(cfg: Settings | None = None) -> EmbeddingProvider:
    cfg = cfg or get_settings()
    match cfg.embedding_provider:
        case "gemini" | "google":
            return (
                GeminiEmbeddings(cfg.gemini_api_key) if cfg.gemini_api_key else HashingEmbeddings()
            )
        case "openai":
            return (
                OpenAIEmbeddings(cfg.openai_api_key) if cfg.openai_api_key else HashingEmbeddings()
            )
        case _:
            return HashingEmbeddings(dimensions=cfg.embedding_dimensions)


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
