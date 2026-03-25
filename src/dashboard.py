"""
polyMad Visual Dashboard — v3
Light/Dark theme | Multi-language | Auto-refresh | MetaMask | Tabs
Run: streamlit run src/dashboard.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statistics
from datetime import datetime, timezone, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from config import settings
from config.i18n import get_text, format_currency, format_pct, format_date, LANGUAGE_OPTIONS
from src.data.polymarket_client import PolymarketClient, parse_weather_market, PolymarketAPIError
from src.data.weather_client import WeatherClient, CityNotFoundError, WeatherAPIError
from src.analysis import edge_calculator
from src.analysis.kelly import compute_position_size, kelly_summary
from src.models.market import WeatherForecast, OpportunityResult
from src.components.wallet import render_wallet_sidebar, render_wallet_tab
from src.notifications import send_alert_email

# ─── Page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="polyMad · Buscador de Oportunidades",
    page_icon="🌡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Theme palettes ──────────────────────────────────────────────────────────

THEMES = {
    "light": {
        "bg":           "#f0f4f8",
        "card":         "#ffffff",
        "card_border":  "#e2e8f0",
        "sidebar_bg":   "#ffffff",
        "sidebar_border":"#e2e8f0",
        "sb_text":      "#1e293b",
        "sb_text_muted":"#64748b",
        "sb_input_bg":  "#f1f5f9",
        "sb_input_border":"#cbd5e1",
        "text_h":       "#0f172a",
        "text_b":       "#475569",
        "text_muted":   "#94a3b8",
        "positive":     "#059669",
        "warning":      "#d97706",
        "negative":     "#dc2626",
        "accent":       "#2563eb",
        "badge_pos_bg": "#d1fae5",
        "badge_pos_fg": "#065f46",
        "badge_warn_bg":"#fef3c7",
        "badge_warn_fg":"#92400e",
        "badge_neg_bg": "#fee2e2",
        "badge_neg_fg": "#991b1b",
        "metric_bg":    "#ffffff",
        "divider":      "#e2e8f0",
        "plot_bg":      "rgba(240,244,248,0.6)",
        "plot_paper":   "rgba(0,0,0,0)",
        "plot_text":    "#475569",
        "plot_grid":    "#e2e8f0",
        "shadow":       "0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.05)",
    },
    "dark": {
        "bg":           "#0f172a",
        "card":         "#1e293b",
        "card_border":  "#334155",
        "sidebar_bg":   "#0f172a",
        "sidebar_border":"#1e293b",
        "sb_text":      "#e2e8f0",
        "sb_text_muted":"#64748b",
        "sb_input_bg":  "#334155",
        "sb_input_border":"#475569",
        "text_h":       "#f1f5f9",
        "text_b":       "#cbd5e1",
        "text_muted":   "#64748b",
        "positive":    "#34d399",
        "warning":     "#fbbf24",
        "negative":    "#f87171",
        "accent":      "#60a5fa",
        "badge_pos_bg":"#064e3b",
        "badge_pos_fg":"#6ee7b7",
        "badge_warn_bg":"#451a03",
        "badge_warn_fg":"#fcd34d",
        "badge_neg_bg": "#450a0a",
        "badge_neg_fg": "#fca5a5",
        "metric_bg":   "#1e293b",
        "divider":     "#1e293b",
        "plot_bg":     "rgba(30,41,59,0.8)",
        "plot_paper":  "rgba(0,0,0,0)",
        "plot_text":   "#94a3b8",
        "plot_grid":   "#334155",
        "shadow":      "0 1px 4px rgba(0,0,0,0.4)",
    },
}


def get_theme() -> dict:
    mode = st.session_state.get("theme", "light")
    return THEMES.get(mode, THEMES["light"])


def inject_css(th: dict) -> None:
    st.markdown(f"""
<style>
/* ── App background ─────────────────────────────────── */
.stApp, .stApp > div {{
    background-color: {th['bg']} !important;
}}

/* ── Sidebar ────────────────────────────────────────── */
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] > div {{
    background-color: {th['sidebar_bg']} !important;
    border-right: 1px solid {th['sidebar_border']} !important;
}}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {{
    color: {th['sb_text']} !important;
}}
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stMultiSelect > div > div,
section[data-testid="stSidebar"] .stNumberInput > div > div > input,
section[data-testid="stSidebar"] .stTextInput > div > div > input {{
    background: {th['sb_input_bg']} !important;
    color: {th['sb_text']} !important;
    border-color: {th['sb_input_border']} !important;
}}
section[data-testid="stSidebar"] .stSlider > div {{
    color: {th['sb_text']} !important;
}}

