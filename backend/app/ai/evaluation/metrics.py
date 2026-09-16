"""RAG and answer evaluation.

Every metric here is computable **offline**. That is the constraint that makes
the Evals Lab work: a player must be able to run an experiment, change one knob,
re-run it, and compare — without a network call, a bill, or a non-deterministic
judge muddying the comparison.

An LLM judge is available (``llm_judge``) and is better at nuance. It is layered
*on top*, never underneath — because an evaluation whose score changes when you
re-run it cannot gate a deploy, and gating a deploy is the only reason
evaluation exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.llm.client import LLMClient
from app.core.logging import get_logger

log = get_logger(__name__)

_WORD_RE = re.compile(r"[a-z0-9_]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

#: Words carrying no discriminative signal. Kept small on purpose — an
#: aggressive stop list would strip terms like "not" that flip meaning.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "from",
        "as",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "you",
        "your",
        "we",
        "our",
        "they",
        "i",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
    ]
)


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


# ══ Retrieval metrics ════════════════════════════════════════════════════════
@dataclass(slots=True)
class RetrievalMetrics:
    precision_at_k: float
    recall_at_k: float
    f1: float
    mrr: float
    ndcg: float
    hit_rate: float
    k: int
    relevant_found: int
    relevant_total: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "precision_at_k": round(self.precision_at_k, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "f1": round(self.f1, 4),
            "mrr": round(self.mrr, 4),
            "ndcg": round(self.ndcg, 4),
            "hit_rate": round(self.hit_rate, 4),
            "k": self.k,
            "relevant_found": self.relevant_found,
            "relevant_total": self.relevant_total,
        }


def retrieval_metrics(retrieved_ids: list[str], relevant_ids: list[str]) -> RetrievalMetrics:
    """Score one query's retrieval against a golden set.

    WHY all six rather than just precision: they disagree in informative ways.
    Precision drops when you raise top-k even if retrieval got *better*; recall
    rises. MRR says "was the right answer near the top", which is what actually
    matters when the context window truncates. nDCG is the only one that cares
    about *order* among the relevant hits.

    Reporting one number here would let a player tune top-k to game it.
    """
    import math

    k = len(retrieved_ids)
    relevant = set(relevant_ids)
    if not relevant:
        return RetrievalMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, k, 0, 0)

    hits = [1 if doc_id in relevant else 0 for doc_id in retrieved_ids]
    found = sum(hits)

    # Precision counts every relevant item retrieved: 4 relevant chunks out of 5
    # returned genuinely is 0.8 precision.
    precision = found / k if k else 0.0

    # Recall must count DISTINCT relevant documents covered, not hits. Retrieved
    # items are chunks and relevant ids are documents, so four chunks from one
    # relevant document is full coverage of that document — counting them
    # separately produced recall above 1.0, which is nonsense.
    covered = len({doc_id for doc_id in retrieved_ids if doc_id in relevant})
    recall = covered / len(relevant)

    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    mrr = 0.0
    for rank, hit in enumerate(hits, start=1):
        if hit:
            mrr = 1.0 / rank
            break

    dcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(hits, start=1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    ndcg = min(1.0, dcg / ideal) if ideal else 0.0

    return RetrievalMetrics(
        precision_at_k=precision,
        recall_at_k=recall,
        f1=f1,
        mrr=mrr,
        ndcg=ndcg,
        hit_rate=1.0 if found else 0.0,
        k=k,
        relevant_found=covered,
        relevant_total=len(relevant),
    )


# ══ Answer metrics ═══════════════════════════════════════════════════════════
@dataclass(slots=True)
class AnswerMetrics:
    faithfulness: float
    answer_relevance: float
    context_relevance: float
    groundedness: float
    #: Sentences with no support in the context — the actual hallucinations.
    unsupported_claims: list[str] = field(default_factory=list)
    refused: bool = False
    cited_sources: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevance": round(self.answer_relevance, 4),
            "context_relevance": round(self.context_relevance, 4),
            "groundedness": round(self.groundedness, 4),
            "unsupported_claims": self.unsupported_claims,
            "refused": self.refused,
            "cited_sources": self.cited_sources,
        }


REFUSAL_MARKERS = (
    "does not contain",
    "not contain that information",
    "cannot answer",
    "no information",
    "not enough context",
    "don't have enough",
    "do not have enough",
    "insufficient context",
)


def answer_metrics(question: str, answer: str, context_chunks: list[str]) -> AnswerMetrics:
    """Score a generated answer against the context it was given.

    **Faithfulness** — is every claim supported by the context?
    **Answer relevance** — does it address the question at all?
    **Context relevance** — was the retrieved context on-topic?
    **Groundedness** — how much of the answer traces back to a source?

    Faithfulness and answer relevance are independent, and that is the subtle
    part players miss: an answer can be perfectly faithful and useless (it
    faithfully repeats an irrelevant chunk), or highly relevant and entirely
    invented.
    """
    context_text = " ".join(context_chunks)
    context_words = _content_words(context_text)
    question_words = _content_words(question)
    answer_sentences = _sentences(answer)

    refused = any(marker in answer.lower() for marker in REFUSAL_MARKERS)
    cited = sorted({int(m) for m in re.findall(r"\[(\d+)\]", answer)})

    if not answer.strip():
        return AnswerMetrics(0.0, 0.0, 0.0, 0.0, refused=False)

    # A correct refusal is maximally faithful: claiming nothing cannot be
    # unsupported. Scoring it as a failure would train the model — and the
    # player — to hallucinate rather than admit ignorance.
    if refused:
        return AnswerMetrics(
            faithfulness=1.0,
            answer_relevance=0.5,
            context_relevance=_overlap(question_words, context_words),
            groundedness=1.0,
            refused=True,
            cited_sources=cited,
        )

    unsupported: list[str] = []
    supported = 0
    for sentence in answer_sentences:
        words = _content_words(sentence)
        if not words:
            continue
        # A sentence counts as supported when most of its content words appear
        # in the context. Crude — it cannot catch a correctly-worded but
        # logically wrong inference — and the Evals Lab says so explicitly when
        # it introduces the LLM judge.
        coverage = len(words & context_words) / len(words)
        if coverage >= 0.6:
            supported += 1
        else:
            unsupported.append(sentence[:200])

    total = supported + len(unsupported)
    faithfulness = supported / total if total else 0.0

    answer_words = _content_words(answer)
    relevance = _overlap(question_words, answer_words)
    context_relevance = _overlap(question_words, context_words)

    # Citations are direct evidence of grounding; without them we fall back to
    # the supported-sentence fraction.
    groundedness = faithfulness
    if cited:
        groundedness = min(1.0, faithfulness + 0.15)

    return AnswerMetrics(
        faithfulness=faithfulness,
        answer_relevance=relevance,
        context_relevance=context_relevance,
        groundedness=groundedness,
        unsupported_claims=unsupported,
        refused=False,
        cited_sources=cited,
    )


def _overlap(a: set[str], b: set[str]) -> float:
    if not a:
        return 0.0
    return min(1.0, len(a & b) / len(a))


def answer_similarity(answer: str, expected: str) -> float:
    """Token-level F1 against a reference answer.

    Deliberately F1 rather than exact match: two correct answers can be worded
    completely differently, and exact match would grade phrasing.
    """
    answer_words = _content_words(answer)
    expected_words = _content_words(expected)
    if not expected_words:
        return 0.0
    if not answer_words:
        return 0.0
    common = len(answer_words & expected_words)
    if not common:
        return 0.0
    precision = common / len(answer_words)
    recall = common / len(expected_words)
    return 2 * precision * recall / (precision + recall)


# ══ LLM-as-judge ═════════════════════════════════════════════════════════════
JUDGE_PROMPT = """You are evaluating an AI assistant's answer.

