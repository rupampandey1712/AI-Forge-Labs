"""The AI layer: attention, embeddings, chunking, evaluation, agents, mentor.

These are the tests that keep the labs *honest*. An attention visualiser whose
softmax rows do not sum to one is drawing a picture of nothing, and a retrieval
metric that can exceed 1.0 will happily report a configuration as better than
perfect. Both of those were real bugs here, caught by assertions in this file.
"""

from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
import pytest

from app.ai.agents import GraphError, StateGraph, add, append, build_graph, merge, replace
from app.ai.agents.prebuilt import GRAPH_INFO
from app.ai.embeddings import HashingEmbeddings, cosine_similarity, top_k_similar
from app.ai.evaluation import (
    aggregate,
    answer_metrics,
    answer_similarity,
    decide_verdict,
    retrieval_metrics,
)
from app.ai.rag import bm25_scores, chunk_text, reciprocal_rank_fusion
from app.ai.transformer import compute_attention, count_tokens, sampling_demo, softmax, tokenize
from app.ai.tutor import ESCALATION, GeneratedQuestion, escalation_for, validate_generated


# ══ Transformer ══════════════════════════════════════════════════════════════
class TestAttention:
    def test_softmax_rows_are_probability_distributions(self):
        result = compute_attention("The cat sat on the mat")
        for head in result.heads:
            sums = head.weights.sum(axis=-1)
            assert np.allclose(sums, 1.0), "attention rows must sum to 1"
            assert (head.weights >= 0).all(), "attention weights cannot be negative"

    def test_softmax_is_numerically_stable(self):
        """Without max-subtraction a large logit overflows to inf, then nan."""
        result = softmax(np.array([1000.0, 999.0, 998.0]))
        assert not np.isnan(result).any()
        assert math.isclose(float(result.sum()), 1.0, rel_tol=1e-9)

    def test_causal_mask_makes_the_matrix_lower_triangular(self):
        """A token must not be able to attend to its own future."""
        result = compute_attention("one two three four five", causal=True)
        for head in result.heads:
            upper = np.triu(head.weights, k=1)
            assert upper.max() == 0.0, "causal mask leaked attention to future tokens"

    def test_without_causal_mask_attention_is_bidirectional(self):
        result = compute_attention("one two three four five", causal=False)
        assert np.triu(result.heads[0].weights, k=1).max() > 0

    def test_scaling_reduces_saturation(self):
        """The whole reason the paper divides by sqrt(d_k)."""
        text = "the quick brown fox jumps over the lazy dog"
        scaled = compute_attention(text, scaled=True)
        unscaled = compute_attention(text, scaled=False)
        assert unscaled.heads[0].weights.max() > scaled.heads[0].weights.max()

        def mean_entropy(result):
            values = [e for h in result.heads for e in h.entropy()]
            return sum(values) / len(values)

        assert mean_entropy(scaled) > mean_entropy(unscaled), (
            "unscaled attention should be sharper (lower entropy) — that is saturation"
        )

    def test_positional_encoding_distinguishes_repeated_tokens(self):
        """Self-attention is permutation-equivariant; position must be injected."""
        without = compute_attention("the cat the cat", use_positional=False)
        with_pe = compute_attention("the cat the cat", use_positional=True)
        assert np.allclose(without.combined[0], without.combined[2]), (
            "without positional encoding, identical tokens must be identical"
        )
        assert not np.allclose(with_pe.combined[0], with_pe.combined[2])

    def test_positional_encoding_matches_the_paper(self):
        from app.ai.transformer import positional_encoding

        pe = positional_encoding(10, 64)
        assert pe.shape == (10, 64)
        assert np.allclose(pe[0, 0::2], 0.0), "sin(0) must be 0 at every even index"
        assert np.allclose(pe[0, 1::2], 1.0), "cos(0) must be 1 at every odd index"
        assert (pe >= -1.0).all() and (pe <= 1.0).all()

    def test_serialises_without_numpy_truthiness_errors(self):
        """`array or default` raises 'truth value is ambiguous'. It shipped once."""
        for kwargs in ({}, {"causal": True}, {"use_positional": False}, {"scaled": False}):
            payload = compute_attention("the cat sat", **kwargs).to_dict()
            assert payload["vectors"]["embedding"]
            assert isinstance(payload["heads"][0]["weights"][0][0], float)

    def test_empty_input_does_not_crash(self):
        result = compute_attention("")
        assert result.tokens == []
        assert result.to_dict()["tokens"] == []

    @pytest.mark.parametrize("heads", [1, 2, 4, 8])
    def test_head_dimensions_partition_the_model(self, heads):
        result = compute_attention("the cat sat on the mat", d_model=64, n_heads=heads)
        assert result.d_head * heads == 64


