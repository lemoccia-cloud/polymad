"""
MetaMask wallet connection component for polyMad Streamlit dashboard.

Authentication flow — uses declare_component (same-origin iframe) so data
flows via postMessage (setComponentValue) and sessionStorage is accessible.

  Phase 0 — Restore check (once per session)
    JS reads window.parent.sessionStorage → returns {action:"restore", jwt} or {action:"none"}
    Python: if restore → validate JWT locally → set session_state → rerun (user stays logged in)

  Phase 1 — Connect
    JS → MetaMask eth_accounts (passive) or eth_requestAccounts (button click)
    → setComponentValue({action:"connected", addr})
    Python → request_nonce → Phase 2

  Phase 2 — Sign
    Python embeds typed_data_json → JS → eth_signTypedData_v4
    → setComponentValue({action:"signed", sig})
    Python → verify_signature → JWT stored → Phase 3

  Phase 3 — Save JWT
    Python passes token/expires_at/addr → JS writes to window.parent.sessionStorage
    Runs once after successful login so the session survives page reloads / Stripe redirect.

  Phase 4 — Clear sessionStorage (sign-out)
    JS removes all _polymad_* keys from window.parent.sessionStorage

Security:
  - Authenticated address comes exclusively from the verified JWT (server-side).
  - JWT stored only in st.session_state (server-side).
  - sessionStorage copy is used only for restore across page reloads (convenience).
  - Typed data / nonce generated fresh per session; replayed values fail server-side.
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.data.supabase_client import (
    get_alert_config,
    upsert_alert_config,
    get_alert_history,
)
from src.components import auth_bridge
from src.components.email_auth import render_email_auth_form
from src.api.security.eip712 import build_eip712_message

logger = logging.getLogger(__name__)

POLYGON_RPC = "https://polygon-rpc.com"
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Declare the component from the local directory.
# Streamlit serves it at /component/polymad_wallet/ (same origin) so the iframe
# can use postMessage (setComponentValue) to return data to Python.
_WALLET_COMP_DIR = Path(__file__).parent / "_wallet_html"
_wallet_component = components.declare_component(
    "polymad_wallet",
    path=str(_WALLET_COMP_DIR),
)

# Session state keys for the auth flow state machine
_PHASE_KEY       = "_wallet_phase"       # None | "restoring" | "connecting" | "signing" | "saving"
_ADDR_KEY        = "_wallet_pending_addr"
_NONCE_KEY       = "_wallet_pending_nonce"
_TYPED_DATA_KEY  = "_wallet_typed_data_json"
_IAT_KEY         = "_wallet_issued_at"
_RESTORE_DONE    = "_wallet_restore_checked"


# ── Auth flow state machine ──────────────────────────────────────────────────

def process_auth_flow() -> None:
    """
    Drive the full EIP-712 authentication flow including sessionStorage
    persistence so the session survives page reloads and Stripe redirects.

    Call once per Streamlit script run (top of main).
    """
    phase = st.session_state.get(_PHASE_KEY)

    # ── Phase "clearing": remove JWT from sessionStorage on sign-out ─────────
    if phase == "clearing":
        result = _wallet_component(phase=4, key="wallet_clear")
        if isinstance(result, dict) and result.get("action") == "cleared":
            st.session_state.pop(_PHASE_KEY, None)
            st.session_state[_RESTORE_DONE] = False  # allow restore check next login
        return

    # ── Phase "saving": persist JWT to sessionStorage after successful auth ────
    if phase == "saving":
        token, expires_at, addr = auth_bridge.get_last_token()
        result = _wallet_component(
            phase=3,
            jwt=token,
            expires_at=expires_at,
            addr=addr,
            key="wallet_save",
        )
        if isinstance(result, dict) and result.get("action") == "saved":
            st.session_state.pop(_PHASE_KEY, None)
            # No rerun needed — auth is already set, just saved to storage
        return

    # ── Already authenticated — nothing more to do ────────────────────────────
    if auth_bridge.is_authenticated():
        return

    # ── Phase 0: Restore check (once per session) ─────────────────────────────
    if not st.session_state.get(_RESTORE_DONE):
        st.session_state[_RESTORE_DONE] = True
        result = _wallet_component(phase=0, key="wallet_restore")
        if isinstance(result, dict) and result.get("action") == "restore":
            jwt = result.get("jwt", "")
            addr = result.get("addr", "")
            expires_at = result.get("expires_at", "")
            from src.api.security.jwt_handler import decode_access_token_full
            decoded = decode_access_token_full(jwt) if jwt else None
            if decoded:
                verified_addr, plan = decoded
                st.session_state[auth_bridge._TOKEN_KEY]     = jwt
                st.session_state[auth_bridge._TOKEN_EXP_KEY] = expires_at
                st.session_state[auth_bridge._ADDRESS_KEY]   = verified_addr
                st.session_state[auth_bridge._PLAN_KEY]      = plan
                st.rerun()
        # Whether restore succeeded or not, fall through to connect flow
        if auth_bridge.is_authenticated():
            return

    # ── Phase 1: Connect (rendered in sidebar — one canonical location) ───────
    if phase is None or phase == "connecting":
        with st.sidebar:
            tab_metamask, tab_email = st.tabs(["🦊 MetaMask", "✉️ Email"])

            with tab_metamask:
                result = _wallet_component(
                    phase=1,
                    connect_label="Connect MetaMask",
                    status_text="",
                    key="wallet_p1",
                )

            with tab_email:
                render_email_auth_form(key_suffix="_sidebar")

        # Handle MetaMask connect result
        if isinstance(result, dict) and result.get("action") == "connected":
            import re
            addr = (result.get("addr") or "").lower()
            if not re.match(r"^0x[0-9a-fA-F]{40}$", addr):
                return
            nonce = auth_bridge.request_nonce(addr)
            if not nonce:
                st.sidebar.error("Could not reach auth server. Please try again.")
                return
            issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            typed_data = build_eip712_message(addr, nonce, issued_at)
            st.session_state[_ADDR_KEY]       = addr
            st.session_state[_NONCE_KEY]      = nonce
            st.session_state[_IAT_KEY]        = issued_at
            st.session_state[_TYPED_DATA_KEY] = json.dumps(typed_data)
            st.session_state[_PHASE_KEY]      = "signing"
            st.rerun()

        # Handle email login — auth_bridge.login_email sets session_state on success
        # After rerun (triggered inside render_email_auth_form), is_authenticated() = True
        # and phase "saving" will persist the JWT to sessionStorage
        if auth_bridge.is_authenticated() and phase != "saving":
            st.session_state[_PHASE_KEY] = "saving"
            st.rerun()
        return

    # ── Phase 2: Sign (rendered in main area) ─────────────────────────────────
    if phase == "signing":
        addr            = st.session_state.get(_ADDR_KEY, "")
        nonce           = st.session_state.get(_NONCE_KEY, "")
        issued_at       = st.session_state.get(_IAT_KEY, "")
        typed_data_json = st.session_state.get(_TYPED_DATA_KEY, "")

        if not (addr and nonce and issued_at and typed_data_json):
            _reset_phase()
            st.rerun()
            return

        result = _wallet_component(
            phase=2,
            address=addr,
            typed_data_json=typed_data_json,
            key="wallet_p2",
        )

        if isinstance(result, dict) and result.get("action") == "signed":
            sig = result.get("sig", "")
            _reset_phase()
            ok = auth_bridge.verify_signature(
                address=addr,
                signature=sig,
                nonce=nonce,
                issued_at=issued_at,
            )
            if ok:
                # Transition to "saving" so next run persists JWT to sessionStorage
                st.session_state[_PHASE_KEY] = "saving"
                st.rerun()
            else:
                st.error("Authentication failed. Please try again.")


def _reset_phase() -> None:
    """Clear all pending auth phase state."""
    for key in (_PHASE_KEY, _ADDR_KEY, _NONCE_KEY, _IAT_KEY, _TYPED_DATA_KEY):
        st.session_state.pop(key, None)


# ── Public component functions ───────────────────────────────────────────────

def render_metamask_button(connect_label: str = "Connect MetaMask", status_text: str = "") -> None:
    """
    Kept for backward compatibility — shows a visual prompt only.
    The actual auth flow is driven by process_auth_flow() (sidebar button).
    """
    st.info(f"🦊 {connect_label} — use the sidebar button to connect.")


def render_auth_status() -> None:
    """
    Render a small auth status badge in the sidebar showing the wallet address
    and a sign-out button. Relies on auth_bridge.is_authenticated().
    """
    if not auth_bridge.is_authenticated():
        return

    address = auth_bridge.get_authenticated_address() or ""
    short = address[:6] + "..." + address[-4:] if address else "unknown"
    expires_at = st.session_state.get("_auth_token_expires_at", "")

    st.sidebar.markdown(
        f"""
        <div style="background:rgba(0,200,150,0.1);border:1px solid #00c896;
                    border-radius:8px;padding:10px;margin:8px 0;">
            <div style="color:#00c896;font-size:12px;font-weight:600;">&#x2713; Authenticated</div>
            <div style="color:#ddd;font-size:11px;margin-top:4px;font-family:monospace;">{short}</div>
            {f'<div style="color:#888;font-size:10px;margin-top:2px;">Expires {expires_at[:16]}</div>' if expires_at else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Sign out", width="stretch"):
        auth_bridge.clear_auth()
        _reset_phase()
        # Clear sessionStorage via same-origin component (phase 4)
        st.session_state[_PHASE_KEY] = "clearing"
        st.rerun()


# ── Legacy helpers ────────────────────────────────────────────────────────────

def get_wallet_address() -> str:
    """
    Return the authenticated wallet address from the verified JWT.
    Returns empty string if not authenticated.
    """
    return auth_bridge.get_authenticated_address() or ""


def get_usdc_balance(address: str) -> float:
    """Fetch USDC balance for address on Polygon via JSON-RPC. Returns 0.0 on error."""
    if not address:
        return 0.0
    try:
        import requests
        padded = address.lower().replace("0x", "").zfill(64)
        data = "0x70a08231" + padded
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": USDC_CONTRACT, "data": data}, "latest"],
            "id": 1,
        }
        resp = requests.post(POLYGON_RPC, json=payload, timeout=8)
        resp.raise_for_status()
        result = resp.json().get("result", "0x0")
        return int(result, 16) / 1e6
    except Exception as exc:
        logger.debug("USDC balance fetch failed: %s", exc)
        return 0.0


