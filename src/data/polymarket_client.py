import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from config import settings
from src.models.market import WeatherMarket

logger = logging.getLogger(__name__)

# Matches highest and lowest temperature question formats:
#   "Will the highest temperature in Beijing be 26°C or higher on March 28?"
#   "Will the lowest temperature in Tokyo be 5°C or below on March 28?"
_WEATHER_PATTERN = re.compile(
    r"^Will the (?P<temp_type>highest|lowest) temperature in (?P<city>.+?) be "
    r"(?P<threshold>-?\d+(?:\.\d+)?)°C(?P<comparison> or below| or higher|) on "
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})\??$",
    re.IGNORECASE,
)

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class PolymarketAPIError(Exception):
    pass


def _month_name_to_int(name: str) -> int:
    key = name.lower()
    if key not in _MONTH_NAMES:
        raise ValueError(f"Unknown month name: {name!r}")
    return _MONTH_NAMES[key]


def parse_weather_market(
    raw_market: dict,
    event_title: str = "",
    end_date_str: str = "",
    event_slug: str = "",
) -> Optional[WeatherMarket]:
    """
    Parse a raw Gamma API market dict (sub-market within a temperature event).
    Returns None if the question does not match the expected format.
    """
    question = raw_market.get("question", "")
    m = _WEATHER_PATTERN.match(question)
    if not m:
        logger.debug("Skipping non-matching market: %s", question[:80])
        return None

    city = m.group("city").strip()
    temp_type = m.group("temp_type").lower()  # "highest" or "lowest"
    threshold = float(m.group("threshold"))
    comparison = m.group("comparison").strip().lower()  # "", "or below", "or higher"

    if comparison == "or higher":
        direction = "above"
        bucket_type = "above"
    elif comparison == "or below":
        direction = "below"
        bucket_type = "below"
    else:
        direction = "exact"
        bucket_type = "exact"

    # Parse end date from the event or market
    date_str = end_date_str or raw_market.get("endDate", "")
    try:
        end_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.debug("Could not parse endDate %r", date_str)
        return None

    try:
        month_int = _month_name_to_int(m.group("month"))
        day_int = int(m.group("day"))
        resolution_date = datetime(
            year=end_dt.year,
            month=month_int,
            day=day_int,
            tzinfo=timezone.utc,
        )
    except (ValueError, KeyError) as exc:
        logger.debug("Date parse error for %r: %s", question, exc)
        return None

    # YES token price: outcomePrices may arrive as a JSON-encoded string
    outcome_prices_raw = raw_market.get("outcomePrices", [])
    if isinstance(outcome_prices_raw, str):
        try:
            outcome_prices_raw = json.loads(outcome_prices_raw)
        except (ValueError, TypeError):
            outcome_prices_raw = []
    try:
        yes_price = float(outcome_prices_raw[0])
    except (IndexError, ValueError, TypeError):
        yes_price = 0.5

    clob_ids = raw_market.get("clobTokenIds", [])

    return WeatherMarket(
        market_id=str(raw_market.get("id", "")),
        condition_id=str(raw_market.get("conditionId", "")),
        question=question,
        city=city,
        threshold_celsius=threshold,
        direction=direction,
        bucket_type=bucket_type,
        resolution_date=resolution_date,
        yes_token_id=str(clob_ids[0]) if len(clob_ids) > 0 else "",
        no_token_id=str(clob_ids[1]) if len(clob_ids) > 1 else "",
        temp_type=temp_type,
        market_implied_prob=yes_price,
        liquidity_usd=float(raw_market.get("liquidity", 0) or 0),
        volume_usd=float(raw_market.get("volume", 0) or 0),
        end_date=end_dt,
        event_title=event_title,
        raw_question=question,
        slug=str(raw_market.get("slug", "")),
        event_slug=event_slug,
    )


