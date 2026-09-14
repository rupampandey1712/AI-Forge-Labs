"""The full game loop: submit → grade → XP → retention → mistake database.

These are the tests that would catch a regression nobody notices for months —
a challenge graded without updating the forgetting model, or XP awarded twice.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

CORRECT = "def dedupe(items):\n    return list(dict.fromkeys(items))"
WRONG = "def dedupe(items):\n    return list(set(items))"
CHALLENGE = "py-dedupe-preserve-order"


class TestChallengeSubmission:
    async def test_correct_solution_passes_and_awards_itemised_xp(
        self, seeded_client, api, auth_headers
    ):
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT, "elapsed_seconds": 120},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["passed"] is True
        assert body["tests_passed"] == body["tests_total"] > 0
        assert body["score"] == 1.0

        progression = body["progression"]
        assert progression["xp_gained"] > 0
        assert progression["grants"], "XP must be itemised so players learn the reward function"
        assert all(g["reason"] for g in progression["grants"])

    async def test_wrong_solution_fails_with_an_incident_framing(
        self, seeded_client, api, auth_headers
    ):
        """Spec §64: failure is a postmortem, not the word 'Wrong'."""
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": WRONG, "elapsed_seconds": 60},
        )
        body = response.json()
        assert body["passed"] is False
        assert body["headline"] and body["headline"] != "Wrong"
        assert body["what_happened"], "a failure must explain what happened"
        assert body["hint"], "a failed first attempt should offer the next hint"
        assert body["can_retry"] is True
        assert body["progression"]["xp_gained"] > 0, "engaging with a hard problem earns something"

    async def test_failure_earns_far_less_than_success(self, seeded_client, api, auth_headers):
        fail = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": WRONG, "elapsed_seconds": 60},
        )
        ok = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT, "elapsed_seconds": 60},
        )
        assert fail.json()["progression"]["xp_gained"] * 5 < ok.json()["progression"]["xp_gained"]

    async def test_syntax_error_is_reported_as_the_players_problem(
        self, seeded_client, api, auth_headers
    ):
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": "def dedupe(items)\n    return items", "elapsed_seconds": 5},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["passed"] is False
        assert "syntax" in (body["stderr"] + body["what_happened"]).lower()

    async def test_run_only_does_not_record_an_attempt(self, seeded_client, api, auth_headers):
        """Experimentation must be free of consequences, or players stop experimenting."""
        before = (
            await seeded_client.get(f"{api}/challenges/{CHALLENGE}", headers=auth_headers)
        ).json()["attempts_made"]

        await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": WRONG, "run_only": True},
        )
        after = (
            await seeded_client.get(f"{api}/challenges/{CHALLENGE}", headers=auth_headers)
        ).json()["attempts_made"]
        assert after == before

    async def test_hidden_test_details_are_never_revealed(self, seeded_client, api, auth_headers):
        """Otherwise a player reconstructs the hidden suite from failure diffs."""
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": WRONG},
        )
        for result in response.json()["test_results"]:
            if result["hidden"]:
                assert result["expected"] in (None, "")
                assert result["actual"] in (None, "")

    async def test_solution_is_revealed_only_after_repeated_failure(
        self, seeded_client, api, auth_headers
    ):
        last = None
        for _ in range(4):
            last = await seeded_client.post(
                f"{api}/challenges/{CHALLENGE}/submit",
                headers=auth_headers,
                json={"code": WRONG},
            )
        body = last.json()
        assert body["reveal_solution"] is True
        assert body["solution"], "after enough genuine attempts, show the answer"


class TestRetentionIntegration:
    async def test_submission_updates_the_forgetting_model(self, seeded_client, api, auth_headers):
        """The single most important integration in the product."""
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT, "elapsed_seconds": 100, "confidence": 0.8},
        )
        body = response.json()
        assert body["next_review_at"], "a graded attempt must schedule a review"
        assert body["mastery_delta"], "mastery must move"
        for delta in body["mastery_delta"].values():
            assert delta["after"] > delta["before"]

    async def test_retention_dashboard_tracks_the_concepts(self, seeded_client, api, auth_headers):
        await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT},
        )
        response = await seeded_client.get(f"{api}/retention", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["concepts_tracked"] >= 1
        assert body["forecast"], "the dashboard must be able to draw the forgetting curve"
        assert body["forecast"][0]["retention"] >= body["forecast"][-1]["retention"]

    async def test_skill_mastery_rolls_up(self, seeded_client, api, auth_headers):
        await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT},
        )
        skills = (await seeded_client.get(f"{api}/player/skills", headers=auth_headers)).json()
        python = next(s for s in skills if s["skill_slug"] == "python")
        assert python["mastery"] > 0
        assert python["attempts"] > 0


class TestMistakeDatabase:
    async def test_a_detected_mistake_is_recorded_with_its_lesson(
        self, seeded_client, api, auth_headers
    ):
        await seeded_client.post(
            f"{api}/challenges/py-fix-mutable-default/submit",
            headers=auth_headers,
            json={
                "code": "def add_item(item, basket=[]):\n    basket.append(item)\n    return basket"
            },
        )
        response = await seeded_client.get(f"{api}/mistakes", headers=auth_headers)
        patterns = {m["pattern"]: m for m in response.json()}
        assert "mutable_default_argument" in patterns
        record = patterns["mutable_default_argument"]
        assert record["why_it_matters"], "a mistake record without a lesson teaches nothing"
        assert record["correct_approach"]
        assert record["occurrences"] == 1

    async def test_repeating_a_mistake_increments_rather_than_duplicating(
        self, seeded_client, api, auth_headers
    ):
        bad = "def add_item(item, basket=[]):\n    basket.append(item)\n    return basket"
        for _ in range(3):
            await seeded_client.post(
                f"{api}/challenges/py-fix-mutable-default/submit",
                headers=auth_headers,
                json={"code": bad},
            )
        records = (await seeded_client.get(f"{api}/mistakes", headers=auth_headers)).json()
        matching = [m for m in records if m["pattern"] == "mutable_default_argument"]
        assert len(matching) == 1, "one pattern is one lesson, not three cards"
        assert matching[0]["occurrences"] == 3

    async def test_clean_code_scores_higher_than_code_with_defects(
        self, seeded_client, api, auth_headers
    ):
        """Passing tests with a critical defect must not earn the clean-code bonus."""
        clean = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT},
        )
        sources = {g["source"] for g in clean.json()["progression"]["grants"]}
        assert "clean_code_bonus" in sources


class TestExplanationGrading:
    async def test_a_thin_explanation_scores_below_a_deep_one(
        self, seeded_client, api, auth_headers
    ):
        thin = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT, "explanation": "It is faster."},
        )
        deep = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={
                "code": CORRECT,
                "explanation": (
                    "The naive version is O(n^2) because `x in result` is a linear scan on "
                    "every iteration. dict.fromkeys is O(n) — each key is hashed once — and "
                    "dicts have preserved insertion order since 3.7, so first-seen ordering "
                    "is kept. In production this took the job from 40 minutes to under a second."
                ),
                "complexity": "O(n)",
            },
        )
        assert deep.json()["explanation_score"] > thin.json()["explanation_score"]

    async def test_missing_points_are_named(self, seeded_client, api, auth_headers):
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT, "explanation": "It is faster."},
        )
        assert response.json()["missing_points"], "tell the player exactly what was missing"


class TestDailyMission:
    async def test_daily_is_generated_with_reasons(self, seeded_client, api, auth_headers):
        response = await seeded_client.get(f"{api}/daily-challenge", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["slots"], "a daily with no slots is a bug"
        for slot in body["slots"]:
            assert slot["reason"], "every slot must explain why it was chosen"
            assert slot["ref_slug"]

    async def test_daily_is_stable_within_a_day(self, seeded_client, api, auth_headers):
        """Rerolling would let players dodge exactly what they need."""
        first = (await seeded_client.get(f"{api}/daily-challenge", headers=auth_headers)).json()
        second = (await seeded_client.get(f"{api}/daily-challenge", headers=auth_headers)).json()
        assert first["id"] == second["id"]
        assert [s["ref_slug"] for s in first["slots"]] == [s["ref_slug"] for s in second["slots"]]

    async def test_always_includes_exactly_one_interview_slot(
        self, seeded_client, api, auth_headers
    ):
        body = (await seeded_client.get(f"{api}/daily-challenge", headers=auth_headers)).json()
        interviews = [s for s in body["slots"] if s["kind"] == "interview"]
        assert len(interviews) == 1


class TestMissionFlow:
    async def test_start_step_and_complete(self, seeded_client, api, auth_headers):
        slug = "m-python-onboarding"
        start = await seeded_client.post(f"{api}/missions/{slug}/start", headers=auth_headers)
        assert start.status_code == 200, start.text
        detail = start.json()
        assert detail["attempt_id"]

        for step in detail["steps"]:
            if step["step_type"] == "challenge":
                payload = {"position": step["position"], "challenge": {"code": CORRECT}}
            elif step["step_type"] == "question":
                payload = {
                    "position": step["position"],
                    "question": {
                        "answer_text": (
                            "Membership testing against a list is O(n), so inside a loop over "
                            "users it is O(n*m). Converting banned_ids to a set makes each "
                            "lookup an O(1) hash lookup. Local fixtures are tiny, so the "
                            "constant is invisible until production data size."
                        )
                    },
                }
            elif step["step_type"] == "explanation":
                payload = {
                    "position": step["position"],
                    "free_text": (
                        "It was O(n^2) before and is O(n) now. The test fixtures were small, "
                        "so the quadratic cost never showed up. I would add a benchmark with "
                        "realistic data size to catch it next time."
                    ),
                }
            else:
                continue
            response = await seeded_client.post(
                f"{api}/missions/{slug}/step", headers=auth_headers, json=payload
            )
            assert response.status_code == 200, response.text

        complete = await seeded_client.post(f"{api}/missions/{slug}/complete", headers=auth_headers)
        assert complete.status_code == 200, complete.text
        body = complete.json()
        assert body["passed"] is True
        assert body["debrief"], "a completed mission must teach"
        assert body["progression"]["xp_gained"] > 0
        assert body["journal_prompt"]

    async def test_cannot_submit_a_step_before_starting(self, seeded_client, api, auth_headers):
        response = await seeded_client.post(
            f"{api}/missions/m-python-onboarding/step",
            headers=auth_headers,
            json={"position": 0, "free_text": "x"},
        )
        assert response.status_code == 409

    async def test_locked_mission_is_refused_with_a_reason(self, seeded_client, api, auth_headers):
        response = await seeded_client.get(
            f"{api}/missions/m-python-boss-framework", headers=auth_headers
        )
        assert response.status_code == 423
        assert response.json()["error"]["code"] == "content_locked"
        assert response.json()["error"]["message"], "tell the player what unlocks it"

    async def test_debrief_is_withheld_until_completion(self, seeded_client, api, auth_headers):
        response = await seeded_client.get(
            f"{api}/missions/m-python-onboarding", headers=auth_headers
        )
        assert response.json()["debrief"] is None


class TestInterviewArena:
    async def test_session_adapts_and_produces_a_report(self, seeded_client, api, auth_headers):
        start = await seeded_client.post(
            f"{api}/interview/start",
            headers=auth_headers,
            json={"level": "mid", "question_count": 3},
        )
        assert start.status_code == 200, start.text
        session = start.json()
        session_id = session["id"]
        turn = session["current_turn"]
        assert turn is not None

        complete = False
        guard = 0
        while turn and not complete and guard < 10:
            guard += 1
            answer = await seeded_client.post(
                f"{api}/interview/{session_id}/answer",
                headers=auth_headers,
                json={
                    "position": turn["position"],
                    "answer_text": (
                        "It compares object identity rather than value, because `is` checks "
                        "id() while `==` dispatches to __eq__. In production the trade-off "
                        "matters for interned values; however you should reserve `is` for "
                        "None and sentinels."
                    ),
                    "selected_option_ids": [turn["options"][0]["id"]] if turn["options"] else [],
                    "elapsed_seconds": 60,
                },
            )
            assert answer.status_code == 200, answer.text
            body = answer.json()
            feedback = body["feedback"]
            assert 0 <= feedback["score"] <= 10
            assert set(feedback["dimension_scores"]), "seven-dimension scoring is the point"
            assert feedback["interviewer_reaction"]
            complete = body["session_complete"]
            turn = body["next_turn"]

        report = await seeded_client.get(
            f"{api}/interview/{session_id}/report", headers=auth_headers
        )
        assert report.status_code == 200, report.text
        data = report.json()
        assert data["verdict"]
        assert data["summary"]
        assert data["per_question"]
        assert 0 <= data["overall_score"] <= 10

    async def test_cannot_answer_the_same_question_twice(self, seeded_client, api, auth_headers):
        start = await seeded_client.post(
            f"{api}/interview/start", headers=auth_headers, json={"question_count": 3}
        )
        session = start.json()
        position = session["current_turn"]["position"]
        payload = {"position": position, "answer_text": "An answer."}
        first = await seeded_client.post(
            f"{api}/interview/{session['id']}/answer", headers=auth_headers, json=payload
        )
        assert first.status_code == 200
        second = await seeded_client.post(
            f"{api}/interview/{session['id']}/answer", headers=auth_headers, json=payload
        )
        assert second.status_code == 409

    async def test_another_player_cannot_read_my_interview(self, seeded_client, api, auth_headers):
        start = await seeded_client.post(
            f"{api}/interview/start", headers=auth_headers, json={"question_count": 3}
        )
        session_id = start.json()["id"]

        other = await seeded_client.post(
            f"{api}/auth/register",
            json={
                "email": "intruder@test.dev",
                "username": "intruder",
                "password": "An0ther-Passphrase!",
            },
        )
        intruder = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
        response = await seeded_client.get(f"{api}/interview/{session_id}", headers=intruder)
        assert response.status_code == 404, "sessions must be scoped to their owner"


class TestProgressionSideEffects:
    async def test_badges_unlock_from_declarative_criteria(self, seeded_client, api, auth_headers):
        response = await seeded_client.post(
            f"{api}/challenges/{CHALLENGE}/submit",
            headers=auth_headers,
            json={"code": CORRECT},
        )
        assert "first-commit" in response.json()["progression"]["new_badges"]

    async def test_xp_ledger_matches_the_profile_total(self, seeded_client, api, auth_headers):
        for _ in range(3):
            await seeded_client.post(
                f"{api}/challenges/{CHALLENGE}/submit",
                headers=auth_headers,
                json={"code": CORRECT},
            )
        profile = (await seeded_client.get(f"{api}/player/profile", headers=auth_headers)).json()
        ledger = (
            await seeded_client.get(f"{api}/player/xp?limit=200", headers=auth_headers)
        ).json()
        assert sum(row["amount"] for row in ledger) == profile["total_xp"], (
            "the denormalised counter must never disagree with the append-only ledger"
        )

    async def test_dashboard_is_one_coherent_snapshot(self, seeded_client, api, auth_headers):
        response = await seeded_client.get(f"{api}/player/dashboard", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        for key in ("profile", "skills", "retention_alerts", "recommended", "streak_calendar"):
            assert key in body
        assert len(body["skills"]) == 16
