"""
Tests for pure logic in src/components/wallet.py.
Tests P&L calculations, USDC balance decoding, and address formatting.
"""
import pytest
from unittest.mock import patch, MagicMock


# ─── P&L calculation helpers (extracted from render_wallet_tab) ───────────────

def _compute_portfolio_pnl(positions: list) -> dict:
    """
    Mirror of the P&L logic at wallet.py lines 270-273.
    Returns dict with total_current, total_initial, total_pnl, total_pnl_pct.
    """
    total_current = sum(float(p.get("currentValue", 0)) for p in positions)
    total_initial = sum(float(p.get("initialValue", 0)) for p in positions)
    total_pnl = total_current - total_initial
    total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0.0
    return {
        "total_current": total_current,
        "total_initial": total_initial,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
    }


def _compute_position_pnl(pos: dict) -> dict:
    """Mirror of per-position P&L logic at wallet.py lines 295-298."""
    current_value = float(pos.get("currentValue", 0))
    initial_value = float(pos.get("initialValue", 0))
    pnl = current_value - initial_value
    pnl_pct = (pnl / initial_value * 100) if initial_value > 0 else 0.0
    return {"pnl": pnl, "pnl_pct": pnl_pct}


# ─── TestPortfolioPnL ─────────────────────────────────────────────────────────

class TestPortfolioPnL:
    def test_profit_scenario(self):
        positions = [
            {"currentValue": 120.0, "initialValue": 100.0},
            {"currentValue": 55.0,  "initialValue": 50.0},
        ]
        r = _compute_portfolio_pnl(positions)
        assert r["total_current"] == pytest.approx(175.0)
        assert r["total_initial"] == pytest.approx(150.0)
        assert r["total_pnl"] == pytest.approx(25.0)
        assert r["total_pnl_pct"] == pytest.approx(25.0 / 150.0 * 100)

    def test_loss_scenario(self):
        positions = [{"currentValue": 80.0, "initialValue": 100.0}]
        r = _compute_portfolio_pnl(positions)
        assert r["total_pnl"] == pytest.approx(-20.0)
        assert r["total_pnl_pct"] == pytest.approx(-20.0)

    def test_breakeven(self):
        positions = [{"currentValue": 100.0, "initialValue": 100.0}]
        r = _compute_portfolio_pnl(positions)
        assert r["total_pnl"] == pytest.approx(0.0)
        assert r["total_pnl_pct"] == pytest.approx(0.0)

    def test_zero_initial_avoids_division_by_zero(self):
        positions = [{"currentValue": 50.0, "initialValue": 0.0}]
        r = _compute_portfolio_pnl(positions)
        assert r["total_pnl_pct"] == 0.0  # safe default

    def test_empty_positions(self):
        r = _compute_portfolio_pnl([])
        assert r["total_current"] == 0.0
        assert r["total_pnl"] == 0.0
        assert r["total_pnl_pct"] == 0.0

    def test_missing_keys_default_to_zero(self):
        positions = [{"currentValue": 50.0}]  # no initialValue
        r = _compute_portfolio_pnl(positions)
        assert r["total_initial"] == 0.0
        assert r["total_pnl_pct"] == 0.0

    def test_string_values_are_coerced(self):
        # API sometimes returns strings
        positions = [{"currentValue": "110.5", "initialValue": "100.0"}]
        r = _compute_portfolio_pnl(positions)
        assert r["total_pnl"] == pytest.approx(10.5)


# ─── TestPositionPnL ──────────────────────────────────────────────────────────

class TestPositionPnL:
    def test_gain(self):
        r = _compute_position_pnl({"currentValue": 75.0, "initialValue": 50.0})
        assert r["pnl"] == pytest.approx(25.0)
        assert r["pnl_pct"] == pytest.approx(50.0)

    def test_loss(self):
        r = _compute_position_pnl({"currentValue": 30.0, "initialValue": 50.0})
        assert r["pnl"] == pytest.approx(-20.0)
        assert r["pnl_pct"] == pytest.approx(-40.0)

    def test_zero_initial_pct_is_zero(self):
        r = _compute_position_pnl({"currentValue": 10.0, "initialValue": 0.0})
        assert r["pnl_pct"] == 0.0


# ─── TestUsdcBalance ──────────────────────────────────────────────────────────

class TestUsdcBalance:
    def test_returns_zero_for_empty_address(self):
        from src.components.wallet import get_usdc_balance
        assert get_usdc_balance("") == 0.0

    def test_returns_zero_on_request_error(self):
        from src.components.wallet import get_usdc_balance
        with patch("requests.post", side_effect=Exception("network error")):
            assert get_usdc_balance("0xAbCd1234") == 0.0

    def test_decodes_hex_result_correctly(self):
        from src.components.wallet import get_usdc_balance
        # 1_000_000 raw units = 1.0 USDC (6 decimals)
        hex_val = hex(1_000_000)  # "0xf4240"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": hex_val}
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp):
            balance = get_usdc_balance("0xAbCd1234")
        assert balance == pytest.approx(1.0)

    def test_decodes_large_balance(self):
        from src.components.wallet import get_usdc_balance
        # 5_000 USDC = 5_000_000_000 raw
        raw = 5_000 * 10 ** 6
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": hex(raw)}
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp):
            balance = get_usdc_balance("0xDeAdBeEf")
        assert balance == pytest.approx(5000.0)

    def test_returns_zero_on_invalid_hex(self):
        from src.components.wallet import get_usdc_balance
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": "not_valid_hex"}
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp):
            assert get_usdc_balance("0xAbCd") == 0.0


# ─── TestAddressFormatting ────────────────────────────────────────────────────

class TestAddressFormatting:
    """Verify the address shortening logic used in wallet.py."""

    def _shorten(self, address: str) -> str:
        return address[:6] + "..." + address[-4:]

    def test_standard_eth_address(self):
        addr = "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12"
        short = self._shorten(addr)
        assert short == "0xAbCd...Ef12"

    def test_short_prefix_and_suffix(self):
        addr = "0x1111222233334444555566667777888899990000"
        short = self._shorten(addr)
        assert short.startswith("0x1111")
        assert short.endswith("0000")
        assert "..." in short
