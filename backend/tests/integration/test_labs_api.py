"""The labs over HTTP.

These are instrument endpoints, so the thing worth testing is not "did it return
200" but "did it return the intermediates the visualiser needs, and are the
claims the UI prints in prose actually true of the numbers". A heatmap whose
causal mask leaks, or a reranker that never reports a rank change, renders
perfectly and teaches something false.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


class TestTransformerLab:
    async def test_causal_mask_zeroes_the_upper_triangle(self, seeded_client, api, auth_headers):
        """The lab tells the player the black wedge is exactly zero. It must be."""
        response = await seeded_client.post(
            f"{api}/labs/transformer/attention",
            headers=auth_headers,
            json={"text": "one two three four", "causal": True},
        )
        assert response.status_code == 200, response.text
        for head in response.json()["heads"]:
            weights = head["weights"]
            leaked = [
                weights[i][j]
                for i in range(len(weights))
                for j in range(i + 1, len(weights))
                if weights[i][j] != 0.0
            ]
            assert not leaked, f"causal mask leaked {leaked}"

    async def test_rows_are_probability_distributions(self, seeded_client, api, auth_headers):
        response = await seeded_client.post(
            f"{api}/labs/transformer/attention",
            headers=auth_headers,
            json={"text": "the cat sat on the mat"},
        )
        for head in response.json()["heads"]:
            for row in head["weights"]:
                assert abs(sum(row) - 1.0) < 5e-3, f"row summed to {sum(row)}"

    async def test_without_positional_encoding_repeated_tokens_are_identical(
        self, seeded_client, api, auth_headers
    ):
        """The lab's central claim about positional encoding, asserted.

        Self-attention is permutation-equivariant: with no position signal, the
        two occurrences of "the" must produce byte-identical vectors. If they
        ever differ, position is leaking in from somewhere and the toggle is
        demonstrating nothing.
        """
        response = await seeded_client.post(
            f"{api}/labs/transformer/attention",
            headers=auth_headers,
            json={"text": "the cat the cat", "use_positional": False},
        )
        vectors = response.json()["vectors"]["combined"]
        assert vectors[0] == vectors[2]
        assert vectors[1] == vectors[3]

    async def test_the_visualiser_gets_every_field_it_renders(
        self, seeded_client, api, auth_headers
    ):
        """Guards the exact drift that a 200 response hides.

        Three of these field names were wrong on the first frontend pass, and
        nothing failed — the panels simply rendered `undefined`.
        """
        response = await seeded_client.post(
            f"{api}/labs/transformer/attention", headers=auth_headers, json={"text": "a b c"}
        )
        body = response.json()
        assert {"tokens", "heads", "vectors", "insight", "d_head"} <= body.keys()
        assert {"weights", "raw_scores", "entropy", "argmax"} <= body["heads"][0].keys()
        assert {"embedding", "positional", "combined", "shown_dimensions"} <= body["vectors"].keys()

        tokens = await seeded_client.post(
            f"{api}/labs/transformer/tokenize",
            headers=auth_headers,
            json={"text": "supercalifragilistic retry decorator"},
        )
        stats = tokens.json()["stats"]
        assert {
            "tokens",
            "words",
            "tokens_per_word",
            "chars_per_token",
            "subword_splits",
        } <= stats.keys()
        estimate = tokens.json()["cost_estimates"][0]
        assert {"model", "cost_per_request", "input_cost_per_1m_requests"} <= estimate.keys()

    async def test_truncation_renormalises_to_a_valid_distribution(
        self, seeded_client, api, auth_headers
    ):
        response = await seeded_client.post(
            f"{api}/labs/transformer/sampling",
            headers=auth_headers,
            json={"temperature": 0.8, "top_p": 0.6},
        )
        body = response.json()
        assert abs(sum(body["final_probabilities"]) - 1.0) < 5e-3
        assert body["tokens_kept"] == sum(body["kept"])


class TestRAGBench:
    async def test_every_metric_the_ui_prints_is_a_proportion(
        self, seeded_client, api, auth_headers
    ):
        """recall@k above 1.0 shipped once. The bench prints these raw."""
        response = await seeded_client.post(
            f"{api}/labs/rag/query",
            headers=auth_headers,
            json={
                "question": "How long is a password reset link valid?",
                "config": {"top_k": 5, "use_hybrid": True, "use_reranker": True},
                "relevant_doc_ids": ["forge-security-policy"],
            },
        )
        assert response.status_code == 200, response.text
        counts = {"k", "relevant_found", "relevant_total"}
        for name, value in response.json()["metrics"].items():
            if name in counts:
                continue
            assert 0.0 <= value <= 1.0, f"{name}={value}"

    async def test_reranking_reports_where_each_chunk_started(
        self, seeded_client, api, auth_headers
    ):
        """The ↑/↓ chip is the reranker's whole visible value.

        Without `original_rank` the player cannot tell whether reranking changed
        anything, which makes the toggle unfalsifiable.
        """
        response = await seeded_client.post(
            f"{api}/labs/rag/query",
            headers=auth_headers,
            json={
                "question": "What happens when a refresh token is reused?",
                "config": {"top_k": 5, "use_reranker": True},
            },
        )
        retrieved = response.json()["retrieved"]
        assert any(chunk["original_rank"] is not None for chunk in retrieved)
        assert all(chunk["rerank_score"] is not None for chunk in retrieved)

    async def test_stage_timings_cover_the_whole_pipeline(self, seeded_client, api, auth_headers):
        response = await seeded_client.post(
            f"{api}/labs/rag/query",
            headers=auth_headers,
            json={"question": "Why is player code run in a separate process?"},
        )
        body = response.json()
        names = [stage["name"] for stage in body["stages"]]
        assert "generate" in names, "the timeline would be missing its most expensive bar"
        assert sum(stage["duration_ms"] for stage in body["stages"]) <= body["total_ms"] + 1.0

    async def test_the_golden_set_contains_an_unanswerable_case(
        self, seeded_client, api, auth_headers
    ):
        """A RAG eval set with no refusal case cannot detect confident invention."""
        response = await seeded_client.get(f"{api}/labs/rag/golden-set", headers=auth_headers)
        cases = response.json()
        assert any(not case["relevant"] for case in cases)


class TestAgentFactory:
    async def test_every_edge_points_at_a_node_that_exists(self, seeded_client, api, auth_headers):
        """A dangling edge is silently dropped by the renderer, not reported."""
        for slug in ("support_agent", "reflection_agent", "runaway_agent", "tool_agent"):
            diagram = (
                await seeded_client.get(f"{api}/labs/agents/{slug}", headers=auth_headers)
            ).json()
            ids = {node["id"] for node in diagram["nodes"]}
            for edge in diagram["edges"]:
                assert edge["source"] in ids, f"{slug}: edge from unknown '{edge['source']}'"
                assert edge["target"] in ids, f"{slug}: edge to unknown '{edge['target']}'"
            assert diagram["entry"] in ids, f"{slug}: entry node is not in the node list"

    async def test_the_broken_graph_halts_and_explains_itself(
        self, seeded_client, api, auth_headers
    ):
        """`runaway_agent` exists to be debugged. If it ever completes, the whole
        lesson about termination conditions silently disappears."""
        response = await seeded_client.post(
            f"{api}/labs/agents/run",
            headers=auth_headers,
            json={"graph": "runaway_agent", "question": "solve it", "recursion_limit": 10},
        )
        body = response.json()
        assert body["status"] == "halted"
        assert body["looped"] is True
        assert max(body["node_visits"].values()) > 2
        assert body["diagnosis"], "a halt with no diagnosis teaches nothing"

    async def test_the_bounded_loop_terminates_where_the_runaway_does_not(
        self, seeded_client, api, auth_headers
    ):
        """The comparison is the lesson: same shape, one has a counter."""
        response = await seeded_client.post(
            f"{api}/labs/agents/run",
            headers=auth_headers,
            json={
                "graph": "reflection_agent",
                "question": "explain decorators",
                "recursion_limit": 25,
            },
        )
        assert response.json()["status"] == "completed"

    async def test_every_replayed_step_maps_onto_the_diagram(
        self, seeded_client, api, auth_headers
    ):
        """The replay highlights nodes by id. An id not in the diagram highlights
        nothing, and the graph just sits there looking broken."""
        diagram = (
            await seeded_client.get(f"{api}/labs/agents/support_agent", headers=auth_headers)
        ).json()
        ids = {node["id"] for node in diagram["nodes"]}
        run = (
            await seeded_client.post(
                f"{api}/labs/agents/run",
                headers=auth_headers,
                json={"graph": "support_agent", "question": "I was charged twice"},
            )
        ).json()
        assert run["history"], "nothing to replay"
        for step in run["history"]:
            assert step["node"] in ids, f"replay references unknown node '{step['node']}'"


class TestHumanInTheLoop:
    """The interrupt is only a lesson if approving actually resumes the graph."""

    async def _interrupted_run(self, client, api, headers) -> dict:
        run = (
            await client.post(
                f"{api}/labs/agents/run",
                headers=headers,
                json={"graph": "support_agent", "question": "I was charged twice"},
            )
        ).json()
        assert run["status"] == "interrupted", "support_agent should pause before escalating"
        assert run["run_id"], "a paused run with no id cannot be resumed from the UI"
        return run

    async def test_approval_executes_the_steps_the_gate_was_holding_back(
        self, seeded_client, api, auth_headers
    ):
        """This shipped as a no-op once: approving recorded a decision and ran
        nothing, which demonstrates a confirmation dialog rather than durable
        state resumed from a checkpoint."""
        run = await self._interrupted_run(seeded_client, api, auth_headers)
        before = len(run["history"])

        response = await seeded_client.post(
            f"{api}/labs/agents/resume",
            headers=auth_headers,
            json={"run_id": run["run_id"], "approved": True, "note": "Refund approved"},
        )
        assert response.status_code == 200, response.text
        resumed = response.json()

        assert len(resumed["history"]) > before, "approval ran no further steps"
        assert any(step["node"] == run["interrupted_at"] for step in resumed["history"]), (
            "the node the graph paused before never executed"
        )
        assert resumed["status"] in {"completed", "interrupted"}
        assert resumed["final_state"]["human_decision"] == "approved"
        assert resumed["final_state"]["human_note"] == "Refund approved"

    async def test_the_merged_history_is_one_contiguous_sequence(
        self, seeded_client, api, auth_headers
    ):
        """The replay scrubber indexes the array while the label shows `step`.
        A gap between them puts the two out of sync mid-trace."""
        run = await self._interrupted_run(seeded_client, api, auth_headers)
        resumed = (
            await seeded_client.post(
                f"{api}/labs/agents/resume",
                headers=auth_headers,
                json={"run_id": run["run_id"], "approved": True},
            )
        ).json()
        steps = [step["step"] for step in resumed["history"]]
        assert steps == list(range(len(steps))), f"non-contiguous step numbers: {steps}"

    async def test_rejection_is_terminal_and_runs_nothing(self, seeded_client, api, auth_headers):
        """Rejecting is the outcome the checkpoint exists to make possible, so
        it must not be modelled as an error — and must not execute the node."""
        run = await self._interrupted_run(seeded_client, api, auth_headers)
        before = len(run["history"])
        resumed = (
            await seeded_client.post(
                f"{api}/labs/agents/resume",
                headers=auth_headers,
                json={"run_id": run["run_id"], "approved": False, "note": "Not warranted"},
            )
        ).json()
        assert resumed["status"] == "rejected"
        assert len(resumed["history"]) == before
        assert resumed["final_state"]["human_decision"] == "rejected"
        assert resumed["diagnosis"]

    async def test_a_run_can_only_be_resolved_once(self, seeded_client, api, auth_headers):
        run = await self._interrupted_run(seeded_client, api, auth_headers)
        first = await seeded_client.post(
            f"{api}/labs/agents/resume",
            headers=auth_headers,
            json={"run_id": run["run_id"], "approved": True},
        )
        assert first.status_code == 200
        second = await seeded_client.post(
            f"{api}/labs/agents/resume",
            headers=auth_headers,
            json={"run_id": run["run_id"], "approved": True},
        )
        assert second.status_code == 422, "a resolved run must not be re-approvable"


class TestMentor:
    async def test_help_escalates_with_effort_not_with_asking(
        self, seeded_client, api, auth_headers
    ):
        """Asking the same question repeatedly must not climb the ladder; only
        demonstrated effort does. The ladder UI lights a rung by name, so the
        level must also be one the frontend knows about."""
        ladder = ["nudge", "hint", "concept", "partial", "full"]
        levels = []
        for attempts, hints in ((0, 0), (2, 1), (6, 4)):
            response = await seeded_client.post(
                f"{api}/labs/mentor/ask",
                headers=auth_headers,
                json={
                    "question": "My decorator broke request validation",
                    "tier": 6,
                    "attempts": attempts,
                    "hints_used": hints,
                },
            )
            assert response.status_code == 200, response.text
            levels.append(response.json()["level"])

        assert all(level in ladder for level in levels), levels
        assert ladder.index(levels[0]) < ladder.index(levels[-1]), (
            f"no escalation across effort: {levels}"
        )

    async def test_generated_questions_always_state_why_they_were_rejected(
        self, seeded_client, api, auth_headers
    ):
        """The panel's honesty depends on this: a rejected question with an empty
        `issues` list renders as rejected for no stated reason."""
        concepts = (await seeded_client.get(f"{api}/concepts?page_size=1")).json()
        slug = concepts["items"][0]["slug"]
        response = await seeded_client.post(
            f"{api}/labs/mentor/generate",
            headers=auth_headers,
            json={"concept_slug": slug, "tier": 5, "kind": "explain", "count": 2},
        )
        body = response.json()
        assert body["accepted"] + body["rejected"] == len(body["generated"])
        for question in body["generated"]:
            if not question["is_usable"]:
                assert question["issues"], "rejected with no reason given"


class TestEvaluationLab:
    async def test_a_verdict_is_always_one_the_ui_can_render(
        self, seeded_client, api, auth_headers
    ):
        """VerdictCard maps exactly three values; anything else falls through to
        an unstyled default that looks like a bug."""
        response = await seeded_client.post(
            f"{api}/labs/evals/run",
            headers=auth_headers,
            json={"name": "k=1", "config": {"top_k": 1}, "use_golden_set": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verdict"] in {"ship", "hold", "rollback"}
        assert body["reasons"], "a verdict with no reasoning is just a number"
        assert body["cases_total"] == len(body["per_case"])
        assert 0 <= body["cases_passed"] <= body["cases_total"]

    async def test_comparing_against_a_baseline_returns_it(self, seeded_client, api, auth_headers):
        """The delta arrows read from `baseline`; without it they never render."""
        first = (
            await seeded_client.post(
                f"{api}/labs/evals/run",
                headers=auth_headers,
                json={"name": "wide", "config": {"top_k": 8}, "use_golden_set": True},
            )
        ).json()
        second = (
            await seeded_client.post(
                f"{api}/labs/evals/run",
                headers=auth_headers,
                json={
                    "name": "narrow",
                    "config": {"top_k": 1},
                    "use_golden_set": True,
                    "baseline_evaluation_id": first["evaluation_id"],
                },
            )
        ).json()
        assert second["baseline"] is not None
        assert second["baseline"].keys() & second["metrics"].keys()
