"""Tests for crypto_client — lognormal math (pure) and CoinGecko HTTP (mocked)."""
import pytest
import requests
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.data.crypto_client import (
    CryptoClient,
    CryptoAPIError,
    lognormal_prob,
    _get_spot_price,
    _get_historical_volatility,
)
from src.data.polymarket_client import (
    _parse_threshold_usd,
    parse_crypto_market,
)
from src.models.market import CryptoMarket, CryptoForecast


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_raw_crypto(**overrides) -> dict:
    base = {
        "id": "c1",
        "conditionId": "cond1",
        "question": "Will Bitcoin exceed $90,000 by March 31?",
        "endDate": "2026-03-31T12:00:00Z",
        "clobTokenIds": ["y1", "n1"],
        "outcomePrices": ["0.35", "0.65"],
        "liquidity": "5000.0",
        "volume": "20000.0",
        "slug": "btc-90k",
    }
    base.update(overrides)
    return base


def make_mock_session(spot: float, prices: list) -> MagicMock:
    """Return a mock session that serves CoinGecko spot + market_chart responses."""
    coin_id = "bitcoin"

    def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "simple/price" in url:
            resp.json.return_value = {coin_id: {"usd": spot}}
        elif "market_chart" in url:
            # Build plausible daily prices from `prices` list
            resp.json.return_value = {
                "prices": [[i * 86400000, p] for i, p in enumerate(prices)]
            }
        else:
            resp.json.return_value = {}
        return resp

    mock_session = MagicMock()
    mock_session.get.side_effect = fake_get
    return mock_session


# ─── TestLognormalProb ────────────────────────────────────────────────────────

class TestLognormalProb:
    def test_atm_near_50_above(self):
        # spot == target, short horizon → near 50%
        p = lognormal_prob(100, 100, 0.80, 1, "above")
        assert 0.35 < p < 0.65

    def test_deep_otm_above_is_low(self):
        # spot 50k, target 200k, only 5 days → negligible prob
        p = lognormal_prob(50_000, 200_000, 0.60, 5, "above")
        assert p < 0.10

    def test_deep_itm_above_is_high(self):
        # spot 200k, target 50k → very likely to be above
        p = lognormal_prob(200_000, 50_000, 0.60, 5, "above")
        assert p > 0.90

    def test_above_below_sum_to_one(self):
        pa = lognormal_prob(82_000, 90_000, 0.60, 30, "above")
        pb = lognormal_prob(82_000, 90_000, 0.60, 30, "below")
        assert pa + pb == pytest.approx(1.0, abs=1e-6)

    def test_zero_days_no_crash(self):
        # days=0 should clamp to 1 internally — no ZeroDivisionError
        p = lognormal_prob(100, 110, 0.50, 0, "above")
        assert 0.0 <= p <= 1.0

    def test_longer_horizon_more_uncertainty(self):
        # With higher T, OTM option has higher probability
        p_short = lognormal_prob(82_000, 90_000, 0.60, 3, "above")
        p_long = lognormal_prob(82_000, 90_000, 0.60, 90, "above")
        assert p_long > p_short

    def test_higher_volatility_more_uncertainty(self):
        # Higher sigma → higher prob for OTM "above"
        p_low_vol = lognormal_prob(80_000, 100_000, 0.20, 30, "above")
        p_high_vol = lognormal_prob(80_000, 100_000, 0.80, 30, "above")
        assert p_high_vol > p_low_vol

    def test_result_clamped_between_zero_and_one(self):
        p = lognormal_prob(1, 1_000_000, 0.01, 1, "above")
        assert 0.0 <= p <= 1.0

    def test_invalid_spot_returns_half(self):
        assert lognormal_prob(0, 90_000, 0.60, 30, "above") == 0.5

    def test_invalid_sigma_returns_half(self):
        assert lognormal_prob(82_000, 90_000, 0.0, 30, "above") == 0.5


# ─── TestParseThresholdUsd ────────────────────────────────────────────────────

class TestParseThresholdUsd:
    def test_k_lowercase(self):
        assert _parse_threshold_usd("90", "k") == pytest.approx(90_000.0)

    def test_k_uppercase(self):
        assert _parse_threshold_usd("75", "K") == pytest.approx(75_000.0)

    def test_m_lowercase(self):
        assert _parse_threshold_usd("1.5", "m") == pytest.approx(1_500_000.0)

    def test_m_uppercase(self):
        assert _parse_threshold_usd("2", "M") == pytest.approx(2_000_000.0)

    def test_no_suffix(self):
        assert _parse_threshold_usd("3500", "") == pytest.approx(3_500.0)

    def test_comma_separated(self):
        # "90,000" with no unit → 90000
        assert _parse_threshold_usd("90,000", "") == pytest.approx(90_000.0)

    def test_decimal_with_k(self):
        assert _parse_threshold_usd("1.25", "k") == pytest.approx(1_250.0)


