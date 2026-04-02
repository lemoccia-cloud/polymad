"""
Unit tests for /auth/email/register and /auth/email/login endpoints.

All Supabase Auth calls are mocked — no network required.
Pattern follows test_auth_router.py and test_billing.py conventions.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

TEST_SECRET = "a" * 32
TEST_EMAIL = "alice@example.com"
TEST_PASSWORD = "hunter42!"
TEST_UID = "supabase-uid-abc123"

os.environ.setdefault("JWT_SECRET_KEY", TEST_SECRET)

_ENV = {
    "JWT_SECRET_KEY": TEST_SECRET,
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_ANON_KEY": "fakekey",
}


def make_client() -> TestClient:
    os.environ["JWT_SECRET_KEY"] = TEST_SECRET
    from src.api.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ── /auth/email/register ──────────────────────────────────────────────────────

class TestEmailRegister:
    def test_success_returns_201(self):
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_signup",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.upsert_email_user", return_value=True):
            resp = client.post("/auth/email/register", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 201
        assert "message" in resp.json()

    def test_success_message_mentions_email(self):
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_signup",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.upsert_email_user", return_value=True):
            resp = client.post("/auth/email/register", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        msg = resp.json()["message"].lower()
        assert "email" in msg or "verif" in msg

    def test_display_name_optional(self):
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_signup",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.upsert_email_user", return_value=True):
            resp = client.post("/auth/email/register", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "display_name": "Alice",
            })
        assert resp.status_code == 201

    def test_invalid_email_returns_422(self):
        client = make_client()
        with patch.dict(os.environ, _ENV):
            resp = client.post("/auth/email/register", json={
                "email": "not-an-email",
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 422

    def test_short_password_returns_422(self):
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_signup",
                   return_value={"user_id": TEST_UID}):
            resp = client.post("/auth/email/register", json={
                "email": TEST_EMAIL,
                "password": "short",
            })
        assert resp.status_code == 422

    def test_supabase_failure_returns_400(self):
        """Supabase returns None (e.g. email already in use)."""
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_signup", return_value=None):
            resp = client.post("/auth/email/register", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 400

    def test_supabase_not_configured_returns_503(self):
        client = make_client()
        env = {k: v for k, v in _ENV.items() if k != "SUPABASE_URL"}
        # Remove both Supabase vars
        with patch.dict(os.environ, env):
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
            resp = client.post("/auth/email/register", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 503

    def test_missing_body_returns_422(self):
        client = make_client()
        resp = client.post("/auth/email/register")
        assert resp.status_code == 422


# ── /auth/email/login ─────────────────────────────────────────────────────────

class TestEmailLogin:
    def test_success_returns_token(self):
        client = make_client()
        mock_user = {"wallet_address": f"email:{TEST_UID}", "plan": "free"}
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_login",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.get_user_by_supabase_id",
                   return_value=mock_user):
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_at" in data
        assert "plan" in data

    def test_jwt_sub_is_email_user_id(self):
        client = make_client()
        mock_user = {"wallet_address": f"email:{TEST_UID}", "plan": "free"}
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_login",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.get_user_by_supabase_id",
                   return_value=mock_user):
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        token = resp.json()["access_token"]
        payload = jose_jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["sub"] == f"email:{TEST_UID}"

    def test_plan_in_jwt_matches_user_row(self):
        client = make_client()
        mock_user = {"wallet_address": f"email:{TEST_UID}", "plan": "pro"}
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_login",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.get_user_by_supabase_id",
                   return_value=mock_user):
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.json()["plan"] == "pro"
        token = resp.json()["access_token"]
        payload = jose_jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["plan"] == "pro"

    def test_wrong_credentials_returns_401(self):
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_login", return_value=None):
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": "wrongpassword",
            })
        assert resp.status_code == 401

    def test_401_message_is_generic(self):
        """Error must not reveal which field was wrong."""
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_login", return_value=None):
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": "wrongpassword",
            })
        detail = resp.json().get("detail", "").lower()
        assert "email" not in detail or "password" not in detail

    def test_invalid_email_format_returns_422(self):
        client = make_client()
        with patch.dict(os.environ, _ENV):
            resp = client.post("/auth/email/login", json={
                "email": "bad-email",
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 422

    def test_first_login_creates_user_row(self):
        """If get_user_by_supabase_id returns None, upsert_email_user is called."""
        client = make_client()
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.auth_email.supabase_auth_login",
                   return_value={"user_id": TEST_UID}), \
             patch("src.api.routers.auth_email.get_user_by_supabase_id",
                   return_value=None), \
             patch("src.api.routers.auth_email.upsert_email_user",
                   return_value=True) as mock_upsert:
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 200
        mock_upsert.assert_called_once()

    def test_supabase_not_configured_returns_503(self):
        client = make_client()
        with patch.dict(os.environ, _ENV):
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
            resp = client.post("/auth/email/login", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert resp.status_code == 503

    def test_missing_body_returns_422(self):
        client = make_client()
        resp = client.post("/auth/email/login")
        assert resp.status_code == 422
