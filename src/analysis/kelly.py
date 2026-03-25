"""
Kelly Criterion position sizing for binary prediction markets.

Typical usage pipeline:
    raw_kelly = compute_kelly_fraction(model_prob, market_price)
    fractional = apply_fractional_kelly(raw_kelly)
    capped = apply_kelly_caps(fractional)
    bet_usd = capped * bankroll
"""
from config import settings


def apply_fractional_kelly(
    kelly_fraction: float,
    multiplier: float = settings.KELLY_FRACTIONAL_MULTIPLIER,
) -> float:
    """
    Scale down the Kelly fraction by multiplier to reduce variance.
    Quarter-Kelly (multiplier=0.25) is a common conservative choice.
    """
    return kelly_fraction * multiplier


def apply_kelly_caps(
    fraction: float,
    min_fraction: float = settings.MIN_KELLY_FRACTION,
    max_fraction: float = settings.MAX_KELLY_FRACTION,
) -> float:
    """
    Clamp the Kelly fraction to [min_fraction, max_fraction].
    Returns 0.0 if fraction is below min_fraction (no bet signal).
    """
    if fraction < min_fraction:
        return 0.0
    return min(fraction, max_fraction)


def compute_position_size(
    bankroll: float,
    kelly_fraction: float,
    multiplier: float = settings.KELLY_FRACTIONAL_MULTIPLIER,
    min_fraction: float = settings.MIN_KELLY_FRACTION,
    max_fraction: float = settings.MAX_KELLY_FRACTION,
) -> float:
    """
    Full pipeline: fractional Kelly -> cap -> dollar amount.

    Returns dollar amount to bet (0.0 means no bet).
    """
    fractional = apply_fractional_kelly(kelly_fraction, multiplier)
    capped = apply_kelly_caps(fractional, min_fraction, max_fraction)
    return bankroll * capped


def kelly_summary(
    raw_kelly: float,
    bankroll: float,
    multiplier: float = settings.KELLY_FRACTIONAL_MULTIPLIER,
) -> dict:
    """
    Return all intermediate Kelly sizing values for display or debugging.
    """
    fractional = apply_fractional_kelly(raw_kelly, multiplier)
    capped = apply_kelly_caps(fractional)
    suggested_bet = bankroll * capped

    return {
        "raw_kelly": raw_kelly,
        "fractional_kelly": fractional,
        "capped_kelly": capped,
        "suggested_bet_usd": suggested_bet,
        "bankroll": bankroll,
        "multiplier": multiplier,
    }