class TestTokenization:
    def test_token_count_exceeds_word_count(self):
        """The lesson: people budget context in words and run out of tokens."""
        stats = count_tokens("Implement a decorator preserving function metadata")
        assert stats["tokens"] >= stats["words"]

    def test_long_unknown_words_split(self):
        tokens = tokenize("supercalifragilistic")
        assert len(tokens) > 1
        assert any(t.is_subword for t in tokens)

    def test_short_words_stay_whole(self):
        assert len(tokenize("the cat sat")) == 3

    def test_tokenization_is_deterministic(self):
        a = [t.id for t in tokenize("the same text")]
        b = [t.id for t in tokenize("the same text")]
        assert a == b


class TestSampling:
    def test_low_temperature_collapses_the_distribution(self):
        cold = sampling_demo([5.0, 4.0, 3.0], ["a", "b", "c"], temperature=0.05)
        hot = sampling_demo([5.0, 4.0, 3.0], ["a", "b", "c"], temperature=2.0)
        assert cold["entropy"] < hot["entropy"]
        assert cold["final_probabilities"][0] > 0.99

    def test_probabilities_always_sum_to_one(self):
        """Renormalisation after truncation must restore a valid distribution.

        The payload is rounded to 4dp for the wire (the visualiser renders
        percentages, not float64), so the tolerance here is the rounding error
        of five summed terms — 5e-4 — not float epsilon. A tighter tolerance
        tests numpy's rounding, not our maths.
        """
        for temperature in (0.1, 0.5, 1.0, 2.0):
            for top_k in (None, 2):
                for top_p in (None, 0.5, 0.9):
                    result = sampling_demo(
                        [5.0, 4.0, 3.0, 2.0, 1.0],
                        list("abcde"),
                        temperature=temperature,
                        top_k=top_k,
                        top_p=top_p,
                    )
                    total = sum(result["final_probabilities"])
                    assert math.isclose(total, 1.0, abs_tol=5e-4), (
                        f"T={temperature} k={top_k} p={top_p} summed to {total}"
                    )

    def test_top_k_truncates(self):
        result = sampling_demo([5.0, 4.0, 3.0, 2.0, 1.0], list("abcde"), top_k=2)
        assert result["tokens_kept"] == 2
        assert sum(1 for p in result["final_probabilities"] if p > 0) == 2

    def test_top_p_keeps_the_token_that_crosses_the_threshold(self):
        """Off-by-one here would keep nothing when the top token exceeds p."""
        result = sampling_demo([10.0, 1.0, 1.0], list("abc"), top_p=0.5)
        assert result["tokens_kept"] >= 1


# ══ Embeddings ═══════════════════════════════════════════════════════════════
class TestEmbeddings:
    async def test_vectors_are_normalised(self):
        result = await HashingEmbeddings().embed(["hello world", "another document"])
        for vector in result.vectors:
            assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)

    async def test_deterministic(self):
        embedder = HashingEmbeddings()
        first = await embedder.embed(["identical text"])
        second = await embedder.embed(["identical text"])
        assert first.vectors == second.vectors

    async def test_related_text_scores_higher_than_unrelated(self):
        result = await HashingEmbeddings().embed(
            [
                "generators produce values lazily with yield",
                "a generator yields values one at a time",
                "kubernetes schedules containers across nodes",
            ]
        )
        related = cosine_similarity(result.vectors[0], result.vectors[1])
        unrelated = cosine_similarity(result.vectors[0], result.vectors[2])
        assert related > unrelated

    def test_cosine_handles_degenerate_input(self):
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_cosine_of_identical_vectors_is_one(self):
        vector = [0.6, 0.8]
        assert math.isclose(cosine_similarity(vector, vector), 1.0, rel_tol=1e-9)

    def test_top_k_is_ordered(self):
        query = [1.0, 0.0]
        candidates = [("a", [1.0, 0.0]), ("b", [0.0, 1.0]), ("c", [0.7, 0.7])]
        ranked = top_k_similar(query, candidates, k=3)
        assert [item for item, _ in ranked] == ["a", "c", "b"]


