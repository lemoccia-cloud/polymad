"""
Portfolio endpoints — authenticated routes.

GET /api/portfolio  — aggregated portfolio summary (P&L, ROI)
GET /api/positions  — individual positions with per-position P&L

SECURITY:
  - Both routes require a valid Bearer JWT (via get_current_address dependency).
  - The wallet address used for ALL data lookups comes exclusively from the
    decoded JWT `sub` claim.  Query parameters and request bodies cannot
    influence which address is queried.
  - Rate limit: 30 req/min per IP.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_current_address
from src.api.schemas.portfolio import (
    PortfolioResponse,
    PositionItem,
    PositionsResponse,
    RoiPoint,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_positions(address: str) -> list[dict]:
    """Fetch raw positions from Polymarket CLOB API via existing client."""
    try:
        from src.data.polymarket_client import PolymarketClient
        client = PolymarketClient()
        return client.get_user_positions(address)
    except Exception:
        logger.error("portfolio.fetch_positions error addr_prefix=%s", address[:8])
        return []


def _build_position_item(raw: dict) -> PositionItem:
    """Convert a raw Polymarket position dict to a typed PositionItem."""
    current_value = float(raw.get("currentValue", 0) or 0)
    initial_value = float(raw.get("initialValue", 0) or 0)
    size = float(raw.get("size", 0) or 0)
    avg_price = float(raw.get("avgPrice", 0) or 0)

    # Derive current price from current value / size (avoid div-by-zero)
    current_price = (current_value / size) if size > 0 else avg_price

    unrealized_pnl = current_value - initial_value
    unrealized_pnl_pct = (
        (unrealized_pnl / initial_value * 100) if initial_value > 0 else 0.0
    )

    # Determine side from outcomeIndex (0 = YES, 1 = NO)
    outcome_index = int(raw.get("outcomeIndex", 0) or 0)
    side = "YES" if outcome_index == 0 else "NO"

    # A position is "closed" when currentValue == 0 and size > 0
    status = "closed" if current_value == 0 and initial_value > 0 else "open"
    realized_pnl: Optional[float] = None
    if status == "closed":
        realized_pnl = -initial_value  # full loss if closed at zero value

    return PositionItem(
        condition_id=str(raw.get("conditionId", "")),
        question=str(raw.get("title", raw.get("question", "Unknown market"))),
        side=side,
        size=size,
        avg_price=avg_price,
        current_price=current_price,
        current_value=current_value,
        initial_value=initial_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        status=status,
        realized_pnl=realized_pnl,
    )


def _compute_realized_pnl(positions: list[PositionItem]) -> float:
    """Sum realized P&L from all closed positions."""
    return sum(p.realized_pnl for p in positions if p.realized_pnl is not None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/portfolio",
    response_model=PortfolioResponse,
    summary="Get aggregated portfolio summary",
)
def get_portfolio(
    address: str = Depends(get_current_address),
) -> PortfolioResponse:
    """
    Returns aggregated portfolio metrics for the authenticated wallet.
    The address is derived exclusively from the verified JWT — not from
    any request parameter.

    Rate limit: 30 requests per minute per IP.
    """
    raw_positions = _fetch_positions(address)
    items = [_build_position_item(p) for p in raw_positions]

    total_current = sum(p.current_value for p in items)
    total_initial = sum(p.initial_value for p in items)
    total_pnl = total_current - total_initial
    total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0.0
    unrealized = sum(p.unrealized_pnl for p in items if p.status == "open")
    realized = _compute_realized_pnl(items)

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        "portfolio.get positions=%d addr_prefix=%s",
        len(items),
        address[:8],
    )

    return PortfolioResponse(
        total_current_value=total_current,
        total_initial_value=total_initial,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        position_count=len(items),
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        roi_history=[],  # placeholder — full history requires Supabase scan records
        fetched_at=fetched_at,
    )


@router.get(
    "/positions",
    response_model=PositionsResponse,
    summary="Get individual positions with per-position P&L",
)
def get_positions(
    include_closed: bool = Query(default=False, description="Include closed positions"),
    address: str = Depends(get_current_address),
) -> PositionsResponse:
    """
    Returns all positions for the authenticated wallet with per-position P&L.
    By default only open positions are returned.  Pass include_closed=true
    to also include resolved/closed positions.

    The address is derived exclusively from the verified JWT.

    Rate limit: 30 requests per minute per IP.
    """
    raw_positions = _fetch_positions(address)
    items = [_build_position_item(p) for p in raw_positions]

    if not include_closed:
        items = [p for p in items if p.status == "open"]

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return PositionsResponse(positions=items, fetched_at=fetched_at)