/* ── Metric cards ───────────────────────────────────── */
div[data-testid="metric-container"] {{
    background: {th['metric_bg']};
    border: 1px solid {th['card_border']};
    border-radius: 12px;
    padding: 16px 20px;
    box-shadow: {th['shadow']};
}}
div[data-testid="metric-container"] label {{
    color: {th['text_muted']} !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
div[data-testid="metric-container"] [data-testid="metric-value"] {{
    color: {th['text_h']} !important;
    font-size: 28px !important;
    font-weight: 700 !important;
}}

/* ── Tab labels ─────────────────────────────────────── */
button[data-baseweb="tab"] {{
    color: {th['text_b']} !important;
    font-weight: 500;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: {th['accent']} !important;
    border-bottom-color: {th['accent']} !important;
}}

/* ── Dataframe ──────────────────────────────────────── */
.stDataFrame {{
    background: {th['card']};
    border-radius: 10px;
    border: 1px solid {th['card_border']};
    overflow: hidden;
}}

/* ── Alert cards ────────────────────────────────────── */
.alert-card {{
    background: {th['card']};
    border: 1px solid {th['card_border']};
    border-left: 5px solid {th['positive']};
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 14px;
    box-shadow: {th['shadow']};
}}
.alert-card.high-edge {{
    border-left-color: {th['warning']};
}}
.alert-card.top-edge {{
    border-left-color: #7c3aed;
    background: {'#faf5ff' if th['bg'] == THEMES['light']['bg'] else '#2e1065'};
}}

/* ── Badges ─────────────────────────────────────────── */
.badge-pos {{
    background: {th['badge_pos_bg']}; color: {th['badge_pos_fg']};
    padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700;
    display: inline-block;
}}
.badge-warn {{
    background: {th['badge_warn_bg']}; color: {th['badge_warn_fg']};
    padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700;
    display: inline-block;
}}
.badge-neg {{
    background: {th['badge_neg_bg']}; color: {th['badge_neg_fg']};
    padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700;
    display: inline-block;
}}

/* ── Trade button ───────────────────────────────────── */
.trade-btn a {{
    background: {th['accent']}; color: #ffffff !important;
    padding: 6px 16px; border-radius: 8px; text-decoration: none;
    font-size: 12px; font-weight: 600; letter-spacing: 0.02em;
    display: inline-block; transition: opacity 0.15s;
}}
.trade-btn a:hover {{ opacity: 0.85; }}

/* ── Kelly panel ─────────────────────────────────────── */
.kelly-panel {{
    background: {th['card']};
    border: 1px solid {th['card_border']};
    border-radius: 10px;
    padding: 14px 16px;
    font-size: 13px;
    box-shadow: {th['shadow']};
}}

/* ── Expander ───────────────────────────────────────── */
details[data-testid="stExpander"] {{
    background: {th['card']};
    border: 1px solid {th['card_border']};
    border-radius: 8px;
}}

/* ── Info/warning box ───────────────────────────────── */
.stAlert {{
    border-radius: 10px;
}}

/* ── General text ───────────────────────────────────── */
.stMarkdown, .stText, p, li {{
    color: {th['text_b']};
}}
h1, h2, h3, h4 {{
    color: {th['text_h']} !important;
}}

/* ── Progress bar ───────────────────────────────────── */
.stProgress > div > div > div {{
    background: linear-gradient(90deg, {th['accent']}, {th['positive']}) !important;
}}
</style>
""", unsafe_allow_html=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def t(key: str) -> str:
    return get_text(key, st.session_state.get("lang", "en"))


def _pct(val: float) -> str:
    return format_pct(val, st.session_state.get("lang", "en"))


def _usd(val: float) -> str:
    return format_currency(val, st.session_state.get("lang", "en"))


# ─── Cached data fetchers ────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_markets_cached(min_liquidity: float, max_days: int) -> list:
    return PolymarketClient().fetch_weather_markets(min_liquidity=min_liquidity, max_days=max_days)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_forecast_cached(
    city: str, date_str: str, threshold: float, bucket_type: str, model: str,
    temp_type: str = "highest",
) -> dict:
    try:
        resolution_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        fc = WeatherClient().get_ensemble_forecast(
            city=city, resolution_date=resolution_date,
            threshold_celsius=threshold, direction=bucket_type, model=model,
            temp_type=temp_type,
        )
        return {
            "model_probability": fc.model_probability,
            "ensemble_member_count": fc.ensemble_member_count,
            "raw_temperatures": fc.raw_temperatures,
            "forecast_model": fc.forecast_model,
        }
    except (CityNotFoundError, WeatherAPIError) as exc:
        return {"error": str(exc)}


# ─── Analysis pipeline ────────────────────────────────────────────────────────

def run_analysis(bankroll, edge_threshold, model, max_markets, cities_filter):
    debug_info = {"raw_tuples": 0, "parsed": 0, "api_error": ""}

    with st.spinner(t("loading")):
        try:
            raw_tuples = fetch_markets_cached(min_liquidity=0.0, max_days=settings.MAX_DAYS_TO_EXPIRY)
        except PolymarketAPIError as exc:
            st.error(f"{t('error')}: {exc}")
            debug_info["api_error"] = str(exc)
            return [], [], debug_info

    debug_info["raw_tuples"] = len(raw_tuples)

    if not raw_tuples:
        return [], [], debug_info

    weather_markets = []
    for tup in raw_tuples[:max_markets]:
        raw_mkt, event_title, event_end = tup[0], tup[1], tup[2]
        event_slug = tup[3] if len(tup) > 3 else ""
        market = parse_weather_market(
            raw_mkt, event_title=event_title, end_date_str=event_end, event_slug=event_slug
        )
        if market is None:
            continue
        if cities_filter and market.city not in cities_filter:
            continue
        weather_markets.append(market)

    debug_info["parsed"] = len(weather_markets)

    if not weather_markets:
        return [], [], debug_info

    results, skipped = [], []
    total = len(weather_markets)
    prog = st.progress(0, text=t("loading"))

    for i, market in enumerate(weather_markets):
        prog.progress(
            (i + 1) / total,
            text=f"🌤  {market.city}  {market.threshold_celsius}°C  ({i+1}/{total})",
        )
        fd = fetch_forecast_cached(
            city=market.city,
            date_str=market.resolution_date.strftime("%Y-%m-%d"),
            threshold=market.threshold_celsius,
            bucket_type=market.bucket_type,
            model=model,
            temp_type=getattr(market, "temp_type", "highest"),
        )
        if "error" in fd:
            skipped.append(f"{market.city}: {fd['error']}")
            continue
        forecast = WeatherForecast(
            city=market.city, resolution_date=market.resolution_date,
            threshold_celsius=market.threshold_celsius, direction=market.bucket_type,
            model_probability=fd["model_probability"],
            ensemble_member_count=fd["ensemble_member_count"],
            forecast_model=fd["forecast_model"],
            raw_temperatures=fd["raw_temperatures"],
        )
        result = edge_calculator.analyze_market(market, forecast)
        result.alert = result.edge > edge_threshold
        results.append(result)

    prog.empty()
    return results, skipped, debug_info


# ─── Chart builders ──────────────────────────────────────────────────────────

def make_probability_comparison(result: OpportunityResult, th: dict) -> go.Figure:
    m, f = result.market, result.forecast
    mkt_pct = m.market_implied_prob * 100
    mdl_pct = f.model_probability * 100
    pos_color = th["positive"]
    neg_color = th["negative"]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=t("market_prob"), x=[mkt_pct], y=[""], orientation="h",
        marker_color=th["accent"],
        text=[f"{mkt_pct:.1f}%"], textposition="inside",
        textfont=dict(color="white", size=14, family="Arial Black"),
    ))
    fig.add_trace(go.Bar(
        name=t("model_prob"), x=[mdl_pct], y=[""], orientation="h",
        marker_color=pos_color if result.edge > 0 else neg_color,
        text=[f"{mdl_pct:.1f}%"], textposition="inside",
        textfont=dict(color="white", size=14, family="Arial Black"),
    ))
    fig.update_layout(
        barmode="group", height=90,
        margin=dict(l=0, r=0, t=2, b=0),
        paper_bgcolor=th["plot_paper"], plot_bgcolor=th["plot_paper"],
        legend=dict(
            orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1,
            font=dict(color=th["plot_text"], size=11),
        ),
        xaxis=dict(range=[0, max(mkt_pct, mdl_pct, 1) * 1.25],
                   showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False),
        font=dict(color=th["plot_text"]),
    )
    return fig


def make_ensemble_distribution(result: OpportunityResult, th: dict) -> go.Figure:
    f, m = result.forecast, result.market
    temps = f.raw_temperatures
    if not temps:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=temps, nbinsx=20,
        marker=dict(color=th["accent"], opacity=0.8, line=dict(color=th["card"], width=0.5)),
        name=f"{t('ensemble_label')} ({f.ensemble_member_count})",
    ))
    fig.add_vline(x=m.threshold_celsius, line_dash="dash", line_color=th["negative"],
                  annotation_text=f"  {t('threshold_label')} {m.threshold_celsius}°C",
                  annotation_font=dict(color=th["negative"], size=11))
    if temps:
        med = statistics.median(temps)
        fig.add_vline(x=med, line_dash="dot", line_color=th["positive"],
                      annotation_text=f"  {t('median_label')} {med:.1f}°C",
                      annotation_font=dict(color=th["positive"], size=11),
                      annotation_position="top left")
    fig.update_layout(
        height=210, margin=dict(l=0, r=0, t=24, b=0),
        paper_bgcolor=th["plot_paper"], plot_bgcolor=th["plot_bg"],
        xaxis=dict(title="°C", color=th["plot_text"],
                   gridcolor=th["plot_grid"], zeroline=False),
        yaxis=dict(title=t("members"), color=th["plot_text"],
                   gridcolor=th["plot_grid"]),
        legend=dict(font=dict(color=th["plot_text"], size=10)),
        font=dict(color=th["plot_text"]),
    )
    return fig


def make_edge_scatter(results: list, threshold_used: float, th: dict) -> go.Figure:
    edges = [r.edge * 100 for r in results]
    evs = [r.expected_value for r in results]
    labels = [f"{r.market.city} {r.market.threshold_celsius:.0f}°C" for r in results]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edges, y=evs, mode="markers+text",
        marker=dict(
            size=11, color=edges,
            colorscale=[[0, th["negative"]], [0.45, th["warning"]], [0.65, th["positive"]], [1, "#065f46"]],
            cmin=-20, cmax=30,
            colorbar=dict(
                title=dict(text="Edge %", font=dict(color=th["plot_text"], size=11)),
                tickfont=dict(color=th["plot_text"], size=10),
            ),
            line=dict(width=1.5, color=th["card_border"]),
        ),
        text=labels, textposition="top center",
        textfont=dict(size=9, color=th["text_muted"]),
        hovertemplate="<b>%{text}</b><br>Edge: %{x:.1f}%<br>EV: $%{y:.3f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=th["text_muted"], line_dash="dash", line_width=1)
    fig.add_vline(x=threshold_used * 100, line_color=th["warning"], line_dash="dot",
                  annotation_text=f" {t('edge_threshold')}",
                  annotation_font=dict(color=th["warning"], size=11))
    fig.update_layout(
        height=330, paper_bgcolor=th["plot_paper"], plot_bgcolor=th["plot_bg"],
        xaxis=dict(title=t("edge_pct"), color=th["plot_text"],
                   gridcolor=th["plot_grid"], zeroline=False),
        yaxis=dict(title=t("ev_per_dollar"), color=th["plot_text"],
                   gridcolor=th["plot_grid"]),
        font=dict(color=th["plot_text"]), margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


# ─── Alert card ──────────────────────────────────────────────────────────────

def render_alert_card(result: OpportunityResult, bankroll: float, th: dict) -> None:
    m, f = result.market, result.forecast
    edge_pct = result.edge * 100
    bet_usd = compute_position_size(bankroll, result.kelly_fraction)
    ks = kelly_summary(result.kelly_fraction, bankroll)
    bucket_sym = {"above": "≥", "below": "≤", "exact": "="}
    sym = bucket_sym.get(m.bucket_type, "")
    poly_url = (
        f"https://polymarket.com/event/{m.event_slug}" if m.event_slug
        else "https://polymarket.com/markets"
    )
    lang = st.session_state.get("lang", "en")

    if edge_pct > 20:
        card_class = "alert-card top-edge"
        badge_class = "badge-warn"
    elif edge_pct > 10:
        card_class = "alert-card high-edge"
        badge_class = "badge-warn"
    else:
        card_class = "alert-card"
        badge_class = "badge-pos"

    st.markdown(f"""
    <div class="{card_class}">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:6px">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
          <span style="font-size:20px; font-weight:800; color:{th['text_h']}">{m.city}</span>
          <span style="color:{th['text_muted']}; font-size:13px; background:{th['bg']};
                       padding:2px 8px; border-radius:6px; border:1px solid {th['card_border']}">
            {format_date(m.resolution_date, lang)}
          </span>
          <span style="color:{th['text_b']}; font-size:14px; font-weight:600">
            {sym} {m.threshold_celsius:.0f}°C
          </span>
        </div>
        <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap">
          <span class="{badge_class}">{edge_pct:+.1f}% {t('edge')}</span>
          <span class="badge-pos">EV {result.expected_value:+.3f}</span>
        </div>
      </div>
      <div style="color:{th['text_muted']}; font-size:12px; margin-bottom:12px;
                  line-height:1.4; border-left:3px solid {th['card_border']};
                  padding-left:10px">
        {m.question}
      </div>
      <div class="trade-btn">
        <a href="{poly_url}" target="_blank">{t('trade_on_polymarket')}</a>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Return calculations
    gross_payout = bet_usd / m.market_implied_prob if m.market_implied_prob > 0 else 0
    net_if_win   = gross_payout - bet_usd
    ev_dollars   = bet_usd * result.expected_value
    return_pct   = (1 / m.market_implied_prob - 1) * 100 if m.market_implied_prob > 0 else 0

    col1, col2 = st.columns([3, 2])
    with col1:
        st.plotly_chart(
            make_probability_comparison(result, th),
            use_container_width=True, config={"displayModeBar": False},
            key=f"prob_{m.condition_id}",
        )
    with col2:
        st.markdown(f"""
        <div class="kelly-panel">
          <div style="color:{th['text_muted']}; font-size:11px; font-weight:600;
                      text-transform:uppercase; letter-spacing:0.06em; margin-bottom:6px">
            {t('kelly_bet')}
          </div>
          <div style="color:{th['positive']}; font-size:26px; font-weight:800;
                      line-height:1.1; margin-bottom:2px">
            {_usd(bet_usd)}
          </div>
          <div style="color:{th['text_muted']}; font-size:11px; margin-bottom:8px">
            {ks['capped_kelly']*100:.1f}% {t('of_bankroll')} · {t('quarter_kelly')}
          </div>
          <div style="background:{th['bg']}; border:1px solid {th['card_border']};
                      border-radius:8px; padding:8px 10px; margin-bottom:10px;
                      display:grid; gap:4px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="color:{th['text_muted']}; font-size:11px;">{t('return_if_win')}</span>
              <span style="color:{th['positive']}; font-weight:700; font-size:14px;">
                +{_usd(net_if_win)}
              </span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="color:{th['text_muted']}; font-size:11px;">{t('return_pct')}</span>
              <span style="color:{th['positive']}; font-weight:600; font-size:12px;">
                +{return_pct:.1f}%
              </span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center;
                        border-top:1px dashed {th['card_border']}; padding-top:4px; margin-top:2px;">
              <span style="color:{th['text_muted']}; font-size:11px;">{t('expected_profit')}</span>
              <span style="color:{'#059669' if ev_dollars >= 0 else th['negative']}; font-size:12px; font-weight:600;">
                {'+' if ev_dollars >= 0 else ''}{_usd(ev_dollars)}
              </span>
            </div>
          </div>
          <div style="border-top:1px solid {th['card_border']}; padding-top:10px;
                      display:grid; gap:6px">
            <div style="display:flex; justify-content:space-between">
              <span style="color:{th['text_muted']}">{t('market_prob')}</span>
              <span style="color:{th['text_h']}; font-weight:600">
                {m.market_implied_prob*100:.1f}%
              </span>
            </div>
            <div style="display:flex; justify-content:space-between">
              <span style="color:{th['text_muted']}">{t('model_prob')}</span>
              <span style="color:{th['positive']}; font-weight:600">
                {f.model_probability*100:.1f}%
              </span>
            </div>
            <div style="display:flex; justify-content:space-between">
              <span style="color:{th['text_muted']}">{t('liquidity')}</span>
              <span style="color:{th['text_h']}">{_usd(m.liquidity_usd)}</span>
            </div>
            <div style="display:flex; justify-content:space-between">
              <span style="color:{th['text_muted']}">{t('members')}</span>
              <span style="color:{th['text_h']}">{f.ensemble_member_count}</span>
            </div>
            <div style="display:flex; justify-content:space-between">
              <span style="color:{th['text_muted']}">{t('resolution')}</span>
              <span style="color:{th['text_h']}">{m.end_date.strftime('%b %d %H:%MZ')}</span>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    with st.expander(f"📊 {t('ensemble_dist')} — {m.city} {format_date(m.resolution_date, lang)}"):
        st.plotly_chart(
            make_ensemble_distribution(result, th),
            use_container_width=True, config={"displayModeBar": False},
            key=f"dist_{m.condition_id}",
        )


# ─── Full results table ───────────────────────────────────────────────────────

def render_full_table(results: list, bankroll: float, th: dict) -> None:
    bucket_label = {"above": "≥", "below": "≤", "exact": "="}
    lang = st.session_state.get("lang", "en")
    rows = []
    for r in results:
        m, f = r.market, r.forecast
        bet = compute_position_size(bankroll, r.kelly_fraction)
        ret_pct = (1 / m.market_implied_prob - 1) * 100 if m.market_implied_prob > 0 else 0
        net_win  = bet * ret_pct / 100
        rows.append({
            "": "🚨" if r.alert else "·",
            t("city"): m.city,
            t("date"): format_date(m.resolution_date, lang),
            t("threshold"): f"{bucket_label.get(m.bucket_type,'')}{m.threshold_celsius:.0f}°C",
            t("mkt_pct"): round(m.market_implied_prob * 100, 1),
            t("model_pct"): round(f.model_probability * 100, 1),
            t("edge_pct"): round(r.edge * 100, 1),
            t("ev_per_dollar"): round(r.expected_value, 3),
            t("bet_size"): round(bet, 0),
            t("return_pct"): round(ret_pct, 1),
            t("return_if_win"): round(net_win, 2),
            t("kelly_fraction"): round(r.suggested_bet_fraction * 100, 1),
            t("members"): f.ensemble_member_count,
            t("liquidity"): f"${m.liquidity_usd:,.0f}",
        })

    df = pd.DataFrame(rows).sort_values(t("ev_per_dollar"), ascending=False)
    edge_col = t("edge_pct")

    def color_edge(val):
        if val > 10:
            return f"color: {th['positive']}; font-weight: 700"
        elif val > 0:
            return f"color: {th['warning']}; font-weight: 600"
        return f"color: {th['negative']}"

    styled = df.style.applymap(color_edge, subset=[edge_col])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=420)


# ─── Auto-refresh ─────────────────────────────────────────────────────────────

def inject_autorefresh_js(interval_minutes: int, th: dict) -> None:
    components.html(
        f"""
        <div style="
            font-size:11px; color:{th['text_muted']};
            text-align:center; padding:4px 0;
        ">
            🔄 Auto-refresh in <span id="cd"
            style="font-weight:700; color:{th['accent']}">{interval_minutes}:00</span>
        </div>
        <script>
        var remaining = {interval_minutes * 60};
        var cdEl = document.getElementById('cd');
        function tick() {{
            if (remaining <= 0) {{
                window.parent.location.reload();
                return;
            }}
            var m = Math.floor(remaining / 60);
            var s = remaining % 60;
            cdEl.textContent = m + ':' + (s < 10 ? '0' : '') + s;
            remaining--;
            setTimeout(tick, 1000);
        }}
        tick();
        </script>
        """,
        height=30,
    )


# ─── Category bar ────────────────────────────────────────────────────────────

def render_category_bar(th: dict) -> str:
    """
    Horizontal category selector. Only 'weather' is active; others are
    visually disabled with an 'Em breve' badge.
    Returns the selected category key (always 'weather' for now).
    """
    cats = [
        ("weather",  t("cat_weather"),  True),
        ("politics", t("cat_politics"), False),
        ("sports",   t("cat_sports"),   False),
        ("finance",  t("cat_finance"),  False),
        ("other",    t("cat_other"),    False),
    ]
    coming_soon = t("cat_coming_soon")
    active = st.session_state.get("category", "weather")

    buttons_html = ""
    for key, label, enabled in cats:
        is_active = enabled and key == active
        if is_active:
            style = (
                f"background:{th['accent']}; color:#ffffff; border:none;"
                f" padding:7px 18px; border-radius:20px; font-size:13px;"
                f" font-weight:700; cursor:pointer; white-space:nowrap;"
            )
        elif enabled:
            style = (
                f"background:{th['card']}; color:{th['text_b']};"
                f" border:1px solid {th['card_border']};"
                f" padding:7px 18px; border-radius:20px; font-size:13px;"
                f" font-weight:500; cursor:pointer; white-space:nowrap;"
            )
        else:
            style = (
                f"background:{th['card']}; color:{th['text_muted']};"
                f" border:1px solid {th['card_border']};"
                f" padding:7px 18px; border-radius:20px; font-size:13px;"
                f" font-weight:400; cursor:not-allowed; white-space:nowrap;"
                f" opacity:0.5; position:relative;"
            )
        badge = (
            f"<span style='font-size:9px; background:{th['warning']}; color:#fff;"
            f" border-radius:8px; padding:1px 6px; margin-left:6px;"
            f" font-weight:700; vertical-align:middle;'>{coming_soon}</span>"
            if not enabled else ""
        )
        buttons_html += (
            f"<div style='{style}'>{label}{badge}</div>"
        )

    st.markdown(
        f"""
        <div style="
            display:flex; gap:8px; flex-wrap:wrap; align-items:center;
            padding:14px 4px 10px;
            border-bottom:1px solid {th['card_border']};
            margin-bottom:20px;
        ">{buttons_html}</div>
        """,
        unsafe_allow_html=True,
    )
    return active


# ─── Header banner ────────────────────────────────────────────────────────────

def render_header(th: dict, results: list, threshold_used: float) -> None:
    alerts = [r for r in results if r.alert]
    best_edge = max((r.edge for r in results), default=0) if results else 0
    best_ev   = max((r.expected_value for r in results), default=0) if results else 0

    st.markdown(f"""
    <div style="
        display:flex; align-items:center; justify-content:space-between;
        flex-wrap:wrap; gap:12px;
        background: {th['card']};
        border: 1px solid {th['card_border']};
        border-radius:14px;
        padding: 16px 24px;
        margin-bottom:20px;
        box-shadow: {th['shadow']};
    ">
      <div style="display:flex; align-items:center; gap:10px">
        <span style="font-size:30px">🌡</span>
        <div>
          <div style="font-size:22px; font-weight:900; color:{th['text_h']}; line-height:1.1">
            polyMad
          </div>
          <div style="font-size:12px; color:{th['text_muted']}; font-weight:500">
            {t('app_subtitle')}
          </div>
        </div>
      </div>
      <div style="display:flex; gap:24px; flex-wrap:wrap">
        <div style="text-align:center">
          <div style="font-size:22px; font-weight:800; color:{th['text_h']}">{len(results)}</div>
          <div style="font-size:10px; color:{th['text_muted']}; text-transform:uppercase; letter-spacing:0.05em">
            {t('markets_analyzed')}
          </div>
        </div>
        <div style="text-align:center">
          <div style="font-size:22px; font-weight:800; color:{th['warning'] if alerts else th['text_muted']}">{len(alerts)}</div>
          <div style="font-size:10px; color:{th['text_muted']}; text-transform:uppercase; letter-spacing:0.05em">
            {t('alerts_found')}
          </div>
        </div>
        <div style="text-align:center">
          <div style="font-size:22px; font-weight:800; color:{th['positive'] if best_edge > 0 else th['text_muted']}">{best_edge*100:+.1f}%</div>
          <div style="font-size:10px; color:{th['text_muted']}; text-transform:uppercase; letter-spacing:0.05em">
            {t('best_edge')}
          </div>
        </div>
        <div style="text-align:center">
          <div style="font-size:22px; font-weight:800; color:{th['positive'] if best_ev > 0 else th['text_muted']}">${best_ev:+.3f}</div>
          <div style="font-size:10px; color:{th['text_muted']}; text-transform:uppercase; letter-spacing:0.05em">
            {t('best_ev')}
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─── Sidebar ──────────────────────────────────────────────────────────────────

def _sb_section(label: str, th: dict) -> None:
    """Render a sidebar section header."""
    st.markdown(
        f"<div style='font-size:10px; color:{th['sb_text_muted']}; text-transform:uppercase; "
        f"letter-spacing:0.1em; font-weight:700; margin:18px 0 8px;'>"
        f"{label}</div>",
        unsafe_allow_html=True,
    )


def render_sidebar(th: dict):
    with st.sidebar:
        # ── Logo ────────────────────────────────────────────────────────────
        st.markdown(f"""
        <div style="padding:16px 0 12px; text-align:center;
                    border-bottom:1px solid {th['sidebar_border']}; margin-bottom:12px">
          <div style="font-size:26px; font-weight:900; letter-spacing:-0.5px;
                      color:{th['sb_text']};">
            🌡 polyMad
          </div>
          <div style="font-size:11px; color:{th['sb_text_muted']}; margin-top:3px; font-weight:500;">
            {t('app_subtitle')}
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Language + Theme ─────────────────────────────────────────────────
        col_lang, col_theme = st.columns([4, 1])
        with col_lang:
            lang_label = st.selectbox(
                t("language"),
                options=list(LANGUAGE_OPTIONS.keys()),
                index=list(LANGUAGE_OPTIONS.values()).index(st.session_state.get("lang", "en")),
                label_visibility="collapsed",
            )
            st.session_state["lang"] = LANGUAGE_OPTIONS[lang_label]
        with col_theme:
            is_dark = st.session_state.get("theme", "light") == "dark"
            if st.button("🌙" if not is_dark else "☀️", use_container_width=True,
                         help="Alternar tema / Toggle theme"):
                st.session_state["theme"] = "light" if is_dark else "dark"
                st.rerun()

        # ── Run button (top, prominent) ──────────────────────────────────────
        st.markdown("<div style='margin-top:10px'>", unsafe_allow_html=True)
        run_btn = st.button(t("run_analysis"), type="primary", use_container_width=True)
        if "last_run" in st.session_state:
            st.markdown(
                f"<div style='text-align:center; color:{th['sb_text_muted']}; font-size:11px; margin-top:4px;'>"
                f"⏱ {t('last_run')}: {st.session_state['last_run']}</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

        # ── Analysis settings ────────────────────────────────────────────────
        _sb_section(t("sidebar_analysis"), th)

        bankroll = st.number_input(
            t("bankroll"), min_value=10.0, max_value=1_000_000.0,
            value=1000.0, step=100.0, format="%.0f",
            help=t("help_bankroll"),
        )
        edge_threshold = st.slider(
            t("edge_threshold"), min_value=1, max_value=30, value=5, step=1,
            help=t("help_edge"),
        ) / 100.0
        _mem = t("members")
        model = st.selectbox(
            t("model"),
            options=["ecmwf_ifs025", "gfs025"],
            format_func=lambda x: f"ECMWF IFS 0.25° (51 {_mem})" if x == "ecmwf_ifs025" else f"GFS 0.25° (31 {_mem})",
            help=t("help_model"),
        )

        # ── Data settings ────────────────────────────────────────────────────
        _sb_section(t("sidebar_data"), th)

        max_markets = int(st.number_input(
            t("max_markets"), min_value=5, max_value=500, value=50, step=10,
            help=t("help_max_markets"),
        ))
        cities_filter = st.multiselect(
            t("filter_cities"),
            options=sorted(settings.CITY_COORDINATES.keys()),
            default=[],
            placeholder="Todas / All",
            help=t("help_cities"),
        )

        # ── Display settings ─────────────────────────────────────────────────
        _sb_section(t("sidebar_display"), th)

        auto_refresh = st.toggle(t("auto_refresh"), value=False, help=t("help_autorefresh"))
        if auto_refresh:
            refresh_interval = int(st.number_input(
                t("refresh_interval"), min_value=1, max_value=60, value=5, step=1,
            ))
            inject_autorefresh_js(refresh_interval, th)

        # ── Notifications ────────────────────────────────────────────────────
        _sb_section(t("sidebar_notifications"), th)
        notify_enabled = st.toggle(t("notify_enable"), value=False, help=t("help_notify"))
        notify_email = ""
        if notify_enabled:
            notify_email = st.text_input(
                t("notify_email"),
                placeholder="seu@email.com",
                label_visibility="collapsed",
            )

        # ── Wallet ───────────────────────────────────────────────────────────
        _sb_section(f"🦊 {t('wallet')}", th)
        wallet_address = render_wallet_sidebar(t)

    return bankroll, edge_threshold, model, max_markets, cities_filter, run_btn, wallet_address, notify_enabled, notify_email


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"
    if "theme" not in st.session_state:
        st.session_state["theme"] = "light"

    th = get_theme()
    inject_css(th)

    bankroll, edge_threshold, model, max_markets, cities_filter, run_btn, wallet_address, notify_enabled, notify_email = render_sidebar(th)

    # ── Category bar ─────────────────────────────────────────────────────────
    render_category_bar(th)

    # ── Run / load state ────────────────────────────────────────────────────
    if run_btn or "results" not in st.session_state:
        results, skipped, debug_info = run_analysis(
            bankroll=bankroll, edge_threshold=edge_threshold,
            model=model, max_markets=max_markets, cities_filter=cities_filter,
        )
        st.session_state.update({
            "results": results, "skipped": skipped, "debug_info": debug_info,
            "bankroll": bankroll, "edge_threshold": edge_threshold,
            "last_run": datetime.now(tz=timezone.utc).strftime("%H:%M UTC"),
        })

        # ── E-mail notifications ─────────────────────────────────────────────
        if run_btn and notify_enabled and notify_email and "@" in notify_email:
            email_alerts = [r for r in results if r.alert]
            if email_alerts:
                try:
                    secrets = st.secrets
                    lang = st.session_state.get("lang", "en")
                    ok, err = send_alert_email(
                        alerts=email_alerts,
                        recipient=notify_email,
                        smtp_user=secrets["SMTP_USER"],
                        smtp_password=secrets["SMTP_PASSWORD"],
                        smtp_from=secrets["SMTP_FROM"],
                        edge_threshold=edge_threshold,
                        bankroll=bankroll,
                        lang=lang,
                    )
                    if ok:
                        st.toast(t("notify_sent"), icon="✉️")
                    else:
                        st.toast(t("notify_error"), icon="⚠️")
                except Exception:
                    st.toast(t("notify_no_secrets"), icon="⚙️")

    results = st.session_state.get("results", [])
    bankroll_used = st.session_state.get("bankroll", bankroll)
    threshold_used = st.session_state.get("edge_threshold", edge_threshold)
    skipped = st.session_state.get("skipped", [])
    debug_info = st.session_state.get("debug_info", {})

    render_header(th, results, threshold_used)

    if not results:
        st.info(t("run_first"))
        if debug_info.get("raw_tuples", -1) == 0 or debug_info.get("parsed", -1) == 0:
            with st.expander(f"⚙ {t('diag_title')}"):
                col_a, col_b, col_c = st.columns(3)
                col_a.metric(t("diag_raw_markets"), debug_info.get("raw_tuples", "–"))
                col_b.metric(t("diag_parsed"), debug_info.get("parsed", "–"))
                col_c.metric("API Error", "✓" if not debug_info.get("api_error") else "✗")
                st.caption(t("diag_tip"))
                if debug_info.get("api_error"):
                    st.error(debug_info["api_error"])
        return

    if skipped:
        with st.expander(f"⚠ {len(skipped)} {t('forecast_errors')}"):
            for s in skipped[:15]:
                st.caption(f"· {s}")

    alerts = [r for r in results if r.alert]
    ranked = edge_calculator.rank_opportunities(results, by="expected_value")

    # ── Tabs ─────────────────────────────────────────────────────────────────
    now_utc = datetime.now(tz=timezone.utc)
    today_date = now_utc.date()
    week_end = today_date + timedelta(days=7)

    tab_alerts, tab_today, tab_week, tab_all, tab_wallet = st.tabs([
        t("tab_alerts"), t("tab_today"), t("tab_week"), t("tab_all"), t("tab_wallet"),
    ])

    # ── Tab: Alerts ───────────────────────────────────────────────────────────
    with tab_alerts:
        if alerts:
            st.markdown(
                f"<p style='color:{th['text_muted']}; font-size:13px; margin-bottom:16px'>"
                f"{len(alerts)} {t('alerts_found')} — {t('edge_threshold')}: >{threshold_used*100:.0f}%</p>",
                unsafe_allow_html=True,
            )
            for i in range(0, len(alerts), 2):
                row = alerts[i:i+2]
                cols = st.columns(len(row))
                for col, result in zip(cols, row):
                    with col:
                        render_alert_card(result, bankroll_used, th)
        else:
            st.info(t("no_alerts"))

        if results:
            st.markdown(f"<div style='height:1px; background:{th['divider']}; margin:20px 0'></div>",
                        unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:13px; font-weight:600; color:{th['text_h']}; margin-bottom:8px'>{t('edge_vs_ev')}</div>",
                        unsafe_allow_html=True)
            st.plotly_chart(
                make_edge_scatter(results, threshold_used, th),
                use_container_width=True, config={"displayModeBar": False},
            )

    # ── Tab: Today ────────────────────────────────────────────────────────────
    with tab_today:
        today_results = [r for r in results if r.market.resolution_date.date() == today_date]
        if today_results:
            today_alerts = [r for r in today_results if r.alert]
            st.markdown(f"<p style='color:{th['text_muted']}; font-size:13px'>{len(today_results)} {t('markets_label')} · {len(today_alerts)} {t('alerts_found')}</p>",
                        unsafe_allow_html=True)
            render_full_table(today_results, bankroll_used, th)
            for r in today_alerts:
                render_alert_card(r, bankroll_used, th)
        else:
            st.info(t("no_markets_today"))

    # ── Tab: This Week ────────────────────────────────────────────────────────
    with tab_week:
        week_results = [
            r for r in results
            if today_date <= r.market.resolution_date.date() <= week_end
        ]
        if week_results:
            week_alerts = [r for r in week_results if r.alert]
            st.markdown(f"<p style='color:{th['text_muted']}; font-size:13px'>{len(week_results)} {t('markets_label')} · {len(week_alerts)} {t('alerts_found')}</p>",
                        unsafe_allow_html=True)
            render_full_table(week_results, bankroll_used, th)
        else:
            st.info(t("no_markets_week"))

    # ── Tab: All Markets ──────────────────────────────────────────────────────
    with tab_all:
        st.markdown(f"<p style='color:{th['text_muted']}; font-size:13px'>{len(results)} {t('markets_total')}</p>",
                    unsafe_allow_html=True)
        sub1, sub2 = st.tabs([f"✅ +EV ({len(ranked)})", f"📋 {t('tab_all').split()[-1]} ({len(results)})"])
        with sub1:
            if ranked:
                render_full_table(ranked, bankroll_used, th)
            else:
                st.info(t("no_positive_ev"))
        with sub2:
            render_full_table(
                sorted(results, key=lambda r: r.expected_value, reverse=True),
                bankroll_used, th,
            )

    # ── Tab: Wallet ───────────────────────────────────────────────────────────
    with tab_wallet:
        render_wallet_tab(t, wallet_address, results, bankroll_used)


if __name__ == "__main__":
    main()
