"""
Account management page.

Shows the authenticated user's profile, session info, and sign-out button.
Accessible via st.navigation() from the main dashboard.
"""
import streamlit as st

import src.components.auth_bridge as auth_bridge
from src.components.app_header import render_app_header
from src.components.wallet import process_auth_flow, render_wallet_sidebar


def render_account_page(t=None) -> None:
    """Render the account management page."""

    def _t(key, default):
        try:
            return t(key) if t else default
        except Exception:
            return default

    render_app_header(t)
    process_auth_flow()

    if not auth_bridge.is_authenticated():
        st.info(_t("account_login_required", "Sign in to manage your account."))
        return

    addr = auth_bridge.get_authenticated_address() or ""
    plan = auth_bridge.get_authenticated_plan()
    display = auth_bridge.get_authenticated_display_name()
    exp = st.session_state.get(auth_bridge._TOKEN_EXP_KEY, "")

    st.title(_t("account_title", "My Account"))

    # ── Profile section ────────────────────────────────────────────────────
    st.subheader(_t("profile_section", "Profile"))

    col_avatar, col_info = st.columns([1, 5], gap="small")
    with col_avatar:
        # Generate an avatar from the first char of address or email
        initial = (display or addr or "?")[0].upper()
        plan_colors = {"free": "#374151", "pro": "#1e3a5f", "trader": "#2e1065"}
        bg = plan_colors.get(plan, "#374151")
        st.markdown(
            f'<div style="width:60px;height:60px;border-radius:50%;background:{bg};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:1.6rem;font-weight:700;color:white;">{initial}</div>',
            unsafe_allow_html=True,
        )

    with col_info:
        if display and not addr.startswith("0x"):
            # Email user
            st.markdown(f"**{_t('email_label', 'Email')}:** {display}")
            st.markdown(f"**{_t('auth_method', 'Auth Method')}:** ✉️ Email / Password")
        elif addr.startswith("0x"):
            # Wallet user
            st.markdown(f"**{_t('wallet_label', 'Wallet')}:** `{addr}`")
            st.markdown(f"**{_t('auth_method', 'Auth Method')}:** 🦊 MetaMask (EIP-712)")
        else:
            st.markdown(f"**ID:** `{addr}`")

        plan_label = {"free": "Free", "pro": "Pro ⭐", "trader": "Trader 🚀"}.get(plan, plan)
        st.markdown(f"**{_t('plan_label', 'Plan')}:** {plan_label}")

    st.divider()

    # ── Session section ────────────────────────────────────────────────────
    st.subheader(_t("session_section", "Session"))

    col_exp, col_out = st.columns([3, 1])
    with col_exp:
        if exp:
            st.markdown(
                f"<small style='color:#888;'>{_t('session_expires', 'Session expires')}: "
                f"{exp.replace('T', ' ').replace('+00:00', ' UTC')[:19]}</small>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<small style='color:#888;'>{_t('session_active', 'Session active')}</small>",
                unsafe_allow_html=True,
            )

    with col_out:
        if st.button(_t("signout_btn", "Sign Out"), type="secondary"):
            # Trigger Phase 4 (clear sessionStorage) via wallet component
            st.session_state["_wallet_phase"] = "clearing"
            auth_bridge.clear_auth()
            st.rerun()

    st.divider()

    # ── Linked wallet (for email users) ───────────────────────────────────
    if not addr.startswith("0x"):
        st.subheader(_t("linked_wallet", "Linked Wallet"))
        st.info(
            _t(
                "link_wallet_info",
                "Link your MetaMask wallet to access portfolio tracking and Polymarket position data.",
            )
        )
        st.caption(
            _t("link_wallet_coming", "Wallet linking coming soon — sign in with MetaMask to use this feature now.")
        )
