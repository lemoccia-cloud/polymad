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
from src.data.polymarket_client import (
    PolymarketClient, parse_weather_market,
    parse_crypto_market, parse_sports_market, parse_politics_market,
    PolymarketAPIError,
)
from src.data.crypto_client import CryptoClient, CryptoAPIError
from src.data.sports_client import SportsClient
from src.data.politics_client import PoliticsClient
from src.data.weather_client import WeatherClient, CityNotFoundError, WeatherAPIError
from src.analysis import edge_calculator
from src.analysis.kelly import compute_position_size, kelly_summary
from src.models.market import WeatherForecast, OpportunityResult
from src.components.wallet import render_wallet_sidebar, render_wallet_tab, process_auth_flow
from src.components.filters import render_filter_bar
from src.notifications import send_alert_email
from src.data.supabase_client import (
    save_scan, get_scan_history, build_alerts_summary,
    save_prediction, get_unresolved_predictions, mark_resolved, get_backtesting_data,
    save_alert_history,
)

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

@st.cache_resource
def _get_politics_client():
    """Singleton PoliticsClient — preserves in-memory query cache across reruns."""
    return PoliticsClient()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_markets_cached(min_liquidity: float, max_days: int) -> list:
    return PolymarketClient().fetch_weather_markets(min_liquidity=min_liquidity, max_days=max_days)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_crypto_markets_cached(max_days: int) -> list:
    return PolymarketClient().fetch_crypto_markets(max_days=max_days)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_sports_markets_cached(max_days: int) -> list:
    return PolymarketClient().fetch_sports_markets(max_days=max_days)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_politics_markets_cached(max_days: int) -> list:
    return PolymarketClient().fetch_politics_markets(max_days=max_days)


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

def _persist_prediction(result, supa_url: str, supa_key: str) -> None:
    """Save one OpportunityResult to market_outcomes (best-effort, never raises)."""
    if not supa_url or not supa_key:
        return
    try:
        m = result.market
        save_prediction(
            supabase_url=supa_url,
            anon_key=supa_key,
            market_id=getattr(m, "market_id", "") or getattr(m, "condition_id", ""),
            condition_id=getattr(m, "condition_id", ""),
            question=getattr(m, "question", "")[:200],
            market_type=getattr(m, "market_type", "weather"),
            model_prob=result.forecast.model_probability,
            market_prob=m.market_implied_prob,
            edge=result.edge,
            resolution_date=getattr(m, "resolution_date", None),
        )
    except Exception:
        pass


