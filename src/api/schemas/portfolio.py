"""
Pydantic response schemas for portfolio and positions endpoints.
All monetary values are in USD. All percentages are expressed as floats (e.g. 12.5 = 12.5%).
"""
from typing import Optional
from pydantic import BaseModel, Field


class RoiPoint(BaseModel):
    """Single data point for the ROI-over-time chart."""
    date: str = Field(description="ISO-8601 date string (YYYY-MM-DD)")
    value: float = Field(description="Portfolio value in USD at this date")


class PositionItem(BaseModel):
    condition_id: str
    question: str
    side: str = Field(description="'YES' or 'NO'")
    size: float = Field(description="Number of outcome tokens held")
    avg_price: float = Field(description="Average entry price (0–1)")
    current_price: float = Field(description="Current market price (0–1)")
    current_value: float = Field(description="Current value in USD")
    initial_value: float = Field(description="Cost basis in USD")
    unrealized_pnl: float
    unrealized_pnl_pct: float
    status: str = Field(description="'open' or 'closed'")
    realized_pnl: Optional[float] = Field(
        default=None, description="Only present for closed positions"
    )


class PortfolioResponse(BaseModel):
    total_current_value: float
    total_initial_value: float
    total_pnl: float
    total_pnl_pct: float
    position_count: int
    unrealized_pnl: float
    realized_pnl: float
    roi_history: list[RoiPoint]
    fetched_at: str = Field(description="ISO-8601 UTC timestamp of data fetch")


class PositionsResponse(BaseModel):
    positions: list[PositionItem]
    fetched_at: str = Field(description="ISO-8601 UTC timestamp of data fetch")