def render_wallet_sidebar(t: "callable") -> str:
    """
    Render wallet authentication section in sidebar.
    Returns current authenticated wallet address (or empty string).

    The Phase 1 connect button is rendered by process_auth_flow() (called at
    the top of main). This function only renders the post-auth status badge
    and sign-out button.
    """
    address = auth_bridge.get_authenticated_address() or ""
    if address:
        render_auth_status()
    return address


def render_wallet_tab(
    t: "callable",
    address: str,
    results: list,
    bankroll: float,
    poly_client=None,
) -> None:
    """
    Render the Wallet tab content.
    Uses auth_bridge for positions when authenticated;
    falls back to poly_client (unauthenticated) only when address is provided
    but no JWT is present (backward-compatible path).
    """
    if not address:
        st.info(f"🦊 {t('connect_wallet')} — use the **Connect MetaMask** button in the sidebar.")
        return

    # Read Supabase secrets (optional — graceful if not configured)
    try:
        supa_url = st.secrets.get("SUPABASE_URL", "")
        supa_key = st.secrets.get("SUPABASE_ANON_KEY", "")
    except Exception:
        supa_url = supa_key = ""

    short = address[:6] + "..." + address[-4:]

    # ── Header cards ──────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"""
            <div style="background:#1e2530;border-radius:8px;padding:12px;text-align:center;">
                <div style="color:#888;font-size:11px;">{t('wallet_address')}</div>
                <div style="color:#ddd;font-size:13px;font-family:monospace;">{short}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        with st.spinner(t("fetching_balance")):
            balance = get_usdc_balance(address)
        st.markdown(
            f"""
            <div style="background:#1e2530;border-radius:8px;padding:12px;text-align:center;">
                <div style="color:#888;font-size:11px;">{t('usdc_balance')}</div>
                <div style="color:#00c896;font-size:18px;font-weight:700;">${balance:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
            <div style="background:#1e2530;border-radius:8px;padding:12px;text-align:center;">
                <div style="color:#888;font-size:11px;">{t('network')}</div>
                <div style="color:#8b5cf6;font-size:13px;font-weight:600;">Polygon</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Real positions ────────────────────────────────────────────────────────
    st.subheader(t("positions_open"))

    if auth_bridge.is_authenticated():
        with st.spinner(t("fetching_positions")):
            api_positions = auth_bridge.get_positions()
        positions_raw = api_positions or []
    elif poly_client is not None:
        with st.spinner(t("fetching_positions")):
            positions_raw = poly_client.get_user_positions(address)
    else:
        positions_raw = []

    if positions_raw:
        total_current = sum(float(p.get("currentValue", p.get("current_value", 0))) for p in positions_raw)
        total_initial = sum(float(p.get("initialValue", p.get("initial_value", 0))) for p in positions_raw)
        total_pnl = total_current - total_initial
        total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0.0

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric(t("portfolio_value"), f"${total_current:,.2f}")
        mc2.metric(t("total_pnl"), f"{'+'if total_pnl>=0 else ''}${total_pnl:.2f}")
        mc3.metric(t("pnl_return_pct"), f"{'+'if total_pnl_pct>=0 else ''}{total_pnl_pct:.1f}%")
        st.markdown("")

        market_by_condition = {r.market.condition_id: r.market for r in results} if results else {}
        rows = []
        for pos in positions_raw:
            cid = pos.get("conditionId", pos.get("condition_id", ""))
            outcome_idx = pos.get("outcomeIndex", pos.get("side", 0))
            side = "YES" if outcome_idx == 0 or outcome_idx == "YES" else "NO"
            size = float(pos.get("size", 0))
            avg_price = float(pos.get("avgPrice", pos.get("avg_price", 0)))
            current_value = float(pos.get("currentValue", pos.get("current_value", 0)))
            initial_value = float(pos.get("initialValue", pos.get("initial_value", 0)))
            pnl = current_value - initial_value
            pnl_pct = (pnl / initial_value * 100) if initial_value > 0 else 0.0
            mkt = market_by_condition.get(cid)
            title = (mkt.question[:60] + "...") if mkt else pos.get("title", pos.get("question", cid[:20]))
            rows.append({
                t("market_col"):      title,
                t("side_col"):        side,
                t("size_col"):        f"{size:.2f}",
                t("entry_price"):     f"${avg_price:.3f}",
                t("current_price"):   f"${current_value/size:.3f}" if size > 0 else "—",
                t("pnl_label"):       f"{'+'if pnl>=0 else '-'}${abs(pnl):.2f}",
                t("pnl_return_pct"):  f"{'+'if pnl_pct>=0 else ''}{pnl_pct:.1f}%",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info(t("no_positions_found"))

    st.markdown("---")

    # ── Scan opportunities ────────────────────────────────────────────────────
    st.subheader(t("wallet_portfolio"))
    if not results:
        st.info(t("run_first"))
    else:
        alerts = [r for r in results if r.alert]
        if not alerts:
            st.info(t("wallet_no_positions"))
        else:
            st.markdown(f"**{len(alerts)}** {t('active_opportunities')}")
            for r in alerts[:5]:
                market = r.market
                bet = bankroll * r.suggested_bet_fraction
                poly_url = (
                    f"https://polymarket.com/event/{market.event_slug}"
                    if getattr(market, "event_slug", None)
                    else "https://polymarket.com"
                )
                res_label = ""
                if hasattr(market, "resolution_date") and market.resolution_date:
                    res_label = market.resolution_date.strftime("%b %d")
                mtype = getattr(market, "market_type", "weather")
                type_badge = {"crypto": "₿", "sports": "⚽", "politics": "🗳️"}.get(mtype, "🌡")
                st.markdown(
                    f"""
                    <div style="background:#1e2530;border:1px solid #2d3748;
                        border-radius:10px;padding:14px;margin:8px 0;">
                        <div style="color:#ddd;font-size:13px;font-weight:600;">
                            {type_badge} {getattr(market,'city',getattr(market,'asset',getattr(market,'topic',''))[:30])}
                            {f"· {res_label}" if res_label else ""}
                        </div>
                        <div style="color:#888;font-size:11px;margin:4px 0;">{market.question[:70]}...</div>
                        <div style="display:flex;gap:20px;margin-top:8px;">
                            <span style="color:#00c896;">Edge: {r.edge*100:+.1f}%</span>
                            <span style="color:#60a5fa;">EV: {r.expected_value:+.2f}</span>
                            <span style="color:#f59e0b;">Bet: ${bet:.2f}</span>
                        </div>
                        <a href="{poly_url}" target="_blank" style="
                            display:inline-block;margin-top:8px;background:#3b82f6;
                            color:white;padding:4px 12px;border-radius:6px;
                            text-decoration:none;font-size:12px;">
                            {t('trade_on_polymarket')}
                        </a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    st.markdown("---")

    # ── Alert configuration ───────────────────────────────────────────────────
    with st.expander(t("alert_config_title"), expanded=False):
        if supa_url and supa_key:
            cfg = get_alert_config(supa_url, supa_key, address)
        else:
            cfg = {}

        saved_edge = int(float(cfg.get("edge_threshold", 0.05)) * 100)
        saved_cats = cfg.get("categories") or ["weather", "crypto", "sports", "politics"]
        saved_email = cfg.get("notify_email") or ""

        new_edge = st.slider(t("alert_edge_threshold"), 1, 30, value=saved_edge, step=1) / 100.0
        new_cats = st.multiselect(
            t("alert_categories"),
            options=["weather", "crypto", "sports", "politics"],
            default=saved_cats,
        )
        new_email = st.text_input(t("alert_email"), value=saved_email, placeholder="you@email.com")

        if st.button(t("alert_save"), type="primary"):
            if supa_url and supa_key:
                ok = upsert_alert_config(supa_url, supa_key, address, new_edge, new_cats, new_email)
                st.toast(t("alert_saved") if ok else t("alert_save_error"))
            else:
                st.warning(t("history_no_supabase"))

    st.markdown("---")

    # ── Alert history ─────────────────────────────────────────────────────────
    st.subheader(t("alert_history_title"))
    history: list = []
    if supa_url and supa_key:
        history = get_alert_history(supa_url, supa_key, address, limit=50)
        if history:
            hist_rows = []
            for h in history:
                rv = h.get("resolved_yes")
                result_str = "✅ YES" if rv is True else ("❌ NO" if rv is False else "⏳ Pending")
                hist_rows.append({
                    t("scan_date_col"):       str(h.get("created_at", ""))[:16],
                    t("market_col"):          (h.get("question") or "")[:55],
                    t("backtest_col_type"):   (h.get("market_type") or "").capitalize(),
                    t("backtest_col_model"):  f"{float(h.get('model_prob', 0))*100:.1f}%",
                    t("backtest_col_market"): f"{float(h.get('market_prob', 0))*100:.1f}%",
                    t("backtest_col_edge"):   f"{float(h.get('edge', 0))*100:+.1f}%",
                    t("backtest_col_result"): result_str,
                })
            st.dataframe(pd.DataFrame(hist_rows), width="stretch", hide_index=True)
        else:
            st.info(t("alert_history_empty"))
    else:
        st.info(t("history_no_supabase"))

    st.markdown("---")

    # ── Model track record ────────────────────────────────────────────────────
    st.subheader(t("track_record_title"))
    if history:
        resolved = [h for h in history if h.get("resolved_yes") is not None]
        n_total    = len(history)
        n_resolved = len(resolved)
        n_correct  = sum(
            1 for h in resolved
            if (float(h.get("model_prob", 0)) >= 0.5) == bool(h.get("resolved_yes"))
        )
        accuracy = n_correct / n_resolved if n_resolved else 0.0
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric(t("track_total_alerts"), n_total)
        tc2.metric(t("track_resolved"), n_resolved)
        tc3.metric(t("track_accuracy"), f"{accuracy*100:.1f}%")

        if resolved:
            by_type: dict = defaultdict(lambda: {"total": 0, "correct": 0})
            for h in resolved:
                mtype = h.get("market_type", "weather")
                by_type[mtype]["total"] += 1
                if (float(h.get("model_prob", 0)) >= 0.5) == bool(h.get("resolved_yes")):
                    by_type[mtype]["correct"] += 1
            type_rows = [
                {
                    "Category": mtype.capitalize(),
                    t("track_resolved"): v["total"],
                    t("track_accuracy"): f"{v['correct']/v['total']*100:.1f}%" if v["total"] else "—",
                }
                for mtype, v in sorted(by_type.items())
            ]
            st.dataframe(pd.DataFrame(type_rows), width="stretch", hide_index=True)
    else:
        st.info(t("alert_history_empty"))
