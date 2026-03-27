import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from config import settings
from src.models.market import WeatherMarket, CryptoMarket, SportsMarket, PoliticsMarket

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


# ─── Crypto patterns ─────────────────────────────────────────────────────────
# "Will Bitcoin exceed $90,000 by March 31?"
# "Will BTC be above $85k on April 5?"
_CRYPTO_ASSET_ALT = (
    "Bitcoin|Ethereum|Solana|Ripple|XRP|Dogecoin|Cardano|Avalanche|Polygon|"
    "Chainlink|Polkadot|Litecoin|Shiba Inu|SHIB|Uniswap|Cosmos|Aptos|Sui|TON|"
    "BTC|ETH|SOL|DOGE|ADA|AVAX|MATIC|LINK|DOT|LTC|BCH|UNI|ATOM|SUI|APT"
)
_CRYPTO_PATTERN = re.compile(
    r"^Will (?P<asset>" + _CRYPTO_ASSET_ALT + r")"
    r"(?:'s?(?:\s+price)?)?\s+"
    r"(?P<comparison>exceed|be above|be below|reach|drop below|be at|be over|be under|surpass|fall below|go above|go below)"
    r"\s+\$(?P<threshold>[\d,]+(?:\.\d+)?)(?P<unit>[kKmM])?"
    r"(?:[\s,]+(?:by|on|before|at)\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}))?\??$",
    re.IGNORECASE,
)

_CRYPTO_ABOVE = {"exceed", "be above", "reach", "surpass", "be over", "go above"}
_CRYPTO_BELOW = {"be below", "drop below", "fall below", "be under", "go below"}

# Maps Polymarket display names → canonical ticker
_ASSET_TICKER = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "solana": "SOL", "sol": "SOL",
    "ripple": "XRP", "xrp": "XRP",
    "dogecoin": "DOGE", "doge": "DOGE",
    "cardano": "ADA", "ada": "ADA",
    "avalanche": "AVAX", "avax": "AVAX",
    "polygon": "MATIC", "matic": "MATIC",
    "chainlink": "LINK", "link": "LINK",
    "polkadot": "DOT", "dot": "DOT",
    "litecoin": "LTC", "ltc": "LTC",
    "shiba inu": "SHIB", "shib": "SHIB",
    "uniswap": "UNI", "uni": "UNI",
    "cosmos": "ATOM", "atom": "ATOM",
    "aptos": "APT", "apt": "APT",
    "sui": "SUI",
    "ton": "TON",
    "bitcoin cash": "BCH", "bch": "BCH",
}


def _parse_threshold_usd(value_str: str, unit: str) -> float:
    """Convert '90,000' + '' or '90' + 'k' → float USD."""
    cleaned = value_str.replace(",", "")
    val = float(cleaned)
    u = (unit or "").lower()
    if u == "k":
        val *= 1_000
    elif u == "m":
        val *= 1_000_000
    return val


