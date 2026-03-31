"""
Unit tests for src/bot/formatters.py

Tests format functions for Telegram messages — no network calls, no Telegram SDK needed.
"""
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot.formatters import (
    format_alerts_message,
    format_help_message,
    format_no_alerts_message,
    format_single_alert,
    format_start_message,
    format_subscribe_message,
    format_unsubscribe_message,
)


# ---------------------------------------------------------------------------
# Minimal stubs — mirror production dataclasses without importing them
# ---------------------------------------------------------------------------

@dataclass
class _Forecast:
    model_probability: float = 0.6
    market_type: str = "weather"
    source: str = "baseline"
    metaculus_title: str = ""
    metaculus_id: Optional[int] = None


@dataclass
class _WeatherMarket:
    market_type: str = "weather"
    city: str = "Paris"
    threshold_celsius: float = 30.0
    bucket_type: str = "above"
    market_implied_prob: float = 0.32
    resolution_date: datetime = field(
        default_factory=lambda: datetime(2026, 4, 15, tzinfo=timezone.utc)
    )
    liquidity_usd: float = 1500.0
    question: str = "Will Paris exceed 30°C?"
    event_slug: str = "paris-weather-april"
    condition_id: str = "abc123"


@dataclass
class _CryptoMarket:
    market_type: str = "crypto"
    asset: str = "BTC"
    threshold_usd: float = 90_000.0
    direction: str = "above"
    market_implied_prob: float = 0.40
    resolution_date: datetime = field(
        default_factory=lambda: datetime(2026, 4, 30, tzinfo=timezone.utc)
    )
    liquidity_usd: float = 5000.0
    question: str = "Will BTC be above $90k?"
    event_slug: str = "btc-90k-april"
    condition_id: str = "def456"


@dataclass
class _SportsMarket:
    market_type: str = "sports"
    home_team: str = "Arsenal"
    away_team: str = "Chelsea"
    market_implied_prob: float = 0.50
    resolution_date: datetime = field(
        default_factory=lambda: datetime(2026, 4, 20, tzinfo=timezone.utc)
    )
    liquidity_usd: float = 3000.0
    question: str = "Will Arsenal win?"
    event_slug: str = "arsenal-chelsea"
    condition_id: str = "ghi789"


@dataclass
class _PoliticsMarket:
    market_type: str = "politics"
    topic: str = "US Presidential Election 2024: Will Biden win?"
    market_implied_prob: float = 0.45
    resolution_date: datetime = field(
        default_factory=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc)
    )
    liquidity_usd: float = 10_000.0
    question: str = "Will Biden win the 2024 election?"
    event_slug: str = "us-election-2024"
    condition_id: str = "pol001"


@dataclass
class _Result:
    market: object
    forecast: object = field(default_factory=_Forecast)
    edge: float = 0.18
    expected_value: float = 1.45
    suggested_bet_fraction: float = 0.05
    alert: bool = True


def _make_result(**kwargs) -> _Result:
    return _Result(**kwargs)


# ---------------------------------------------------------------------------
# format_single_alert
# ---------------------------------------------------------------------------

class TestFormatSingleAlert:
    def test_weather_contains_city(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_single_alert(r)
        assert "Paris" in msg

    def test_weather_contains_edge(self):
        r = _make_result(market=_WeatherMarket(), edge=0.18)
        msg = format_single_alert(r)
        assert "+18.0%" in msg or "18" in msg

    def test_crypto_contains_asset(self):
        r = _make_result(market=_CryptoMarket())
        msg = format_single_alert(r)
        assert "BTC" in msg

    def test_sports_contains_teams(self):
        r = _make_result(market=_SportsMarket())
        msg = format_single_alert(r)
        assert "Arsenal" in msg
        assert "Chelsea" in msg

    def test_politics_contains_topic(self):
        r = _make_result(market=_PoliticsMarket())
        msg = format_single_alert(r)
        assert "US Presidential" in msg or "Biden" in msg or "POLÍTICA" in msg

    def test_contains_polymarket_url(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_single_alert(r)
        assert "polymarket.com" in msg

    def test_contains_kelly_usd(self):
        r = _make_result(market=_WeatherMarket(), suggested_bet_fraction=0.05)
        msg = format_single_alert(r, bankroll=1000.0)
        assert "$50" in msg  # 1000 * 0.05

    def test_no_event_slug_uses_markets_url(self):
        mkt = _WeatherMarket()
        mkt.event_slug = ""
        r = _make_result(market=mkt)
        msg = format_single_alert(r)
        assert "polymarket.com/markets" in msg

    def test_resolution_date_shown(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_single_alert(r)
        assert "2026" in msg or "Apr" in msg or "Abr" in msg


# ---------------------------------------------------------------------------
# format_alerts_message
# ---------------------------------------------------------------------------

class TestFormatAlertsMessage:
    def test_empty_list_returns_empty_string(self):
        assert format_alerts_message([], edge_threshold=0.10) == ""

    def test_single_alert_contains_header(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_alerts_message([r], edge_threshold=0.10)
        assert "polyMad" in msg
        assert "1 alerta" in msg

    def test_plural_header(self):
        alerts = [
            _make_result(market=_WeatherMarket()),
            _make_result(market=_CryptoMarket()),
        ]
        msg = format_alerts_message(alerts, edge_threshold=0.10)
        assert "2 alertas" in msg

    def test_max_alerts_limits_output(self):
        alerts = [_make_result(market=_WeatherMarket()) for _ in range(20)]
        msg = format_alerts_message(alerts, edge_threshold=0.10, max_alerts=5)
        # Should only show 5 blocks (5 separators)
        assert msg.count("━━━━━━━━━━━━━━━━━━") == 5

    def test_is_digest_adds_footer(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_alerts_message([r], edge_threshold=0.10, is_digest=True)
        assert "unsubscribe" in msg

    def test_not_digest_no_footer(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_alerts_message([r], edge_threshold=0.10, is_digest=False)
        assert "unsubscribe" not in msg

    def test_edge_threshold_in_header(self):
        r = _make_result(market=_WeatherMarket())
        msg = format_alerts_message([r], edge_threshold=0.15)
        assert "15%" in msg


# ---------------------------------------------------------------------------
# Static message functions
# ---------------------------------------------------------------------------

class TestStaticMessages:
    def test_start_message_not_empty(self):
        msg = format_start_message()
        assert len(msg) > 50
        assert "polyMad" in msg

    def test_help_message_contains_commands(self):
        msg = format_help_message()
        assert "/alerts" in msg
        assert "/subscribe" in msg
        assert "/unsubscribe" in msg

    def test_no_alerts_message_contains_threshold(self):
        msg = format_no_alerts_message(edge_threshold=0.10)
        assert "10%" in msg

    def test_subscribe_message_contains_threshold(self):
        msg = format_subscribe_message(edge_threshold=0.12)
        assert "12%" in msg

    def test_unsubscribe_message_not_empty(self):
        msg = format_unsubscribe_message()
        assert len(msg) > 10
