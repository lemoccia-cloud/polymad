"""Tests for Polymarket client — market parsing (pure) and HTTP (mocked)."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.data.polymarket_client import (
    parse_weather_market,
    PolymarketClient,
    PolymarketAPIError,
    _month_name_to_int,
)
from src.models.market import WeatherMarket


def make_raw_market(**overrides) -> dict:
    base = {
        "id": "abc123",
        "conditionId": "cond456",
        "question": "Will the highest temperature in Warsaw be 13°C or higher on March 24?",
        "endDate": "2026-03-24T12:00:00Z",
        "clobTokenIds": ["token_yes", "token_no"],
        "outcomePrices": ["0.62", "0.38"],
        "liquidity": "2500.0",
        "volume": "10000.0",
    }
    base.update(overrides)
    return base


class TestParseWeatherMarket:
    def test_valid_above_market(self):
        raw = make_raw_market()
        result = parse_weather_market(raw, end_date_str="2026-03-24T12:00:00Z")
        assert isinstance(result, WeatherMarket)
        assert result.city == "Warsaw"
        assert result.threshold_celsius == 13.0
        assert result.direction == "above"
        assert result.bucket_type == "above"
        assert result.market_implied_prob == pytest.approx(0.62)
        assert result.resolution_date.year == 2026
        assert result.resolution_date.month == 3
        assert result.resolution_date.day == 24

    def test_valid_below_market(self):
        raw = make_raw_market(
            question="Will the highest temperature in Berlin be 5°C or below on March 25?",
            outcomePrices=["0.45", "0.55"],
        )
        result = parse_weather_market(raw, end_date_str="2026-03-25T12:00:00Z")
        assert result is not None
        assert result.city == "Berlin"
        assert result.threshold_celsius == 5.0
        assert result.direction == "below"
        assert result.bucket_type == "below"

    def test_valid_exact_market(self):
        raw = make_raw_market(
            question="Will the highest temperature in Beijing be 18°C on March 28?",
            outcomePrices=["0.175", "0.825"],
        )
        result = parse_weather_market(raw, end_date_str="2026-03-28T12:00:00Z")
        assert result is not None
        assert result.city == "Beijing"
        assert result.threshold_celsius == 18.0
        assert result.direction == "exact"
        assert result.bucket_type == "exact"

    def test_negative_threshold(self):
        raw = make_raw_market(
            question="Will the highest temperature in Oslo be -3°C or below on January 10?",
            outcomePrices=["0.30", "0.70"],
        )
        result = parse_weather_market(raw, end_date_str="2026-01-10T12:00:00Z")
        assert result is not None
        assert result.threshold_celsius == -3.0
        assert result.direction == "below"

    def test_city_with_spaces(self):
        raw = make_raw_market(
            question="Will the highest temperature in San Francisco be 20°C or higher on June 15?",
            outcomePrices=["0.55", "0.45"],
        )
        result = parse_weather_market(raw, end_date_str="2026-06-15T12:00:00Z")
        assert result is not None
        assert result.city == "San Francisco"

    def test_old_format_returns_none(self):
        raw = make_raw_market(question="Warsaw: Will the high temperature be 13°C or higher on March 24?")
        result = parse_weather_market(raw, end_date_str="2026-03-24T12:00:00Z")
        assert result is None

    def test_non_weather_market_returns_none(self):
        raw = make_raw_market(question="Will Bitcoin exceed $100,000 by December 31?")
        result = parse_weather_market(raw)
        assert result is None

    def test_invalid_end_date_returns_none(self):
        raw = make_raw_market()
        result = parse_weather_market(raw, end_date_str="not-a-date")
        assert result is None

    def test_yes_price_from_outcome_prices(self):
        raw = make_raw_market(outcomePrices=["0.73", "0.27"])
        result = parse_weather_market(raw, end_date_str="2026-03-24T12:00:00Z")
        assert result.market_implied_prob == pytest.approx(0.73)

    def test_event_title_stored(self):
        raw = make_raw_market()
        result = parse_weather_market(raw, event_title="Warsaw Temp March 24", end_date_str="2026-03-24T12:00:00Z")
        assert result.event_title == "Warsaw Temp March 24"


class TestMonthNameToInt:
    def test_all_months(self):
        months = [
            ("January", 1), ("February", 2), ("March", 3), ("April", 4),
            ("May", 5), ("June", 6), ("July", 7), ("August", 8),
            ("September", 9), ("October", 10), ("November", 11), ("December", 12),
        ]
        for name, expected in months:
            assert _month_name_to_int(name) == expected

    def test_case_insensitive(self):
        assert _month_name_to_int("march") == 3
        assert _month_name_to_int("DECEMBER") == 12

    def test_unknown_month_raises(self):
        with pytest.raises(ValueError):
            _month_name_to_int("Octember")


class TestPolymarketClient:
    def _mock_events_response(self, title: str = "Highest temperature in Warsaw on March 24?") -> dict:
        return {
            "title": title,
            "endDate": "2026-03-24T12:00:00Z",
            "startDate": "2026-03-24T10:00:00Z",
            "markets": [
                {
                    "id": "m1",
                    "conditionId": "cond1",
                    "question": "Will the highest temperature in Warsaw be 13°C or higher on March 24?",
                    "outcomePrices": ["0.62", "0.38"],
                    "outcomes": ["Yes", "No"],
                    "clobTokenIds": ["y1", "n1"],
                    "liquidity": "1500.0",
                    "volume": "5000.0",
                }
            ],
        }

    def test_fetch_weather_markets_parses_events(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [self._mock_events_response()]
        mock_session.get.return_value = mock_response

        client = PolymarketClient(session=mock_session)
        results = client.fetch_weather_markets()
        # Should return list of (market_dict, event_title, end_date, event_slug) tuples
        assert len(results) == 1
        mkt, title, end_date, *_ = results[0]
        assert "Warsaw" in mkt.get("question", "")
        assert "Warsaw" in title

    def test_get_clob_price_parses_yes_token(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "tokens": [
                {"outcome": "Yes", "price": 0.73},
                {"outcome": "No", "price": 0.27},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        client = PolymarketClient(session=mock_session)
        price = client.get_clob_price("cond123")
        assert price == pytest.approx(0.73)

    def test_get_clob_price_returns_none_on_empty(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"tokens": []}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        client = PolymarketClient(session=mock_session)
        price = client.get_clob_price("cond123")
        assert price is None
