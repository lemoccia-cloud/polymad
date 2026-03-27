"""
Sports probability client for polyMad.

Uses ClubElo (http://api.clubelo.com) — free, no API key — for football/soccer.
Applies the standard Elo win-probability formula.
Falls back to 0.50 baseline for non-football sports or unknown teams.

No extra dependencies — uses only requests.
"""
import logging
import time
from datetime import datetime, timezone
from difflib import get_close_matches
from typing import Optional

import requests

from src.models.market import SportsForecast

logger = logging.getLogger(__name__)

CLUBELO_BASE = "http://api.clubelo.com"
_REQUEST_TIMEOUT = 10

# Home advantage in Elo points (standard football assumption ~65)
HOME_ADVANTAGE_ELO = 65.0


class SportsAPIError(Exception):
    pass


def _elo_win_prob(elo_a: float, elo_b: float) -> float:
    """
    Expected win probability for team A (home) against team B (away).
    Includes a home-advantage adjustment.
    Standard Elo formula: P = 1 / (1 + 10^((Elo_B - Elo_A_adj) / 400))
    """
    elo_a_adj = elo_a + HOME_ADVANTAGE_ELO
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a_adj) / 400.0))


def _normalize_team(name: str) -> str:
    return name.lower().strip()


class SportsClient:
    """Fetches Elo ratings from ClubElo and computes football win probabilities."""

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": "polyMad/1.0"})
        self._elo_cache: dict = {}   # (team, date_str) → elo float

    def get_outcome_forecast(
        self,
        home_team: str,
        away_team: str,
        sport: str,
        outcome: str,
        resolution_date: datetime,
    ) -> SportsForecast:
        """
        Compute model probability for a sports outcome market.

        For football: uses ClubElo ratings.
        For other sports: returns 0.50 baseline.

        Args:
            home_team: name of the home / first-listed team
            away_team: name of the away / second-listed team
            sport: "football" | "basketball" | "other"
            outcome: "home_win" | "away_win" | "draw"
            resolution_date: match date

        Returns:
            SportsForecast with model_probability, elo values, source tag
        """
        if sport != "football":
            logger.debug("Non-football sport %r — using 0.50 baseline", sport)
            return SportsForecast(
                home_team=home_team, away_team=away_team, outcome=outcome,
                model_probability=0.50, elo_home=1500.0, elo_away=1500.0,
                source="baseline",
            )

        date_str = resolution_date.strftime("%Y-%m-%d")
        elo_home = self._get_elo(home_team, date_str)
        elo_away = self._get_elo(away_team, date_str)

        if elo_home is None or elo_away is None:
            logger.debug("Elo not found for %r or %r — baseline", home_team, away_team)
            return SportsForecast(
                home_team=home_team, away_team=away_team, outcome=outcome,
                model_probability=0.50, elo_home=1500.0, elo_away=1500.0,
                source="baseline",
            )

        p_home = _elo_win_prob(elo_home, elo_away)

        if outcome == "home_win":
            prob = p_home
        elif outcome == "away_win":
            # Away win: complement, minus draw allowance (roughly)
            prob = 1.0 - p_home
        else:  # draw
            # Approximate draw probability ~25% at equal strength, less at extremes
            strength_diff = abs(elo_home + HOME_ADVANTAGE_ELO - elo_away)
            prob = max(0.10, 0.28 - strength_diff / 2000.0)

        prob = max(0.01, min(0.99, prob))

        logger.debug(
            "Sports forecast: %s(%.0f) vs %s(%.0f) → %s=%.3f",
            home_team, elo_home, away_team, elo_away, outcome, prob,
        )

        return SportsForecast(
            home_team=home_team, away_team=away_team, outcome=outcome,
            model_probability=prob, elo_home=elo_home, elo_away=elo_away,
            source="clubelo",
        )

    def _get_elo(self, team: str, date_str: str) -> Optional[float]:
        """Fetch Elo rating for a team on a given date from ClubElo."""
        cache_key = (_normalize_team(team), date_str)
        if cache_key in self._elo_cache:
            return self._elo_cache[cache_key]

        # ClubElo endpoint: GET /{date} returns CSV of all teams on that date
        url = f"{CLUBELO_BASE}/{date_str}"
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("ClubElo fetch failed for %s: %s", date_str, exc)
            return None

        # CSV format: Rank,Club,Country,Level,Elo,From,To
        lines = resp.text.strip().splitlines()
        team_elos: dict = {}
        for line in lines[1:]:  # skip header
            parts = line.split(",")
            if len(parts) >= 5:
                club_name = parts[1].strip()
                try:
                    elo = float(parts[4])
                    team_elos[_normalize_team(club_name)] = elo
                except ValueError:
                    continue

        # Exact match
        norm_team = _normalize_team(team)
        if norm_team in team_elos:
            result = team_elos[norm_team]
            self._elo_cache[cache_key] = result
            return result

        # Fuzzy match (cutoff 0.75)
        matches = get_close_matches(norm_team, list(team_elos.keys()), n=1, cutoff=0.75)
        if matches:
            result = team_elos[matches[0]]
            logger.debug("ClubElo fuzzy match: %r → %r (%.0f)", team, matches[0], result)
            self._elo_cache[cache_key] = result
            return result

        logger.debug("ClubElo: team %r not found on %s", team, date_str)
        return None
