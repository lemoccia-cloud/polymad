"""Tests for sports_client — Elo math (pure) and ClubElo HTTP (mocked)."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.data.sports_client import (
    SportsClient,
    SportsAPIError,
    _elo_win_prob,
    HOME_ADVANTAGE_ELO,
)
from src.data.polymarket_client import parse_sports_market
from src.models.market import SportsMarket, SportsForecast


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_raw_sports(**overrides) -> dict:
    base = {
        "id": "s1",
        "conditionId": "cond2",
        "question": "Will Real Madrid beat Barcelona?",
        "endDate": "2026-04-05T18:00:00Z",
        "clobTokenIds": ["y1", "n1"],
        "outcomePrices": ["0.55", "0.45"],
        "liquidity": "8000.0",
        "volume": "30000.0",
        "slug": "real-madrid-beat-barcelona",
    }
    base.update(overrides)
    return base


def make_elo_csv(entries: list) -> str:
    """Build a ClubElo-style CSV string from a list of (club_name, elo) tuples."""
    lines = ["Rank,Club,Country,Level,Elo,From,To"]
    for i, (club, elo) in enumerate(entries, start=1):
        lines.append(f"{i},{club},ENG,1,{elo:.1f},2024-01-01,2026-12-31")
    return "\n".join(lines)


def make_mock_session(entries: list) -> MagicMock:
    """Return mock session whose GET returns a ClubElo CSV."""
    csv_body = make_elo_csv(entries)
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = csv_body
    mock_session.get.return_value = mock_response
    return mock_session


def resolution_dt() -> datetime:
    return datetime(2026, 4, 5, tzinfo=timezone.utc)


# ─── TestEloWinProb ───────────────────────────────────────────────────────────

class TestEloWinProb:
    def test_equal_teams_home_advantage(self):
        # Equal Elo → home team wins more often due to +65 adjustment
        p = _elo_win_prob(1500.0, 1500.0)
        expected = 1.0 / (1.0 + 10.0 ** (-HOME_ADVANTAGE_ELO / 400.0))
        assert p == pytest.approx(expected, abs=1e-6)
        assert 0.55 < p < 0.65

    def test_strong_home_team(self):
        p = _elo_win_prob(1800.0, 1400.0)
        assert p > 0.85

    def test_weak_home_team(self):
        p = _elo_win_prob(1300.0, 1800.0)
        assert p < 0.30

    def test_probability_bounds(self):
        for elo_a, elo_b in [(1000, 2000), (2000, 1000), (1500, 1500)]:
            p = _elo_win_prob(elo_a, elo_b)
            assert 0.0 < p < 1.0

    def test_higher_home_elo_gives_higher_prob(self):
        p1 = _elo_win_prob(1600.0, 1500.0)
        p2 = _elo_win_prob(1500.0, 1600.0)
        assert p1 > p2

    def test_home_advantage_applies(self):
        # Same Elo: home should win more often than not
        p = _elo_win_prob(1500.0, 1500.0)
        assert p > 0.5

    def test_extreme_elo_difference(self):
        # 400-point Elo gap is roughly 10:1 odds  — adjusted here by home advantage
        p_strong = _elo_win_prob(2000.0, 1400.0)
        p_weak = _elo_win_prob(1400.0, 2000.0)
        assert p_strong > p_weak
        assert p_strong > 0.90


# ─── TestParseSportsMarket ────────────────────────────────────────────────────

class TestParseSportsMarket:
    def test_beat_pattern(self):
        m = parse_sports_market(make_raw_sports(
            question="Will Real Madrid beat Barcelona?"))
        assert m is not None
        assert m.home_team == "Real Madrid"
        assert m.away_team == "Barcelona"

    def test_defeat_pattern(self):
        m = parse_sports_market(make_raw_sports(
            question="Will Liverpool defeat Arsenal on April 3?"))
        assert m is not None
        assert m.home_team == "Liverpool"
        assert m.away_team == "Arsenal"

    def test_win_vs_pattern(self):
        m = parse_sports_market(make_raw_sports(
            question="Will Man City win vs Chelsea?"))
        assert m is not None
        assert m.home_team == "Man City"
        assert m.away_team == "Chelsea"

    def test_win_against_pattern(self):
        m = parse_sports_market(make_raw_sports(
            question="Will PSG win against Bayern Munich?"))
        assert m is not None
        assert m.home_team == "PSG"
        assert m.away_team == "Bayern Munich"

    def test_away_team_no_trailing_question_mark(self):
        m = parse_sports_market(make_raw_sports(
            question="Will Barcelona beat Real Madrid?"))
        assert m is not None
        assert "?" not in m.away_team

    def test_market_type_is_sports(self):
        m = parse_sports_market(make_raw_sports())
        assert m is not None
        assert m.market_type == "sports"

    def test_outcome_is_home_win(self):
        m = parse_sports_market(make_raw_sports())
        assert m is not None
        assert m.outcome == "home_win"

    def test_sport_detected_football_from_event_title(self):
        m = parse_sports_market(
            make_raw_sports(question="Will Real Madrid beat Barcelona?"),
            event_title="Champions League Final",
        )
        assert m is not None
        assert m.sport == "football"

    def test_sport_detected_basketball_from_event_title(self):
        m = parse_sports_market(
            make_raw_sports(question="Will Lakers beat Celtics?"),
            event_title="NBA Finals 2026",
        )
        assert m is not None
        assert m.sport == "basketball"

    def test_implied_prob_from_prices(self):
        m = parse_sports_market(make_raw_sports(outcomePrices=["0.60", "0.40"]))
        assert m is not None
        assert m.market_implied_prob == pytest.approx(0.60)

    def test_crypto_question_returns_none(self):
        m = parse_sports_market(make_raw_sports(
            question="Will Bitcoin exceed $90,000 by March 31?"))
        assert m is None

    def test_weather_question_returns_none(self):
        m = parse_sports_market(make_raw_sports(
            question="Will the highest temperature in Warsaw be 13°C or higher on March 24?"))
        assert m is None

    def test_missing_end_date_returns_none(self):
        m = parse_sports_market(make_raw_sports(endDate="bad-date"))
        assert m is None


# ─── TestSportsClient ─────────────────────────────────────────────────────────

class TestSportsClient:
    def test_football_uses_clubelo(self):
        entries = [("Real Madrid", 1950.0), ("Barcelona", 1900.0)]
        client = SportsClient(session=make_mock_session(entries))
        fc = client.get_outcome_forecast(
            home_team="Real Madrid", away_team="Barcelona",
            sport="football", outcome="home_win",
            resolution_date=resolution_dt(),
        )
        assert isinstance(fc, SportsForecast)
        assert fc.source == "clubelo"
        assert fc.model_probability > 0.5  # Real Madrid (home, higher Elo) favoured

    def test_football_away_win_outcome(self):
        entries = [("Real Madrid", 1950.0), ("Barcelona", 1900.0)]
        client = SportsClient(session=make_mock_session(entries))
        fc_home = client.get_outcome_forecast(
            "Real Madrid", "Barcelona", "football", "home_win", resolution_dt())
        fc_away = client.get_outcome_forecast(
            "Real Madrid", "Barcelona", "football", "away_win", resolution_dt())
        # away_win uses complement of home_win
        assert fc_away.model_probability == pytest.approx(1.0 - fc_home.model_probability, abs=0.01)

    def test_non_football_returns_baseline(self):
        client = SportsClient(session=MagicMock())
        fc = client.get_outcome_forecast(
            "Lakers", "Celtics", "basketball", "home_win", resolution_dt())
        assert fc.model_probability == pytest.approx(0.50)
        assert fc.source == "baseline"

    def test_unknown_team_falls_back_to_baseline(self):
        # CSV contains no matching team
        entries = [("FC Unknown1", 1500.0), ("FC Unknown2", 1500.0)]
        client = SportsClient(session=make_mock_session(entries))
        fc = client.get_outcome_forecast(
            "Real Madrid", "Barcelona", "football", "home_win", resolution_dt())
        # No fuzzy match found → baseline
        assert fc.model_probability == pytest.approx(0.50)
        assert fc.source == "baseline"

    def test_http_error_falls_back_gracefully(self):
        import requests as req
        mock_session = MagicMock()
        mock_session.get.side_effect = req.ConnectionError("timeout")
        client = SportsClient(session=mock_session)
        # Should not raise — graceful fallback
        fc = client.get_outcome_forecast(
            "Real Madrid", "Barcelona", "football", "home_win", resolution_dt())
        assert fc.model_probability == pytest.approx(0.50)
        assert fc.source == "baseline"

    def test_elo_values_stored_in_forecast(self):
        entries = [("Real Madrid", 1980.0), ("Barcelona", 1890.0)]
        client = SportsClient(session=make_mock_session(entries))
        fc = client.get_outcome_forecast(
            "Real Madrid", "Barcelona", "football", "home_win", resolution_dt())
        assert fc.elo_home == pytest.approx(1980.0)
        assert fc.elo_away == pytest.approx(1890.0)

    def test_probability_clamped_in_bounds(self):
        entries = [("TeamA", 2200.0), ("TeamB", 1000.0)]
        client = SportsClient(session=make_mock_session(entries))
        fc = client.get_outcome_forecast(
            "TeamA", "TeamB", "football", "home_win", resolution_dt())
        assert 0.0 < fc.model_probability < 1.0