def parse_crypto_market(
    raw_market: dict,
    event_title: str = "",
    end_date_str: str = "",
    event_slug: str = "",
) -> Optional[CryptoMarket]:
    """
    Parse a raw Gamma API market dict as a crypto price market.
    Returns None if the question does not match the crypto pattern.
    """
    question = raw_market.get("question", "")
    m = _CRYPTO_PATTERN.match(question)
    if not m:
        logger.debug("Crypto: no match for %s", question[:80])
        return None

    asset_raw = m.group("asset").strip()
    ticker = _ASSET_TICKER.get(asset_raw.lower(), asset_raw.upper())
    asset_name = asset_raw.capitalize() if asset_raw.upper() == asset_raw else asset_raw

    threshold_usd = _parse_threshold_usd(
        m.group("threshold"),
        m.group("unit") or "",
    )

    comparison = m.group("comparison").strip().lower()
    direction = "above" if comparison in _CRYPTO_ABOVE else "below"

    # Resolve date from event or market endDate
    date_str = end_date_str or raw_market.get("endDate", "")
    try:
        end_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    # If month/day captured use them; otherwise fall back to end_date
    try:
        if m.group("month") and m.group("day"):
            month_int = _month_name_to_int(m.group("month"))
            day_int = int(m.group("day"))
            resolution_date = datetime(
                year=end_dt.year, month=month_int, day=day_int,
                tzinfo=timezone.utc,
            )
        else:
            resolution_date = end_dt
    except (ValueError, KeyError):
        resolution_date = end_dt

    # YES token price
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

    return CryptoMarket(
        market_id=str(raw_market.get("id", "")),
        condition_id=str(raw_market.get("conditionId", "")),
        question=question,
        asset=ticker,
        asset_name=asset_name,
        threshold_usd=threshold_usd,
        direction=direction,
        resolution_date=resolution_date,
        yes_token_id=str(clob_ids[0]) if len(clob_ids) > 0 else "",
        no_token_id=str(clob_ids[1]) if len(clob_ids) > 1 else "",
        market_implied_prob=yes_price,
        liquidity_usd=float(raw_market.get("liquidity", 0) or 0),
        volume_usd=float(raw_market.get("volume", 0) or 0),
        end_date=end_dt,
        event_title=event_title,
        slug=str(raw_market.get("slug", "")),
        event_slug=event_slug,
    )


# ─── Sports patterns ──────────────────────────────────────────────────────────
# "Will [Team A] beat [Team B] on March 30?"
# "Will Real Madrid win vs Barcelona on April 1?"
_SPORTS_BEAT_PATTERN = re.compile(
    r"^Will (?P<home>.+?) (?:beat|defeat) (?P<away>.+?)"
    r"(?:\s+(?:on|in)\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}))?\??$",
    re.IGNORECASE,
)
_SPORTS_WIN_PATTERN = re.compile(
    r"^Will (?P<home>.+?) win (?:vs?\.?\s+|against\s+)(?P<away>.+?)"
    r"(?:\s+(?:on|in)\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}))?\??$",
    re.IGNORECASE,
)

_FOOTBALL_KEYWORDS = {
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "champions league", "europa league", "world cup", "copa", "fa cup",
    "mls", "soccer", "football", "epl", "ucl", "uel",
}
_BASKETBALL_KEYWORDS = {"nba", "basketball", "lakers", "celtics", "knicks", "warriors"}


def _detect_sport(title: str, question: str) -> str:
    combined = (title + " " + question).lower()
    if any(k in combined for k in _FOOTBALL_KEYWORDS):
        return "football"
    if any(k in combined for k in _BASKETBALL_KEYWORDS):
        return "basketball"
    return "other"


def parse_sports_market(
    raw_market: dict,
    event_title: str = "",
    end_date_str: str = "",
    event_slug: str = "",
) -> Optional[SportsMarket]:
    """Parse a raw Gamma API market dict as a sports outcome market."""
    question = raw_market.get("question", "")

    m = _SPORTS_BEAT_PATTERN.match(question) or _SPORTS_WIN_PATTERN.match(question)
    if not m:
        logger.debug("Sports: no match for %s", question[:80])
        return None

    home_team = m.group("home").strip()
    away_team = m.group("away").strip()

    # Strip trailing "?" artifacts from away team name
    away_team = away_team.rstrip("?").strip()

    date_str = end_date_str or raw_market.get("endDate", "")
    try:
        end_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    try:
        if m.group("month") and m.group("day"):
            month_int = _month_name_to_int(m.group("month"))
            day_int = int(m.group("day"))
            resolution_date = datetime(
                year=end_dt.year, month=month_int, day=day_int,
                tzinfo=timezone.utc,
            )
        else:
            resolution_date = end_dt
    except (ValueError, KeyError):
        resolution_date = end_dt

    sport = _detect_sport(event_title, question)

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

    return SportsMarket(
        market_id=str(raw_market.get("id", "")),
        condition_id=str(raw_market.get("conditionId", "")),
        question=question,
        home_team=home_team,
        away_team=away_team,
        sport=sport,
        outcome="home_win",   # all parsed questions are "Will HOME win/beat AWAY"
        resolution_date=resolution_date,
        yes_token_id=str(clob_ids[0]) if len(clob_ids) > 0 else "",
        no_token_id=str(clob_ids[1]) if len(clob_ids) > 1 else "",
        market_implied_prob=yes_price,
        liquidity_usd=float(raw_market.get("liquidity", 0) or 0),
        volume_usd=float(raw_market.get("volume", 0) or 0),
        end_date=end_dt,
        event_title=event_title,
        slug=str(raw_market.get("slug", "")),
        event_slug=event_slug,
    )


