"""
Integration tests for /api/portfolio and /api/positions endpoints.

Verifies:
  - 401 when no JWT is provided
  - 401 when JWT is expired or invalid
  - Correct data returned when authenticated
  - The wallet address comes EXCLUSIVELY from the JWT sub claim,
    NOT from any query parameter or request body.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TEST_SECRET = "a" * 32
TEST_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
ATTACKER_ADDRESS = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"

# Set JWT_SECRET_KEY for the entire module so routes always find it
os.environ["JWT_SECRET_KEY"] = TEST_SECRET

MOCK_POSITIONS = [
    {
        "conditionId": "0xcondition1",
        "title": "Will BTC be above $50k?",
        "outcomeIndex": 0,
        "size": 10.0,
        "avgPrice": 0.6,
        "currentValue": 7.0,
        "initialValue": 6.0,
    },
    {
        "conditionId": "0xcondition2",
        "title": "Will ETH be above $3k?",
        "outcomeIndex": 1,
        "size": 5.0,
        "avgPrice": 0.4,
        "currentValue": 2.5,
        "initialValue": 2.0,
    },
]


def make_client() -> TestClient:
    os.environ["JWT_SECRET_KEY"] = TEST_SECRET
    from src.api.main import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def make_jwt(address: str = TEST_ADDRESS) -> str:
    from src.api.security.jwt_handler import create_access_token
    token, _ = create_access_token(address)
    return token


def auth_headers(address: str = TEST_ADDRESS) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_jwt(address)}"}


# ── /api/portfolio ────────────────────────────────────────────────────────────

class TestPortfolioEndpoint:
    def test_missing_auth_returns_401(self):
        client = make_client()
        resp = client.get("/api/portfolio")
        assert resp.status_code == 401

    def test_invalid_jwt_returns_401(self):
        client = make_client()
        resp = client.get("/api/portfolio", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401

    def test_valid_jwt_returns_portfolio(self):
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=MOCK_POSITIONS):
            resp = client.get("/api/portfolio", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "total_current_value" in data
        assert "total_pnl" in data
        assert data["position_count"] == 2

    def test_pnl_calculation_correct(self):
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=MOCK_POSITIONS):
            resp = client.get("/api/portfolio", headers=auth_headers())
        data = resp.json()
        # total_current = 7.0 + 2.5 = 9.5, total_initial = 6.0 + 2.0 = 8.0
        assert data["total_current_value"] == pytest.approx(9.5, abs=0.01)
        assert data["total_pnl"] == pytest.approx(1.5, abs=0.01)

    def test_address_from_jwt_not_query_params(self):
        """SECURITY: attacker cannot query a victim's portfolio via URL param."""
        client = make_client()
        captured_addresses = []

        def mock_fetch(addr):
            captured_addresses.append(addr)
            return []

        with patch("src.api.routers.portfolio._fetch_positions", side_effect=mock_fetch):
            # Authenticated as TEST_ADDRESS but trying to query ATTACKER_ADDRESS
            resp = client.get(
                "/api/portfolio",
                params={"address": ATTACKER_ADDRESS},  # should be ignored
                headers=auth_headers(TEST_ADDRESS),
            )
        assert resp.status_code == 200
        # The fetch must have used the JWT address, not the query param
        assert len(captured_addresses) == 1
        assert captured_addresses[0] == TEST_ADDRESS

    def test_empty_positions_returns_zeros(self):
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=[]):
            resp = client.get("/api/portfolio", headers=auth_headers())
        data = resp.json()
        assert data["position_count"] == 0
        assert data["total_pnl"] == 0.0


# ── /api/positions ────────────────────────────────────────────────────────────

class TestPositionsEndpoint:
    def test_missing_auth_returns_401(self):
        client = make_client()
        resp = client.get("/api/positions")
        assert resp.status_code == 401

    def test_valid_jwt_returns_positions(self):
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=MOCK_POSITIONS):
            resp = client.get("/api/positions", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert len(data["positions"]) > 0

    def test_open_positions_only_by_default(self):
        """Closed positions (currentValue=0) excluded by default."""
        positions_with_closed = MOCK_POSITIONS + [{
            "conditionId": "0xclosed",
            "title": "Closed market",
            "outcomeIndex": 0,
            "size": 5.0,
            "avgPrice": 0.5,
            "currentValue": 0.0,
            "initialValue": 2.5,
        }]
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=positions_with_closed):
            resp = client.get("/api/positions", headers=auth_headers())
        data = resp.json()
        statuses = [p["status"] for p in data["positions"]]
        assert "closed" not in statuses

    def test_include_closed_param(self):
        positions_with_closed = MOCK_POSITIONS + [{
            "conditionId": "0xclosed",
            "title": "Closed market",
            "outcomeIndex": 0,
            "size": 5.0,
            "avgPrice": 0.5,
            "currentValue": 0.0,
            "initialValue": 2.5,
        }]
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=positions_with_closed):
            resp = client.get("/api/positions", params={"include_closed": "true"}, headers=auth_headers())
        data = resp.json()
        statuses = [p["status"] for p in data["positions"]]
        assert "closed" in statuses

    def test_each_position_has_pnl_fields(self):
        client = make_client()
        with patch("src.api.routers.portfolio._fetch_positions", return_value=MOCK_POSITIONS):
            resp = client.get("/api/positions", headers=auth_headers())
        for pos in resp.json()["positions"]:
            assert "unrealized_pnl" in pos
            assert "unrealized_pnl_pct" in pos
            assert "current_value" in pos
            assert "initial_value" in pos

    def test_address_from_jwt_not_query_params(self):
        """SECURITY: attacker cannot query a victim's positions via URL param."""
        client = make_client()
        captured = []

        def mock_fetch(addr):
            captured.append(addr)
            return []

        with patch("src.api.routers.portfolio._fetch_positions", side_effect=mock_fetch):
            resp = client.get(
                "/api/positions",
                params={"address": ATTACKER_ADDRESS},
                headers=auth_headers(TEST_ADDRESS),
            )
        assert resp.status_code == 200
        assert captured[0] == TEST_ADDRESS