def run_analysis(bankroll, edge_threshold, model, max_markets, cities_filter):
    debug_info = {"raw_tuples": 0, "parsed": 0, "api_error": ""}
    try:
        supa_url = st.secrets.get("SUPABASE_URL", "")
        supa_key = st.secrets.get("SUPABASE_ANON_KEY", "")
    except Exception:
        supa_url = supa_key = ""

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
    debug_info["parsed_crypto"] = 0
    debug_info["parsed_sports"] = 0
    debug_info["parsed_politics"] = 0

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
        _persist_prediction(result, supa_url, supa_key)

    prog.empty()

    # ── Crypto pipeline ───────────────────────────────────────────────────────
    try:
        raw_crypto = fetch_crypto_markets_cached(max_days=settings.MAX_DAYS_TO_EXPIRY)
    except PolymarketAPIError:
        raw_crypto = []

    if raw_crypto:
        crypto_client = CryptoClient()
        crypto_prog = st.progress(0, text="📈 Crypto…")
        parsed_crypto = []
        for tup in raw_crypto[:max_markets]:
            raw_mkt, event_title, event_end = tup[0], tup[1], tup[2]
            event_slug = tup[3] if len(tup) > 3 else ""
            mkt = parse_crypto_market(
                raw_mkt, event_title=event_title,
                end_date_str=event_end, event_slug=event_slug,
            )
            if mkt is not None:
                parsed_crypto.append(mkt)

        for i, mkt in enumerate(parsed_crypto):
            crypto_prog.progress((i + 1) / max(len(parsed_crypto), 1), text=f"📈 {mkt.asset}")
            try:
                forecast = crypto_client.get_lognormal_forecast(
                    asset=mkt.asset,
                    resolution_date=mkt.resolution_date,
                    threshold_usd=mkt.threshold_usd,
                    direction=mkt.direction,
                )
            except (CryptoAPIError, ValueError):
                skipped.append(f"{mkt.asset}: forecast error")
                continue
            result = edge_calculator.analyze_market(mkt, forecast)
            result.alert = result.edge > edge_threshold
            results.append(result)
            _persist_prediction(result, supa_url, supa_key)

        debug_info["parsed_crypto"] = len(parsed_crypto)
        crypto_prog.empty()

    # ── Sports pipeline ───────────────────────────────────────────────────────
    try:
        raw_sports = fetch_sports_markets_cached(max_days=settings.MAX_DAYS_TO_EXPIRY)
    except PolymarketAPIError:
        raw_sports = []

    if raw_sports:
        sports_client = SportsClient()
        sports_prog = st.progress(0, text="⚽ Sports…")
        parsed_sports = []
        for tup in raw_sports[:max_markets]:
            raw_mkt, event_title, event_end = tup[0], tup[1], tup[2]
            event_slug = tup[3] if len(tup) > 3 else ""
            mkt = parse_sports_market(
                raw_mkt, event_title=event_title,
                end_date_str=event_end, event_slug=event_slug,
            )
            if mkt is not None:
                parsed_sports.append(mkt)

        for i, mkt in enumerate(parsed_sports):
            sports_prog.progress((i + 1) / max(len(parsed_sports), 1),
                                  text=f"⚽ {mkt.home_team} vs {mkt.away_team}")
            forecast = sports_client.get_outcome_forecast(
                home_team=mkt.home_team,
                away_team=mkt.away_team,
                sport=mkt.sport,
                outcome=mkt.outcome,
                resolution_date=mkt.resolution_date,
            )
            result = edge_calculator.analyze_market(mkt, forecast)
            result.alert = result.edge > edge_threshold
            results.append(result)
            _persist_prediction(result, supa_url, supa_key)

        debug_info["parsed_sports"] = len(parsed_sports)
        sports_prog.empty()

    # ── Politics pipeline ─────────────────────────────────────────────────────
    try:
        raw_politics = fetch_politics_markets_cached(max_days=settings.MAX_DAYS_TO_EXPIRY)
    except PolymarketAPIError:
        raw_politics = []

    if raw_politics:
        politics_client = _get_politics_client()
        pol_prog = st.progress(0, text="🗳 Politics…")
        parsed_politics = []
        for tup in raw_politics[:max_markets]:
            raw_mkt, event_title, event_end = tup[0], tup[1], tup[2]
            event_slug = tup[3] if len(tup) > 3 else ""
            mkt = parse_politics_market(
                raw_mkt, event_title=event_title,
                end_date_str=event_end, event_slug=event_slug,
            )
            if mkt is not None:
                parsed_politics.append(mkt)

        for i, mkt in enumerate(parsed_politics):
            pol_prog.progress((i + 1) / max(len(parsed_politics), 1),
                               text=f"🗳 {mkt.topic[:50]}")
            forecast = politics_client.get_metaculus_forecast(
                topic=mkt.topic,
                resolution_date=mkt.resolution_date,
            )
            result = edge_calculator.analyze_market(mkt, forecast)
            result.alert = result.edge > edge_threshold
            results.append(result)
            _persist_prediction(result, supa_url, supa_key)

        debug_info["parsed_politics"] = len(parsed_politics)
        pol_prog.empty()

    debug_info["parsed"] = (
        debug_info["parsed"]
        + debug_info["parsed_crypto"]
        + debug_info["parsed_sports"]
        + debug_info["parsed_politics"]
    )
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
    def _scatter_label(m) -> str:
        mtype = getattr(m, "market_type", "weather")
        if mtype == "crypto":
            d = "≥" if getattr(m, "direction", "") == "above" else "≤"
            return f"{getattr(m, 'asset', '')} {d}${getattr(m, 'threshold_usd', 0):,.0f}"
        if mtype == "sports":
            return f"{getattr(m, 'home_team', '')} v {getattr(m, 'away_team', '')}"
        if mtype == "politics":
            return getattr(m, "topic", "")[:30]
        return f"{getattr(m, 'city', '')} {getattr(m, 'threshold_celsius', 0):.0f}°C"
    labels = [_scatter_label(r.market) for r in results]
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

def _prob_bar(pct: float, color: str, bg: str) -> str:
    """Inline HTML horizontal progress bar — no Plotly iframe needed."""
    w = max(2, min(100, round(pct)))
    return (
        f"<div style='flex:1; background:{bg}; border-radius:4px; height:8px; overflow:hidden;'>"
        f"<div style='width:{w}%; background:{color}; height:8px; border-radius:4px;"
        f" transition:width .3s ease;'></div></div>"
    )