# ─── Politics parser ──────────────────────────────────────────────────────────
# Generic: any market from a politics/elections event not matched by other parsers
# We use the question as-is for Metaculus search.

def parse_politics_market(
    raw_market: dict,
    event_title: str = "",
    end_date_str: str = "",
    event_slug: str = "",
) -> Optional[PoliticsMarket]:
    """Parse a raw Gamma API market dict as a politics market."""
    question = raw_market.get("question", "")
    if not question:
        return None

    # Simple heuristic: question must start with "Will" and contain no °C / price markers
    if not question.strip().lower().startswith("will"):
        return None
    if "°C" in question or "$" in question:
        return None   # let weather/crypto parsers handle these

    date_str = end_date_str or raw_market.get("endDate", "")
    try:
        end_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    # Use end_date as resolution_date for politics
    resolution_date = end_dt

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

    # topic = combined event title + question for richer Metaculus search
    topic = f"{event_title}: {question}".strip(": ") if event_title else question

    return PoliticsMarket(
        market_id=str(raw_market.get("id", "")),
        condition_id=str(raw_market.get("conditionId", "")),
        question=question,
        topic=topic,
        resolution_date=resolution_date,
        yes_token_id=str(clob_ids[0]) if len(clob_ids) > 0 else "",
        no_token_id=str(clob_ids[1]) if len(clob_ids) > 1 else "",
        market_implied_prob=yes_price,
        liquidity_usd=float(raw_market.get("liquidity", 0) or 0),
        volume_usd=float(raw_market.get("volume", 0) or 0),
        end_date=end_dt,
        event_title=event_title,
        slug=str(raw_market.get("slug", "")),
        event_slug=event_slug,
    )


