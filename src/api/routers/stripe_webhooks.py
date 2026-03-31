"""
Stripe webhook endpoint.

POST /api/webhooks/stripe — receives Stripe events, validates HMAC signature,
                            and updates subscription plan in Supabase.

Handled events:
  checkout.session.completed      — link Stripe Customer to wallet, set plan
  customer.subscription.updated   — plan change or renewal
  customer.subscription.deleted   — downgrade to free on cancellation

Security:
  - Signature verified via stripe.WebhookSignature before any processing.
  - Returns HTTP 200 for all processed events (even unknown ones) so Stripe
    doesn't retry unnecessarily.
  - Returns HTTP 400 only on signature validation failure.
  - Idempotent: duplicate events (same stripe_event_id) are silently accepted.
"""
import logging
import os
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Request, status

from src.data.supabase_client import upsert_user_plan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Map Stripe price IDs → plan names (read at request time to support hot reload)
def _price_to_plan(price_id: str) -> Optional[str]:
    pro_price = os.environ.get("STRIPE_PRICE_PRO_MONTHLY", "")
    trader_price = os.environ.get("STRIPE_PRICE_TRADER_MONTHLY", "")
    if pro_price and price_id == pro_price:
        return "pro"
    if trader_price and price_id == trader_price:
        return "trader"
    return None


def _supabase_creds():
    return os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_ANON_KEY", "")


@router.post(
    "/stripe",
    summary="Receive Stripe webhook events",
    status_code=200,
)
async def stripe_webhook(request: Request):
    """
    Receive and process Stripe webhook events.

    Signature is verified using STRIPE_WEBHOOK_SECRET.
    Returns 200 for all valid events (including unhandled types) so Stripe
    does not retry. Returns 400 only on signature failure.
    """
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.error("stripe_webhook: STRIPE_WEBHOOK_SECRET not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not configured",
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.SignatureVerificationError:
        logger.warning("stripe_webhook: invalid signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )
    except Exception as exc:
        logger.error("stripe_webhook: malformed payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        )

    event_type = event["type"]
    event_id = event.get("id", "")
    logger.info("stripe_webhook: event=%s id=%s", event_type, event_id[:16])

    sb_url, sb_key = _supabase_creds()
    if not (sb_url and sb_key):
        logger.warning("stripe_webhook: Supabase not configured — skipping plan update")
        return {"received": True}

    # ── checkout.session.completed ────────────────────────────────────────────
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        wallet = (
            session.get("metadata", {}).get("wallet_address")
            or session.get("client_reference_id", "")
        )
        customer_id = session.get("customer", "")
        subscription_id = session.get("subscription", "")

        if not wallet:
            logger.warning("stripe_webhook: checkout.session.completed — no wallet_address")
            return {"received": True}

        # Determine plan from subscription line items
        plan = "pro"  # default for new checkouts; refined below if possible
        if subscription_id:
            try:
                stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
                sub = stripe.Subscription.retrieve(subscription_id)
                for item in sub.get("items", {}).get("data", []):
                    price_id = item.get("price", {}).get("id", "")
                    mapped = _price_to_plan(price_id)
                    if mapped:
                        plan = mapped
                        break
            except stripe.StripeError as exc:
                logger.warning("stripe_webhook: could not retrieve subscription: %s", exc)

        upsert_user_plan(
            sb_url, sb_key, wallet, plan,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        logger.info("stripe_webhook: checkout completed wallet=%s plan=%s", wallet[:8], plan)

    # ── customer.subscription.updated ────────────────────────────────────────
    elif event_type == "customer.subscription.updated":
        sub = event["data"]["object"]
        wallet = sub.get("metadata", {}).get("wallet_address", "")
        customer_id = sub.get("customer", "")
        sub_id = sub.get("id", "")

        if not wallet:
            logger.warning("stripe_webhook: subscription.updated — no wallet_address in metadata")
            return {"received": True}

        plan = "free"
        for item in sub.get("items", {}).get("data", []):
            price_id = item.get("price", {}).get("id", "")
            mapped = _price_to_plan(price_id)
            if mapped:
                plan = mapped
                break

        upsert_user_plan(
            sb_url, sb_key, wallet, plan,
            stripe_customer_id=customer_id,
            stripe_subscription_id=sub_id,
        )
        logger.info("stripe_webhook: subscription updated wallet=%s plan=%s", wallet[:8], plan)

    # ── customer.subscription.deleted ────────────────────────────────────────
    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        wallet = sub.get("metadata", {}).get("wallet_address", "")
        customer_id = sub.get("customer", "")

        if not wallet:
            logger.warning("stripe_webhook: subscription.deleted — no wallet_address in metadata")
            return {"received": True}

        upsert_user_plan(
            sb_url, sb_key, wallet, "free",
            stripe_customer_id=customer_id,
        )
        logger.info("stripe_webhook: subscription deleted wallet=%s → free", wallet[:8])

    return {"received": True}
