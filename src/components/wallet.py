"""MetaMask wallet connection component for polyMad Streamlit dashboard."""
import json
import logging
import streamlit as st
import streamlit.components.v1 as components

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


def render_wallet_tab(t: "callable", address: str, results: list, bankroll: float) -> None:
    """Render the Wallet tab content."""
    if not address:
        st.info(f"🦊 {t('connect_wallet')} to see your portfolio.")
        render_metamask_button(connect_label=t("connect_wallet"))
        return

    short = address[:6] + "..." + address[-4:]

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
    st.subheader(t("wallet_portfolio"))

    if not results:
        st.info(t("run_first"))
        return

    alerts = [r for r in results if r.alert]
    if not alerts:
        st.info(t("wallet_no_positions"))
        return

    st.markdown(f"**{len(alerts)} active opportunities matched to wallet**")

    for r in alerts[:5]:
        market = r.market
        bet = bankroll * r.suggested_bet_fraction
        poly_url = (
            f"https://polymarket.com/event/{market.event_slug}"
            if market.event_slug
            else "https://polymarket.com"
        )
        st.markdown(
            f"""
            <div style="
                background:#1e2530;
                border:1px solid #2d3748;
                border-radius:10px;
                padding:14px;
                margin:8px 0;
            ">
                <div style="color:#ddd;font-size:13px;font-weight:600;">{market.city} · {market.resolution_date.strftime('%b %d')}</div>
                <div style="color:#888;font-size:11px;margin:4px 0;">{market.question[:70]}...</div>
                <div style="display:flex;gap:20px;margin-top:8px;">
                    <span style="color:#00c896;">Edge: {r.edge*100:+.1f}%</span>
                    <span style="color:#60a5fa;">EV: {r.expected_value:+.2f}</span>
                    <span style="color:#f59e0b;">Bet: ${bet:.2f}</span>
                </div>
                <a href="{poly_url}" target="_blank" style="
                    display:inline-block;
                    margin-top:8px;
                    background:#3b82f6;
                    color:white;
                    padding:4px 12px;
                    border-radius:6px;
                    text-decoration:none;
                    font-size:12px;
                ">{t('trade_on_polymarket')}</a>
            </div>
            """,
            unsafe_allow_html=True,
        )
