"""Tests for src/components/filters.py — pure functions only (no Streamlit)."""
import csv
import io
from datetime import datetime, timezone, timedelta

import pytest

from src.components.filters import apply_filters, results_to_csv, _market_label, _search_corpus
from src.models.market import (
    WeatherMarket, WeatherForecast,
    CryptoMarket, CryptoForecast,
    SportsMarket, SportsForecast,
    PoliticsMarket, PoliticsForecast,
    OpportunityResult,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

_NOW = datetime.now(tz=timezone.utc)
_SOON = _NOW + timedelta(days=3)
_FAR = _NOW + timedelta(days=60)


def make_weather_result(
    market_prob: float = 0.55,
    model_prob: float = 0.70,
    liquidity: float = 3000.0,
    resolution_date: datetime = None,
    city: str = "Berlin",
    threshold: float = 20.0,
) -> OpportunityResult:
    if resolution_date is None:
        resolution_date = _SOON
    edge = model_prob - market_prob
    market = WeatherMarket(
        market_id="m-w1",
        condition_id="c-w1",
        question=f"Will it be ≥{threshold}°C in {city}?",
        city=city,
        threshold_celsius=threshold,
        direction="above",
        bucket_type="above",
        resolution_date=resolution_date,
        yes_token_id="y1",
        no_token_id="n1",
        market_implied_prob=market_prob,
        liquidity_usd=liquidity,
        volume_usd=10000.0,
        end_date=resolution_date,
    )
    forecast = WeatherForecast(
        city=city,
        resolution_date=resolution_date,
        threshold_celsius=threshold,
        direction="above",
        model_probability=model_prob,
        ensemble_member_count=51,
        forecast_model="ecmwf_ifs025",
        raw_temperatures=[19.0, 21.0, 22.0],
    )
    return OpportunityResult(
        market=market,
        forecast=forecast,
        edge=edge,
        expected_value=edge / market_prob if market_prob > 0 else 0,
        kelly_fraction=edge / (1 - market_prob) if market_prob < 1 else 0,
        suggested_bet_fraction=min(0.25, edge / (1 - market_prob)) if market_prob < 1 else 0,
        alert=edge > 0.05,
    )


def make_crypto_result(
    market_prob: float = 0.48,
    model_prob: float = 0.62,
    liquidity: float = 8000.0,
    resolution_date: datetime = None,
    asset: str = "BTC",
    threshold_usd: float = 100_000.0,
) -> OpportunityResult:
    if resolution_date is None:
        resolution_date = _SOON
    edge = model_prob - market_prob
    market = CryptoMarket(
        market_id="m-c1",
        condition_id="c-c1",
        question=f"Will {asset} be above ${threshold_usd:,.0f}?",
        asset=asset,
        asset_name="Bitcoin" if asset == "BTC" else asset,
        threshold_usd=threshold_usd,
        direction="above",
        resolution_date=resolution_date,
        yes_token_id="y2",
        no_token_id="n2",
        market_implied_prob=market_prob,
        liquidity_usd=liquidity,
        volume_usd=50000.0,
        end_date=resolution_date,
    )
    forecast = CryptoForecast(
        asset=asset,
        resolution_date=resolution_date,
        threshold_usd=threshold_usd,
        direction="above",
        model_probability=model_prob,
        spot_price=95_000.0,
        sigma_annual=0.75,
        days_to_expiry=3,
    )
    return OpportunityResult(
        market=market,
        forecast=forecast,
        edge=edge,
        expected_value=edge / market_prob if market_prob > 0 else 0,
        kelly_fraction=edge / (1 - market_prob) if market_prob < 1 else 0,
        suggested_bet_fraction=min(0.25, edge / (1 - market_prob)) if market_prob < 1 else 0,
        alert=edge > 0.05,
    )


def make_sports_result(
    market_prob: float = 0.40,
    model_prob: float = 0.55,
    liquidity: float = 5000.0,
    resolution_date: datetime = None,
    home_team: str = "Real Madrid",
    away_team: str = "Barcelona",
) -> OpportunityResult:
    if resolution_date is None:
        resolution_date = _SOON
    edge = model_prob - market_prob
    market = SportsMarket(
        market_id="m-s1",
        condition_id="c-s1",
        question=f"Will {home_team} beat {away_team}?",
        home_team=home_team,
        away_team=away_team,
        sport="football",
        outcome="home_win",
        resolution_date=resolution_date,
        yes_token_id="y3",
        no_token_id="n3",
        market_implied_prob=market_prob,
        liquidity_usd=liquidity,
        volume_usd=20000.0,
        end_date=resolution_date,
    )
    forecast = SportsForecast(
        home_team=home_team,
        away_team=away_team,
        outcome="home_win",
        model_probability=model_prob,
        elo_home=1820.0,
        elo_away=1790.0,
        source="clubelo",
    )
    return OpportunityResult(
        market=market,
        forecast=forecast,
        edge=edge,
        expected_value=edge / market_prob if market_prob > 0 else 0,
        kelly_fraction=edge / (1 - market_prob) if market_prob < 1 else 0,
        suggested_bet_fraction=min(0.25, edge / (1 - market_prob)) if market_prob < 1 else 0,
        alert=edge > 0.05,
    )


def make_politics_result(
    market_prob: float = 0.35,
    model_prob: float = 0.50,
    liquidity: float = 2000.0,
    resolution_date: datetime = None,
    topic: str = "Will candidate X win the election?",
) -> OpportunityResult:
    if resolution_date is None:
        resolution_date = _SOON
    edge = model_prob - market_prob
    market = PoliticsMarket(
        market_id="m-p1",
        condition_id="c-p1",
        question=topic,
        topic=topic,
        resolution_date=resolution_date,
        yes_token_id="y4",
        no_token_id="n4",
        market_implied_prob=market_prob,
        liquidity_usd=liquidity,
        volume_usd=5000.0,
        end_date=resolution_date,
    )
    forecast = PoliticsForecast(
        topic=topic,
        model_probability=model_prob,
        source="baseline",
    )
    return OpportunityResult(
        market=market,
        forecast=forecast,
        edge=edge,
        expected_value=edge / market_prob if market_prob > 0 else 0,
        kelly_fraction=edge / (1 - market_prob) if market_prob < 1 else 0,
        suggested_bet_fraction=min(0.25, edge / (1 - market_prob)) if market_prob < 1 else 0,
        alert=edge > 0.05,
    )


# ─── TestMarketLabel ──────────────────────────────────────────────────────────

class TestMarketLabel:
    def test_weather_above(self):
        r = make_weather_result(city="Berlin", threshold=20.0)
        label = _market_label(r.market)
        assert "Berlin" in label
        assert "20" in label
        assert "≥" in label

    def test_weather_below(self):
        r = make_weather_result(city="Oslo")
        r.market.bucket_type = "below"
        label = _market_label(r.market)
        assert "≤" in label

    def test_crypto_above(self):
        r = make_crypto_result(asset="BTC", threshold_usd=100_000)
        label = _market_label(r.market)
        assert "BTC" in label
        assert "100,000" in label
        assert "≥" in label

    def test_sports(self):
        r = make_sports_result(home_team="Real Madrid", away_team="Barcelona")
        label = _market_label(r.market)
        assert "Real Madrid" in label
        assert "Barcelona" in label
        assert "vs" in label

    def test_politics(self):
        topic = "Will candidate X win?"
        r = make_politics_result(topic=topic)
        label = _market_label(r.market)
        assert label == topic


# ─── TestApplyFilters ─────────────────────────────────────────────────────────

class TestApplyFilters:
    def _make_results(self):
        return [
            make_weather_result(liquidity=1000.0, market_prob=0.55, model_prob=0.70),
            make_crypto_result(liquidity=8000.0, market_prob=0.48, model_prob=0.62),
            make_sports_result(liquidity=5000.0, market_prob=0.40, model_prob=0.55),
        ]

    def test_no_filters_returns_all(self):
        results = self._make_results()
        out = apply_filters(results)
        assert len(out) == 3

    def test_filter_by_min_edge(self):
        results = self._make_results()
        # edges: 0.15, 0.14, 0.15 → all above 10%
        out = apply_filters(results, min_edge_pct=10.0)
        assert len(out) == 3

        out2 = apply_filters(results, min_edge_pct=20.0)
        assert len(out2) == 0

    def test_filter_by_min_liquidity(self):
        results = self._make_results()
        out = apply_filters(results, min_liquidity=4000.0)
        assert len(out) == 2  # crypto (8000) + sports (5000)

    def test_filter_by_max_days(self):
        near = make_weather_result(resolution_date=_NOW + timedelta(days=2))
        far = make_weather_result(resolution_date=_NOW + timedelta(days=50))
        out = apply_filters([near, far], max_days=5)
        assert len(out) == 1
        assert out[0] is near

    def test_filter_by_search_city(self):
        r1 = make_weather_result(city="Berlin")
        r2 = make_weather_result(city="Tokyo")
        out = apply_filters([r1, r2], search="berlin")
        assert len(out) == 1
        assert out[0] is r1

    def test_filter_by_search_asset(self):
        r_btc = make_crypto_result(asset="BTC")
        r_eth = make_crypto_result(asset="ETH")
        r_eth.market.asset_name = "Ethereum"
        out = apply_filters([r_btc, r_eth], search="bitcoin")
        assert len(out) == 1
        assert out[0] is r_btc

    def test_filter_by_search_team(self):
        results = [
            make_sports_result(home_team="Real Madrid", away_team="Barcelona"),
            make_sports_result(home_team="Bayern", away_team="Dortmund"),
        ]
        out = apply_filters(results, search="madrid")
        assert len(out) == 1

    def test_filter_combined(self):
        results = [
            make_weather_result(liquidity=500.0, market_prob=0.55, model_prob=0.70),   # edge 15%, liq 500
            make_crypto_result(liquidity=8000.0, market_prob=0.48, model_prob=0.62),   # edge 14%, liq 8000
        ]
        out = apply_filters(results, min_liquidity=1000.0, min_edge_pct=10.0)
        assert len(out) == 1
        assert out[0].market.market_type == "crypto"

    def test_empty_input(self):
        assert apply_filters([]) == []


# ─── TestResultsToCsv ─────────────────────────────────────────────────────────

class TestResultsToCsv:
    def _parse_csv(self, csv_str: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(csv_str))
        return list(reader)

    def test_header_columns(self):
        csv_str = results_to_csv([], bankroll=1000.0)
        reader = csv.reader(io.StringIO(csv_str))
        header = next(reader)
        assert "Type" in header
        assert "Market" in header
        assert "Edge %" in header
        assert "Kelly %" in header
        assert "Bet $" in header

    def test_empty_list_only_header(self):
        csv_str = results_to_csv([], bankroll=1000.0)
        rows = self._parse_csv(csv_str)
        assert rows == []

    def test_weather_row_values(self):
        r = make_weather_result(market_prob=0.55, model_prob=0.70)
        csv_str = results_to_csv([r], bankroll=1000.0)
        rows = self._parse_csv(csv_str)
        assert len(rows) == 1
        row = rows[0]
        assert row["Type"] == "Weather"
        assert "Berlin" in row["Market"]
        assert float(row["Edge %"]) == pytest.approx(15.0, abs=0.1)
        assert float(row["Mkt Prob %"]) == pytest.approx(55.0, abs=0.1)
        assert float(row["Model Prob %"]) == pytest.approx(70.0, abs=0.1)

    def test_multiple_types(self):
        results = [
            make_weather_result(),
            make_crypto_result(),
            make_sports_result(),
            make_politics_result(),
        ]
        csv_str = results_to_csv(results, bankroll=500.0)
        rows = self._parse_csv(csv_str)
        assert len(rows) == 4
        types = {row["Type"] for row in rows}
        assert types == {"Weather", "Crypto", "Sports", "Politics"}
