"""XP curve, ranks and award rules.

These are pure functions, so the tests assert *properties* (monotonicity,
invertibility, ordering) rather than hard-coded numbers wherever possible. A
test that asserts `total_xp_for_level(22) == 13048` fails the moment anyone
tunes the curve, even when the tuning is correct — property tests survive
balance changes and still catch real breakage.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from app.domain.enums import RANK_ORDER, DifficultyTier, Rank, XPSource
from app.game.xp.engine import (
    MAX_LEVEL,
    RANK_LEVEL_THRESHOLDS,
    TIER_BASE_XP,
    AwardContext,
    apply_xp,
    coins_for_grants,
    compute_award,
    experience_band_for_level,
    level_for_xp,
    next_rank,
    rank_for_level,
    total_xp_for_level,
    xp_to_next_level,
)


class TestCurve:
    def test_level_one_is_free(self):
        assert total_xp_for_level(1) == 0
        assert level_for_xp(0) == 1

    def test_curve_is_strictly_increasing(self):
        values = [total_xp_for_level(lv) for lv in range(1, MAX_LEVEL + 1)]
        assert all(b > a for a, b in pairwise(values))

    def test_cost_per_level_increases(self):
        """Superlinear: each level must cost more than the one before."""
        costs = [xp_to_next_level(lv) for lv in range(1, MAX_LEVEL)]
        assert all(b >= a for a, b in pairwise(costs))

    @pytest.mark.parametrize("level", [1, 2, 5, 12, 22, 50, 84, 95, 100])
    def test_level_lookup_inverts_the_curve(self, level):
        assert level_for_xp(total_xp_for_level(level)) == level

    def test_one_xp_below_a_threshold_is_the_previous_level(self):
        for level in (2, 10, 50, 100):
            assert level_for_xp(total_xp_for_level(level) - 1) == level - 1

    def test_negative_and_huge_xp_are_clamped(self):
        assert level_for_xp(-500) == 1
        assert level_for_xp(10**9) == MAX_LEVEL
        assert xp_to_next_level(MAX_LEVEL) == 0


class TestRanks:
    def test_every_rank_has_a_threshold(self):
        assert set(RANK_LEVEL_THRESHOLDS) == set(RANK_ORDER)

    def test_thresholds_are_ordered(self):
        thresholds = [RANK_LEVEL_THRESHOLDS[r] for r in RANK_ORDER]
        assert thresholds == sorted(thresholds)

    def test_rank_is_monotonic_in_level(self):
        seen = [RANK_ORDER.index(rank_for_level(lv)) for lv in range(1, MAX_LEVEL + 1)]
        assert all(b >= a for a, b in pairwise(seen))

    def test_boundaries(self):
        assert rank_for_level(1) is Rank.PYTHON_APPRENTICE
        assert rank_for_level(4) is Rank.PYTHON_APPRENTICE
        assert rank_for_level(5) is Rank.PYTHON_DEVELOPER
        assert rank_for_level(100) is Rank.PRINCIPAL_AI_ENGINEER

    def test_next_rank_terminates(self):
        assert next_rank(Rank.PRINCIPAL_AI_ENGINEER) is None
        assert next_rank(Rank.PYTHON_APPRENTICE) is Rank.PYTHON_DEVELOPER

    def test_experience_band_advances(self):
        assert experience_band_for_level(1).value == "0-1"
        assert experience_band_for_level(100).value == "10+"


class TestAwards:
    def test_higher_tiers_pay_more(self):
        totals = []
        for tier in DifficultyTier:
            grants = compute_award(AwardContext(tier=tier, passed=True))
            totals.append(sum(g.amount for g in grants))
        assert totals == sorted(totals)

    def test_failure_still_pays_something_but_far_less(self):
        ctx = AwardContext(tier=DifficultyTier.DEBUG, passed=False)
        failed = sum(g.amount for g in compute_award(ctx))
        passed = sum(
            g.amount for g in compute_award(AwardContext(tier=DifficultyTier.DEBUG, passed=True))
        )
        assert 0 < failed < passed / 5

    def test_grinding_tier_one_cannot_beat_deep_work(self):
        """The core balance guarantee: depth must dominate volume."""
        tier1 = sum(
            g.amount for g in compute_award(AwardContext(tier=DifficultyTier.REMEMBER, passed=True))
        )
        tier9 = sum(
            g.amount
            for g in compute_award(AwardContext(tier=DifficultyTier.STAFF_TRADEOFF, passed=True))
        )
        assert tier9 > tier1 * 10

    def test_bonuses_are_itemised_and_attributable(self):
        grants = compute_award(
            AwardContext(
                tier=DifficultyTier.PRODUCTION,
                passed=True,
                first_attempt=True,
                elapsed_seconds=60,
                par_seconds=300,
                explanation_score=1.0,
                streak_days=30,
            )
        )
        sources = {g.source for g in grants}
        assert XPSource.FIRST_ATTEMPT_BONUS in sources
        assert XPSource.SPEED_BONUS in sources
        assert XPSource.EXPLANATION_BONUS in sources
        assert XPSource.STREAK_BONUS in sources
        assert all(g.reason for g in grants), "every grant must explain itself to the player"

    def test_no_speed_bonus_when_over_par(self):
        grants = compute_award(
            AwardContext(
                tier=DifficultyTier.IMPLEMENT, passed=True, elapsed_seconds=900, par_seconds=300
            )
        )
        assert XPSource.SPEED_BONUS not in {g.source for g in grants}

    def test_boss_multiplier_applies(self):
        normal = sum(
            g.amount for g in compute_award(AwardContext(tier=DifficultyTier.DESIGN, passed=True))
        )
        boss = sum(
            g.amount
            for g in compute_award(
                AwardContext(tier=DifficultyTier.DESIGN, passed=True, is_boss=True)
            )
        )
        assert boss > normal * 2

    def test_optimisation_bonus_is_logarithmic(self):
        """A 100x speedup should feel great, not 50x better than 2x."""

        def award_for(factor: float) -> int:
            grants = compute_award(
                AwardContext(tier=DifficultyTier.OPTIMIZE, passed=True, optimization_factor=factor)
            )
            return next((g.amount for g in grants if g.source == XPSource.OPTIMIZATION), 0)

        assert award_for(2.0) > 0
        assert award_for(100.0) > award_for(2.0)
        assert award_for(100.0) < award_for(2.0) * 8

    def test_streak_bonus_is_capped(self):
        def streak_amount(days: int) -> int:
            grants = compute_award(
                AwardContext(tier=DifficultyTier.IMPLEMENT, passed=True, streak_days=days)
            )
            return next((g.amount for g in grants if g.source == XPSource.STREAK_BONUS), 0)

        assert streak_amount(30) == streak_amount(400), "an unbounded streak bonus breaks balance"

    def test_award_amounts_are_never_negative(self):
        for tier in DifficultyTier:
            for passed in (True, False):
                grants = compute_award(AwardContext(tier=tier, passed=passed))
                assert all(g.amount >= 0 for g in grants)


class TestApplyXP:
    def test_reports_level_up(self):
        grants = compute_award(
            AwardContext(tier=DifficultyTier.PRINCIPAL_ARCHITECTURE, passed=True)
        )
        result = apply_xp(0, grants)
        assert result.total_xp == sum(g.amount for g in grants)
        assert result.new_level >= result.previous_level
        assert result.leveled_up == (result.new_level > result.previous_level)

    def test_rank_up_flag(self):
        before = total_xp_for_level(RANK_LEVEL_THRESHOLDS[Rank.PYTHON_DEVELOPER]) - 1
        from app.game.xp.engine import XPGrant

        result = apply_xp(before, [XPGrant(XPSource.CHALLENGE_PASSED, 5, "t")])
        assert result.ranked_up
        assert result.new_rank is Rank.PYTHON_DEVELOPER

    def test_progress_pct_is_bounded(self):
        from app.game.xp.engine import XPGrant

        for xp in (0, 100, 5_000, 50_000, 150_000):
            result = apply_xp(xp, [XPGrant(XPSource.CHALLENGE_PASSED, 1, "t")])
            assert 0.0 <= result.progress_pct <= 100.0

    def test_totals_never_go_negative(self):
        from app.game.xp.engine import XPGrant

        result = apply_xp(10, [XPGrant(XPSource.CHALLENGE_PASSED, -999, "penalty")])
        assert result.total_xp == 0

    def test_coins_scale_with_xp(self):
        from app.game.xp.engine import XPGrant

        small = coins_for_grants([XPGrant(XPSource.CHALLENGE_PASSED, 10, "t")])
        large = coins_for_grants([XPGrant(XPSource.CHALLENGE_PASSED, 1000, "t")])
        assert 1 <= small < large


def test_every_tier_has_base_xp():
    assert set(TIER_BASE_XP) == set(DifficultyTier)
