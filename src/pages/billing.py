"""
Billing management page.

Shows the user's current plan, upgrade options, Stripe portal link, and invoice history.
Accessible via st.navigation() from the main dashboard.
"""
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as _components

import src.components.auth_bridge as auth_bridge
from src.components.app_header import render_app_header
from src.components.wallet import process_auth_flow


def _redirect(url: str) -> None:
    """Perform a top-level browser redirect to url."""
    _components.html(
        f'<script>window.top.location.href = {repr(url)};</script>',
        height=0,
    )

_PLAN_FEATURES = {
    "free": [
        "✅ Weather markets analysis",
        "✅ Up to 50 markets per scan",
        "✅ Edge / EV / Kelly calculator",
        "❌ All categories (sports, politics, crypto)",
        "❌ Email alerts",
        "❌ Telegram bot",
    ],
    "pro": [
        "✅ All categories",
        "✅ Up to 200 markets per scan",
        "✅ Edge / EV / Kelly calculator",
        "✅ Email alerts",
        "❌ Telegram bot",
        "❌ Priority support",
    ],
    "trader": [
        "✅ All categories",
        "✅ Unlimited markets per scan",
        "✅ Email alerts",
        "✅ Telegram bot",
        "✅ Monthly P&L report",
        "✅ Priority support",
    ],
}


def render_billing_page(t=None, app_base_url: str = "") -> None:
    """Render the billing management page."""

    def _t(key, default):
        try:
            return t(key) if t else default
        except Exception:
            return default

    render_app_header(t)
    process_auth_flow()

    if not auth_bridge.is_authenticated():
        st.info(_t("billing_login_required", "Sign in to manage your subscription."))
        return

    plan = auth_bridge.get_authenticated_plan()

    st.title(_t("billing_title", "Billing"))

    # ── Current plan ───────────────────────────────────────────────────────
    st.subheader(_t("current_plan", "Current Plan"))

    plan_colors  = {"free": "#374151", "pro": "#1e3a5f", "trader": "#2e1065"}
    plan_labels  = {"free": "Free",    "pro": "Pro ⭐",  "trader": "Trader 🚀"}
    plan_prices  = {"free": "$0/mo",   "pro": "$19/mo",  "trader": "$49/mo"}

    col_plan, col_actions = st.columns([2, 3], gap="medium")

    with col_plan:
        bg = plan_colors.get(plan, "#374151")
        st.markdown(
            f'<div style="background:{bg};border-radius:12px;padding:20px 24px;">'
            f'<div style="font-size:1.4rem;font-weight:700;margin-bottom:4px;">'
            f'{plan_labels.get(plan, plan.title())}</div>'
            f'<div style="font-size:1.1rem;color:#aaa;">{plan_prices.get(plan, "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown("")
        for feat in _PLAN_FEATURES.get(plan, []):
            st.markdown(f"<small>{feat}</small>", unsafe_allow_html=True)

    with col_actions:
        base = app_base_url.rstrip("/") if app_base_url else ""
        success_url = f"{base}/?plan_success=1" if base else "/?plan_success=1"
        cancel_url  = f"{base}/billing" if base else "/billing"

        if plan != "trader":
            st.markdown(f"**{_t('upgrade_heading', 'Upgrade your plan')}**")

        if plan == "free":
            if st.button("⭐ Upgrade to Pro — $19/mo", type="primary"):
                url = auth_bridge.get_checkout_url("pro", success_url, cancel_url)
                if url:
                    _redirect(url)
                else:
                    st.error(_t("checkout_error", "Could not create checkout session. Please try again."))

        if plan in ("free", "pro"):
            btn_label = "🚀 Upgrade to Trader — $49/mo" if plan == "pro" else "🚀 Get Trader — $49/mo"
            if st.button(btn_label, type="secondary" if plan == "pro" else "primary"):
                url = auth_bridge.get_checkout_url("trader", success_url, cancel_url)
                if url:
                    _redirect(url)
                else:
                    st.error(_t("checkout_error", "Could not create checkout session. Please try again."))

        if plan != "free":
            st.divider()
            portal_url_return = f"{base}/billing" if base else "/billing"
            if st.button(_t("manage_sub_btn", "Manage Subscription"), type="secondary"):
                url = auth_bridge.get_portal_url(portal_url_return)
                if url:
                    _redirect(url)
                else:
                    st.error(_t("portal_error", "No billing account found. Complete a purchase first."))

    st.divider()

    # ── Invoice history ────────────────────────────────────────────────────
    st.subheader(_t("invoices_title", "Invoice History"))

    with st.spinner(_t("loading_invoices", "Loading invoices…")):
        invoices = auth_bridge.get_invoices()

    if invoices is None:
        st.info(_t("no_billing_account", "No billing account found."))
    elif len(invoices) == 0:
        st.info(_t("no_invoices", "No invoices yet. They will appear here after your first payment."))
    else:
        rows = []
        for inv in invoices:
            try:
                date_str = datetime.fromtimestamp(int(inv.get("date", 0))).strftime("%Y-%m-%d")
            except Exception:
                date_str = inv.get("date", "")
            status_icon = {"paid": "✅", "open": "🔵", "void": "⬜"}.get(inv.get("status", ""), "•")
            rows.append({
                "Date": date_str,
                "Amount": f"${inv.get('amount', 0):.2f} {inv.get('currency', 'USD')}",
                "Status": f"{status_icon} {inv.get('status', '').title()}",
                "PDF": inv.get("pdf_url", ""),
            })

        import pandas as pd
        df = pd.DataFrame(rows)
        # Render as simple table with PDF links
        for row in rows:
            col_date, col_amt, col_status, col_link = st.columns([2, 2, 2, 2])
            with col_date:
                st.text(row["Date"])
            with col_amt:
                st.text(row["Amount"])
            with col_status:
                st.markdown(row["Status"])
            with col_link:
                if row["PDF"]:
                    st.markdown(f"[📄 PDF]({row['PDF']})")
                else:
                    st.text("—")
