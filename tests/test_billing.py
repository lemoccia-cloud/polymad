"""
Unit tests for src/api/routers/billing.py

All Stripe API calls and Supabase lookups are mocked.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET_KEY", "a" * 32)

from src.api.main import create_app
from src.api.security.jwt_handler import create_access_token

app = create_app()
client = TestClient(app)

TEST_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"

_ENV = {
    "STRIPE_SECRET_KEY": "sk_test_fake",
    "STRIPE_PRICE_PRO_MONTHLY": "price_pro",
    "STRIPE_PRICE_TRADER_MONTHLY": "price_trader",
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_ANON_KEY": "fakekey",
}


def _make_token(plan: str = "free") -> str:
    token, _ = create_access_token(TEST_ADDRESS, plan=plan)
    return token


def _auth_headers(plan: str = "free") -> dict:
    return {"Authorization": f"Bearer {_make_token(plan)}"}


# ── /api/billing/checkout ─────────────────────────────────────────────────────

class TestCheckoutEndpoint:
    def test_requires_auth(self):
        resp = client.post(
            "/api/billing/checkout",
            params={"plan": "pro", "success_url": "http://ok", "cancel_url": "http://cancel"},
        )
        assert resp.status_code == 401

    def test_invalid_plan_returns_422(self):
        with patch.dict(os.environ, _ENV):
            resp = client.post(
                "/api/billing/checkout",
                params={"plan": "enterprise", "success_url": "http://ok", "cancel_url": "http://cancel"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_returns_checkout_url(self):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/test_session"
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.billing.get_stripe_customer_id", return_value=None), \
             patch("stripe.checkout.Session.create", return_value=mock_session):
            resp = client.post(
                "/api/billing/checkout",
                params={"plan": "pro", "success_url": "http://ok", "cancel_url": "http://cancel"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/test_session"

    def test_reuses_existing_customer(self):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/xyz"
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.billing.get_stripe_customer_id", return_value="cus_existing"), \
             patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
            client.post(
                "/api/billing/checkout",
                params={"plan": "pro", "success_url": "http://ok", "cancel_url": "http://cancel"},
                headers=_auth_headers(),
            )
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs.get("customer") == "cus_existing"

    def test_stripe_error_returns_502(self):
        import stripe
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.billing.get_stripe_customer_id", return_value=None), \
             patch("stripe.checkout.Session.create", side_effect=stripe.StripeError("fail")):
            resp = client.post(
                "/api/billing/checkout",
                params={"plan": "trader", "success_url": "http://ok", "cancel_url": "http://cancel"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 502

    def test_missing_stripe_key_returns_503(self):
        env = {**_ENV}
        env.pop("STRIPE_SECRET_KEY", None)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("STRIPE_SECRET_KEY", None)
            resp = client.post(
                "/api/billing/checkout",
                params={"plan": "pro", "success_url": "http://ok", "cancel_url": "http://cancel"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 503


# ── /api/billing/portal ───────────────────────────────────────────────────────

class TestPortalEndpoint:
    def test_requires_auth(self):
        resp = client.get(
            "/api/billing/portal",
            params={"return_url": "http://return"},
        )
        assert resp.status_code == 401

    def test_no_customer_returns_404(self):
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.billing.get_stripe_customer_id", return_value=None):
            resp = client.get(
                "/api/billing/portal",
                params={"return_url": "http://return"},
                headers=_auth_headers("pro"),
            )
        assert resp.status_code == 404

    def test_returns_portal_url(self):
        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/portal/test"
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.billing.get_stripe_customer_id", return_value="cus_abc"), \
             patch("stripe.billing_portal.Session.create", return_value=mock_session):
            resp = client.get(
                "/api/billing/portal",
                params={"return_url": "http://return"},
                headers=_auth_headers("pro"),
            )
        assert resp.status_code == 200
        assert resp.json()["portal_url"] == "https://billing.stripe.com/portal/test"

    def test_stripe_error_returns_502(self):
        import stripe
        with patch.dict(os.environ, _ENV), \
             patch("src.api.routers.billing.get_stripe_customer_id", return_value="cus_abc"), \
             patch("stripe.billing_portal.Session.create", side_effect=stripe.StripeError("fail")):
            resp = client.get(
                "/api/billing/portal",
                params={"return_url": "http://return"},
                headers=_auth_headers("pro"),
            )
        assert resp.status_code == 502