class PolymarketClient:
    """Fetches market data from Polymarket Gamma API."""

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

    def get_user_positions(self, address: str) -> list:
        """
        Fetch open positions for a wallet from Polymarket Data API.
        Returns list of position dicts (empty list on error or no positions).

        Each position dict includes:
            conditionId, outcomeIndex (0=YES/1=NO), size (tokens),
            avgPrice, currentValue, initialValue, title/question.
        """
        if not address:
            return []
        try:
            data = self._get_with_retry(
                "https://data-api.polymarket.com/positions",
                {"user": address, "sizeThreshold": "0.01"},
            )
            if isinstance(data, list):
                return data
            return data.get("data", []) if isinstance(data, dict) else []
        except PolymarketAPIError:
            return []

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

    # ── Keyword sets for non-weather category fetching ────────────────────────

    _CRYPTO_KEYWORDS = {
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
        "ripple", "xrp", "dogecoin", "doge", "cardano", "ada",
        "avalanche", "avax", "polygon", "matic", "chainlink", "polkadot",
    }

    _SPORTS_KEYWORDS = {
        "soccer", "football", "nba", "basketball", "nfl", "mlb", "nhl",
        "premier league", "champions league", "la liga", "bundesliga",
        "serie a", "ligue 1", "copa", "world cup", "mls", "ufc",
        "tennis", "golf", "f1", "formula 1",
    }

    _POLITICS_KEYWORDS = {
        "election", "president", "senate", "congress", "vote", "poll",
        "government", "minister", "chancellor", "prime minister", "trump",
        "biden", "democrat", "republican", "party", "candidate", "campaign",
        "referendum", "impeach", "approve", "approval rating",
    }

    def _fetch_category_markets(
        self,
        keywords: set,
        category: str,
        max_days: int = settings.MAX_DAYS_TO_EXPIRY,
        max_pages: int = 30,
    ) -> list:
        """
        Generic paginated event fetch filtered by keyword set.
        Returns list of (raw_market, event_title, event_end_date, event_slug) tuples.
        """
        now = datetime.now(tz=timezone.utc)
        cutoff = now + timedelta(days=max_days)
        earliest_ok = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        results = []
        seen_condition_ids: set = set()
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
                logger.warning("%s events API error: %s", category, exc)
                break

            events = data if isinstance(data, list) else data.get("data", [])
            if not events:
                break

            for evt in events:
                title = (evt.get("title", "") or "").lower()
                description = (evt.get("description", "") or "").lower()
                combined = title + " " + description

                if not any(k in combined for k in keywords):
                    continue

                end_date = evt.get("endDate", "")
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    if end_dt > cutoff:
                        continue
                except (ValueError, AttributeError):
                    pass

                event_title = evt.get("title", "")
                event_end_date = evt.get("endDate", "")
                event_slug = evt.get("slug", "")

                for mkt in evt.get("markets", []):
                    cid = mkt.get("conditionId", "")
                    if not cid or cid in seen_condition_ids:
                        continue
                    seen_condition_ids.add(cid)
                    results.append((mkt, event_title, event_end_date, event_slug))

            newest_start = max(
                (e.get("startDate", "0000") for e in events if e.get("startDate")),
                default="0000",
            )
            if newest_start < earliest_ok:
                break

            if len(events) < limit:
                break
            offset += limit

        logger.info("Fetched %d %s markets after scanning %d offsets", len(results), category, offset)
        return results

    def fetch_crypto_markets(
        self,
        max_days: int = settings.MAX_DAYS_TO_EXPIRY,
    ) -> list:
        """Fetch crypto price market tuples (raw_market, event_title, end_date, event_slug)."""
        return self._fetch_category_markets(self._CRYPTO_KEYWORDS, "crypto", max_days=max_days)

    def fetch_sports_markets(
        self,
        max_days: int = settings.MAX_DAYS_TO_EXPIRY,
    ) -> list:
        """Fetch sports outcome market tuples (raw_market, event_title, end_date, event_slug)."""
        return self._fetch_category_markets(self._SPORTS_KEYWORDS, "sports", max_days=max_days)

    def fetch_politics_markets(
        self,
        max_days: int = settings.MAX_DAYS_TO_EXPIRY,
    ) -> list:
        """Fetch politics market tuples (raw_market, event_title, end_date, event_slug)."""
        return self._fetch_category_markets(self._POLITICS_KEYWORDS, "politics", max_days=max_days)

    # ── Resolution check ──────────────────────────────────────────────────────

    _CLOB_BASE = "https://clob.polymarket.com"

    def fetch_market_outcome(self, condition_id: str) -> Optional[bool]:
        """
        Check whether a market has resolved and which side won.

        Queries the Polymarket CLOB API for the given condition_id.

        Returns:
            True  — YES resolved (price → 1.0)
            False — NO resolved  (price → 0.0)
            None  — not yet resolved, or API unavailable
        """
        if not condition_id:
            return None
        url = f"{self._CLOB_BASE}/markets/{condition_id}"
        try:
            resp = self._session.get(
                url,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("fetch_market_outcome(%s): %s", condition_id, exc)
            return None

        # CLOB response contains tokens list with final_outcome when resolved
        tokens = data.get("tokens") or []
        for token in tokens:
            outcome = str(token.get("outcome", "")).upper()
            price   = float(token.get("price", 0))
            # A resolved YES token trades at 1.0; NO token at 0.0
            if price >= 0.99:
                return outcome == "YES"
            if price <= 0.01 and outcome == "YES":
                return False   # YES at ~0 → NO won

        # Also check top-level resolved flag if present
        if data.get("closed") and data.get("winner"):
            return str(data["winner"]).upper() == "YES"

        return None  # not yet resolved

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
