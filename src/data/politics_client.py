"""
Metaculus-based politics probability client for polyMad.

Searches the Metaculus community-forecasting API for questions matching
the Polymarket politics question, then uses the community median (q2)
as the model probability.

Falls back to 0.50 baseline when no match is found.
No API key required — Metaculus has a public API.
"""
import logging
from difflib import SequenceMatcher
from typing import Optional

import requests

from src.models.market import PoliticsForecast

logger = logging.getLogger(__name__)

METACULUS_BASE = "https://www.metaculus.com/api2"
_REQUEST_TIMEOUT = 12
_SIMILARITY_THRESHOLD = 0.45   # minimum title similarity to accept a match


class PoliticsAPIError(Exception):
    pass


def _similarity(a: str, b: str) -> float:
    """Normalised string similarity in [0, 1]."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class PoliticsClient:
    """Fetches community predictions from Metaculus for politics markets."""

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        })
        self._cache: dict = {}  # query → list of results

    def get_metaculus_forecast(
        self,
        topic: str,
        resolution_date=None,
    ) -> PoliticsForecast:
        """
        Search Metaculus for a question matching `topic` and return
        the community probability.

        Args:
            topic: question or description to search for
            resolution_date: not used directly, but logged for context

        Returns:
            PoliticsForecast with model_probability from Metaculus or 0.50 baseline
        """
        questions = self._search_questions(topic)
        if not questions:
            logger.debug("Metaculus: no results for %r — baseline", topic[:60])
            return PoliticsForecast(topic=topic, model_probability=0.50, source="baseline")

        # Pick the question with the best title similarity
        best = max(
            questions,
            key=lambda q: _similarity(topic, q.get("title", "")),
        )
        sim = _similarity(topic, best.get("title", ""))

        if sim < _SIMILARITY_THRESHOLD:
            logger.debug(
                "Metaculus: best match similarity %.2f < %.2f for %r — baseline",
                sim, _SIMILARITY_THRESHOLD, topic[:60],
            )
            return PoliticsForecast(topic=topic, model_probability=0.50, source="baseline")

        # Community prediction: q2 is the median (50th percentile)
        cp = best.get("community_prediction") or {}
        full = cp.get("full") or {}
        q2 = full.get("q2")

        if q2 is None:
            logger.debug("Metaculus: no community prediction for question %s", best.get("id"))
            return PoliticsForecast(
                topic=topic, model_probability=0.50, source="baseline",
                metaculus_id=best.get("id"),
            )

        prob = max(0.01, min(0.99, float(q2)))
        logger.debug(
            "Metaculus match: %r → %r (sim=%.2f) prob=%.3f",
            topic[:50], best.get("title", "")[:50], sim, prob,
        )

        return PoliticsForecast(
            topic=topic,
            model_probability=prob,
            source="metaculus",
            metaculus_id=best.get("id"),
            metaculus_title=best.get("title", ""),
        )

    def _search_questions(self, query: str, limit: int = 5) -> list:
        """
        Search Metaculus questions via the public API.
        Results are cached per query to avoid duplicate requests.
        """
        short_query = " ".join(query.split()[:8])
        if short_query in self._cache:
            return self._cache[short_query]

        params = {
            "search": short_query,
            "type": "forecast",
            "status": "open",
            "limit": limit,
        }
        try:
            resp = self._session.get(
                f"{METACULUS_BASE}/questions/",
                params=params,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            logger.debug("Metaculus search %r → %d results", short_query, len(results))
            self._cache[short_query] = results
            return results
        except requests.RequestException as exc:
            logger.warning("Metaculus search failed: %s", exc)
            self._cache[short_query] = []  # cache failure to avoid hammering
            return []
