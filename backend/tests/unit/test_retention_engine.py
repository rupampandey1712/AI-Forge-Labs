"""The Knowledge Retention Engine.

Time is injected everywhere (``now=``), never read from the clock, so these
tests are deterministic and can simulate a year of forgetting in milliseconds.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise

import pytest

from app.game.retention.model import (
    CRITICAL_DECAY_THRESHOLD,
    DECAY_ALERT_THRESHOLD,
    LADDER_DAYS,
    MAX_EASE,
    MAX_INTERVAL_DAYS,
    MIN_EASE,
    MIN_INTERVAL_DAYS,
    RETENTION_FLOOR,
    TIER_MASTERY_CEILING,
    ReviewState,
    bootstrap,
    calibration_error,
    decay_report,
    effective_mastery,
    mastery_ceiling,
    retrievability,
    review,
    stability_from_interval,
)


def study(state: ReviewState, now, *, score=0.95, tier=5, **kw) -> ReviewState:
    return review(state, score=score, tier=tier, now=now, **kw)


class TestForgettingCurve:
    def test_unseen_concept_has_no_retrievability(self, frozen_now):
        """Never learned is not the same as forgotten — it must report 0, not 1."""
        assert retrievability(ReviewState(), frozen_now) == 0.0
        assert effective_mastery(ReviewState(), frozen_now) == 0.0

    def test_retrievability_is_one_at_the_moment_of_review(self, frozen_now):
        state = study(ReviewState(), frozen_now)
        assert retrievability(state, frozen_now) == pytest.approx(1.0)

    def test_retrievability_decays_monotonically(self, frozen_now):
        state = study(ReviewState(), frozen_now)
        values = [retrievability(state, frozen_now + timedelta(days=d)) for d in range(0, 200, 7)]
        assert all(b <= a for a, b in pairwise(values))
        assert values[-1] < 0.1

    def test_scheduled_interval_lands_near_target_retention(self, frozen_now):
        """The scheduler's promise: at the due date, recall should be ~90%."""
        state = study(ReviewState(), frozen_now)
        at_due = retrievability(state, state.due_at)
        assert 0.85 <= at_due <= 0.95

    def test_stronger_memories_decay_more_slowly(self, frozen_now):
        weak = study(ReviewState(), frozen_now)

        strong = ReviewState()
        now = frozen_now
        for _ in range(5):
            strong = study(strong, now)
            now += timedelta(days=strong.interval_days)

        later = timedelta(days=20)
        assert retrievability(strong, now + later) > retrievability(weak, frozen_now + later)

    def test_effective_mastery_never_falls_below_the_savings_floor(self, frozen_now):
        """Ebbinghaus savings: relearning is faster, so mastery rusts, it does
        not vanish. A player returning after a year must not see 0%."""
        state = study(ReviewState(), frozen_now, tier=8)
        far_future = frozen_now + timedelta(days=3650)
        eff = effective_mastery(state, far_future)
        assert eff == pytest.approx(state.mastery * RETENTION_FLOOR, abs=1e-3)
        assert eff > 0