QUESTION:
{question}

CONTEXT PROVIDED TO THE ASSISTANT:
{context}

ASSISTANT'S ANSWER:
{answer}

{expected_block}
Score each dimension from 0.0 to 1.0 and respond with ONLY a JSON object:

{{
  "faithfulness": <is every claim supported by the context?>,
  "answer_relevance": <does it actually answer the question?>,
  "completeness": <does it cover what the context supports?>,
  "conciseness": <is it free of padding?>,
  "reasoning": "<one sentence>",
  "unsupported_claims": ["<any claim not in the context>"]
}}"""


async def llm_judge(
    llm: LLMClient,
    *,
    question: str,
    answer: str,
    context_chunks: list[str],
    expected: str | None = None,
) -> dict[str, Any]:
    """Judge an answer with a model.

    Returns `graded_by: "mock"` when no provider is configured, so a score is
    never silently presented as authoritative when it came from the offline
    stub. Any evaluation pipeline that hides that distinction is lying to you.
    """
    expected_block = f"REFERENCE ANSWER (for comparison):\n{expected}\n\n" if expected else ""
    prompt = JUDGE_PROMPT.format(
        question=question,
        context="\n---\n".join(context_chunks)[:6000] or "(none)",
        answer=answer,
        expected_block=expected_block,
    )
    data, response = await llm.complete_json(prompt, temperature=0.0, max_tokens=500)

    def _score(key: str) -> float:
        value = data.get(key, 0.0)
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    return {
        "faithfulness": _score("faithfulness"),
        "answer_relevance": _score("answer_relevance"),
        "completeness": _score("completeness"),
        "conciseness": _score("conciseness"),
        "reasoning": str(data.get("reasoning", ""))[:500],
        "unsupported_claims": [str(c)[:200] for c in data.get("unsupported_claims", [])][:5],
        "graded_by": "mock" if response.simulated else response.provider,
        "model": response.model,
    }


# ══ Experiment comparison ════════════════════════════════════════════════════
@dataclass(slots=True)
class EvalCase:
    question: str
    relevant_doc_ids: list[str] = field(default_factory=list)
    expected_answer: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalRunResult:
    name: str
    cases_total: int
    cases_passed: int
    metrics: dict[str, float]
    per_case: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = "hold"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cases_total": self.cases_total,
            "cases_passed": self.cases_passed,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "per_case": self.per_case,
            "verdict": self.verdict,
        }


#: Ship gates. These are *defaults a player can argue with* — the Evals Lab's
#: tier-9 question is "defend this threshold", and there is no universal answer.
SHIP_THRESHOLDS = {
    "faithfulness": 0.85,
    "precision_at_k": 0.70,
    "answer_relevance": 0.60,
}


def decide_verdict(
    metrics: dict[str, float], baseline: dict[str, float] | None = None
) -> tuple[str, list[str]]:
    """Ship / hold / rollback, with the reasons.

    A verdict without reasons is a coin flip with extra steps. Regression
    against a baseline outranks absolute thresholds: a system that got *worse*
    is a rollback even if it still clears the bar, because the next change will
    make it worse again.
    """
    reasons: list[str] = []

    if baseline:
        for key in SHIP_THRESHOLDS:
            if key not in metrics or key not in baseline:
                continue
            delta = metrics[key] - baseline[key]
            if delta < -0.05:
                reasons.append(
                    f"{key} regressed {baseline[key]:.2f} → {metrics[key]:.2f} ({delta:+.2f})"
                )
        if reasons:
            return "rollback", reasons

    failures = [
        f"{key} {metrics[key]:.2f} below the {floor:.2f} gate"
        for key, floor in SHIP_THRESHOLDS.items()
        if key in metrics and metrics[key] < floor
    ]
    if failures:
        return "hold", failures

    improvements = []
    if baseline:
        improvements = [
            f"{key} improved {baseline[key]:.2f} → {metrics[key]:.2f}"
            for key in SHIP_THRESHOLDS
            if key in metrics and key in baseline and metrics[key] - baseline[key] > 0.02
        ]
    return "ship", improvements or ["all gates cleared"]


def aggregate(per_case: list[dict[str, Any]]) -> dict[str, float]:
    """Mean every numeric metric across cases."""
    if not per_case:
        return {}
    keys = {
        k
        for case in per_case
        for k, v in case.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    return {
        key: sum(float(case.get(key, 0.0)) for case in per_case) / len(per_case) for key in keys
    }
