"""MetaMask wallet connection component for polyMad Streamlit dashboard."""
import json
import logging
from collections import defaultdict

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.data.supabase_client import (
    get_alert_config,
    upsert_alert_config,
    get_alert_history,
)

logger = logging.getLogger(__name__)

POLYGON_RPC = "https://polygon-rpc.com"
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon


_METAMASK_HTML = """
<div id="wallet-container">
  <button id="connect-btn" onclick="connectWallet()" style="
    background: linear-gradient(135deg, #f6851b, #e2761b);
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    width: 100%;
    transition: opacity 0.2s;
  " onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
    {connect_label}
  </button>
  <div id="status" style="
    margin-top: 8px;
    font-size: 12px;
    color: #aaa;
    text-align: center;
  ">{status_text}</div>
</div>

<script>
async function connectWallet() {
  const btn = document.getElementById('connect-btn');
  const status = document.getElementById('status');

  if (typeof window.parent.ethereum === 'undefined') {
    status.textContent = 'MetaMask not detected. Please install it.';
    status.style.color = '#ff6b6b';
    return;
  }

  try {
    btn.disabled = true;
    btn.style.opacity = '0.6';
    status.textContent = 'Connecting...';
    status.style.color = '#aaa';

    const accounts = await window.parent.ethereum.request({
      method: 'eth_requestAccounts'
    });

    const address = accounts[0];
    const shortAddr = address.slice(0, 6) + '...' + address.slice(-4);

    status.textContent = 'Connected: ' + shortAddr;
    status.style.color = '#00c896';
    btn.textContent = shortAddr;
    btn.style.background = 'linear-gradient(135deg, #00c896, #00a876)';

    // Send address back to Streamlit via URL param + reload
    const url = new URL(window.parent.location.href);
    url.searchParams.set('wallet_address', address);
    window.parent.history.replaceState({}, '', url.toString());

    // Notify Streamlit
    window.parent.postMessage({
      type: 'wallet_connected',
      address: address
    }, '*');

  } catch (err) {
    status.textContent = 'Connection refused.';
    status.style.color = '#ff6b6b';
    btn.disabled = false;
    btn.style.opacity = '1';
  }
}

// Check if already connected
(async () => {
  if (typeof window.parent.ethereum !== 'undefined') {
    const accounts = await window.parent.ethereum.request({
      method: 'eth_accounts'
    });
    if (accounts.length > 0) {
      const address = accounts[0];
      const shortAddr = address.slice(0, 6) + '...' + address.slice(-4);
      const btn = document.getElementById('connect-btn');
      const status = document.getElementById('status');
      btn.textContent = shortAddr;
      btn.style.background = 'linear-gradient(135deg, #00c896, #00a876)';
      status.textContent = 'Wallet connected';
      status.style.color = '#00c896';
    }
  }
})();
</script>
"""


def render_metamask_button(connect_label: str = "Connect MetaMask", status_text: str = "") -> None:
    """Render the MetaMask connect button as an HTML component."""
    # Replace only the two placeholders; all JS braces are already literal in the template
    html = _METAMASK_HTML.replace("{connect_label}", connect_label).replace("{status_text}", status_text)
    components.html(html, height=90)


def get_wallet_address() -> str:
    """Read wallet address from Streamlit query params (set by JS after connect)."""
    params = st.query_params
    return params.get("wallet_address", "")


def get_usdc_balance(address: str) -> float:
    """
    Fetch USDC balance for address on Polygon via JSON-RPC.
    Returns 0.0 on any error.
    """
    if not address:
        return 0.0
    try:
        import requests

        # ERC-20 balanceOf(address) selector: 0x70a08231
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
        return raw / 1e6  # USDC has 6 decimals
    except Exception as exc:
        logger.debug("USDC balance fetch failed: %s", exc)
        return 0.0


def render_wallet_sidebar(t: "callable") -> str:
    """
    Render wallet connect section in sidebar.
    Returns current wallet address (or empty string).
    """
    address = get_wallet_address()

    if address:
        short = address[:6] + "..." + address[-4:]
        st.sidebar.markdown(
            f"""
            <div style="
                background: rgba(0,200,150,0.1);
                border: 1px solid #00c896;
                border-radius: 8px;
                padding: 10px;
                margin: 8px 0;
            ">
                <div style="color:#00c896; font-size:12px; font-weight:600;">
                    ✓ {t('wallet_connected')}
                </div>
                <div style="color:#ddd; font-size:11px; margin-top:4px; font-family:monospace;">
                    {short}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.sidebar.button(t("disconnect_wallet"), use_container_width=True):
            params = dict(st.query_params)
            params.pop("wallet_address", None)
            st.query_params.clear()
            for k, v in params.items():
                st.query_params[k] = v
            st.rerun()
    else:
        render_metamask_button(connect_label=t("connect_wallet"))

    return address


def render_wallet_tab(
    t: "callable",
    address: str,
    results: list,
    bankroll: float,
    poly_client=None,
) -> None:
    """Render the Wallet tab content with real positions and scan opportunities."""
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

    # ── Header cards ─────────────────────────────────────────────────────────
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

    if poly_client is not None:
        with st.spinner(t("fetching_positions")):
            positions = poly_client.get_user_positions(address)
    else:
        positions = []

    if positions:
        # Aggregate portfolio totals
        total_current = sum(float(p.get("currentValue", 0)) for p in positions)
        total_initial = sum(float(p.get("initialValue", 0)) for p in positions)
        total_pnl = total_current - total_initial
        total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0.0

        # Summary metric strip
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric(t("portfolio_value"), f"${total_current:,.2f}")
        pnl_sign = "+" if total_pnl >= 0 else ""
        mc2.metric(t("total_pnl"), f"{pnl_sign}${total_pnl:.2f}")
        ret_sign = "+" if total_pnl_pct >= 0 else ""
        mc3.metric(t("pnl_return_pct"), f"{ret_sign}{total_pnl_pct:.1f}%")

        st.markdown("")

        # Build condition_id → market lookup from current scan results
        market_by_condition = {r.market.condition_id: r.market for r in results} if results else {}

        rows = []
        for pos in positions:
            cid = pos.get("conditionId", "")
            outcome_idx = pos.get("outcomeIndex", 0)
            side = "YES" if outcome_idx == 0 else "NO"
            size = float(pos.get("size", 0))
            avg_price = float(pos.get("avgPrice", 0))
            current_value = float(pos.get("currentValue", 0))
            initial_value = float(pos.get("initialValue", 0))
            pnl = current_value - initial_value
            pnl_pct = (pnl / initial_value * 100) if initial_value > 0 else 0.0

            mkt = market_by_condition.get(cid)
            title = (mkt.question[:60] + "...") if mkt else pos.get("title", cid[:20])

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
                    t("scan_date_col"):           str(h.get("created_at", ""))[:16],
                    t("market_col"):              (h.get("question") or "")[:55],
                    t("backtest_col_type"):       (h.get("market_type") or "").capitalize(),
                    t("backtest_col_model"):      f"{float(h.get('model_prob', 0)) * 100:.1f}%",
                    t("backtest_col_market"):     f"{float(h.get('market_prob', 0)) * 100:.1f}%",
                    t("backtest_col_edge"):       f"{float(h.get('edge', 0)) * 100:+.1f}%",
                    t("backtest_col_result"):     result_str,
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
