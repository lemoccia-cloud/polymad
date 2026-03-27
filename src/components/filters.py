"""
Fase 6 — Filtros avançados + CSV export.

apply_filters() é pura (sem I/O) e pode ser testada offline.
render_filter_bar() é a UI Streamlit — retorna os parâmetros de filtro actuais
e um flag indicando se o utilizador pediu download de CSV.
"""
from __future__ import annotations

import io
import csv
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports at runtime


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def _market_label(market) -> str:
    """Return a human-readable label for any market type."""
    mtype = getattr(market, "market_type", "weather")
    if mtype == "crypto":
        direction = "≥" if market.direction == "above" else "≤"
        return f"{market.asset} {direction} ${market.threshold_usd:,.0f}"
    if mtype == "sports":
        return f"{market.home_team} vs {market.away_team}"
    if mtype == "politics":
        return market.topic
    # weather
    bucket_sym = {"above": "≥", "below": "≤", "exact": "="}
    return f"{market.city} {bucket_sym.get(market.bucket_type, '')} {market.threshold_celsius:.0f}°C"


def _search_corpus(market) -> str:
    """
    Build a lower-case searchable string from all human-readable fields.
    Covers label, question text, asset_name (Bitcoin / Ethereum), event_title.
    """
    parts = [
        _market_label(market),
        getattr(market, "question", ""),
        getattr(market, "asset_name", ""),   # "Bitcoin", "Ethereum" …
        getattr(market, "event_title", ""),
        getattr(market, "home_team", ""),
        getattr(market, "away_team", ""),
        getattr(market, "topic", ""),
        getattr(market, "city", ""),
    ]
    return " ".join(p for p in parts if p).lower()


def apply_filters(
    results: list,
    search: str = "",
    min_liquidity: float = 0.0,
    min_edge_pct: float = 0.0,
    max_days: int = 365,
) -> list:
    """
    Filter OpportunityResult list by:
      - search: case-insensitive substring match across label, question, asset name, teams, topic
      - min_liquidity: USD
      - min_edge_pct: percentage (0-100)
      - max_days: days until resolution
    """
    today = datetime.now(tz=timezone.utc).date()
    search_lower = search.strip().lower()
    out = []
    for r in results:
        m = r.market
        # text search — broad corpus
        if search_lower and search_lower not in _search_corpus(m):
            continue
        # liquidity
        if getattr(m, "liquidity_usd", 0) < min_liquidity:
            continue
        # edge
        if r.edge * 100 < min_edge_pct:
            continue
        # days to expiry
        res_date = getattr(m, "resolution_date", None)
        if res_date is not None:
            days = (res_date.date() - today).days
            if days > max_days:
                continue
        out.append(r)
    return out


def results_to_csv(results: list, bankroll: float) -> str:
    """
    Convert OpportunityResult list to CSV string.
    Columns: Type, Market, Resolution, Mkt%, Model%, Edge%, EV, Kelly%, Bet$, Liquidity$
    """
    from src.analysis.kelly import compute_position_size  # local import avoids circular

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Type", "Market", "Resolution Date",
        "Mkt Prob %", "Model Prob %", "Edge %", "EV/$ ",
        "Kelly %", "Bet $", "Liquidity $",
    ])
    for r in results:
        m, f = r.market, r.forecast
        mtype = getattr(m, "market_type", "weather")
        res_date = getattr(m, "resolution_date", None)
        res_str = res_date.strftime("%Y-%m-%d") if res_date else ""
        try:
            bet = compute_position_size(bankroll, r.kelly_fraction)
        except Exception:
            bet = 0.0
        writer.writerow([
            mtype.capitalize(),
            _market_label(m),
            res_str,
            round(m.market_implied_prob * 100, 2),
            round(f.model_probability * 100, 2),
            round(r.edge * 100, 2),
            round(r.expected_value, 4),
            round(r.suggested_bet_fraction * 100, 2),
            round(bet, 2),
            round(getattr(m, "liquidity_usd", 0), 0),
        ])
    return buf.getvalue()


# ─── Streamlit UI ─────────────────────────────────────────────────────────────

def render_filter_bar(th: dict, results: list, bankroll: float) -> tuple:
    """
    Render a compact filter bar using Streamlit widgets.

    Returns:
        (filtered_results, csv_bytes_or_none)
        csv_bytes_or_none is bytes when user clicked the download button,
        None otherwise (we pass it straight to st.download_button outside).
    """
    import streamlit as st
    from config.i18n import get_text
    lang = st.session_state.get("lang", "en")
    t = lambda key: get_text(key, lang)  # noqa: E731

    if not results:
        return results, None

    # ── derive range bounds from current results ──────────────────────────────
    liq_vals = [getattr(r.market, "liquidity_usd", 0) for r in results]
    max_liq   = max(liq_vals) if liq_vals else 100_000.0
    today     = datetime.now(tz=timezone.utc).date()
    day_vals  = []
    for r in results:
        rd = getattr(r.market, "resolution_date", None)
        if rd:
            day_vals.append(max(0, (rd.date() - today).days))
    max_day = max(day_vals) if day_vals else 90

    with st.expander(f"🔍  {t('filter_title')}", expanded=False):
        col_search, col_edge, col_liq, col_days = st.columns([3, 2, 2, 2])

        with col_search:
            search = st.text_input(
                t("filter_search"),
                placeholder=t("filter_search_placeholder"),
                label_visibility="collapsed",
                key="filter_search_input",
            )

        with col_edge:
            min_edge = st.slider(
                t("filter_min_edge"),
                min_value=0.0, max_value=50.0, value=0.0, step=0.5,
                format="%.1f%%",
                key="filter_min_edge_slider",
            )

        with col_liq:
            min_liq = st.slider(
                t("filter_min_liquidity"),
                min_value=0.0, max_value=float(max(max_liq, 1)),
                value=0.0, step=500.0,
                format="$%,.0f",
                key="filter_min_liq_slider",
            )

        with col_days:
            max_days_val = st.slider(
                t("filter_max_days"),
                min_value=1, max_value=max(max_day, 1),
                value=max(max_day, 1),
                key="filter_max_days_slider",
            )

    # apply
    filtered = apply_filters(
        results,
        search=search,
        min_liquidity=min_liq,
        min_edge_pct=min_edge,
        max_days=max_days_val,
    )

    # showing count + CSV button side-by-side
    c_info, c_csv = st.columns([6, 1])
    with c_info:
        st.caption(
            f"{t('filter_showing')} **{len(filtered)}** / {len(results)} {t('markets_label')}"
        )
    with c_csv:
        csv_str = results_to_csv(filtered, bankroll)
        st.download_button(
            label=t("export_csv"),
            data=csv_str.encode("utf-8"),
            file_name=f"polymad_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="csv_download_btn",
        )

    return filtered, None
