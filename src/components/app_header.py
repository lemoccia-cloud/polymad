"""
App-wide header component for polyMad.

Renders a styled header strip at the top of every page with:
  - Logo + brand name
  - Plan badge (colour-coded)
  - User identifier (wallet address or email)
  - Sign-out button (compact)

The header is implemented as a Streamlit column layout with injected CSS.
It is NOT truly sticky/fixed — it scrolls with the page content, which
is acceptable for a dashboard tool.

Public API:
    render_app_header(t) → None
"""
import streamlit as st

import src.components.auth_bridge as auth_bridge

_HEADER_CSS = """
<style>
/* Tighten default Streamlit top padding */
.block-container { padding-top: 0.5rem !important; }

/* Header strip styling */
.polymad-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0 10px 0;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 1rem;
}
.polymad-header .brand {
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: inherit;
}
.polymad-header .user-info {
    font-size: 0.78rem;
    color: #888;
    text-align: right;
    line-height: 1.4;
}
.plan-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.3px;
    text-transform: uppercase;
}
.plan-free     { background: #374151; color: #9ca3af; }
.plan-pro      { background: #1e3a5f; color: #60a5fa; }
.plan-trader   { background: #2e1065; color: #c4b5fd; }
</style>
"""

_PLAN_BADGE = {
    "free":   '<span class="plan-badge plan-free">Free</span>',
    "pro":    '<span class="plan-badge plan-pro">Pro</span>',
    "trader": '<span class="plan-badge plan-trader">Trader</span>',
}


def render_app_header(t=None) -> None:
    """
    Render the top header bar.

    Args:
        t: optional translation callable. Falls back to English.
    """
    st.markdown(_HEADER_CSS, unsafe_allow_html=True)

    col_brand, col_spacer, col_user = st.columns([3, 5, 4], gap="small")

    with col_brand:
        st.markdown("### 🌡 polyMad")

    with col_user:
        if auth_bridge.is_authenticated():
            addr = auth_bridge.get_authenticated_address() or ""
            plan = auth_bridge.get_authenticated_plan()
            display = auth_bridge.get_authenticated_display_name()

            # Show email or shortened wallet address
            if display and display != addr:
                label = display  # email address stored as display name
            elif addr.startswith("email:"):
                label = addr[6:50]  # strip 'email:' prefix
            else:
                label = f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr

            badge = _PLAN_BADGE.get(plan, _PLAN_BADGE["free"])
            st.markdown(
                f'<div style="text-align:right; padding-top:6px;">'
                f'{badge}&nbsp;&nbsp;<span style="font-size:0.8rem;color:#ccc;">{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="text-align:right; padding-top:6px;">'
                '<span style="font-size:0.8rem;color:#666;">Not signed in</span>'
                '</div>',
                unsafe_allow_html=True,
            )
