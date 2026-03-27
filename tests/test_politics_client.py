"""Tests for politics_client — Metaculus integration (mocked) and parser."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.data.politics_client import (
    PoliticsClient,
    _similarity,
)
from src.data.polymarket_client import parse_politics_market
from src.models.market import PoliticsMarket, PoliticsForecast


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_raw_politics(**overrides) -> dict:
    base = {
        "id": "p1",
        "conditionId": "cond3",
        "question": "Will Donald Trump win the 2026 midterms?",
        "endDate": "2026-11-04T00:00:00Z",
        "clobTokenIds": ["y1", "n1"],
        "outcomePrices": ["0.45", "0.55"],
        "liquidity": "3000.0",
        "volume": "12000.0",
        "slug": "trump-midterms",
    }
    base.update(overrides)
    return base


def make_metaculus_response(results: list) -> dict:
    """Build a Metaculus /questions/ API JSON response."""
    return {"results": results}


def make_metaculus_question(
    qid: int = 1,
    title: str = "Will Donald Trump win the 2026 midterms?",
    prob: float = 0.48,
) -> dict:
    return {
        "id": qid,
        "title": title,
        "community_prediction": {"full": {"q2": prob}},
    }


def make_mock_session(results: list) -> MagicMock:
    """Return a mock session that returns a Metaculus-style response."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = make_metaculus_response(results)
    mock_session.get.return_value = mock_response
    return mock_session


def resolution_dt() -> datetime:
    return datetime(2026, 11, 4, tzinfo=timezone.utc)


# ─── TestSimilarity ───────────────────────────────────────────────────────────

class TestSimilarity:
    def test_identical_strings(self):
        assert _similarity("foo bar", "foo bar") == pytest.approx(1.0)

    def test_completely_different(self):
        assert _similarity("hello", "xyz") < 0.5

    def test_case_insensitive(self):
        assert _similarity("Trump", "trump") == pytest.approx(1.0)

    def test_partial_overlap(self):
        s = _similarity(
            "Will Trump win the 2026 election?",
            "Will Trump win the 2026 US election?",
        )
        assert s > 0.7

    def test_result_in_zero_to_one(self):
        for a, b in [("a", "b"), ("foo", "foo"), ("long text here", "")]:
            assert 0.0 <= _similarity(a, b) <= 1.0


# ─── TestParsePoliticsMarket ──────────────────────────────────────────────────

class TestParsePoliticsMarket:
    def test_any_will_question_parses(self):
        m = parse_politics_market(make_raw_politics())
        assert m is not None
        assert isinstance(m, PoliticsMarket)

    def test_market_type_is_politics(self):
        m = parse_politics_market(make_raw_politics())
        assert m is not None
        assert m.market_type == "politics"

    def test_implied_prob_from_prices(self):
        m = parse_politics_market(make_raw_politics(outcomePrices=["0.52", "0.48"]))
        assert m is not None
        assert m.market_implied_prob == pytest.approx(0.52)

    def test_topic_contains_question(self):
        m = parse_politics_market(make_raw_politics())
        assert m is not None
        # Topic must include the original question text
        assert "Trump" in m.topic

    def test_weather_question_rejected(self):
        # Contains °C
        m = parse_politics_market(make_raw_politics(
            question="Will the highest temperature in Warsaw be 13°C or higher on March 24?"))
        assert m is None

    def test_crypto_question_rejected(self):
        # Contains $ sign
        m = parse_politics_market(make_raw_politics(
            question="Will Bitcoin exceed $90,000 by March 31?"))
        assert m is None

    def test_non_will_question_rejected(self):
        m = parse_politics_market(make_raw_politics(
            question="Is Donald Trump going to win?"))
        assert m is None

    def test_empty_question_returns_none(self):
        m = parse_politics_market(make_raw_politics(question=""))
        assert m is None

    def test_missing_end_date_returns_none(self):
        m = parse_politics_market(make_raw_politics(endDate="bad-date"))
        assert m is None

    def test_event_title_included_in_topic(self):
        m = parse_politics_market(
            make_raw_politics(), event_title="US 2026 Midterms")
        assert m is not None
        assert "US 2026 Midterms" in m.topic


# ─── TestPoliticsClient ───────────────────────────────────────────────────────

class TestPoliticsClient:
    def test_high_similarity_uses_metaculus_probability(self):
        topic = "Will Donald Trump win the 2026 midterms?"
        # Metaculus title is nearly identical → similarity above threshold
        results = [make_metaculus_question(title=topic, prob=0.42)]
        client = PoliticsClient(session=make_mock_session(results))
        fc = client.get_metaculus_forecast(topic=topic, resolution_date=resolution_dt())
        assert fc.source == "metaculus"
        assert fc.model_probability == pytest.approx(0.42)

    def test_low_similarity_uses_baseline(self):
        topic = "Will Donald Trump win the 2026 midterms?"
        # Metaculus title is about something completely unrelated
        results = [make_metaculus_question(title="Will the moon be full tonight?", prob=0.80)]
        client = PoliticsClient(session=make_mock_session(results))
        fc = client.get_metaculus_forecast(topic=topic, resolution_date=resolution_dt())
        assert fc.source == "baseline"
        assert fc.model_probability == pytest.approx(0.50)

    def test_empty_results_uses_baseline(self):
        client = PoliticsClient(session=make_mock_session([]))
        fc = client.get_metaculus_forecast(
            topic="Will anything happen?", resolution_date=resolution_dt())
        assert fc.source == "baseline"
        assert fc.model_probability == pytest.approx(0.50)

    def test_http_error_uses_baseline_no_crash(self):
        import requests as req
        mock_session = MagicMock()
        mock_session.get.side_effect = req.ConnectionError("timeout")
        client = PoliticsClient(session=mock_session)
        fc = client.get_metaculus_forecast(
            topic="Will Trump win?", resolution_date=resolution_dt())
        assert fc.source == "baseline"
        assert fc.model_probability == pytest.approx(0.50)

    def test_metaculus_id_stored(self):
        topic = "Will Donald Trump win the 2026 midterms?"
        results = [make_metaculus_question(qid=12345, title=topic, prob=0.55)]
        client = PoliticsClient(session=make_mock_session(results))
        fc = client.get_metaculus_forecast(topic=topic, resolution_date=resolution_dt())
        assert fc.source == "metaculus"
        assert fc.metaculus_id == 12345

    def test_none_q2_falls_back_to_baseline(self):
        topic = "Will Donald Trump win the 2026 midterms?"
        # q2 is None → no community prediction
        results = [{
            "id": 1,
            "title": topic,
            "community_prediction": {"full": {"q2": None}},
        }]
        client = PoliticsClient(session=make_mock_session(results))
        fc = client.get_metaculus_forecast(topic=topic, resolution_date=resolution_dt())
        assert fc.source == "baseline"
        assert fc.model_probability == pytest.approx(0.50)

    def test_probability_clamped_in_bounds(self):
        topic = "Will this market resolve Yes?"
        results = [make_metaculus_question(title=topic, prob=0.99)]
        client = PoliticsClient(session=make_mock_session(results))
        fc = client.get_metaculus_forecast(topic=topic, resolution_date=resolution_dt())
        assert 0.0 < fc.model_probability <= 0.99

    def test_returns_politics_forecast_instance(self):
        topic = "Will Donald Trump win the 2026 midterms?"
        results = [make_metaculus_question(title=topic, prob=0.48)]
        client = PoliticsClient(session=make_mock_session(results))
        fc = client.get_metaculus_forecast(topic=topic, resolution_date=resolution_dt())
        assert isinstance(fc, PoliticsForecast)
