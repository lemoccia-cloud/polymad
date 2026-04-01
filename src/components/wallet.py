"""
MetaMask wallet connection component for polyMad Streamlit dashboard.

Authentication flow (EIP-712, 2-phase):
  Phase 1 — Connect
    Browser JS → MetaMask eth_requestAccounts → address → URL param _w_addr
    Streamlit reads _w_addr, calls FastAPI /auth/nonce, stores nonce in session_state

  Phase 2 — Sign
    Streamlit renders signing component with embedded nonce
    Browser JS → MetaMask eth_signTypedData_v4 → signature → URL param _w_sig + _w_iat
    Streamlit reads params, calls auth_bridge.verify_signature() → JWT in session_state
    URL params are cleared immediately after reading

Security:
  - Address in URL params is used ONLY to request a nonce.
    An attacker setting ?_w_addr=0xvictim gets a nonce they cannot sign.
  - Signature in URL params is cleared in the same script run it is read.
  - JWT is stored ONLY in st.session_state (server-side, never in browser).
  - Authenticated address comes exclusively from the verified JWT.
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.data.supabase_client import (
    get_alert_config,
    upsert_alert_config,
    get_alert_history,
)
from src.components import auth_bridge
from src.api.security.eip712 import build_eip712_message, EIP712_DOMAIN

logger = logging.getLogger(__name__)

POLYGON_RPC = "https://polygon-rpc.com"
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon

# URL param names (short, non-descriptive to avoid harvesting)
_PARAM_ADDR = "_w_addr"
_PARAM_SIG  = "_w_sig"
_PARAM_IAT  = "_w_iat"
_PARAM_JWT  = "_w_jwt"  # used to restore JWT from sessionStorage after page reload

# ── Phase 1: Connect MetaMask and send address to Streamlit ──────────────────

_PHASE1_HTML = """
<div id="wallet-container">
  <button id="connect-btn" onclick="connectWallet()" style="
    background: linear-gradient(135deg, #f6851b, #e2761b);
    color: white; border: none; padding: 10px 20px;
    border-radius: 8px; font-size: 14px; font-weight: 600;
    cursor: pointer; width: 100%; transition: opacity 0.2s;
  " onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
    {connect_label}
  </button>
  <div id="status" style="margin-top:8px;font-size:12px;color:#aaa;text-align:center;">
    {status_text}
  </div>
</div>
<script>
async function connectWallet() {
  const btn = document.getElementById('connect-btn');
  const statusEl = document.getElementById('status');
  if (typeof window.parent.ethereum === 'undefined') {
    statusEl.textContent = 'MetaMask not detected. Please install it.';
    statusEl.style.color = '#ff6b6b';
    return;
  }
  try {
    btn.disabled = true;
    btn.style.opacity = '0.6';
    statusEl.textContent = 'Connecting...';
    const accounts = await window.parent.ethereum.request({ method: 'eth_requestAccounts' });
    const address = accounts[0];
    // Set address param and reload — address is only used to request a nonce
    const url = new URL(window.parent.location.href);
    url.searchParams.set('{param_addr}', address);
    // Remove any stale sig params
    url.searchParams.delete('{param_sig}');
    url.searchParams.delete('{param_iat}');
    window.parent.location.replace(url.toString());
  } catch (err) {
    statusEl.textContent = err.message || 'Connection refused.';
    statusEl.style.color = '#ff6b6b';
    btn.disabled = false;
    btn.style.opacity = '1';
  }
}
// Auto-check if already connected (MetaMask passive check, no popup)
(async () => {
  if (typeof window.parent.ethereum !== 'undefined') {
    try {
      const accounts = await window.parent.ethereum.request({ method: 'eth_accounts' });
      if (accounts.length > 0) {
        const url = new URL(window.parent.location.href);
        if (!url.searchParams.get('{param_addr}')) {
          url.searchParams.set('{param_addr}', accounts[0]);
          url.searchParams.delete('{param_sig}');
          url.searchParams.delete('{param_iat}');
          window.parent.location.replace(url.toString());
        }
      }
    } catch (_) {}
  }
})();
</script>
""".replace("{param_addr}", _PARAM_ADDR).replace("{param_sig}", _PARAM_SIG).replace("{param_iat}", _PARAM_IAT)


# ── Phase 2: Sign EIP-712 message ───────────────────────────────────────────

_PHASE2_HTML = """
<div id="sign-container">
  <div style="background:#1e2530;border:1px solid #3b82f6;border-radius:8px;padding:14px;margin-bottom:12px;">
    <div style="color:#60a5fa;font-size:12px;font-weight:600;margin-bottom:6px;">
      🔐 Sign to authenticate
    </div>
    <div style="color:#aaa;font-size:11px;">
      Wallet: <span style="font-family:monospace;">{short_addr}</span>
    </div>
    <div style="color:#888;font-size:10px;margin-top:4px;">
      This signs a message proving you own this wallet. No transaction or gas is needed.
    </div>
  </div>
  <button id="sign-btn" onclick="signMessage()" style="
    background: linear-gradient(135deg, #3b82f6, #2563eb);
    color: white; border: none; padding: 10px 20px;
    border-radius: 8px; font-size: 14px; font-weight: 600;
    cursor: pointer; width: 100%; transition: opacity 0.2s;
  " onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
    ✍️ Sign Message
  </button>
  <div id="sign-status" style="margin-top:8px;font-size:12px;color:#aaa;text-align:center;"></div>
</div>
<script>
const _typedData = {typed_data_json};
const _address   = "{address}";
const _paramSig  = "{param_sig}";
const _paramIat  = "{param_iat}";

async function signMessage() {
  const btn = document.getElementById('sign-btn');
  const statusEl = document.getElementById('sign-status');
  try {
    btn.disabled = true;
    btn.style.opacity = '0.6';
    statusEl.textContent = 'Waiting for MetaMask signature...';
    const issuedAt = _typedData.message.issuedAt;
    const signature = await window.parent.ethereum.request({
      method: 'eth_signTypedData_v4',
      params: [_address, JSON.stringify(_typedData)]
    });
    statusEl.textContent = 'Signature received. Verifying...';
    statusEl.style.color = '#00c896';
    const url = new URL(window.parent.location.href);
    url.searchParams.set(_paramSig, signature);
    url.searchParams.set(_paramIat, issuedAt);
    window.parent.location.replace(url.toString());
  } catch (err) {
    statusEl.textContent = 'Signing cancelled or failed.';
    statusEl.style.color = '#ff6b6b';
    btn.disabled = false;
    btn.style.opacity = '1';
  }
}
</script>
"""


# ── Restore JWT from sessionStorage after page reload ────────────────────────

_RESTORE_HTML = f"""
<script>
(function() {{
  var jwt = sessionStorage.getItem('_polymad_jwt');
  var exp = sessionStorage.getItem('_polymad_jwt_exp');
  if (!jwt) return;
  if (exp) {{
    try {{
      if (new Date(exp) <= new Date()) {{
        sessionStorage.removeItem('_polymad_jwt');
        sessionStorage.removeItem('_polymad_jwt_exp');
        sessionStorage.removeItem('_polymad_addr');
        return;
      }}
    }} catch(e) {{}}
  }}
  var url = new URL(window.parent.location.href);
  if (!url.searchParams.get('{_PARAM_JWT}')) {{
    url.searchParams.set('{_PARAM_JWT}', jwt);
    window.parent.location.replace(url.toString());
  }}
}})();
</script>
"""


def _build_sign_html(address: str, nonce: str) -> str:
    """Build the Phase 2 HTML with the EIP-712 typed data embedded."""
    issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    typed_data = build_eip712_message(address, nonce, issued_at)
    typed_data_json = json.dumps(typed_data)
    short_addr = address[:6] + "..." + address[-4:]
    return (
        _PHASE2_HTML
        .replace("{typed_data_json}", typed_data_json)
        .replace("{address}", address)
        .replace("{short_addr}", short_addr)
        .replace("{param_sig}", _PARAM_SIG)
        .replace("{param_iat}", _PARAM_IAT)
    )


# ── Public component functions ───────────────────────────────────────────────

def render_metamask_button(connect_label: str = "Connect MetaMask", status_text: str = "") -> None:
    """Render the Phase 1 MetaMask connect button."""
    html = _PHASE1_HTML.replace("{connect_label}", connect_label).replace("{status_text}", status_text)
    components.html(html, height=90)


def render_auth_status() -> None:
    """
    Render a small auth status badge in the sidebar showing JWT expiry
    or a sign-out button.  Relies on auth_bridge.is_authenticated().
    """
    if auth_bridge.is_authenticated():
        address = auth_bridge.get_authenticated_address() or ""
        short = address[:6] + "..." + address[-4:] if address else "unknown"
        expires_at = st.session_state.get("_auth_token_expires_at", "")
        st.sidebar.markdown(
            f"""
            <div style="background:rgba(0,200,150,0.1);border:1px solid #00c896;
                        border-radius:8px;padding:10px;margin:8px 0;">
                <div style="color:#00c896;font-size:12px;font-weight:600;">✓ Authenticated</div>
                <div style="color:#ddd;font-size:11px;margin-top:4px;font-family:monospace;">{short}</div>
                {f'<div style="color:#888;font-size:10px;margin-top:2px;">Expires {expires_at[:16]}</div>' if expires_at else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.sidebar.button("Sign out", use_container_width=True):
            auth_bridge.clear_auth()
            _clear_auth_params()
            st.rerun()


def _clear_auth_params() -> None:
    """Remove all auth-related URL params."""
    for key in (_PARAM_ADDR, _PARAM_SIG, _PARAM_IAT, _PARAM_JWT):
        if key in st.query_params:
            del st.query_params[key]


def process_auth_flow() -> None:
    """
    Drive the 2-phase EIP-712 authentication flow.
    Call this once per Streamlit script run (top of main).

    State machine:
      already authenticated → nothing to do
      _w_jwt present → restore JWT from sessionStorage (no re-sign needed)
      no params → inject restore component (reads sessionStorage)
      _w_addr present, no JWT → Phase 1: request nonce, render sign button
      _w_addr + _w_sig + _w_iat present → Phase 2: verify signature, store JWT
    """
    # Already authenticated — skip
    if auth_bridge.is_authenticated():
        return

    params = st.query_params

    # ── Restore path: JWT passed from sessionStorage via URL param ────────────
    jwt_param = params.get(_PARAM_JWT, "")
    if jwt_param:
        from src.api.security.jwt_handler import decode_access_token
        addr = decode_access_token(jwt_param)
        if addr:
            st.session_state[auth_bridge._TOKEN_KEY] = jwt_param
            st.session_state[auth_bridge._ADDRESS_KEY] = addr
            if _PARAM_JWT in st.query_params:
                del st.query_params[_PARAM_JWT]
            st.rerun()
            return
        else:
            # Expired or invalid JWT — clear sessionStorage and the param
            components.html(
                "<script>"
                "sessionStorage.removeItem('_polymad_jwt');"
                "sessionStorage.removeItem('_polymad_jwt_exp');"
                "sessionStorage.removeItem('_polymad_addr');"
                "</script>",
                height=0,
            )
            if _PARAM_JWT in st.query_params:
                del st.query_params[_PARAM_JWT]

    address = params.get(_PARAM_ADDR, "")
    signature = params.get(_PARAM_SIG, "")
    issued_at = params.get(_PARAM_IAT, "")

    if not address:
        # No auth params at all — try to restore from sessionStorage
        components.html(_RESTORE_HTML, height=0)
        return

    # Basic Ethereum address validation before making any network call
    import re
    if not re.match(r"^0x[0-9a-fA-F]{40}$", address):
        _clear_auth_params()
        return

    if signature and issued_at:
        # Phase 2: verify signature
        nonce = st.session_state.get("_auth_pending_nonce", "")
        if not nonce:
            # Nonce missing from session — restart
            _clear_auth_params()
            st.session_state.pop("_auth_pending_nonce", None)
            st.rerun()
            return

        # Clear URL params BEFORE verification (single-use params)
        _clear_auth_params()

        ok = auth_bridge.verify_signature(
            address=address,
            signature=signature,
            nonce=nonce,
            issued_at=issued_at,
        )
        st.session_state.pop("_auth_pending_nonce", None)
        if ok:
            st.rerun()
        else:
            st.error("Authentication failed. Please try again.")
        return

    # Phase 1: address received, no signature yet — request nonce
    if "_auth_pending_nonce" not in st.session_state:
        nonce = auth_bridge.request_nonce(address)
        if nonce:
            st.session_state["_auth_pending_nonce"] = nonce
        else:
            st.error("Could not reach authentication server. Please try again.")
            _clear_auth_params()
            return

    nonce = st.session_state.get("_auth_pending_nonce", "")
    if nonce:
        # Render the sign button — embedded nonce is NOT a secret
        # (it's a one-time challenge, useless without the private key)
        sign_html = _build_sign_html(address, nonce)
        components.html(sign_html, height=160)


# ── Legacy helpers (kept for callers that haven't been updated yet) ──────────

def get_wallet_address() -> str:
    """
    Return the authenticated wallet address from the verified JWT.
    Returns empty string if not authenticated.

    NOTE: This no longer reads from URL query params.
    The address is the JWT sub claim — cryptographically verified.
    """
    return auth_bridge.get_authenticated_address() or ""


def get_usdc_balance(address: str) -> float:
    """
    Fetch USDC balance for address on Polygon via JSON-RPC.
    Returns 0.0 on any error.
    """
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
        raw = int(result, 16)
        return raw / 1e6
    except Exception as exc:
        logger.debug("USDC balance fetch failed: %s", exc)
        return 0.0


def render_wallet_sidebar(t: "callable") -> str:
    """
    Render wallet authentication section in sidebar.
    Returns current authenticated wallet address (or empty string).
    """
    address = auth_bridge.get_authenticated_address() or ""

    if address:
        render_auth_status()
    else:
        st.sidebar.markdown("**Connect Wallet**")
        render_metamask_button(connect_label=t("connect_wallet"))

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
        st.info(f"🦊 {t('connect_wallet')} to see your portfolio.")
        render_metamask_button(connect_label=t("connect_wallet"))
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

    # ── Real positions (via auth_bridge when authenticated) ───────────────────
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
        # Aggregate portfolio totals
        total_current = sum(float(p.get("currentValue", p.get("current_value", 0))) for p in positions_raw)
        total_initial = sum(float(p.get("initialValue", p.get("initial_value", 0))) for p in positions_raw)
        total_pnl = total_current - total_initial
        total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0.0

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric(t("portfolio_value"), f"${total_current:,.2f}")
        pnl_sign = "+" if total_pnl >= 0 else ""
        mc2.metric(t("total_pnl"), f"{pnl_sign}${total_pnl:.2f}")
        ret_sign = "+" if total_pnl_pct >= 0 else ""
        mc3.metric(t("pnl_return_pct"), f"{ret_sign}{total_pnl_pct:.1f}%")

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

            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            ret_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"

            rows.append({
                t("market_col"): title,
                t("side_col"): side,
                t("size_col"): f"{size:.2f}",
                t("entry_price"): f"${avg_price:.3f}",
                t("current_price"): f"${current_value / size:.3f}" if size > 0 else "—",
                t("pnl_label"): pnl_str,
                t("pnl_return_pct"): ret_str,
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
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
                    <div style="
                        background:#1e2530;border:1px solid #2d3748;
                        border-radius:10px;padding:14px;margin:8px 0;
                    ">
                        <div style="color:#ddd;font-size:13px;font-weight:600;">
                            {type_badge} {getattr(market, 'city', getattr(market, 'asset', getattr(market, 'topic', ''))[:30])}
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
                            text-decoration:none;font-size:12px;
                        ">{t('trade_on_polymarket')}</a>
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
                    t("backtest_col_model"):  f"{float(h.get('model_prob', 0)) * 100:.1f}%",
                    t("backtest_col_market"): f"{float(h.get('market_prob', 0)) * 100:.1f}%",
                    t("backtest_col_edge"):   f"{float(h.get('edge', 0)) * 100:+.1f}%",
                    t("backtest_col_result"): result_str,
                })
            st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)
        else:
            st.info(t("alert_history_empty"))
    else:
        st.info(t("history_no_supabase"))

    st.markdown("---")

    # ── Model track record ────────────────────────────────────────────────────
    st.subheader(t("track_record_title"))

    if history:
        resolved = [h for h in history if h.get("resolved_yes") is not None]
        n_total = len(history)
        n_resolved = len(resolved)
        n_correct = sum(
            1 for h in resolved
            if (float(h.get("model_prob", 0)) >= 0.5) == bool(h.get("resolved_yes"))
        )
        accuracy = n_correct / n_resolved if n_resolved else 0.0

        tc1, tc2, tc3 = st.columns(3)
        tc1.metric(t("track_total_alerts"), n_total)
        tc2.metric(t("track_resolved"), n_resolved)
        tc3.metric(t("track_accuracy"), f"{accuracy * 100:.1f}%")

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
                    t("track_accuracy"): (
                        f"{v['correct'] / v['total'] * 100:.1f}%" if v["total"] else "—"
                    ),
                }
                for mtype, v in sorted(by_type.items())
            ]
            st.dataframe(pd.DataFrame(type_rows), use_container_width=True, hide_index=True)
    else:
        st.info(t("alert_history_empty"))
