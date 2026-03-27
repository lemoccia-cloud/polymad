"""
Edge calculation for prediction market opportunities.

All functions are pure (no I/O, no side effects) and operate on floats.

Key formulas:
  edge     = model_prob - market_price
  EV       = model_prob * (1/price - 1) - (1 - model_prob)
             = (model_prob / price) - 1
  Kelly    = (b * p - q) / b
             where b = (1/price) - 1, p = model_prob, q = 1 - model_prob
"""
from config import settings
from typing import Any
from src.models.market import OpportunityResult
from src.analysis.kelly import apply_fractional_kelly, apply_kelly_caps


def compute_edge(market_implied_prob: float, model_probability: float) -> float:
    """
    Difference between model probability and market-implied probability.
    Positive means model thinks YES is more likely than the market prices in.
    """
    return model_probability - market_implied_prob


def compute_expected_value(model_probability: float, market_price: float) -> float:
    """
    Expected value of a $1 bet on YES at market_price.

    Using decimal odds: payout on a winning $1 bet = (1/price - 1)
      EV = p * (1/price - 1) - (1 - p) * 1
         = p/price - p - 1 + p
         = p/price - 1

    Example: model_prob=0.78, market_price=0.62
      b = 1/0.62 - 1 = 0.613
      EV = 0.78 * 0.613 - 0.22 = 0.478 - 0.22 = +$0.258 per dollar at risk
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0
    return (model_probability / market_price) - 1.0


def compute_kelly_fraction(model_probability: float, market_price: float) -> float:
    """
    Raw Kelly criterion fraction for a binary market.

    Kelly = (b * p - q) / b
    where:
      b = (1 / market_price) - 1   (decimal odds minus 1, i.e. net profit per $1)
      p = model_probability
      q = 1 - p

    Returns a fraction of bankroll to wager. Negative = no bet.
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0
    b = (1.0 / market_price) - 1.0
    if b <= 0:
        return 0.0
    p = model_probability
    q = 1.0 - p
    return (b * p - q) / b


def analyze_market(market: Any, forecast: Any) -> OpportunityResult:
    """
    Compute edge, EV, and Kelly sizing for one market vs. its forecast.
    Works for any market type (weather, crypto, sports, politics).
    """
    edge = compute_edge(market.market_implied_prob, forecast.model_probability)
    ev = compute_expected_value(forecast.model_probability, market.market_implied_prob)
    raw_kelly = compute_kelly_fraction(forecast.model_probability, market.market_implied_prob)

    fractional = apply_fractional_kelly(raw_kelly)
    suggested = apply_kelly_caps(fractional)

    alert = edge > settings.EDGE_ALERT_THRESHOLD

    return OpportunityResult(
        market=market,
        forecast=forecast,
        edge=edge,
        expected_value=ev,
        kelly_fraction=raw_kelly,
        suggested_bet_fraction=suggested,
        alert=alert,
    )


def rank_opportunities(results: list, by: str = "expected_value") -> list:
    """
    Sort OpportunityResult list descending by the chosen metric.
    Filters out results with non-positive EV (no edge to exploit).

    Args:
        results: list of OpportunityResult
        by: one of "expected_value", "edge", "kelly_fraction"

    Returns:
        New sorted list (input is not mutated).
    """
    key_map = {
        "expected_value": lambda r: r.expected_value,
        "edge": lambda r: r.edge,
        "kelly_fraction": lambda r: r.kelly_fraction,
    }
    key_fn = key_map.get(by, key_map["expected_value"])
    positive = [r for r in results if r.expected_value > 0]
    return sorted(positive, key=key_fn, reverse=True)
