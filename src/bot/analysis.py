"""
Background analysis pipeline for the polyMad Telegram bot.

Mirrors the dashboard's run_analysis() logic but without any Streamlit
dependency. All network calls are wrapped in run_in_executor so they
can be awaited from async handlers.

All data sources are open APIs (no auth keys required):
  - Polymarket Gamma API (market discovery)
  - Open-Meteo Ensemble API (weather forecasts)
  - ClubElo (football Elo ratings)
  - Metaculus API (politics forecasts)
"""
import asyncio
import logging
from functools import partial
from typing import List

from config import settings
from src.analysis import edge_calculator
from src.data.crypto_client import CryptoClient, CryptoAPIError
from src.data.politics_client import PoliticsClient
from src.data.polymarket_client import (
    PolymarketClient,
    PolymarketAPIError,
    parse_weather_market,
    parse_crypto_market,
    parse_sports_market,
    parse_politics_market,
)
from src.data.sports_client import SportsClient
from src.data.weather_client import WeatherClient, CityNotFoundError, WeatherAPIError
from src.models.market import OpportunityResult

logger = logging.getLogger(__name__)

# Singletons — re-used across calls (thread-safe for GET-only clients)
_poly_client = PolymarketClient()
_crypto_client = CryptoClient()
_sports_client = SportsClient()
_politics_client = PoliticsClient()
_weather_client = WeatherClient()


