"""Transformers from first principles, computed for real.

Every number the Attention Visualiser renders is *actually computed here* with
NumPy — real embeddings, real positional encodings, real Q·Kᵀ/√d, real softmax.
Nothing is faked for the animation.

WHY that matters: an attention heatmap generated from random numbers teaches a
player that attention produces pretty squares. One computed from a deterministic
embedding of the sentence they typed lets them discover that changing a word
changes a specific column, that masking is what makes generation causal, and
that √d is not decoration — because they can turn it off and watch the softmax
saturate.

The weights are deterministic pseudo-random (seeded per head), not trained. That
is stated in the UI: the *mechanism* is real, the learned behaviour is not.
Claiming otherwise would be the exact dishonesty this project is arguing against.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_D_MODEL = 64
DEFAULT_HEADS = 4
MAX_TOKENS = 64


# ══ Tokenization ═════════════════════════════════════════════════════════════
_WORD_PIECE_RE = re.compile(r"\w+|[^\w\s]")

#: A tiny, hand-built subword vocabulary. Real BPE is learned from a corpus;
#: this reproduces the *behaviours* that matter pedagogically — common words
#: stay whole, rare words split, and the split is visible.
_COMMON_SUFFIXES = ("ing", "tion", "ness", "ment", "able", "ible", "ed", "er", "est", "ly", "s")
_COMMON_PREFIXES = ("un", "re", "pre", "dis", "non", "sub", "inter")


@dataclass(slots=True)
class Token:
    text: str
    index: int
    id: int
    #: True when this piece came from splitting a larger word.
    is_subword: bool = False
    of_word: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "index": self.index,
            "id": self.id,
            "is_subword": self.is_subword,
            "of_word": self.of_word,
        }


def tokenize(text: str, *, max_tokens: int = MAX_TOKENS) -> list[Token]:
    """Split text into tokens, demonstrating subword behaviour.

    The lesson this exists to deliver: **token count is not word count**.
    Players consistently under-estimate context usage because they think in
    words, and the cost of that mistake is a truncated prompt with no error.
    """
    tokens: list[Token] = []
    for word in _WORD_PIECE_RE.findall(text.strip()):
        pieces = _split_word(word)
        for i, piece in enumerate(pieces):
            tokens.append(
                Token(
                    text=piece,
                    index=len(tokens),
                    id=_token_id(piece),
                    is_subword=len(pieces) > 1,
                    of_word=word if len(pieces) > 1 else "",
                )
            )
            if len(tokens) >= max_tokens:
                return tokens
            del i
    return tokens


def _split_word(word: str) -> list[str]:
    lowered = word.lower()
    # Short and common: one token, like a real tokenizer's frequent-word entries.
    if len(lowered) <= 4 or not lowered.isalpha():
        return [word]

    for prefix in _COMMON_PREFIXES:
        if lowered.startswith(prefix) and len(lowered) > len(prefix) + 3:
            return [word[: len(prefix)], "##" + word[len(prefix) :]]
    for suffix in _COMMON_SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) > len(suffix) + 3:
            return [word[: -len(suffix)], "##" + word[-len(suffix) :]]
    # Long and unrecognised: split in the middle, the way BPE handles a word it
    # has never seen. This is why an unusual identifier costs several tokens.
    if len(lowered) > 9:
        mid = len(word) // 2
        return [word[:mid], "##" + word[mid:]]
    return [word]


def _token_id(piece: str) -> int:
    return int(hashlib.blake2b(piece.lower().encode(), digest_size=4).hexdigest(), 16) % 50_000


def count_tokens(text: str) -> dict[str, Any]:
    """Token accounting, for the LLM Lab's cost missions."""
    tokens = tokenize(text, max_tokens=100_000)
    words = len(text.split())
    return {
        "tokens": len(tokens),
        "words": words,
        "characters": len(text),
        "tokens_per_word": round(len(tokens) / words, 2) if words else 0.0,
        "chars_per_token": round(len(text) / len(tokens), 2) if tokens else 0.0,
        "subword_splits": sum(1 for t in tokens if t.is_subword),
    }


