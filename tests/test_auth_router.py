"""
Integration tests for /auth/nonce and /auth/verify endpoints.

Uses FastAPI TestClient (no real network).
External dependencies (nonce_store, eip712 verifier) are mocked.
"""
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

TEST_SECRET = "a" * 32
TEST_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
# Valid 130-hex signature format (content doesn't matter for mocked tests)
MOCK_SIGNATURE = "0x" + "a" * 130

# Set JWT_SECRET_KEY for the entire module so routes always find it
os.environ.setdefault("JWT_SECRET_KEY", TEST_SECRET)


def make_client() -> TestClient:
    """Build a TestClient with JWT_SECRET_KEY in the environment."""
    os.environ["JWT_SECRET_KEY"] = TEST_SECRET
    from src.api.main import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


# ── /auth/nonce ───────────────────────────────────────────────────────────────

class TestNonceEndpoint:
    def test_valid_address_returns_nonce(self):
        client = make_client()
        resp = client.post("/auth/nonce", json={"address": TEST_ADDRESS})
        assert resp.status_code == 200
        data = resp.json()
        assert "nonce" in data
        assert len(data["nonce"]) > 10
        assert data["expires_in"] == 300

    def test_invalid_address_format_returns_422(self):
        client = make_client()
        resp = client.post("/auth/nonce", json={"address": "not-an-address"})
        assert resp.status_code == 422

    def test_address_too_short_returns_422(self):
        client = make_client()
        resp = client.post("/auth/nonce", json={"address": "0xabc"})
        assert resp.status_code == 422

    def test_missing_body_returns_422(self):
        client = make_client()
        resp = client.post("/auth/nonce")
        assert resp.status_code == 422

    def test_nonce_stored_in_store(self):
        client = make_client()
        resp = client.post("/auth/nonce", json={"address": TEST_ADDRESS})
        assert resp.status_code == 200
        # Second call for same address produces a different nonce
        resp2 = client.post("/auth/nonce", json={"address": TEST_ADDRESS})
        assert resp.json()["nonce"] != resp2.json()["nonce"]

    def test_address_normalised_to_lowercase(self):
        client = make_client()
        mixed = "0xF39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        resp = client.post("/auth/nonce", json={"address": mixed})
        assert resp.status_code == 200


# ── /auth/verify ──────────────────────────────────────────────────────────────

class TestVerifyEndpoint:
    def _get_nonce(self, client: TestClient) -> str:
        resp = client.post("/auth/nonce", json={"address": TEST_ADDRESS})
        return resp.json()["nonce"]

    def test_valid_verification_returns_jwt(self):
        client = make_client()
        nonce = self._get_nonce(client)
        with patch("src.api.routers.auth.verify_eip712_signature", return_value=True):
            resp = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": nonce,
                "issued_at": "2024-01-01T00:00:00Z",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_at" in data

    def test_jwt_sub_matches_address(self):
        client = make_client()
        nonce = self._get_nonce(client)
        with patch("src.api.routers.auth.verify_eip712_signature", return_value=True):
            resp = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": nonce,
                "issued_at": "2024-01-01T00:00:00Z",
            })
        token = resp.json()["access_token"]
        payload = jose_jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["sub"] == TEST_ADDRESS.lower()

    def test_invalid_signature_returns_401(self):
        client = make_client()
        nonce = self._get_nonce(client)
        with patch("src.api.routers.auth.verify_eip712_signature", return_value=False):
            resp = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": nonce,
                "issued_at": "2024-01-01T00:00:00Z",
            })
        assert resp.status_code == 401

    def test_wrong_nonce_returns_401(self):
        client = make_client()
        self._get_nonce(client)  # put a valid nonce in store for addr
        with patch("src.api.routers.auth.verify_eip712_signature", return_value=True):
            resp = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": "A" * 20,  # wrong nonce
                "issued_at": "2024-01-01T00:00:00Z",
            })
        assert resp.status_code == 401

    def test_nonce_cannot_be_reused(self):
        """After a successful verify, the nonce is consumed and cannot be reused."""
        client = make_client()
        nonce = self._get_nonce(client)
        with patch("src.api.routers.auth.verify_eip712_signature", return_value=True):
            resp1 = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": nonce,
                "issued_at": "2024-01-01T00:00:00Z",
            })
            assert resp1.status_code == 200
            resp2 = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": nonce,
                "issued_at": "2024-01-01T00:00:00Z",
            })
        assert resp2.status_code == 401

    def test_malformed_signature_format_returns_422(self):
        client = make_client()
        nonce = self._get_nonce(client)
        resp = client.post("/auth/verify", json={
            "address": TEST_ADDRESS,
            "signature": "0xshort",  # invalid format
            "nonce": nonce,
            "issued_at": "2024-01-01T00:00:00Z",
        })
        assert resp.status_code == 422

    def test_malformed_issued_at_returns_422(self):
        client = make_client()
        nonce = self._get_nonce(client)
        resp = client.post("/auth/verify", json={
            "address": TEST_ADDRESS,
            "signature": MOCK_SIGNATURE,
            "nonce": nonce,
            "issued_at": "not-a-timestamp",
        })
        assert resp.status_code == 422

    def test_error_message_is_generic(self):
        """Error response must not reveal which check failed."""
        client = make_client()
        nonce = self._get_nonce(client)
        with patch("src.api.routers.auth.verify_eip712_signature", return_value=False):
            resp = client.post("/auth/verify", json={
                "address": TEST_ADDRESS,
                "signature": MOCK_SIGNATURE,
                "nonce": nonce,
                "issued_at": "2024-01-01T00:00:00Z",
            })
        body = resp.json()
        assert "detail" in body
        assert "nonce" not in body["detail"].lower()
        assert "signature" not in body["detail"].lower()
        assert "expired" not in body["detail"].lower()


# ── Health check ──────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_ok(self):
        client = make_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