class PolymarketClient:
    """Fetches weather market data from Polymarket Gamma API."""

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": "polyMad/1.0"})

    def fetch_weather_events(
        self,
        max_days: int = settings.MAX_DAYS_TO_EXPIRY,
        max_pages: int = 40,
    ) -> list:
        """
        Fetch active temperature events by paginating the events endpoint
        sorted by startDate descending. Returns list of raw event dicts.

        Weather events typically appear several hundred positions into the
        events feed (behind high-frequency crypto mini-markets), so we use
        limit=100 and up to 20 pages to ensure we scan far enough.
        """
        now = datetime.now(tz=timezone.utc)
        cutoff = now + timedelta(days=max_days)
        # Earliest startDate we care about — don't fetch events older than 3 days
        earliest_ok = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        results = []
        offset = 0
        limit = 100

        for _ in range(max_pages):
            try:
                data = self._get_with_retry(
                    settings.GAMMA_API_BASE + "/events",
                    {
                        "limit": limit,
                        "offset": offset,
                        "order": "startDate",
                        "ascending": "false",
                        "closed": "false",
                    },
                )
            except PolymarketAPIError as exc:
                logger.warning("Events API error: %s", exc)
                break

            events = data if isinstance(data, list) else data.get("data", [])
            if not events:
                break

            for evt in events:
                title = evt.get("title", "")
                if not any(w in title.lower() for w in ["temperature", "high temp", "low temp"]):
                    continue

                # Apply expiry filter (skip events resolving too far in the future)
                end_date = evt.get("endDate", "")
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    if end_dt > cutoff:
                        continue
                except (ValueError, AttributeError):
                    pass

                results.append(evt)

            # Stop only when the NEWEST event in this page is older than our window.
            # (We intentionally do NOT stop on the oldest item because a page may
            # contain a mix of very old non-weather events and recent weather events.)
            newest_start = max(
                (e.get("startDate", "0000") for e in events if e.get("startDate")),
                default="0000",
            )
            if newest_start < earliest_ok:
                break

            if len(events) < limit:
                break
            offset += limit

        logger.info("Fetched %d temperature events after scanning %d offsets", len(results), offset)
        return results

    def fetch_weather_markets(
        self,
        min_liquidity: float = settings.MIN_LIQUIDITY_USD,
        max_days: int = settings.MAX_DAYS_TO_EXPIRY,
    ) -> list:
        """
        Fetch all individual temperature sub-markets from weather events.
        Returns list of (raw_market_dict, event_title, event_end_date) tuples.
        """
        events = self.fetch_weather_events(max_days=max_days)
        results = []
        seen_condition_ids = set()

        for evt in events:
            event_title = evt.get("title", "")
            event_end_date = evt.get("endDate", "")
            event_slug = evt.get("slug", "")
            sub_markets = evt.get("markets", [])

            for mkt in sub_markets:
                cid = mkt.get("conditionId", "")
                if not cid or cid in seen_condition_ids:
                    continue

                liquidity = float(mkt.get("liquidity", 0) or 0)
                if liquidity < min_liquidity:
                    pass  # Still include — many weather markets have low liquidity

                seen_condition_ids.add(cid)
                results.append((mkt, event_title, event_end_date, event_slug))

        logger.info("Expanded to %d individual temperature markets", len(results))
        return results

    def get_clob_price(self, condition_id: str) -> Optional[float]:
        """
        Fetch live YES token mid-price from CLOB API.
        Returns None if unavailable (caller should fall back to outcomePrices).
        """
        try:
            data = self._get_with_retry(
                settings.CLOB_API_BASE + "/markets",
                {"condition_id": condition_id},
            )
        except PolymarketAPIError:
            return None

        if isinstance(data, list):
            market_data = data[0] if data else {}
        elif isinstance(data, dict) and "data" in data:
            items = data["data"]
            market_data = items[0] if items else {}
        else:
            market_data = data

        tokens = market_data.get("tokens", [])
        for token in tokens:
            if str(token.get("outcome", "")).lower() == "yes":
                return float(token.get("price", 0))

        return None

    def _get_with_retry(self, url: str, params: dict) -> object:
        """GET with exponential backoff. Raises PolymarketAPIError on failure."""
        delay = 1.0
        for attempt in range(settings.MAX_RETRIES):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response else 0
                if (status == 429 or status >= 500) and attempt < settings.MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise PolymarketAPIError(f"HTTP {status} from {url}: {exc}") from exc
            except requests.exceptions.RequestException as exc:
                if attempt < settings.MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise PolymarketAPIError(f"Request failed for {url}: {exc}") from exc

        raise PolymarketAPIError(f"All {settings.MAX_RETRIES} retries exhausted for {url}")
