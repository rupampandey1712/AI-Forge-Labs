"""Embeddings with a deterministic offline provider."""

from app.ai.embeddings.service import (
    EmbeddingResult,
    EmbeddingService,
    HashingEmbeddings,
    cosine_similarity,
    get_embedding_service,
    top_k_similar,
)

__all__ = [
    "EmbeddingResult",
    "EmbeddingService",
    "HashingEmbeddings",
    "cosine_similarity",
    "get_embedding_service",
    "top_k_similar",
]
