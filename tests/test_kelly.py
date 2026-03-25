"""Tests for Kelly position sizing."""
import pytest
from src.analysis.kelly import (
    apply_fractional_kelly,
    apply_kelly_caps,
    compute_position_size,
    kelly_summary,
)


class TestApplyFractionalKelly:
    def test_quarter_kelly_default(self):
        assert apply_fractional_kelly(0.40) == pytest.approx(0.10)

    def test_custom_multiplier(self):
        assert apply_fractional_kelly(0.40, multiplier=0.5) == pytest.approx(0.20)

    def test_negative_kelly_stays_negative(self):
        assert apply_fractional_kelly(-0.10) == pytest.approx(-0.025)

    def test_zero(self):
        assert apply_fractional_kelly(0.0) == pytest.approx(0.0)


class TestApplyKellyCaps:
    def test_below_min_returns_zero(self):
        assert apply_kelly_caps(0.005) == 0.0  # < 0.01 min

    def test_above_max_capped(self):
        assert apply_kelly_caps(0.50) == pytest.approx(0.25)  # capped at 0.25

    def test_within_range_unchanged(self):
        assert apply_kelly_caps(0.10) == pytest.approx(0.10)

    def test_exactly_at_min(self):
        assert apply_kelly_caps(0.01) == pytest.approx(0.01)

    def test_exactly_at_max(self):
        assert apply_kelly_caps(0.25) == pytest.approx(0.25)

    def test_negative_returns_zero(self):
        assert apply_kelly_caps(-0.10) == 0.0


class TestComputePositionSize:
    def test_standard_bet(self):
        # raw_kelly=0.40 → fractional=0.10 → capped=0.10 → 0.10 * 1000 = $100
        size = compute_position_size(bankroll=1000.0, kelly_fraction=0.40)
        assert size == pytest.approx(100.0)

    def test_zero_for_no_edge(self):
        size = compute_position_size(bankroll=1000.0, kelly_fraction=-0.10)
        assert size == 0.0

    def test_cap_at_max(self):
        # raw_kelly=10.0, fractional=2.5, capped=0.25 → $250
        size = compute_position_size(bankroll=1000.0, kelly_fraction=10.0)
        assert size == pytest.approx(250.0)

    def test_proportional_to_bankroll(self):
        s1 = compute_position_size(1000.0, 0.40)
        s2 = compute_position_size(2000.0, 0.40)
        assert s2 == pytest.approx(s1 * 2)


class TestKellySummary:
    def test_summary_keys(self):
        summary = kelly_summary(raw_kelly=0.40, bankroll=1000.0)
        assert set(summary.keys()) == {
            "raw_kelly", "fractional_kelly", "capped_kelly",
            "suggested_bet_usd", "bankroll", "multiplier",
        }

    def test_summary_values(self):
        summary = kelly_summary(raw_kelly=0.40, bankroll=1000.0)
        assert summary["raw_kelly"] == pytest.approx(0.40)
        assert summary["fractional_kelly"] == pytest.approx(0.10)
        assert summary["capped_kelly"] == pytest.approx(0.10)
        assert summary["suggested_bet_usd"] == pytest.approx(100.0)
        assert summary["bankroll"] == 1000.0