class TestDecayReport:
    def test_reports_the_drop_the_dashboard_shows(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        for tier in (3, 5, 6, 8, 8):
            state = study(state, now, tier=tier)
            now += timedelta(days=state.interval_days)

        peak = state.mastery
        report = decay_report(state, now + timedelta(days=120))
        assert report.effective_mastery < peak
        assert report.mastery_drop == pytest.approx(peak - report.effective_mastery, abs=1e-3)
        assert 0.0 <= report.urgency <= 1.0

    def test_thresholds_escalate_with_time(self, frozen_now):
        state = study(ReviewState(), frozen_now)
        fresh = decay_report(state, frozen_now)
        assert not fresh.is_due and not fresh.is_decayed and not fresh.is_critical

        # Walk forward until each threshold trips, and assert the ordering.
        def first_day_where(predicate) -> int:
            for day in range(0, 400):
                if predicate(decay_report(state, frozen_now + timedelta(days=day))):
                    return day
            return 10_000

        due_day = first_day_where(lambda r: r.is_due)
        decayed_day = first_day_where(lambda r: r.is_decayed)
        critical_day = first_day_where(lambda r: r.is_critical)
        assert due_day <= decayed_day <= critical_day

    def test_urgency_prioritises_a_big_loss_at_equal_retrievability(self, frozen_now):
        """Forgetting something you had at 90% matters more than something you
        only reached 30% on.

        The comparison must hold *retrievability* constant, otherwise it only
        measures which memory is staler. Each state is sampled at its own
        equivalent point on the curve (same fraction of its stability), so the
        only thing differing is how much mastery was at stake.
        """
        high = ReviewState()
        now = frozen_now
        for _ in range(6):
            high = study(high, now, tier=9)
            now += timedelta(days=high.interval_days)

        low = study(ReviewState(), frozen_now, score=0.65, tier=2)

        # Sample both at R ~ 0.5 (t = S * ln 2).
        import math

        high_at = high.last_seen + timedelta(days=high.stability_days * math.log(2))
        low_at = low.last_seen + timedelta(days=low.stability_days * math.log(2))
        high_report = decay_report(high, high_at)
        low_report = decay_report(low, low_at)

        assert high_report.retrievability == pytest.approx(low_report.retrievability, abs=0.02)
        assert high_report.mastery_drop > low_report.mastery_drop
        assert high_report.urgency > low_report.urgency

    def test_thresholds_are_ordered_constants(self):
        assert CRITICAL_DECAY_THRESHOLD < DECAY_ALERT_THRESHOLD < 1.0


class TestScheduling:
    def test_first_reviews_follow_the_ladder(self, frozen_now):
        state = ReviewState()
        intervals = []
        now = frozen_now
        for _ in range(5):
            state = study(state, now)
            intervals.append(state.interval_days)
            now += timedelta(days=state.interval_days)

        assert intervals == sorted(intervals), "intervals must grow with each success"
        # Within a factor of ~2 of the canonical 1/3/7/14/30 ladder.
        for actual, canonical in zip(intervals, LADDER_DAYS, strict=False):
            assert canonical / 2 <= actual <= canonical * 2.5

    def test_failure_shortens_the_interval_sharply(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        for _ in range(4):
            state = study(state, now)
            now += timedelta(days=state.interval_days)
        long_interval = state.interval_days

        lapsed = review(state, score=0.2, tier=5, now=now)
        assert lapsed.interval_days < long_interval / 3
        assert lapsed.lapses == 1
        assert lapsed.repetitions == 0

    def test_repeated_failures_compound(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        first = review(state, score=0.1, tier=5, now=now)
        second = review(first, score=0.1, tier=5, now=now + timedelta(days=1))
        third = review(second, score=0.1, tier=5, now=now + timedelta(days=2))
        assert third.lapses == 3
        assert third.ease <= second.ease <= first.ease

    def test_ease_stays_in_bounds(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        for score in [1.0] * 30:
            state = review(state, score=score, tier=8, now=now)
            now += timedelta(days=state.interval_days)
        assert state.ease <= MAX_EASE

        for score in [0.0] * 30:
            state = review(state, score=score, tier=8, now=now)
            now += timedelta(days=1)
        assert state.ease >= MIN_EASE

    def test_intervals_stay_in_bounds(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        for _ in range(60):
            state = study(state, now, tier=10)
            assert MIN_INTERVAL_DAYS <= state.interval_days <= MAX_INTERVAL_DAYS
            now += timedelta(days=state.interval_days)

    def test_hints_shorten_the_schedule(self, frozen_now):
        """A solution reached with three hints was not recalled — scheduling it
        like a clean recall would make the player forget it again."""
        clean = study(ReviewState(), frozen_now, hints_used=0)
        helped = study(ReviewState(), frozen_now, hints_used=3)
        assert helped.interval_days < clean.interval_days

    def test_stability_matches_the_interval(self):
        for interval in (1.0, 7.0, 90.0):
            s = stability_from_interval(interval)
            assert s > interval  # S is always larger than the 90%-recall interval


class TestMastery:
    def test_tier_ceiling_prevents_faking_depth(self, frozen_now):
        """Answering tier-1 questions forever must not produce 90% mastery."""
        state = ReviewState()
        now = frozen_now
        for _ in range(60):
            state = review(state, score=1.0, tier=1, now=now)
            now += timedelta(days=state.interval_days)
        assert state.mastery <= TIER_MASTERY_CEILING[1] + 1e-6

    def test_deeper_tiers_raise_the_ceiling(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        for tier in (2, 4, 6, 8, 9, 10):
            for _ in range(4):
                state = review(state, score=1.0, tier=tier, now=now)
                now += timedelta(days=state.interval_days)
        assert state.mastery > TIER_MASTERY_CEILING[4]

    def test_mastery_rebuilds_from_decayed_value_not_from_peak(self, frozen_now):
        """The retention loop is only real if a single review cannot instantly
        restore a year-old 95%."""
        state = ReviewState()
        now = frozen_now
        for _ in range(6):
            state = study(state, now, tier=8)
            now += timedelta(days=state.interval_days)
        peak = state.mastery

        much_later = now + timedelta(days=365)
        restored = review(state, score=1.0, tier=8, now=much_later)
        assert restored.mastery < peak, "one review must not undo a year of decay"
        assert restored.peak_mastery == pytest.approx(peak, abs=1e-6)

    def test_peak_mastery_is_a_high_water_mark(self, frozen_now):
        """Peak must never fall, even when current mastery does — it is what the
        dashboard's "91% -> 68%" headline is measured against."""
        state = ReviewState()
        now = frozen_now
        for _ in range(5):
            state = study(state, now, tier=8)
            now += timedelta(days=state.interval_days)
        peak = state.peak_mastery

        for _ in range(3):
            state = review(state, score=0.0, tier=8, now=now)
            now += timedelta(days=1)
        assert state.mastery < peak
        assert state.peak_mastery == pytest.approx(peak, abs=1e-6)

    def test_accuracy_tracks_outcomes(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        state = review(state, score=1.0, tier=5, now=now)
        state = review(state, score=0.1, tier=5, now=now + timedelta(days=1))
        assert state.attempts == 2
        assert state.correct == 1
        assert state.accuracy == pytest.approx(0.5)

    def test_mastery_ceiling_lookup(self):
        # Nothing cleared yet is treated as tier 1, not as "no ceiling".
        assert mastery_ceiling(0) == TIER_MASTERY_CEILING[1]
        assert mastery_ceiling(1) == TIER_MASTERY_CEILING[1]
        assert mastery_ceiling(10) == 1.0
        assert mastery_ceiling(99) == 1.0  # clamped
        ceilings = [mastery_ceiling(t) for t in range(1, 11)]
        assert ceilings == sorted(ceilings), "ceilings must rise with tier"


class TestBootstrapAndCalibration:
    def test_bootstrap_schedules_a_first_review_without_claiming_mastery(self, frozen_now):
        state = bootstrap(frozen_now)
        assert state.mastery == 0.0
        assert state.attempts == 0
        assert state.due_at == frozen_now + timedelta(days=LADDER_DAYS[0])

    def test_calibration_needs_evidence(self, frozen_now):
        assert calibration_error(ReviewState()) == 0.0

    def test_overconfident_and_wrong_is_detected(self, frozen_now):
        state = ReviewState()
        now = frozen_now
        for _ in range(4):
            state = review(state, score=0.2, tier=5, now=now, confidence=0.95)
            now += timedelta(days=1)
        assert calibration_error(state) > 0.5

    def test_overconfidence_penalises_the_schedule(self, frozen_now):
        """Being sure and wrong should bring the review forward more than being
        unsure and wrong."""
        sure = review(ReviewState(), score=0.3, tier=5, now=frozen_now, confidence=0.95)
        unsure = review(ReviewState(), score=0.3, tier=5, now=frozen_now, confidence=0.1)
        assert sure.interval_days <= unsure.interval_days


def test_spec_scenario_generators_after_a_month(frozen_now):
    """Spec §4: a mid-strength memory, untouched for ~32 days, must show a real
    drop and raise a decay alert."""
    state = ReviewState()
    now = frozen_now
    for tier in (3, 4, 5):
        state = review(state, score=0.9, tier=tier, now=now)
        now += timedelta(days=state.interval_days)

    # Measure from the last review, not from the loop cursor (which has already
    # advanced by the final interval).
    report = decay_report(state, state.last_seen + timedelta(days=32))
    assert report.is_due
    assert report.is_decayed
    assert report.mastery_drop > 0.05
    assert report.days_since_practice == pytest.approx(32.0, abs=0.1)
