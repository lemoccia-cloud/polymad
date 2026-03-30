"""
Unit tests for realized P&L calculation logic in the portfolio router.

Tests the _compute_realized_pnl helper and _build_position_item conversion.
"""
import pytest

from src.api.routers.portfolio import _compute_realized_pnl, _build_position_item
from src.api.schemas.portfolio import PositionItem


def make_position(**overrides) -> dict:
    """Factory for raw Polymarket position dicts."""
    base = {
        "conditionId": "0xabc",
        "title": "Will it rain?",
        "outcomeIndex": 0,
        "size": 10.0,
        "avgPrice": 0.5,
        "currentValue": 6.0,
        "initialValue": 5.0,
    }
    base.update(overrides)
    return base


def make_item(**overrides) -> PositionItem:
    """Factory for PositionItem instances using _build_position_item."""
    return _build_position_item(make_position(**overrides))


# ── _build_position_item ──────────────────────────────────────────────────────

class TestBuildPositionItem:
    def test_yes_side_from_outcome_index_0(self):
        item = make_item(outcomeIndex=0)
        assert item.side == "YES"

    def test_no_side_from_outcome_index_1(self):
        item = make_item(outcomeIndex=1)
        assert item.side == "NO"

    def test_open_status_for_nonzero_value(self):
        item = make_item(currentValue=5.0, initialValue=10.0)
        assert item.status == "open"

    def test_closed_status_when_current_value_is_zero(self):
        item = make_item(currentValue=0.0, initialValue=10.0)
        assert item.status == "closed"

    def test_unrealized_pnl_gain(self):
        item = make_item(currentValue=7.0, initialValue=5.0)
        assert pytest.approx(item.unrealized_pnl, abs=0.01) == 2.0

    def test_unrealized_pnl_loss(self):
        item = make_item(currentValue=3.0, initialValue=5.0)
        assert pytest.approx(item.unrealized_pnl, abs=0.01) == -2.0

    def test_unrealized_pnl_pct_calculation(self):
        item = make_item(currentValue=6.0, initialValue=5.0)
        assert pytest.approx(item.unrealized_pnl_pct, abs=0.1) == 20.0

    def test_zero_initial_value_no_division_error(self):
        item = make_item(currentValue=1.0, initialValue=0.0)
        assert item.unrealized_pnl_pct == 0.0

    def test_closed_position_has_realized_pnl(self):
        item = make_item(currentValue=0.0, initialValue=10.0)
        assert item.realized_pnl is not None
        assert item.realized_pnl == pytest.approx(-10.0, abs=0.01)

    def test_open_position_realized_pnl_is_none(self):
        item = make_item(currentValue=5.0, initialValue=10.0)
        assert item.realized_pnl is None

    def test_string_values_are_coerced_to_float(self):
        """Raw API may return numeric strings."""
        item = make_item(currentValue="6.5", initialValue="5.0", size="10.0")
        assert item.current_value == pytest.approx(6.5)
        assert item.initial_value == pytest.approx(5.0)


# ── _compute_realized_pnl ─────────────────────────────────────────────────────

class TestComputeRealizedPnl:
    def test_empty_list_returns_zero(self):
        assert _compute_realized_pnl([]) == 0.0

    def test_all_open_positions_returns_zero(self):
        items = [make_item(currentValue=5.0, initialValue=10.0) for _ in range(3)]
        assert _compute_realized_pnl(items) == 0.0

    def test_single_closed_losing_position(self):
        items = [make_item(currentValue=0.0, initialValue=10.0)]
        result = _compute_realized_pnl(items)
        assert result == pytest.approx(-10.0, abs=0.01)

    def test_multiple_closed_positions_summed(self):
        items = [
            make_item(currentValue=0.0, initialValue=10.0),  # -10
            make_item(currentValue=0.0, initialValue=5.0),   # -5
        ]
        result = _compute_realized_pnl(items)
        assert result == pytest.approx(-15.0, abs=0.01)

    def test_mixed_open_and_closed(self):
        items = [
            make_item(currentValue=7.0, initialValue=5.0),   # open, no realized
            make_item(currentValue=0.0, initialValue=8.0),   # closed, -8
        ]
        result = _compute_realized_pnl(items)
        assert result == pytest.approx(-8.0, abs=0.01)
