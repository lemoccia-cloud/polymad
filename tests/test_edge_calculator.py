"""Tests for edge_calculator — pure math, no mocking needed."""
import pytest
from datetime import datetime, timezone

from src.analysis.edge_calculator import (
    compute_edge,
    compute_expected_value,
    compute_kelly_fraction,
    analyze_market,
    rank_opportunities,
)
from src.models.market import WeatherMarket, WeatherForecast, OpportunityResult


def make_market(market_prob: float = 0.62) -> WeatherMarket:
    return WeatherMarket(
        market_id="m1",
        condition_id="c1",
        question="Will the highest temperature in Warsaw be 13°C or higher on March 24?",
        city="Warsaw",
        threshold_celsius=13.0,
        direction="above",
        bucket_type="above",
        resolution_date=datetime(2026, 3, 24, tzinfo=timezone.utc),
        yes_token_id="y1",
        no_token_id="n1",
        market_implied_prob=market_prob,
        liquidity_usd=2500.0,
        volume_usd=10000.0,
        end_date=datetime(2026, 3, 24, 12, tzinfo=timezone.utc),
    )


def make_forecast(model_prob: float = 0.78) -> WeatherForecast:
    return WeatherForecast(
        city="Warsaw",
        resolution_date=datetime(2026, 3, 24, tzinfo=timezone.utc),
        threshold_celsius=13.0,
        direction="above",
        model_probability=model_prob,
        ensemble_member_count=51,
        forecast_model="ecmwf_ifs025",
        raw_temperatures=[12.0, 13.5, 14.0, 13.0],
    )


class TestComputeEdge:
    def test_positive_edge(self):
        assert compute_edge(0.62, 0.78) == pytest.approx(0.16)

    def test_negative_edge(self):
        assert compute_edge(0.80, 0.65) == pytest.approx(-0.15)

    def test_zero_edge(self):
        assert compute_edge(0.50, 0.50) == pytest.approx(0.0)

    def test_edge_preserves_sign(self):
        assert compute_edge(0.99, 0.98) < 0


class TestComputeExpectedValue:
    def test_positive_ev(self):
        # model_prob=0.78, price=0.62 → EV = 0.78/0.62 - 1 = 0.2581
        ev = compute_expected_value(0.78, 0.62)
        assert ev == pytest.approx(0.2581, abs=1e-3)

    def test_zero_ev_at_fair_price(self):
        # If model agrees with market, EV = model/price - 1 = p/p - 1 = 0
        ev = compute_expected_value(0.60, 0.60)
        assert ev == pytest.approx(0.0, abs=1e-9)

    def test_negative_ev(self):
        # model < market price → negative EV
        ev = compute_expected_value(0.40, 0.60)
        assert ev < 0

    def test_edge_case_price_zero(self):
        assert compute_expected_value(0.5, 0.0) == 0.0

    def test_edge_case_price_one(self):
        assert compute_expected_value(0.5, 1.0) == 0.0


class TestComputeKellyFraction:
    def test_positive_kelly(self):
        # market=0.62, model=0.78
        # b = 1/0.62 - 1 = 0.6129
        # Kelly = (0.6129*0.78 - 0.22) / 0.6129 = (0.4781 - 0.22) / 0.6129
        kelly = compute_kelly_fraction(0.78, 0.62)
        assert kelly == pytest.approx(0.421, abs=1e-2)

    def test_negative_kelly_no_edge(self):
        # model < market → negative kelly
        kelly = compute_kelly_fraction(0.40, 0.70)
        assert kelly < 0

    def test_zero_kelly_at_fair_price(self):
        kelly = compute_kelly_fraction(0.50, 0.50)
        assert kelly == pytest.approx(0.0, abs=1e-9)

    def test_invalid_price_zero(self):
        assert compute_kelly_fraction(0.5, 0.0) == 0.0

    def test_invalid_price_one(self):
        assert compute_kelly_fraction(0.5, 1.0) == 0.0


class TestAnalyzeMarket:
    def test_produces_opportunity_result(self):
        result = analyze_market(make_market(0.62), make_forecast(0.78))
        assert isinstance(result, OpportunityResult)
        assert result.edge == pytest.approx(0.16)
        assert result.expected_value > 0
        assert result.kelly_fraction > 0

    def test_alert_triggered_above_threshold(self):
        result = analyze_market(make_market(0.60), make_forecast(0.80))
        assert result.alert is True  # edge = 0.20 > 0.05 threshold

    def test_no_alert_below_threshold(self):
        result = analyze_market(make_market(0.60), make_forecast(0.62))
        assert result.alert is False  # edge = 0.02 < 0.05 threshold

    def test_suggested_bet_is_capped(self):
        # Extreme edge: model=0.99, market=0.01 → huge raw Kelly
        result = analyze_market(make_market(0.01), make_forecast(0.99))
        assert result.suggested_bet_fraction <= 0.25  # MAX_KELLY_FRACTION cap


class TestRankOpportunities:
    def _make_result(self, edge: float, ev: float, kelly: float) -> OpportunityResult:
        return OpportunityResult(
            market=make_market(),
            forecast=make_forecast(),
            edge=edge,
            expected_value=ev,
            kelly_fraction=kelly,
            suggested_bet_fraction=kelly * 0.25,
            alert=edge > 0.05,
        )

    def test_sorted_descending_by_ev(self):
        r1 = self._make_result(0.10, 0.15, 0.20)
        r2 = self._make_result(0.20, 0.30, 0.35)
        r3 = self._make_result(0.05, 0.08, 0.10)
        ranked = rank_opportunities([r1, r2, r3], by="expected_value")
        assert ranked[0].expected_value == 0.30
        assert ranked[-1].expected_value == 0.08

    def test_filters_negative_ev(self):
        r1 = self._make_result(-0.05, -0.08, -0.10)
        r2 = self._make_result(0.10, 0.15, 0.20)
        ranked = rank_opportunities([r1, r2])
        assert len(ranked) == 1
        assert ranked[0].expected_value == 0.15

    def test_does_not_mutate_input(self):
        r1 = self._make_result(0.10, 0.15, 0.20)
        r2 = self._make_result(0.20, 0.30, 0.35)
        original = [r1, r2]
        rank_opportunities(original)
        assert original[0] is r1  # original unchanged

    def test_rank_by_edge(self):
        r1 = self._make_result(0.05, 0.20, 0.15)
        r2 = self._make_result(0.15, 0.10, 0.12)
        ranked = rank_opportunities([r1, r2], by="edge")
        assert ranked[0].edge == 0.15