def _kpi_cell(label: str, value: str, value_color: str, th: dict, border_left: str = "transparent") -> str:
    """One KPI cell in the metrics strip."""
    return (
        f"<div style='flex:1; padding:10px 14px; border-left:1px solid {th['card_border']};"
        f" min-width:80px;'>"
        f"<div style='font-size:10px; font-weight:700; color:{th['text_muted']};"
        f" text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px;'>{label}</div>"
        f"<div style='font-size:15px; font-weight:800; color:{value_color};"
        f" white-space:nowrap;'>{value}</div>"
        f"</div>"
    )


def render_alert_card(result: OpportunityResult, bankroll: float, th: dict) -> None:
    m, f = result.market, result.forecast
    edge_pct    = result.edge * 100
    bet_usd     = compute_position_size(bankroll, result.kelly_fraction)
    ks          = kelly_summary(result.kelly_fraction, bankroll)
    lang        = st.session_state.get("lang", "en")
    mtype       = getattr(m, "market_type", "weather")
    mkt_pct     = m.market_implied_prob * 100
    mdl_pct     = f.model_probability * 100
    gross_payout = bet_usd / m.market_implied_prob if m.market_implied_prob > 0 else 0
    net_if_win  = gross_payout - bet_usd
    ev_dollars  = bet_usd * result.expected_value
    return_pct  = (1 / m.market_implied_prob - 1) * 100 if m.market_implied_prob > 0 else 0

    poly_url = (
        f"https://polymarket.com/event/{m.event_slug}" if getattr(m, "event_slug", "")
        else "https://polymarket.com/markets"
    )

    # ── Type dispatch ─────────────────────────────────────────────────────────
    _TYPE_META = {
        "crypto":   ("₿",  "#f59e0b", "CRYPTO"),
        "sports":   ("⚽", "#10b981", "SPORTS"),
        "politics": ("🗳", "#8b5cf6", "POLITICS"),
        "weather":  ("🌡", "#3b82f6", "WEATHER"),
    }
    badge_icon, badge_color, badge_label = _TYPE_META.get(mtype, ("📊", th["accent"], mtype.upper()))

    if mtype == "crypto":
        title_text  = m.asset
        detail_text = f"{'≥' if m.direction=='above' else '≤'} ${m.threshold_usd:,.0f}"
        footer_parts = [
            f"{t('card_spot')}: ${getattr(f,'spot_price',0):,.0f}",
            f"{t('card_vol_annual')}: {getattr(f,'sigma_annual',0)*100:.0f}%",
            f"{t('card_days_expiry')}: {getattr(f,'days_to_expiry','—')}d",
            f"{t('liquidity')}: {_usd(m.liquidity_usd)}",
        ]
    elif mtype == "sports":
        title_text  = m.home_team
        detail_text = f"vs {m.away_team}"
        src = getattr(f, "source", "—").replace("_", " ").title()
        footer_parts = [
            f"{t('card_elo_home')}: {getattr(f,'elo_home',0):.0f}",
            f"{t('card_elo_away')}: {getattr(f,'elo_away',0):.0f}",
            f"{t('card_source')}: {src}",
            f"{t('liquidity')}: {_usd(m.liquidity_usd)}",
        ]
    elif mtype == "politics":
        title_text  = m.topic[:44]
        detail_text = ""
        src = getattr(f, "source", "—").replace("_", " ").title()
        met_ref = getattr(f, "metaculus_title", "") or (f"#{getattr(f,'metaculus_id','—')}" if getattr(f,"metaculus_id",None) else "baseline")
        footer_parts = [
            f"{t('card_source')}: {src}",
            f"ref: {met_ref[:32]}",
            f"{t('liquidity')}: {_usd(m.liquidity_usd)}",
        ]
    else:  # weather
        bucket_sym  = {"above": "≥", "below": "≤", "exact": "="}
        title_text  = m.city
        detail_text = f"{bucket_sym.get(m.bucket_type,'')} {m.threshold_celsius:.0f}°C"
        footer_parts = [
            f"{t('card_forecast_model')}: {getattr(f,'forecast_model','—')}",
            f"{t('members')}: {getattr(f,'ensemble_member_count','—')}",
            f"{t('liquidity')}: {_usd(m.liquidity_usd)}",
            f"{t('resolution')}: {m.end_date.strftime('%b %d %H:%MZ')}",
        ]

    footer_html = "  ·  ".join(footer_parts)

    # ── Edge tier → border accent ─────────────────────────────────────────────
    if edge_pct > 20:
        accent_border = th["positive"]
        ev_color      = th["positive"]
    elif edge_pct > 10:
        accent_border = th["warning"]
        ev_color      = th["warning"]
    else:
        accent_border = th["accent"]
        ev_color      = th["accent"]

    edge_color = th["positive"] if result.edge > 0 else th["negative"]

    # ── Probability bars ──────────────────────────────────────────────────────
    bar_bg     = th["bg"]
    bar_market = th["accent"]
    bar_model  = th["positive"] if result.edge > 0 else th["negative"]
    prob_row = (
        f"<div style='display:flex; align-items:center; gap:8px; margin:12px 0;'>"
        f"<span style='font-size:11px; color:{th['text_muted']}; white-space:nowrap; min-width:52px;'>{t('market_prob')}</span>"
        f"{_prob_bar(mkt_pct, bar_market, bar_bg)}"
        f"<span style='font-size:12px; font-weight:700; color:{th['text_b']}; min-width:36px; text-align:right;'>{mkt_pct:.1f}%</span>"
        f"<span style='font-size:11px; color:{th['text_muted']}; padding:0 4px;'>vs</span>"
        f"<span style='font-size:11px; color:{th['text_muted']}; white-space:nowrap; min-width:44px;'>{t('model_prob')}</span>"
        f"{_prob_bar(mdl_pct, bar_model, bar_bg)}"
        f"<span style='font-size:12px; font-weight:700; color:{bar_model}; min-width:36px; text-align:right;'>{mdl_pct:.1f}%</span>"
        f"</div>"
    )

    # ── KPI strip ─────────────────────────────────────────────────────────────
    kpi_strip = (
        f"<div style='display:flex; border-top:1px solid {th['card_border']};"
        f" border-bottom:1px solid {th['card_border']}; margin:0 -18px; overflow:hidden;'>"
        + _kpi_cell(t("edge"),            f"{edge_pct:+.1f}%",          edge_color,    th)
        + _kpi_cell(t("ev_per_dollar"),   f"{result.expected_value:+.3f}", ev_color,   th)
        + _kpi_cell(t("kelly_bet"),       _usd(bet_usd),                th["positive"], th)
        + _kpi_cell(t("return_if_win"),   f"+{_usd(net_if_win)}",       th["positive"], th)
        + _kpi_cell(t("return_pct"),      f"+{return_pct:.1f}%",        th["text_h"],  th)
        + f"</div>"
    )

    # ── Full card (single st.markdown call) ───────────────────────────────────
    st.markdown(f"""
    <div style="
        background:{th['card']}; border:1px solid {th['card_border']};
        border-left:4px solid {accent_border};
        border-radius:14px; padding:16px 18px 12px;
        margin-bottom:16px; overflow:hidden;
    ">
      <!-- Row 1: type badge · title · detail · date · trade button -->
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px; flex-wrap:wrap;">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; flex:1; min-width:0;">
          <span style="font-size:10px; font-weight:700; padding:2px 8px; border-radius:20px;
                       background:{badge_color}22; color:{badge_color};
                       border:1px solid {badge_color}44; white-space:nowrap; flex-shrink:0;">
            {badge_icon} {badge_label}
          </span>
          <span style="font-size:18px; font-weight:800; color:{th['text_h']};
                       white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {title_text}
          </span>
          {"<span style='font-size:13px; font-weight:600; color:" + th['text_b'] + "; white-space:nowrap;'>" + detail_text + "</span>" if detail_text else ""}
          <span style="font-size:11px; color:{th['text_muted']}; background:{th['bg']};
                       padding:2px 8px; border-radius:6px; border:1px solid {th['card_border']};
                       white-space:nowrap; flex-shrink:0;">
            {format_date(m.resolution_date, lang)}
          </span>
        </div>
        <a href="{poly_url}" target="_blank" style="
            font-size:11px; font-weight:700; color:{badge_color};
            background:{badge_color}15; border:1px solid {badge_color}44;
            padding:4px 12px; border-radius:20px; text-decoration:none;
            white-space:nowrap; flex-shrink:0;">
          {t('trade_on_polymarket')} ↗
        </a>
      </div>

      <!-- Row 2: question text -->
      <div style="font-size:12px; color:{th['text_muted']}; line-height:1.5;
                  margin-top:8px; padding-left:4px;
                  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
                  overflow:hidden;">
        {m.question}
      </div>

      <!-- Row 3: probability bars -->
      {prob_row}

      <!-- Row 4: KPI strip -->
      {kpi_strip}

      <!-- Row 5: model footer -->
      <div style="font-size:11px; color:{th['text_muted']}; margin-top:10px;
                  padding-top:8px; border-top:1px solid {th['card_border']}; line-height:1.6;">
        {footer_html}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Ensemble expander — weather only, unchanged ───────────────────────────
    if mtype == "weather":
        with st.expander(f"📊 {t('ensemble_dist')} — {getattr(m, 'city', '')} {format_date(m.resolution_date, lang)}"):
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
        mtype = getattr(m, "market_type", "weather")
        bet = compute_position_size(bankroll, r.kelly_fraction)
        ret_pct = (1 / m.market_implied_prob - 1) * 100 if m.market_implied_prob > 0 else 0
        net_win  = bet * ret_pct / 100

        if mtype == "crypto":
            label = f"{m.asset} {'≥' if m.direction=='above' else '≤'} ${m.threshold_usd:,.0f}"
            members_val = "—"
        elif mtype == "sports":
            label = f"{m.home_team} vs {m.away_team}"
            members_val = "—"
        elif mtype == "politics":
            label = m.topic[:40]
            members_val = "—"
        else:  # weather
            label = f"{m.city} {bucket_label.get(m.bucket_type,'')}{m.threshold_celsius:.0f}°C"
            members_val = str(getattr(f, "ensemble_member_count", "—"))

        rows.append({
            "": "🚨" if r.alert else "·",
            t("city"): label,
            t("date"): format_date(m.resolution_date, lang),
            t("threshold"): mtype.upper(),
            t("mkt_pct"): round(m.market_implied_prob * 100, 1),
            t("model_pct"): round(f.model_probability * 100, 1),
            t("edge_pct"): round(r.edge * 100, 1),
            t("ev_per_dollar"): round(r.expected_value, 3),
            t("bet_size"): round(bet, 0),
            t("return_pct"): round(ret_pct, 1),
            t("return_if_win"): round(net_win, 2),
            t("kelly_fraction"): round(r.suggested_bet_fraction * 100, 1),
            t("members"): members_val,
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

    styled = df.style.map(color_edge, subset=[edge_col])
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
    Horizontal category selector using st.radio.
    Returns the selected category key ('all', 'weather', 'crypto', 'sports', 'politics').
    """
    cats_keys   = ["all", "weather", "crypto", "sports", "politics"]
    cats_labels = [t(f"cat_{k}") for k in cats_keys]

    if "category" not in st.session_state:
        st.session_state["category"] = "all"

    current = st.session_state.get("category", "all")
    try:
        idx = cats_keys.index(current)
    except ValueError:
        idx = 0

    st.markdown(
        f"<div style='padding:6px 0 2px; border-bottom:1px solid {th['card_border']};"
        f" margin-bottom:20px;'></div>",
        unsafe_allow_html=True,
    )
    chosen_label = st.radio(
        label=t("cat_all"),
        options=cats_labels,
        index=idx,
        horizontal=True,
        key="category_radio",
        label_visibility="collapsed",
    )
    selected = cats_keys[cats_labels.index(chosen_label)]
    st.session_state["category"] = selected
    return selected


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


# ─── Backtesting helpers ──────────────────────────────────────────────────────

def _compute_calibration(data: list) -> tuple:
    """
    Given a list of dicts {model_prob, resolved_yes}, return:
      (bucket_mids, actual_rates, bucket_counts)
    using 10-percentage-point buckets [0,10), [10,20) … [90,100].
    """
    buckets: dict = {i: {"total": 0, "yes": 0} for i in range(10)}
    for row in data:
        p = float(row.get("model_prob") or 0)
        outcome = row.get("resolved_yes")
        if outcome is None:
            continue
        bucket = min(int(p * 10), 9)
        buckets[bucket]["total"] += 1
        if outcome:
            buckets[bucket]["yes"] += 1

    mids, rates, counts = [], [], []
    for i in range(10):
        n = buckets[i]["total"]
        if n == 0:
            continue
        mids.append(i * 10 + 5)
        rates.append(buckets[i]["yes"] / n * 100)
        counts.append(n)
    return mids, rates, counts


def _brier_score(data: list) -> float:
    total, s = 0, 0.0
    for row in data:
        p = float(row.get("model_prob") or 0)
        outcome = row.get("resolved_yes")
        if outcome is None:
            continue
        s += (p - (1.0 if outcome else 0.0)) ** 2
        total += 1
    return round(s / total, 4) if total else 0.0


def _accuracy(data: list) -> float:
    total, correct = 0, 0
    for row in data:
        p = float(row.get("model_prob") or 0)
        outcome = row.get("resolved_yes")
        if outcome is None:
            continue
        predicted_yes = p >= 0.5
        if predicted_yes == bool(outcome):
            correct += 1
        total += 1
    return round(correct / total, 4) if total else 0.0


def make_calibration_chart(data: list, th: dict) -> go.Figure:
    mids, rates, counts = _compute_calibration(data)
    fig = go.Figure()
    # perfect calibration diagonal
    fig.add_trace(go.Scatter(
        x=[0, 100], y=[0, 100],
        mode="lines",
        line=dict(color=th["text_muted"], dash="dash", width=1),
        name=t("backtest_calibration_ideal"),
    ))
    # actual calibration points
    fig.add_trace(go.Scatter(
        x=mids, y=rates,
        mode="lines+markers",
        marker=dict(size=[max(6, min(20, c // 2 + 6)) for c in counts],
                    color=th["accent"], line=dict(color="white", width=1)),
        line=dict(color=th["accent"], width=2),
        name=t("model_prob"),
        text=[f"n={c}" for c in counts],
        hovertemplate="%{x:.0f}% model → %{y:.1f}% actual (%{text})<extra></extra>",
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=24, b=0),
        paper_bgcolor=th["plot_paper"], plot_bgcolor=th["plot_bg"],
        xaxis=dict(title=t("backtest_calibration_x"), range=[0, 100],
                   color=th["plot_text"], gridcolor=th["plot_grid"]),
        yaxis=dict(title=t("backtest_calibration_y"), range=[0, 100],
                   color=th["plot_text"], gridcolor=th["plot_grid"]),
        legend=dict(font=dict(color=th["plot_text"], size=11)),
        font=dict(color=th["plot_text"]),
    )
    return fig


def make_accuracy_by_type_chart(data: list, th: dict) -> go.Figure:
    from collections import defaultdict
    counts: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    for row in data:
        mtype = row.get("market_type", "weather")
        p = float(row.get("model_prob") or 0)
        outcome = row.get("resolved_yes")
        if outcome is None:
            continue
        counts[mtype]["total"] += 1
        if (p >= 0.5) == bool(outcome):
            counts[mtype]["correct"] += 1

    types, accs, ns = [], [], []
    for mtype, v in sorted(counts.items()):
        if v["total"] == 0:
            continue
        types.append(mtype.capitalize())
        accs.append(round(v["correct"] / v["total"] * 100, 1))
        ns.append(v["total"])

    fig = go.Figure(go.Bar(
        x=types, y=accs,
        text=[f"{a}% (n={n})" for a, n in zip(accs, ns)],
        textposition="outside",
        marker_color=th["accent"],
    ))
    fig.add_hline(y=50, line_dash="dash", line_color=th["text_muted"],
                  annotation_text="50% baseline", annotation_font_color=th["text_muted"])
    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=24, b=0),
        paper_bgcolor=th["plot_paper"], plot_bgcolor=th["plot_bg"],
        yaxis=dict(range=[0, 110], color=th["plot_text"], gridcolor=th["plot_grid"]),
        xaxis=dict(color=th["plot_text"]),
        font=dict(color=th["plot_text"]),
        showlegend=False,
    )
    return fig


def check_and_update_resolutions(poly_client, supa_url: str, supa_key: str) -> int:
    """
    Fetch unresolved predictions from Supabase, check each against Polymarket CLOB,
    and mark resolved ones. Returns the count of newly resolved predictions.
    """
    if not supa_url or not supa_key:
        return 0
    unresolved = get_unresolved_predictions(supa_url, supa_key, limit=50)
    updated = 0
    for row in unresolved:
        cid = row.get("condition_id", "")
        if not cid:
            continue
        outcome = poly_client.fetch_market_outcome(cid)
        if outcome is not None:
            mark_resolved(supa_url, supa_key, row["id"], outcome)
            updated += 1
    return updated


def render_backtesting_tab(th: dict, poly_client) -> None:
    """Render the Backtesting tab: calibration curve + Brier score + resolved table."""
    try:
        supa_url = st.secrets.get("SUPABASE_URL", "")
        supa_key = st.secrets.get("SUPABASE_ANON_KEY", "")
    except Exception:
        supa_url = supa_key = ""

    if not supa_url or not supa_key:
        st.info(t("backtest_no_supabase"))
        return

    # ── Check for newly resolved markets ─────────────────────────────────────
    with st.spinner(t("backtest_checking")):
        updated = check_and_update_resolutions(poly_client, supa_url, supa_key)
    if updated:
        st.toast(f"🎯 {updated} {t('backtest_updated')}", icon="🎯")

    # ── Load resolved data ────────────────────────────────────────────────────
    data = get_backtesting_data(supa_url, supa_key, limit=500)
    resolved = [r for r in data if r.get("resolved_yes") is not None]

    if not resolved:
        st.info(t("backtest_no_data"))
        return

    # ── Top metrics ──────────────────────────────────────────────────────────
    brier  = _brier_score(resolved)
    acc    = _accuracy(resolved)
    col1, col2, col3 = st.columns(3)
    col1.metric(t("backtest_total"), len(resolved))
    col2.metric(
        t("backtest_brier"),
        f"{brier:.4f}",
        help=t("backtest_brier_help"),
    )
    col3.metric(
        t("backtest_accuracy"),
        f"{acc*100:.1f}%",
        help=t("backtest_accuracy_help"),
    )

    st.markdown(f"<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    ch_cal, ch_type = st.columns([3, 2])
    with ch_cal:
        st.markdown(f"**{t('backtest_title')}**")
        st.plotly_chart(
            make_calibration_chart(resolved, th),
            use_container_width=True, config={"displayModeBar": False},
            key="backtest_calibration",
        )
    with ch_type:
        st.markdown(f"**{t('backtest_by_type')}**")
        st.plotly_chart(
            make_accuracy_by_type_chart(resolved, th),
            use_container_width=True, config={"displayModeBar": False},
            key="backtest_by_type_chart",
        )

    # ── Resolved predictions table ────────────────────────────────────────────
    st.markdown(f"**{t('backtest_table_title')}**")
    rows = []
    for row in resolved[:200]:
        rows.append({
            t("backtest_col_type"):     row.get("market_type", "—").capitalize(),
            t("backtest_col_question"): (row.get("question") or "")[:60],
            t("backtest_col_model"):    f"{float(row.get('model_prob', 0))*100:.1f}%",
            t("backtest_col_market"):   f"{float(row.get('market_prob', 0))*100:.1f}%",
            t("backtest_col_edge"):     f"{float(row.get('edge', 0))*100:+.1f}%",
            t("backtest_col_result"):   (
                t("backtest_result_yes") if row["resolved_yes"]
                else t("backtest_result_no")
            ),
            t("backtest_col_date"):     str(row.get("resolution_date", ""))[:10],
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ─── Main ─────────────────────────────────────────────────────────────────────

def render_history_tab(t: "callable", th: dict, wallet_address: str) -> None:
    """Render the Scan History tab using Supabase data."""
    st.subheader(t("scan_history_title"))

    try:
        secrets = st.secrets
        supabase_url = secrets.get("SUPABASE_URL", "")
        anon_key = secrets.get("SUPABASE_ANON_KEY", "")
    except Exception:
        supabase_url, anon_key = "", ""

    if not supabase_url or not anon_key:
        st.info(t("history_no_supabase"))
        st.code(
            'SUPABASE_URL      = "https://xxxx.supabase.co"\n'
            'SUPABASE_ANON_KEY = "eyJ..."',
            language="toml",
        )
        return

    with st.spinner(t("loading_history")):
        history = get_scan_history(supabase_url, anon_key, wallet_address or None, limit=30)

    if not history:
        st.info(t("history_no_data"))
        return

    # ── Chart: alerts over time ───────────────────────────────────────────────
    dates = []
    alert_counts = []
    market_counts = []

    for row in history:
        try:
            dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            dates.append(dt)
            alert_counts.append(row.get("alert_count", 0))
            market_counts.append(row.get("total_markets", 0))
        except (KeyError, ValueError):
            continue

    if dates:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=alert_counts,
            mode="lines+markers",
            name=t("total_alerts_col"),
            line=dict(color="#00c896", width=2),
            marker=dict(size=6),
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=market_counts,
            mode="lines",
            name=t("markets_label"),
            line=dict(color="#3b82f6", width=1, dash="dot"),
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor=th.get("plot_bg", "rgba(0,0,0,0)"),
            font=dict(color=th.get("plot_text", "#94a3b8"), size=12),
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            xaxis=dict(gridcolor=th.get("plot_grid", "#334155")),
            yaxis=dict(gridcolor=th.get("plot_grid", "#334155")),
            height=220,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Table ─────────────────────────────────────────────────────────────────
    table_rows = []
    for row in history:
        try:
            dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            date_str = "—"

        alerts_summary = row.get("alerts_summary") or []
        top_label = (
            alerts_summary[0].get("label") or alerts_summary[0].get("city", "—")
            if alerts_summary else "—"
        )

        table_rows.append({
            t("scan_date_col"): date_str,
            t("total_alerts_col"): row.get("alert_count", 0),
            t("markets_label"): row.get("total_markets", 0),
            "Top Alert": top_label,
        })

    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


def _detect_browser_lang() -> str:
    """Infer language from the browser's Accept-Language header."""
    try:
        accept = st.context.headers.get("Accept-Language", "")
        primary = accept.split(",")[0].split(";")[0].lower().strip()
        if primary.startswith("pt"):
            return "pt"
        if primary.startswith("es"):
            return "es"
        if primary.startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"


def main():
    if "lang" not in st.session_state:
        st.session_state["lang"] = _detect_browser_lang()
    if "theme" not in st.session_state:
        st.session_state["theme"] = "light"

    # Drive EIP-712 auth state machine (nonce request + signature verification)
    # Must run before any wallet-gated UI is rendered.
    process_auth_flow()

    th = get_theme()
    inject_css(th)

    bankroll, edge_threshold, model, max_markets, cities_filter, run_btn, wallet_address, notify_enabled, notify_email = render_sidebar(th)

    # ── Category bar ─────────────────────────────────────────────────────────
    selected_category = render_category_bar(th)

    # ── Run / load state ────────────────────────────────────────────────────
    # Cache a PolymarketClient for the wallet tab (positions fetch)
    if "_poly_client" not in st.session_state:
        st.session_state["_poly_client"] = PolymarketClient()

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

        # ── Save scan to Supabase ────────────────────────────────────────────
        if run_btn and results:
            try:
                supa_url = st.secrets.get("SUPABASE_URL", "")
                supa_key = st.secrets.get("SUPABASE_ANON_KEY", "")
                if supa_url and supa_key:
                    alerts_summary = build_alerts_summary(results)
                    saved = save_scan(
                        supabase_url=supa_url,
                        anon_key=supa_key,
                        wallet_address=wallet_address or "anonymous",
                        alert_count=sum(1 for r in results if r.alert),
                        total_markets=len(results),
                        alerts_summary=alerts_summary,
                    )
                    if saved:
                        st.toast(t("scan_saved"), icon="💾")
                    # ── Save alert history for connected wallet ──────────────
                    if wallet_address and wallet_address != "anonymous":
                        alerts_to_save = [r for r in results if r.alert]
                        if alerts_to_save:
                            save_alert_history(supa_url, supa_key, wallet_address, alerts_to_save)
            except Exception:
                pass  # Supabase is optional — never block the app

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

    # ── Category filter ───────────────────────────────────────────────────────
    if selected_category and selected_category != "all":
        results = [r for r in results
                   if getattr(r.market, "market_type", "weather") == selected_category]

    # ── Filter bar + CSV export ───────────────────────────────────────────────
    results, _ = render_filter_bar(th, results, bankroll_used)

    alerts = [r for r in results if r.alert]
    ranked = edge_calculator.rank_opportunities(results, by="expected_value")

    # ── Tabs ─────────────────────────────────────────────────────────────────
    now_utc = datetime.now(tz=timezone.utc)
    today_date = now_utc.date()
    week_end = today_date + timedelta(days=7)

    tab_alerts, tab_today, tab_week, tab_all, tab_wallet, tab_history, tab_backtest = st.tabs([
        t("tab_alerts"), t("tab_today"), t("tab_week"), t("tab_all"),
        t("tab_wallet"), t("tab_history"), t("tab_backtest"),
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
        render_wallet_tab(
            t, wallet_address, results, bankroll_used,
            poly_client=st.session_state.get("_poly_client"),
        )

    # ── Tab: Histórico ────────────────────────────────────────────────────────
    with tab_history:
        render_history_tab(t, th, wallet_address)

    # ── Tab: Backtesting ──────────────────────────────────────────────────────
    with tab_backtest:
        render_backtesting_tab(th, poly_client=st.session_state.get("_poly_client"))


if __name__ == "__main__":
    main()