# ─── TestParseCryptoMarket ────────────────────────────────────────────────────

class TestParseCryptoMarket:
    def test_bitcoin_exceed(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will Bitcoin exceed $90,000 by March 31?"))
        assert m is not None
        assert m.asset == "BTC"
        assert m.direction == "above"
        assert m.threshold_usd == pytest.approx(90_000.0)

    def test_eth_be_above(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will ETH be above $3,500 on April 5?"))
        assert m is not None
        assert m.asset == "ETH"
        assert m.direction == "above"
        assert m.threshold_usd == pytest.approx(3_500.0)

    def test_btc_drop_below_k_suffix(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will BTC drop below $75k?"))
        assert m is not None
        assert m.asset == "BTC"
        assert m.direction == "below"
        assert m.threshold_usd == pytest.approx(75_000.0)

    def test_solana_surpass(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will Solana surpass $200 by May 1?"))
        assert m is not None
        assert m.asset == "SOL"
        assert m.direction == "above"

    def test_doge_reach(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will Dogecoin reach $1 by December 31?"))
        assert m is not None
        assert m.asset == "DOGE"
        assert m.threshold_usd == pytest.approx(1.0)

    def test_non_crypto_returns_none(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will Real Madrid beat Barcelona on April 5?"))
        assert m is None

    def test_weather_question_returns_none(self):
        m = parse_crypto_market(make_raw_crypto(
            question="Will the highest temperature in Warsaw be 13°C or higher on March 24?"))
        assert m is None

    def test_market_type_is_crypto(self):
        m = parse_crypto_market(make_raw_crypto())
        assert m is not None
        assert m.market_type == "crypto"

    def test_implied_prob_from_prices(self):
        m = parse_crypto_market(make_raw_crypto(outcomePrices=["0.42", "0.58"]))
        assert m is not None
        assert m.market_implied_prob == pytest.approx(0.42)

    def test_event_title_stored(self):
        m = parse_crypto_market(make_raw_crypto(), event_title="Crypto Weekly")
        assert m is not None
        assert m.event_title == "Crypto Weekly"

    def test_missing_end_date_returns_none(self):
        raw = make_raw_crypto(endDate="not-a-date")
        m = parse_crypto_market(raw)
        assert m is None


# ─── TestCryptoClient ─────────────────────────────────────────────────────────

class TestCryptoClient:
    # Build 31 synthetic daily prices with ~20% drift (realistic BTC history)
    _PRICES = [82_000.0 * (1 + 0.005 * i) for i in range(32)]

    def _make_client(self, spot: float = 82_000.0) -> CryptoClient:
        return CryptoClient(session=make_mock_session(spot, self._PRICES))

    def test_returns_crypto_forecast(self):
        client = self._make_client()
        fc = client.get_lognormal_forecast(
            asset="BTC",
            resolution_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
            threshold_usd=90_000.0,
            direction="above",
        )
        assert isinstance(fc, CryptoForecast)

    def test_forecast_has_correct_asset(self):
        client = self._make_client()
        fc = client.get_lognormal_forecast("BTC", datetime(2026, 4, 30, tzinfo=timezone.utc), 90_000.0, "above")
        assert fc.asset == "BTC"

    def test_forecast_spot_price_matches_api(self):
        client = self._make_client(spot=95_000.0)
        fc = client.get_lognormal_forecast("BTC", datetime(2026, 4, 30, tzinfo=timezone.utc), 90_000.0, "above")
        assert fc.spot_price == pytest.approx(95_000.0)

    def test_forecast_probability_in_range(self):
        client = self._make_client()
        fc = client.get_lognormal_forecast("BTC", datetime(2026, 4, 30, tzinfo=timezone.utc), 90_000.0, "above")
        assert 0.0 < fc.model_probability < 1.0

    def test_higher_spot_gives_higher_above_prob(self):
        fc_low = self._make_client(spot=70_000.0).get_lognormal_forecast(
            "BTC", datetime(2026, 4, 30, tzinfo=timezone.utc), 90_000.0, "above")
        fc_high = self._make_client(spot=95_000.0).get_lognormal_forecast(
            "BTC", datetime(2026, 4, 30, tzinfo=timezone.utc), 90_000.0, "above")
        assert fc_high.model_probability > fc_low.model_probability

    def test_api_error_raises_crypto_api_error(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("timeout")
        client = CryptoClient(session=mock_session)
        with pytest.raises(CryptoAPIError):
            client.get_lognormal_forecast(
                "BTC", datetime(2026, 4, 30, tzinfo=timezone.utc), 90_000.0, "above")

    def test_unknown_asset_raises(self):
        client = self._make_client()
        with pytest.raises((CryptoAPIError, ValueError)):
            client.get_lognormal_forecast(
                "UNKNOWN", datetime(2026, 4, 30, tzinfo=timezone.utc), 1000.0, "above")
