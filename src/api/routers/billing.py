"""
Billing endpoints — Stripe Checkout and Customer Portal.

POST /api/billing/checkout  — create a Stripe Checkout Session for plan upgrade
GET  /api/billing/portal    — return a Stripe Customer Portal URL (manage sub)

Both endpoints require a valid JWT (authenticated wallet).
Stripe keys are read from environment variables — never hardcoded.
"""
import logging
import os
from typing import Tuple

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.api.deps import get_current_address_and_plan
from src.data.supabase_client import get_stripe_customer_id, upsert_user_plan



logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

_VALID_PLANS = ("pro", "trader")


def _stripe_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing not configured",
        )
    return key


def _price_id(plan: str) -> str:
    env_key = f"STRIPE_PRICE_{plan.upper()}_MONTHLY"
    price = os.environ.get(env_key, "")
    if not price:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Price not configured for plan: {plan}",
        )
    return price


def _supabase_creds() -> Tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    return url, key


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class InvoiceItem(BaseModel):
    id: str
    date: str
    amount: float        # in USD
    currency: str
    status: str          # "paid" | "open" | "void"
    pdf_url: str
    hosted_url: str


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Create a Stripe Checkout Session for plan upgrade",
)
def create_checkout_session(
    plan: str = Query(..., description="Target plan: pro or trader"),
    success_url: str = Query(..., description="URL to redirect after successful payment"),
    cancel_url: str = Query(..., description="URL to redirect on cancellation"),
    auth: Tuple[str, str] = Depends(get_current_address_and_plan),
) -> CheckoutResponse:
    """
    Create a Stripe Checkout Session for the authenticated wallet.

    - Reuses existing Stripe Customer if wallet already has one.
    - Returns a checkout_url the frontend should redirect to.
    - plan must be "pro" or "trader".
    """
    address, current_plan = auth

    if plan not in _VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid plan. Choose from: {_VALID_PLANS}",
        )

    stripe.api_key = _stripe_key()
    price_id = _price_id(plan)
    sb_url, sb_key = _supabase_creds()

    # Reuse or create Stripe Customer
    customer_id = get_stripe_customer_id(sb_url, sb_key, address) if (sb_url and sb_key) else None

    try:
        session_params: dict = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"wallet_address": address},
            "subscription_data": {"metadata": {"wallet_address": address}},
        }
        if customer_id:
            session_params["customer"] = customer_id
        else:
            session_params["client_reference_id"] = address

        session = stripe.checkout.Session.create(**session_params)
        logger.info("billing.checkout: session created addr=%s plan=%s", address[:8], plan)
        return CheckoutResponse(checkout_url=session.url)

    except stripe.StripeError as exc:
        logger.error("billing.checkout Stripe error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider error — please try again",
        ) from exc


@router.get(
    "/portal",
    response_model=PortalResponse,
    summary="Get Stripe Customer Portal URL",
)
def get_customer_portal(
    return_url: str = Query(..., description="URL to redirect after leaving the portal"),
    auth: Tuple[str, str] = Depends(get_current_address_and_plan),
) -> PortalResponse:
    """
    Return a Stripe Customer Portal URL for the authenticated wallet.
    The user can cancel or change their subscription from this portal.
    Requires that a Stripe Customer exists (i.e., the user has subscribed at least once).
    """
    address, _ = auth

    stripe.api_key = _stripe_key()
    sb_url, sb_key = _supabase_creds()

    customer_id = get_stripe_customer_id(sb_url, sb_key, address) if (sb_url and sb_key) else None
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No billing account found for this wallet",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        logger.info("billing.portal: session created addr=%s", address[:8])
        return PortalResponse(portal_url=session.url)

    except stripe.StripeError as exc:
        logger.error("billing.portal Stripe error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider error — please try again",
        ) from exc


@router.get(
    "/invoices",
    response_model=list[InvoiceItem],
    summary="List Stripe invoices for the authenticated user",
)
def list_invoices(
    auth: Tuple[str, str] = Depends(get_current_address_and_plan),
) -> list[InvoiceItem]:
    """
    Return up to 12 recent Stripe invoices for the authenticated user.
    Returns an empty list if the user has no billing account.
    """
    address, _ = auth

    stripe.api_key = _stripe_key()
    sb_url, sb_key = _supabase_creds()

    customer_id = get_stripe_customer_id(sb_url, sb_key, address) if (sb_url and sb_key) else None
    if not customer_id:
        return []

    try:
        invoices = stripe.Invoice.list(customer=customer_id, limit=12)
        items = []
        for inv in invoices.auto_paging_iter():
            items.append(InvoiceItem(
                id=inv.id,
                date=str(inv.created),
                amount=round((inv.amount_paid or inv.amount_due or 0) / 100, 2),
                currency=(inv.currency or "usd").upper(),
                status=inv.status or "unknown",
                pdf_url=inv.invoice_pdf or "",
                hosted_url=inv.hosted_invoice_url or "",
            ))
            if len(items) >= 12:
                break
        return items
    except stripe.StripeError as exc:
        logger.error("billing.invoices Stripe error: %s", exc)
        return []
