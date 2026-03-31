"""
Unit tests for src/api/routers/stripe_webhooks.py

All Stripe and Supabase calls are mocked — no real network required.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET_KEY", "a" * 32)

from src.api.main import create_app

app = create_app()
client = TestClient(app)

_WEBHOOK_SECRET = "whsec_test123"
_SUPABASE_ENV = {
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_ANON_KEY": "fakekey",
    "STRIPE_WEBHOOK_SECRET": _WEBHOOK_SECRET,
    "STRIPE_PRICE_PRO_MONTHLY": "price_pro",
    "STRIPE_PRICE_TRADER_MONTHLY": "price_trader",
}


def _mock_event(event_type: str, data_object: dict) -> dict:
    return {
        "id": "evt_test_123",
        "type": event_type,
        "data": {"object": data_object},
    }


class TestWebhookSignatureValidation:
    def test_missing_webhook_secret_returns_503(self):
        """If STRIPE_WEBHOOK_SECRET is not set, endpoint returns 503."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
            resp = client.post(
                "/api/webhooks/stripe",
                content=b"{}",
                headers={"stripe-signature": "t=1,v1=abc"},
            )
        assert resp.status_code == 503

    def test_invalid_signature_returns_400(self):
        """Invalid HMAC signature returns 400."""
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event",
                              side_effect=stripe.SignatureVerificationError("bad sig", "header")):
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b'{"type":"test"}',
                    headers={"stripe-signature": "t=1,v1=invalid"},
                )
        assert resp.status_code == 400

    def test_valid_event_returns_200(self):
        """Valid event with known signature returns 200."""
        event = _mock_event("unknown.event", {})
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event):
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=json.dumps(event).encode(),
                    headers={"stripe-signature": "t=1,v1=valid"},
                )
        assert resp.status_code == 200
        assert resp.json()["received"] is True


class TestCheckoutSessionCompleted:
    def test_updates_plan_on_checkout_completed(self):
        """checkout.session.completed with wallet_address metadata updates plan to pro."""
        event = _mock_event("checkout.session.completed", {
            "metadata": {"wallet_address": "0xabc123"},
            "customer": "cus_test",
            "subscription": "",
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan", return_value=True) as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args.args[2] == "0xabc123"  # wallet_address

    def test_no_wallet_skips_upsert(self):
        """checkout.session.completed without wallet_address is a no-op."""
        event = _mock_event("checkout.session.completed", {
            "metadata": {},
            "customer": "cus_test",
            "subscription": "",
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan") as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        mock_upsert.assert_not_called()


class TestSubscriptionUpdated:
    def test_updates_plan_on_subscription_update(self):
        """customer.subscription.updated maps price_id to plan and calls upsert."""
        event = _mock_event("customer.subscription.updated", {
            "metadata": {"wallet_address": "0xdef456"},
            "customer": "cus_test",
            "id": "sub_test",
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan", return_value=True) as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args.args[3] == "pro"   # plan

    def test_trader_price_maps_to_trader_plan(self):
        event = _mock_event("customer.subscription.updated", {
            "metadata": {"wallet_address": "0xghi789"},
            "customer": "cus_test",
            "id": "sub_test",
            "items": {"data": [{"price": {"id": "price_trader"}}]},
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan", return_value=True) as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        call_args = mock_upsert.call_args
        assert call_args.args[3] == "trader"

    def test_unknown_price_defaults_to_free(self):
        event = _mock_event("customer.subscription.updated", {
            "metadata": {"wallet_address": "0xjkl"},
            "customer": "cus_test",
            "id": "sub_test",
            "items": {"data": [{"price": {"id": "price_unknown"}}]},
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan", return_value=True) as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        call_args = mock_upsert.call_args
        assert call_args.args[3] == "free"


class TestSubscriptionDeleted:
    def test_downgrades_to_free_on_delete(self):
        event = _mock_event("customer.subscription.deleted", {
            "metadata": {"wallet_address": "0xmno"},
            "customer": "cus_test",
            "id": "sub_test",
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan", return_value=True) as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args.args[3] == "free"

    def test_no_wallet_on_delete_skips_upsert(self):
        event = _mock_event("customer.subscription.deleted", {
            "metadata": {},
            "customer": "cus_test",
        })
        with patch.dict(os.environ, _SUPABASE_ENV):
            import stripe
            with patch.object(stripe.Webhook, "construct_event", return_value=event), \
                 patch("src.api.routers.stripe_webhooks.upsert_user_plan") as mock_upsert:
                resp = client.post(
                    "/api/webhooks/stripe",
                    content=b"payload",
                    headers={"stripe-signature": "t=1,v1=ok"},
                )
        assert resp.status_code == 200
        mock_upsert.assert_not_called()