def _run_analysis_sync(
    edge_threshold: float = 0.10,
    max_markets: int = 100,
    model: str = "ecmwf_ifs025",
) -> List[OpportunityResult]:
    """
    Synchronous analysis pipeline — called via run_in_executor.
    Returns list of OpportunityResult with result.alert == True.
    """
    results: List[OpportunityResult] = []

    # ── Weather markets ────────────────────────────────────────────────────────
    try:
        raw_weather = _poly_client.fetch_markets(
            min_liquidity=0.0, max_days=settings.MAX_DAYS_TO_EXPIRY
        )
    except PolymarketAPIError as exc:
        logger.warning("bot analysis: weather fetch failed: %s", exc)
        raw_weather = []

    weather_markets = []
    for tup in raw_weather[:max_markets]:
        raw_mkt = tup[0]
        event_title = tup[1] if len(tup) > 1 else ""
        event_end   = tup[2] if len(tup) > 2 else ""
        event_slug  = tup[3] if len(tup) > 3 else ""
        mkt = parse_weather_market(
            raw_mkt, event_title=event_title,
            end_date_str=event_end, event_slug=event_slug,
        )
        if mkt:
            weather_markets.append(mkt)

    for mkt in weather_markets:
        try:
            forecast = _weather_client.get_ensemble_forecast(
                city=mkt.city,
                resolution_date=mkt.resolution_date,
                threshold_celsius=mkt.threshold_celsius,
                direction=mkt.bucket_type,
                model=model,
                temp_type=getattr(mkt, "temp_type", "highest"),
            )
        except (CityNotFoundError, WeatherAPIError, Exception) as exc:
            logger.debug("bot analysis: weather skip %s: %s", mkt.city, exc)
            continue
        result = edge_calculator.analyze_market(mkt, forecast)
        result.alert = result.edge > edge_threshold
        if result.alert:
            results.append(result)

    # ── Crypto markets ─────────────────────────────────────────────────────────
    try:
        raw_crypto = _poly_client.fetch_crypto_markets(
            max_days=settings.MAX_DAYS_TO_EXPIRY
        )
    except PolymarketAPIError as exc:
        logger.warning("bot analysis: crypto fetch failed: %s", exc)
        raw_crypto = []

    for tup in raw_crypto[:max_markets]:
        raw_mkt    = tup[0]
        event_title = tup[1] if len(tup) > 1 else ""
        event_end   = tup[2] if len(tup) > 2 else ""
        event_slug  = tup[3] if len(tup) > 3 else ""
        mkt = parse_crypto_market(
            raw_mkt, event_title=event_title,
            end_date_str=event_end, event_slug=event_slug,
        )
        if mkt is None:
            continue
        try:
            forecast = _crypto_client.get_lognormal_forecast(
                asset=mkt.asset,
                resolution_date=mkt.resolution_date,
                threshold_usd=mkt.threshold_usd,
                direction=mkt.direction,
            )
        except (CryptoAPIError, ValueError, Exception) as exc:
            logger.debug("bot analysis: crypto skip %s: %s", mkt.asset, exc)
            continue
        result = edge_calculator.analyze_market(mkt, forecast)
        result.alert = result.edge > edge_threshold
        if result.alert:
            results.append(result)

    # ── Sports markets ─────────────────────────────────────────────────────────
    try:
        raw_sports = _poly_client.fetch_sports_markets(
            max_days=settings.MAX_DAYS_TO_EXPIRY
        )
    except PolymarketAPIError as exc:
        logger.warning("bot analysis: sports fetch failed: %s", exc)
        raw_sports = []

    for tup in raw_sports[:max_markets]:
        raw_mkt    = tup[0]
        event_title = tup[1] if len(tup) > 1 else ""
        event_end   = tup[2] if len(tup) > 2 else ""
        event_slug  = tup[3] if len(tup) > 3 else ""
        mkt = parse_sports_market(
            raw_mkt, event_title=event_title,
            end_date_str=event_end, event_slug=event_slug,
        )
        if mkt is None:
            continue
        try:
            forecast = _sports_client.get_outcome_forecast(
                home_team=mkt.home_team,
                away_team=mkt.away_team,
                sport=mkt.sport,
                outcome=mkt.outcome,
                resolution_date=mkt.resolution_date,
            )
        except Exception as exc:
            logger.debug("bot analysis: sports skip %s: %s", mkt.home_team, exc)
            continue
        result = edge_calculator.analyze_market(mkt, forecast)
        result.alert = result.edge > edge_threshold
        if result.alert:
            results.append(result)

    # ── Politics markets ───────────────────────────────────────────────────────
    try:
        raw_politics = _poly_client.fetch_politics_markets(
            max_days=settings.MAX_DAYS_TO_EXPIRY
        )
    except PolymarketAPIError as exc:
        logger.warning("bot analysis: politics fetch failed: %s", exc)
        raw_politics = []

    for tup in raw_politics[:max_markets]:
        raw_mkt    = tup[0]
        event_title = tup[1] if len(tup) > 1 else ""
        event_end   = tup[2] if len(tup) > 2 else ""
        event_slug  = tup[3] if len(tup) > 3 else ""
        mkt = parse_politics_market(
            raw_mkt, event_title=event_title,
            end_date_str=event_end, event_slug=event_slug,
        )
        if mkt is None:
            continue
        try:
            forecast = _politics_client.get_metaculus_forecast(
                topic=mkt.topic,
                resolution_date=mkt.resolution_date,
            )
        except Exception as exc:
            logger.debug("bot analysis: politics skip %s: %s", mkt.topic[:30], exc)
            continue
        result = edge_calculator.analyze_market(mkt, forecast)
        result.alert = result.edge > edge_threshold
        if result.alert:
            results.append(result)

    # Sort by edge descending
    results.sort(key=lambda r: r.edge, reverse=True)
    logger.info(
        "bot analysis: %d alerts found (threshold=%.0f%%)",
        len(results), edge_threshold * 100,
    )
    return results


async def run_analysis_for_bot(
    edge_threshold: float = 0.10,
    max_markets: int = 100,
    model: str = "ecmwf_ifs025",
) -> List[OpportunityResult]:
    """
    Async wrapper for the analysis pipeline.
    Runs the sync pipeline in a thread pool executor so it doesn't block
    the asyncio event loop (FastAPI + Telegram bot share the same loop).
    """
    loop = asyncio.get_event_loop()
    func = partial(
        _run_analysis_sync,
        edge_threshold=edge_threshold,
        max_markets=max_markets,
        model=model,
    )
    return await loop.run_in_executor(None, func)
