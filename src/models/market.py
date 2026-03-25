from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WeatherMarket:
    """Parsed Polymarket weather market, ready for analysis."""
    market_id: str
    condition_id: str
    question: str
    city: str
    threshold_celsius: float
    direction: str           # "above", "below", or "exact"
    bucket_type: str         # "above", "below", "exact" — mirrors direction
    resolution_date: datetime
    yes_token_id: str
    no_token_id: str
    market_implied_prob: float   # YES token price from Gamma/CLOB [0.0–1.0]
    liquidity_usd: float
    volume_usd: float
    end_date: datetime
    temp_type: str = field(default="highest")  # "highest" or "lowest"
    event_title: str = field(default="")
    raw_question: str = field(repr=False, default="")
    slug: str = field(default="")
    event_slug: str = field(default="")


@dataclass
class WeatherForecast:
    """Model probability output from Open-Meteo ensemble."""
    city: str
    resolution_date: datetime
    threshold_celsius: float
    direction: str           # "above" or "below"
    model_probability: float         # fraction of ensemble members meeting condition
    ensemble_member_count: int
    forecast_model: str              # e.g. "ecmwf_ifs025"
    raw_temperatures: list           # per-member daily max temps for audit


@dataclass
class OpportunityResult:
    """Combined analysis output for one market."""
    market: WeatherMarket
    forecast: WeatherForecast
    edge: float                      # model_prob - market_implied_prob
    expected_value: float            # EV per dollar wagered on YES
    kelly_fraction: float            # raw Kelly fraction (uncapped)
    suggested_bet_fraction: float    # fractional Kelly after caps
    alert: bool                      # True if edge > EDGE_ALERT_THRESHOLD