# ══ Chunking and retrieval ═══════════════════════════════════════════════════
class TestChunking:
    def test_chunks_respect_the_size_budget_approximately(self):
        text = ". ".join(f"Sentence number {i} with some filler content" for i in range(40))
        for size in (150, 400, 800):
            chunks = chunk_text(text, chunk_size=size, overlap=0)
            assert chunks
            # Structure-aware splitting will not break a unit, so a chunk can
            # slightly exceed the budget — but never wildly.
            assert max(len(c.text) for c in chunks) <= size * 1.6

    def test_smaller_chunks_produce_more_of_them(self):
        text = ". ".join(f"Sentence {i} of the document" for i in range(60))
        assert len(chunk_text(text, chunk_size=100)) > len(chunk_text(text, chunk_size=600))

    def test_overlap_duplicates_content(self):
        text = ". ".join(f"Sentence {i} with content" for i in range(40))
        none = sum(len(c.text) for c in chunk_text(text, chunk_size=200, overlap=0))
        some = sum(len(c.text) for c in chunk_text(text, chunk_size=200, overlap=80))
        assert some > none, "overlap must duplicate text — that is its cost"

    def test_empty_and_whitespace_input(self):
        assert chunk_text("") == []
        assert chunk_text("   \n  ") == []

    def test_chunk_indices_are_sequential(self):
        chunks = chunk_text(". ".join(f"S{i}" for i in range(50)), chunk_size=80)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_fixed_window_mode_ignores_structure(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        structured = chunk_text(text, chunk_size=20, respect_structure=True)
        fixed = chunk_text(text, chunk_size=20, respect_structure=False)
        assert structured != fixed


class TestLexicalRetrieval:
    def test_bm25_ranks_the_matching_document_first(self):
        docs = [
            "The reset link expires after 15 minutes",
            "Containers isolate processes using namespaces",
            "Mastery is capped by the deepest tier cleared",
        ]
        scores = bm25_scores("how long until the reset link expires", docs)
        assert scores.index(max(scores)) == 0

    def test_bm25_handles_no_overlap(self):
        assert bm25_scores("zzz qqq", ["completely different text"]) == [0.0]

    def test_bm25_handles_empty_input(self):
        assert bm25_scores("", ["a doc"]) == [0.0]
        assert bm25_scores("query", []) == []

    def test_rrf_rewards_agreement_between_rankings(self):
        """A document both rankings like should beat one only a single ranking does."""
        fused = reciprocal_rank_fusion([[0, 1, 2], [0, 2, 1]])
        assert fused[0] > fused[2] > fused[1] or fused[0] > fused[1]
        assert fused[0] == max(fused.values())


# ══ Evaluation ═══════════════════════════════════════════════════════════════
class TestRetrievalMetrics:
    @pytest.mark.parametrize(
        "retrieved,relevant",
        [
            (["a", "b", "c"], ["a"]),
            (["a", "a", "a", "a"], ["a"]),
            (["a", "b"], ["a", "b", "c"]),
            (["x"], ["a"]),
            ([], ["a"]),
            (["a"], []),
        ],
    )
    def test_every_metric_stays_within_bounds(self, retrieved, relevant):
        """Recall above 1.0 shipped once: multiple chunks from one relevant
        document were each counted as a separate hit."""
        m = retrieval_metrics(retrieved, relevant)
        for name, value in m.to_dict().items():
            if name in ("k", "relevant_found", "relevant_total"):
                continue
            assert 0.0 <= value <= 1.0, f"{name}={value} is out of bounds"

    def test_many_chunks_from_one_document_is_full_recall_not_more(self):
        m = retrieval_metrics(["sec", "sec", "sec", "sec"], ["sec"])
        assert m.recall_at_k == 1.0
        assert m.precision_at_k == 1.0
        assert m.relevant_found == 1

    def test_mrr_reflects_the_rank_of_the_first_hit(self):
        assert retrieval_metrics(["a", "x", "y"], ["a"]).mrr == 1.0
        assert retrieval_metrics(["x", "a", "y"], ["a"]).mrr == 0.5
        assert retrieval_metrics(["x", "y", "z"], ["a"]).mrr == 0.0

    def test_ndcg_rewards_better_ordering(self):
        good = retrieval_metrics(["a", "b", "x", "y"], ["a", "b"])
        bad = retrieval_metrics(["x", "y", "a", "b"], ["a", "b"])
        assert good.ndcg > bad.ndcg


class TestAnswerMetrics:
    CONTEXT: ClassVar[list[str]] = [
        "The password reset link expires after 15 minutes for security reasons."
    ]

    def test_grounded_answer_scores_high(self):
        m = answer_metrics(
            "How long is the reset link valid?",
            "The reset link expires after 15 minutes. [1]",
            self.CONTEXT,
        )
        assert m.faithfulness >= 0.9
        assert m.cited_sources == [1]
        assert not m.unsupported_claims

    def test_hallucination_is_detected(self):
        m = answer_metrics(
            "How long is the reset link valid?",
            "The link never expires and remains valid indefinitely across devices.",
            self.CONTEXT,
        )
        assert m.faithfulness < 0.5
        assert m.unsupported_claims

    def test_correct_refusal_is_maximally_faithful(self):
        """Scoring a refusal as failure would train the system to hallucinate."""
        m = answer_metrics(
            "What is the CEO's salary?",
            "The provided context does not contain that information.",
            self.CONTEXT,
        )
        assert m.refused
        assert m.faithfulness == 1.0

    def test_empty_answer_scores_zero(self):
        assert answer_metrics("q", "", self.CONTEXT).faithfulness == 0.0

    def test_answer_similarity_is_order_independent(self):
        a = answer_similarity("expires after fifteen minutes", "fifteen minutes expiry")
        b = answer_similarity("completely unrelated wording here", "fifteen minutes expiry")
        assert a > b


class TestVerdicts:
    def test_clearing_every_gate_ships(self):
        verdict, _ = decide_verdict(
            {"faithfulness": 0.9, "precision_at_k": 0.8, "answer_relevance": 0.7}
        )
        assert verdict == "ship"

    def test_failing_a_gate_holds_and_says_which(self):
        verdict, reasons = decide_verdict(
            {"faithfulness": 0.5, "precision_at_k": 0.8, "answer_relevance": 0.7}
        )
        assert verdict == "hold"
        assert any("faithfulness" in r for r in reasons)

    def test_regression_rolls_back_even_when_gates_pass(self):
        """A system that got worse is a rollback; the next change makes it worse again."""
        verdict, reasons = decide_verdict(
            {"faithfulness": 0.86, "precision_at_k": 0.75, "answer_relevance": 0.65},
            baseline={"faithfulness": 0.96, "precision_at_k": 0.75, "answer_relevance": 0.65},
        )
        assert verdict == "rollback"
        assert any("regressed" in r for r in reasons)

    def test_a_verdict_always_carries_reasons(self):
        for metrics in (
            {"faithfulness": 0.9, "precision_at_k": 0.8, "answer_relevance": 0.7},
            {"faithfulness": 0.1, "precision_at_k": 0.1, "answer_relevance": 0.1},
        ):
            _, reasons = decide_verdict(metrics)
            assert reasons, "a verdict without reasons is a coin flip with extra steps"

    def test_aggregate_means_numeric_keys_only(self):
        result = aggregate([{"a": 1.0, "b": "x"}, {"a": 3.0, "b": "y"}])
        assert result == {"a": 2.0}


# ══ Agent graphs ═════════════════════════════════════════════════════════════
class TestReducers:
    def test_append_accumulates_rather_than_clobbers(self):
        """Getting this wrong presents as 'the agent forgot everything'."""
        assert append(None, "a") == ["a"]
        assert append(["a"], "b") == ["a", "b"]
        assert append(["a"], ["b", "c"]) == ["a", "b", "c"]

    def test_add_accumulates_tokens(self):
        assert add(None, 5) == 5
        assert add(10, 5) == 15

    def test_merge_and_replace(self):
        assert merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
        assert replace("old", "new") == "new"


class TestGraphConstruction:
    def test_dangling_node_is_rejected(self):
        """A node with no outgoing edge silently ends the run — almost never intended."""
        graph = StateGraph().add_node("a", lambda s: {}).set_entry_point("a")
        with pytest.raises(GraphError, match="no outgoing edge"):
            graph.compile()

    def test_edge_to_unknown_target_is_rejected(self):
        graph = StateGraph().add_node("a", lambda s: {}).add_edge("a", "ghost").set_entry_point("a")
        with pytest.raises(GraphError, match="unknown target"):
            graph.compile()

    def test_unreachable_node_is_rejected(self):
        from app.ai.agents import END

        graph = (
            StateGraph()
            .add_node("a", lambda s: {})
            .add_node("orphan", lambda s: {})
            .add_edge("a", END)
            .add_edge("orphan", END)
            .set_entry_point("a")
        )
        with pytest.raises(GraphError, match="unreachable"):
            graph.compile()

    def test_a_node_cannot_have_both_edge_kinds(self):
        from app.ai.agents import END

        graph = StateGraph().add_node("a", lambda s: {}).add_edge("a", END)
        with pytest.raises(GraphError):
            graph.add_conditional_edges("a", lambda s: "x", {"x": END})

    def test_duplicate_node_is_rejected(self):
        graph = StateGraph().add_node("a", lambda s: {})
        with pytest.raises(GraphError, match="duplicate"):
            graph.add_node("a", lambda s: {})


class TestGraphExecution:
    async def test_runs_to_end_and_records_every_step(self):
        from app.ai.agents import END

        graph = (
            StateGraph(reducers={"log": append})
            .add_node("one", lambda s: {"log": "one", "value": 1})
            .add_node("two", lambda s: {"log": "two", "value": 2})
            .add_edge("one", "two")
            .add_edge("two", END)
            .set_entry_point("one")
            .compile()
        )
        run = await graph.run({})
        assert run.status == "completed"
        assert run.final_state["log"] == ["one", "two"]
        assert run.final_state["value"] == 2
        assert [r.node for r in run.history] == ["one", "two"]
        assert all(r.state_diff for r in run.history)

    async def test_recursion_limit_halts_a_runaway_loop(self):
        from app.ai.agents import END

        graph = (
            StateGraph()
            .add_node("spin", lambda s: {"n": s.get("n", 0) + 1})
            .add_conditional_edges("spin", lambda s: "again", {"again": "spin", "done": END})
            .set_entry_point("spin")
            .compile()
        )
        run = await graph.run({}, recursion_limit=7)
        assert run.status == "halted"
        assert run.steps == 7
        assert run.looped
        assert "recursion limit" in (run.halted_reason or "").lower()
        assert run.node_visits["spin"] == 7

    async def test_a_failing_node_stops_cleanly_with_history(self):
        from app.ai.agents import END

        def explode(_state):
            raise ValueError("node blew up")

        graph = (
            StateGraph()
            .add_node("ok", lambda s: {"a": 1})
            .add_node("bad", explode)
            .add_edge("ok", "bad")
            .add_edge("bad", END)
            .set_entry_point("ok")
            .compile()
        )
        run = await graph.run({})
        assert run.status == "error"
        assert "ValueError" in (run.halted_reason or "")
        assert len(run.history) == 2, "history must survive the failure"

    async def test_interrupt_pauses_before_the_node(self):
        from app.ai.agents import END

        graph = (
            StateGraph()
            .add_node("first", lambda s: {"a": 1})
            .add_node("gated", lambda s: {"b": 2}, interrupt_before=True)
            .add_edge("first", "gated")
            .add_edge("gated", END)
            .set_entry_point("first")
            .compile()
        )
        run = await graph.run({})
        assert run.status == "interrupted"
        assert run.interrupted_at == "gated"
        assert "b" not in run.final_state, "the gated node must not have executed"

    async def test_unmapped_router_label_ends_cleanly_and_says_why(self):
        from app.ai.agents import END

        graph = (
            StateGraph()
            .add_node("a", lambda s: {})
            .add_conditional_edges("a", lambda s: "typo", {"real": END})
            .set_entry_point("a")
            .compile()
        )
        run = await graph.run({})
        assert run.status == "completed"
        assert "unmapped" in (run.history[0].edge_reason or "")


class TestPrebuiltGraphs:
    @pytest.mark.parametrize("slug", list(GRAPH_INFO))
    def test_every_graph_compiles_and_is_inspectable(self, slug):
        graph = build_graph(slug)
        diagram = graph.to_diagram()
        assert diagram["entry"]
        assert len(diagram["nodes"]) >= 3
        assert diagram["edges"]

    def test_the_runaway_graph_has_a_cycle_and_is_labelled_broken(self):
        assert GRAPH_INFO["runaway_agent"]["broken"] is True
        assert build_graph("runaway_agent").find_cycles()

    def test_the_support_graph_has_no_cycle(self):
        assert build_graph("support_agent").find_cycles() == []

    async def test_runaway_halts_while_reflection_completes(self):
        """Nearly identical topology; the difference is a counter the router reads."""
        runaway = await build_graph("runaway_agent").run({"question": "x"}, recursion_limit=10)
        reflection = await build_graph("reflection_agent").run(
            {"question": "x"}, recursion_limit=25
        )
        assert runaway.status == "halted"
        assert reflection.status == "completed"

    async def test_support_agent_escalates_without_context(self):
        """No retrieved context must cap confidence — a fluent answer from
        nothing is the dangerous case."""
        run = await build_graph("support_agent").run({"question": "billing issue"})
        assert run.status == "interrupted"
        assert run.interrupted_at == "escalate"

    def test_unknown_graph_raises(self):
        with pytest.raises(KeyError):
            build_graph("does_not_exist")


# ══ Mentor and content generation ════════════════════════════════════════════
class TestMentorEscalation:
    def test_first_attempt_only_earns_a_nudge(self):
        """Handing over the answer at attempt one makes the tool useless."""
        assert escalation_for(0, 0) == "nudge"
        assert escalation_for(1, 0) == "nudge"

    def test_escalation_is_monotonic(self):
        levels = [ESCALATION.index(escalation_for(a, a // 2)) for a in range(0, 12)]
        assert levels == sorted(levels)

    def test_full_help_is_reachable(self):
        assert escalation_for(20, 10) == "full"

    def test_hints_used_outranks_attempts(self):
        assert ESCALATION.index(escalation_for(0, 3)) > ESCALATION.index(escalation_for(3, 0))


class TestGeneratedContentValidation:
    """Generated content is held to the same bar as hand-authored content."""

    def test_mcq_with_two_correct_options_is_rejected(self):
        question = GeneratedQuestion(
            prompt="Which of these statements about decorators is accurate?",
            kind="mcq",
            tier=3,
            options=[
                {"id": "a", "text": "one", "correct": True, "why": "yes"},
                {"id": "b", "text": "two", "correct": True, "why": "also yes"},
                {"id": "c", "text": "three", "correct": False, "why": "no"},
            ],
            ideal_senior_answer="A decorator replaces a function.",
            hints=["one", "two"],
        )
        assert any("more than one correct" in i for i in validate_generated(question))

    def test_options_without_explanations_are_rejected(self):
        question = GeneratedQuestion(
            prompt="Which of these statements about generators is accurate?",
            kind="mcq",
            tier=3,
            options=[
                {"id": "a", "text": "one", "correct": True, "why": "because"},
                {"id": "b", "text": "two", "correct": False, "why": ""},
                {"id": "c", "text": "three", "correct": False, "why": ""},
            ],
            ideal_senior_answer="Generators are lazy.",
            hints=["one", "two"],
        )
        assert any("no explanation" in i for i in validate_generated(question))

    def test_rubric_its_own_ideal_answer_fails_is_rejected(self):
        """The most important check: an unscoreable question is worse than none."""
        question = GeneratedQuestion(
            prompt="Explain why the GIL prevents parallel bytecode execution in CPython.",
            kind="explain",
            tier=6,
            ideal_senior_answer="Threads take turns.",
            rubric=[
                {
                    "point": "Mentions reference counting",
                    "keywords": ["reference counting", "refcount"],
                    "weight": 3.0,
                }
            ],
            hints=["a hint here", "another hint"],
        )
        assert any("against its own rubric" in i for i in validate_generated(question))

    def test_free_text_without_a_rubric_is_rejected(self):
        question = GeneratedQuestion(
            prompt="Explain the difference between a list and a tuple in Python.",
            kind="explain",
            tier=3,
            ideal_senior_answer="Tuples are immutable and hashable.",
            hints=["one", "two"],
        )
        assert any("no rubric" in i for i in validate_generated(question))

    def test_a_well_formed_question_passes(self):
        question = GeneratedQuestion(
            prompt="Why does a mutable default argument leak state between calls?",
            kind="explain",
            tier=4,
            ideal_senior_answer=(
                "Default arguments are evaluated once, when the def statement executes, so "
                "the same list object is shared by every call that relies on the default."
            ),
            rubric=[
                {
                    "point": "Evaluated once at definition",
                    "keywords": ["once", "def"],
                    "weight": 3.0,
                },
                {"point": "Shared object", "keywords": ["shared", "same list"], "weight": 2.0},
            ],
            hints=["When is the default evaluated?", "Inspect __defaults__ after two calls."],
        )
        assert validate_generated(question) == []
        assert question.is_usable