# ══ Embeddings and positional encoding ═══════════════════════════════════════
def token_embeddings(tokens: list[Token], d_model: int = DEFAULT_D_MODEL) -> np.ndarray:
    """Deterministic embedding per token id.

    The same token always gets the same vector, so "the" in position 0 and "the"
    in position 5 are *identical* before positional encoding is added. That
    identity is the setup for the next lesson.
    """
    matrix = np.zeros((len(tokens), d_model), dtype=np.float64)
    for i, token in enumerate(tokens):
        rng = np.random.default_rng(token.id)
        vector = rng.normal(0.0, 1.0, d_model)
        matrix[i] = vector / (np.linalg.norm(vector) + 1e-9)
    return matrix


def positional_encoding(length: int, d_model: int = DEFAULT_D_MODEL) -> np.ndarray:
    """The original sinusoidal encoding from *Attention Is All You Need*.

        PE(pos, 2i)   = sin(pos / 10000^(2i/d))
        PE(pos, 2i+1) = cos(pos / 10000^(2i/d))

    WHY this is needed at all — the tier-7 question: self-attention is a
    *permutation-equivariant* operation. Shuffle the input tokens and you get
    the same outputs, shuffled. "dog bites man" and "man bites dog" would be
    indistinguishable. Position has to be injected into the representation
    because the mechanism itself cannot see order.

    WHY sinusoidal specifically: relative position becomes a linear function of
    the encoding, so the model can learn "attend three tokens back" as a single
    transformation rather than memorising every absolute pair.
    """
    positions = np.arange(length)[:, None]
    dimensions = np.arange(d_model)[None, :]
    angle_rates = 1.0 / np.power(10_000.0, (2 * (dimensions // 2)) / d_model)
    angles = positions * angle_rates
    encoding = np.zeros((length, d_model))
    encoding[:, 0::2] = np.sin(angles[:, 0::2])
    encoding[:, 1::2] = np.cos(angles[:, 1::2])
    return encoding


# ══ Attention ════════════════════════════════════════════════════════════════
def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    """Numerically stable softmax.

    Subtracting the max before exponentiating is not an optimisation — without
    it, a large logit overflows to `inf` and the whole row becomes `nan`. This
    is a real failure mode in float16 training, and the Deep Learning Lab has a
    mission on it.
    """
    shifted = x - np.max(x, axis=axis, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / (np.sum(exponentiated, axis=axis, keepdims=True) + 1e-9)


@dataclass(slots=True)
class AttentionHead:
    head: int
    #: (seq, seq) post-softmax attention weights.
    weights: np.ndarray
    #: (seq, seq) pre-softmax scores, so the UI can show what scaling does.
    raw_scores: np.ndarray
    queries: np.ndarray
    keys: np.ndarray
    values: np.ndarray
    output: np.ndarray

    def entropy(self) -> list[float]:
        """Per-row attention entropy.

        Low entropy = this token attends sharply to one place. High entropy =
        it is averaging over everything, which is what an untrained (or
        collapsed) head looks like. Showing it turns "the heatmap looks uniform"
        into a number.
        """
        w = np.clip(self.weights, 1e-9, 1.0)
        return (-np.sum(w * np.log(w), axis=-1)).round(4).tolist()


@dataclass(slots=True)
class AttentionResult:
    tokens: list[Token]
    d_model: int
    n_heads: int
    d_head: int
    heads: list[AttentionHead] = field(default_factory=list)
    embeddings: np.ndarray | None = None
    positional: np.ndarray | None = None
    combined: np.ndarray | None = None
    multi_head_output: np.ndarray | None = None
    causal: bool = False
    scaled: bool = True

    def to_dict(self, *, include_matrices: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tokens": [t.to_dict() for t in self.tokens],
            "d_model": self.d_model,
            "n_heads": self.n_heads,
            "d_head": self.d_head,
            "causal": self.causal,
            "scaled": self.scaled,
            "heads": [
                {
                    "head": h.head,
                    "weights": np.round(h.weights, 4).tolist(),
                    "raw_scores": np.round(h.raw_scores, 3).tolist(),
                    "entropy": h.entropy(),
                    # Which token each token attends to most — the single most
                    # readable summary of a head's behaviour.
                    "argmax": np.argmax(h.weights, axis=-1).tolist(),
                }
                for h in self.heads
            ],
        }
        if include_matrices and self.embeddings is not None:
            # Truncated to 16 dimensions: the point is to show the *shape* and
            # that positional encoding changed the values, not to dump 64 floats
            # per token into a table nobody reads.
            #
            # NOTE the explicit `is not None` checks. `array or default` raises
            # "truth value of an array is ambiguous" — NumPy refuses to guess
            # whether you meant .any() or .all(). This is the same class of bug
            # the game's own mistake detector flags as `equality_with_singleton`,
            # and it reached here because the first test exercised the attributes
            # directly and never serialised.
            shown = 16
            payload["vectors"] = {
                "embedding": np.round(self.embeddings[:, :shown], 3).tolist(),
                "positional": (
                    np.round(self.positional[:, :shown], 3).tolist()
                    if self.positional is not None
                    else []
                ),
                "combined": (
                    np.round(self.combined[:, :shown], 3).tolist()
                    if self.combined is not None
                    else []
                ),
                "shown_dimensions": shown,
            }
        return payload


def _projection(seed: int, d_model: int, d_head: int) -> np.ndarray:
    """Deterministic pseudo-random projection matrix.

    Xavier-scaled so the resulting logits sit in a sensible range. These are
    NOT learned weights, and the UI says so — the mechanism is real, the
    behaviour is arbitrary.
    """
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, math.sqrt(1.0 / d_model), (d_model, d_head))


def compute_attention(
    text: str,
    *,
    d_model: int = DEFAULT_D_MODEL,
    n_heads: int = DEFAULT_HEADS,
    causal: bool = False,
    scaled: bool = True,
    use_positional: bool = True,
    seed: int = 42,
) -> AttentionResult:
    """Run one multi-head self-attention block and return every intermediate.

    The three toggles are the lab's entire pedagogy:

    * ``scaled=False`` — drop the 1/√d. Watch the softmax saturate into
      near-one-hot rows. That is *why* the paper divides.
    * ``causal=True`` — apply the upper-triangular mask. Watch the matrix become
      triangular. That is what makes generation autoregressive.
    * ``use_positional=False`` — remove position. Watch identical tokens in
      different positions produce identical rows, and the whole thing become
      order-blind.
    """
    tokens = tokenize(text)
    if not tokens:
        return AttentionResult([], d_model, n_heads, d_model // n_heads)

    seq_len = len(tokens)
    d_head = d_model // n_heads

    embeddings = token_embeddings(tokens, d_model)
    positional = positional_encoding(seq_len, d_model)
    # Addition, not concatenation — the residual stream has one width, and every
    # sublayer reads and writes the same space.
    combined = embeddings + positional if use_positional else embeddings.copy()

    heads: list[AttentionHead] = []
    outputs: list[np.ndarray] = []

    for head_index in range(n_heads):
        base = seed * 1000 + head_index * 7
        w_q = _projection(base + 1, d_model, d_head)
        w_k = _projection(base + 2, d_model, d_head)
        w_v = _projection(base + 3, d_model, d_head)

        queries = combined @ w_q
        keys = combined @ w_k
        values = combined @ w_v

        # Q·Kᵀ — how much each token's *query* matches every token's *key*.
        raw_scores = queries @ keys.T

        # The scaling. Without it, dot products of d_head-dimensional vectors
        # have variance ~d_head, so logits grow with dimension, softmax
        # saturates, and gradients vanish. Dividing by √d_head normalises the
        # variance back to ~1.
        scores = raw_scores / math.sqrt(d_head) if scaled else raw_scores

        if causal:
            # -inf above the diagonal so softmax sends those to exactly zero.
            # A token cannot attend to its own future.
            mask = np.triu(np.ones((seq_len, seq_len), dtype=bool), k=1)
            scores = np.where(mask, -np.inf, scores)

        weights = softmax(scores, axis=-1)
        output = weights @ values

        heads.append(
            AttentionHead(
                head=head_index,
                weights=weights,
                raw_scores=raw_scores,
                queries=queries,
                keys=keys,
                values=values,
                output=output,
            )
        )
        outputs.append(output)

    # Concatenate heads and project back to d_model — the step that lets
    # different heads specialise and still contribute to one residual stream.
    concatenated = np.concatenate(outputs, axis=-1)
    w_o = _projection(seed * 1000 + 99, d_model, d_model)
    multi_head_output = concatenated @ w_o

    return AttentionResult(
        tokens=tokens,
        d_model=d_model,
        n_heads=n_heads,
        d_head=d_head,
        heads=heads,
        embeddings=embeddings,
        positional=positional,
        combined=combined,
        multi_head_output=multi_head_output,
        causal=causal,
        scaled=scaled,
    )


# ══ Sampling ═════════════════════════════════════════════════════════════════
def sampling_demo(
    logits: list[float],
    labels: list[str],
    *,
    temperature: float = 1.0,
    top_k: int | None = None,
    top_p: float | None = None,
) -> dict[str, Any]:
    """Show exactly what temperature, top-k and top-p do to a distribution.

    The LLM Lab's core experiment. Players set temperature to 0.1, 0.7 and 1.5
    on the *same* logits and watch the probability mass move — which is far more
    convincing than reading that "higher temperature is more random".

    Order matters and is a genuine gotcha: temperature is applied to the logits
    **before** truncation, so changing it changes which tokens survive top-p.
    """
    array = np.asarray(logits, dtype=np.float64)
    temperature = max(0.01, temperature)

    scaled = array / temperature
    probabilities = softmax(scaled)

    kept = np.ones(len(array), dtype=bool)
    reason = "full distribution"

    if top_k is not None and 0 < top_k < len(array):
        threshold = np.sort(probabilities)[-top_k]
        kept &= probabilities >= threshold
        reason = f"top-{top_k}"

    if top_p is not None and 0.0 < top_p < 1.0:
        order = np.argsort(-probabilities)
        cumulative = np.cumsum(probabilities[order])
        # `searchsorted` + 1 keeps the token that *crosses* the threshold —
        # otherwise top_p=0.9 on a [0.95, ...] distribution would keep nothing.
        cutoff = int(np.searchsorted(cumulative, top_p) + 1)
        nucleus = set(order[:cutoff].tolist())
        kept &= np.array([i in nucleus for i in range(len(array))])
        reason = f"{reason} + top-p {top_p}" if top_k else f"top-p {top_p}"

    truncated = np.where(kept, probabilities, 0.0)
    total = truncated.sum()
    final = truncated / total if total > 0 else probabilities

    return {
        "labels": labels,
        "logits": np.round(array, 3).tolist(),
        "temperature": temperature,
        "scaled_logits": np.round(scaled, 3).tolist(),
        "probabilities": np.round(probabilities, 4).tolist(),
        "final_probabilities": np.round(final, 4).tolist(),
        "kept": kept.tolist(),
        "tokens_kept": int(kept.sum()),
        "truncation": reason,
        "entropy": round(float(-np.sum(final * np.log(final + 1e-9))), 4),
        # Greedy would always pick this; sampling only usually does.
        "argmax": labels[int(np.argmax(final))] if labels else "",
    }


#: Fixed next-token logits for "The cat sat on the". Explicitly typed because
#: an untyped literal with mixed value types widens to ``object`` and callers
#: then cannot pass the members to ``sampling_demo`` without a cast.
DEMO_LOGITS: dict[str, Any] = {
    "labels": ["mat", "floor", "chair", "table", "roof", "ground", "sofa", "bed"],
    "logits": [5.2, 4.1, 3.6, 3.4, 1.9, 2.8, 3.1, 2.2],
    "prompt": "The cat sat on the",
}
