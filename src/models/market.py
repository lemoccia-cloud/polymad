from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


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
    market_type: str = field(default="weather")


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
    market_type: str = field(default="weather")


# ─── Crypto ──────────────────────────────────────────────────────────────────

@dataclass
class CryptoMarket:
    """Parsed Polymarket crypto price market."""
    market_id: str
    condition_id: str
    question: str
    asset: str               # "BTC", "ETH", "SOL", …
    asset_name: str          # "Bitcoin", "Ethereum", …
    threshold_usd: float
    direction: str           # "above" or "below"
    resolution_date: datetime
    yes_token_id: str
    no_token_id: str
    market_implied_prob: float
    liquidity_usd: float
    volume_usd: float
    end_date: datetime
    event_title: str = field(default="")
    slug: str = field(default="")
    event_slug: str = field(default="")
    market_type: str = field(default="crypto")


@dataclass
class CryptoForecast:
    """Log-normal probability estimate for a crypto price market."""
    asset: str
    resolution_date: datetime
    threshold_usd: float
    direction: str
    model_probability: float
    spot_price: float
    sigma_annual: float      # 30-day historical annualised volatility
    days_to_expiry: int
    market_type: str = field(default="crypto")


# ─── Sports ──────────────────────────────────────────────────────────────────

@dataclass
class SportsMarket:
    """Parsed Polymarket sports outcome market."""
    market_id: str
    condition_id: str
    question: str
    home_team: str
    away_team: str
    sport: str               # "football", "basketball", "other"
    outcome: str             # "home_win", "away_win", "draw"
    resolution_date: datetime
    yes_token_id: str
    no_token_id: str
    market_implied_prob: float
    liquidity_usd: float
    volume_usd: float
    end_date: datetime
    event_title: str = field(default="")
    slug: str = field(default="")
    event_slug: str = field(default="")
    market_type: str = field(default="sports")


@dataclass
class SportsForecast:
    """Elo-based win probability for a sports market."""
    home_team: str
    away_team: str
    outcome: str
    model_probability: float
    elo_home: float
    elo_away: float
    source: str = field(default="clubelo")   # "clubelo" or "baseline"
    market_type: str = field(default="sports")


# ─── Politics ────────────────────────────────────────────────────────────────

@dataclass
class PoliticsMarket:
    """Parsed Polymarket politics/elections market."""
    market_id: str
    condition_id: str
    question: str
    topic: str               # short description for search
    resolution_date: datetime
    yes_token_id: str
    no_token_id: str
    market_implied_prob: float
    liquidity_usd: float
    volume_usd: float
    end_date: datetime
    event_title: str = field(default="")
    slug: str = field(default="")
    event_slug: str = field(default="")
    market_type: str = field(default="politics")


@dataclass
class PoliticsForecast:
    """Metaculus community probability for a politics market."""
    topic: str
    model_probability: float
    source: str = field(default="baseline")   # "metaculus" or "baseline"
    metaculus_id: Optional[int] = field(default=None)
    metaculus_title: str = field(default="")
    market_type: str = field(default="politics")


# ─── Generic result ──────────────────────────────────────────────────────────

@dataclass
class OpportunityResult:
    """Combined analysis output for one market (any type)."""
    market: Any                      # WeatherMarket | CryptoMarket | SportsMarket | PoliticsMarket
    forecast: Any                    # WeatherForecast | CryptoForecast | SportsForecast | PoliticsForecast
    edge: float                      # model_prob - market_implied_prob
    expected_value: float            # EV per dollar wagered on YES
    kelly_fraction: float            # raw Kelly fraction (uncapped)
    suggested_bet_fraction: float    # fractional Kelly after caps
    alert: bool                      # True if edge > EDGE_ALERT_THRESHOLD
