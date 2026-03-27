"""
CoinGecko-based crypto probability client for polyMad.

Uses the CoinGecko public API (no API key required for basic endpoints)
to fetch spot price + 30-day historical volatility, then applies a
log-normal (risk-neutral) model to compute P(price ≥ threshold).

No extra dependencies — uses only stdlib + requests.
"""
import logging
import math
import time
from datetime import datetime, timezone
from statistics import NormalDist, stdev
from typing import Optional

import requests

from src.models.market import CryptoForecast

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Polymarket name/symbol → CoinGecko coin id
ASSET_IDS: dict = {
    "BTC":      "bitcoin",
    "BITCOIN":  "bitcoin",
    "ETH":      "ethereum",
    "ETHEREUM": "ethereum",
    "SOL":      "solana",
    "SOLANA":   "solana",
    "XRP":      "ripple",
    "DOGE":     "dogecoin",
    "DOGECOIN": "dogecoin",
    "ADA":      "cardano",
    "CARDANO":  "cardano",
    "AVAX":     "avalanche-2",
    "AVALANCHE":"avalanche-2",
    "MATIC":    "matic-network",
    "POLYGON":  "matic-network",
    "LINK":     "chainlink",
    "DOT":      "polkadot",
    "SHIB":     "shiba-inu",
    "LTC":      "litecoin",
    "BCH":      "bitcoin-cash",
    "UNI":      "uniswap",
    "ATOM":     "cosmos",
    "TON":      "the-open-network",
    "SUI":      "sui",
    "APT":      "aptos",
}

_REQUEST_TIMEOUT = 10
_HISTORY_DAYS = 30   # volatility window


class CryptoAPIError(Exception):
    pass


def _resolve_asset(symbol_or_name: str) -> Optional[str]:
    """Return CoinGecko id for an asset symbol/name, or None."""
    key = symbol_or_name.strip().upper()
    return ASSET_IDS.get(key)


def _get_json(session: requests.Session, url: str, params: dict = None) -> dict:
    """Simple GET with retry on rate-limit (429)."""
    for attempt in range(3):
        try:
            resp = session.get(url, params=params or {}, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise CryptoAPIError(f"CoinGecko request failed: {exc}") from exc
            time.sleep(1)
    raise CryptoAPIError("CoinGecko: max retries exceeded")


def _get_spot_price(session: requests.Session, coin_id: str) -> float:
    """Fetch current USD price for a coin."""
    data = _get_json(
        session,
        f"{COINGECKO_BASE}/simple/price",
        {"ids": coin_id, "vs_currencies": "usd"},
    )
    price = data.get(coin_id, {}).get("usd")
    if price is None:
        raise CryptoAPIError(f"No price returned for {coin_id}")
    return float(price)


def _get_historical_volatility(session: requests.Session, coin_id: str, days: int = _HISTORY_DAYS) -> float:
    """
    Compute annualised daily-close volatility from CoinGecko market_chart.

    Returns sigma as a fraction (e.g. 0.65 = 65% annual volatility).
    Falls back to 0.80 (high volatility assumption) on any error.
    """
    try:
        data = _get_json(
            session,
            f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": str(days), "interval": "daily"},
        )
        prices = [p[1] for p in data.get("prices", []) if p[1] is not None]
        if len(prices) < 5:
            logger.warning("Insufficient price history for %s, using fallback sigma", coin_id)
            return 0.80

        # Daily log-returns
        log_returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        daily_sigma = stdev(log_returns)
        annual_sigma = daily_sigma * math.sqrt(365)
        logger.debug("Volatility for %s: daily=%.4f annual=%.4f", coin_id, daily_sigma, annual_sigma)
        return annual_sigma

    except (CryptoAPIError, ZeroDivisionError, ValueError) as exc:
        logger.warning("Volatility fetch failed for %s: %s — using 0.80 fallback", coin_id, exc)
        return 0.80


def lognormal_prob(
    spot: float,
    target: float,
    sigma_annual: float,
    days_to_expiry: int,
    direction: str,
) -> float:
    """
    Compute P(S_T >= target) or P(S_T <= target) using risk-neutral log-normal.

    Assumes zero drift (conservative / risk-neutral measure).
    Uses Python stdlib NormalDist — no scipy required.

    Args:
        spot: current asset price
        target: threshold price from the market question
        sigma_annual: annualised volatility fraction (e.g. 0.65)
        days_to_expiry: calendar days until resolution
        direction: "above" → P(S_T ≥ target); "below" → P(S_T ≤ target)

    Returns:
        Probability in [0.0, 1.0]
    """
    if spot <= 0 or target <= 0 or sigma_annual <= 0:
        return 0.5

    T = max(days_to_expiry, 1) / 365.0
    sigma_T = sigma_annual * math.sqrt(T)

    # d = [ln(K/S) - mu*T] / sigma_T  where mu = -0.5*sigma^2 (risk-neutral)
    mu_T = -0.5 * sigma_annual ** 2 * T
    d = (math.log(target / spot) - mu_T) / sigma_T

    norm = NormalDist()
    p_above = 1.0 - norm.cdf(d)   # P(S_T >= target)
    p_above = max(0.001, min(0.999, p_above))

    return p_above if direction == "above" else (1.0 - p_above)


class CryptoClient:
    """Fetches crypto price forecasts using CoinGecko + log-normal model."""

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": "polyMad/1.0"})

    def get_lognormal_forecast(
        self,
        asset: str,
        resolution_date: datetime,
        threshold_usd: float,
        direction: str,
    ) -> CryptoForecast:
        """
        Compute model probability for a crypto price market.

        Args:
            asset: ticker symbol, e.g. "BTC", "ETH"
            resolution_date: expiry date of the market
            threshold_usd: price threshold from the question
            direction: "above" or "below"

        Returns:
            CryptoForecast with model_probability, spot, sigma, days

        Raises:
            CryptoAPIError: if CoinGecko is unavailable
            ValueError: if asset is unknown
        """
        coin_id = _resolve_asset(asset)
        if coin_id is None:
            raise ValueError(f"Unknown asset symbol: {asset!r}. Add to ASSET_IDS.")

        spot = _get_spot_price(self._session, coin_id)
        sigma = _get_historical_volatility(self._session, coin_id)

        today = datetime.now(tz=timezone.utc).date()
        days = max(1, (resolution_date.date() - today).days)

        probability = lognormal_prob(spot, threshold_usd, sigma, days, direction)

        logger.debug(
            "Crypto forecast: %s spot=%.2f target=%.2f sigma=%.2f T=%dd dir=%s → prob=%.3f",
            asset, spot, threshold_usd, sigma, days, direction, probability,
        )

        return CryptoForecast(
            asset=asset.upper(),
            resolution_date=resolution_date,
            threshold_usd=threshold_usd,
            direction=direction,
            model_probability=probability,
            spot_price=spot,
            sigma_annual=sigma,
            days_to_expiry=days,
        )
