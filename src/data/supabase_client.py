"""
Supabase REST client for polyMad scan history + backtesting.

Uses plain HTTP requests — no extra SDK required.
All functions return gracefully on error (never raise to caller).

Required Streamlit secrets:
    SUPABASE_URL      = "https://<project-ref>.supabase.co"
    SUPABASE_ANON_KEY = "eyJ..."

Supabase DDL (run once in the Supabase SQL editor):

    -- Scan history (existing)
    CREATE TABLE IF NOT EXISTS scans (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at     timestamptz DEFAULT now(),
        wallet_address text,
        alert_count    int,
        total_markets  int,
        alerts_summary jsonb
    );
    CREATE INDEX IF NOT EXISTS idx_scans_wallet ON scans (wallet_address, created_at DESC);

    -- Backtesting: one row per prediction, updated when market resolves
    CREATE TABLE IF NOT EXISTS market_outcomes (
        id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at      timestamptz DEFAULT now(),
        market_id       text NOT NULL,
        condition_id    text,
        question        text,
        market_type     text,
        model_prob      float,
        market_prob     float,
        edge            float,
        resolved_yes    boolean,          -- NULL until resolved
        resolution_date date,
        UNIQUE (market_id)                -- one row per market, no duplicates
    );
    CREATE INDEX IF NOT EXISTS idx_market_outcomes_resolved ON market_outcomes (resolved_yes, resolution_date);
    CREATE INDEX IF NOT EXISTS idx_market_outcomes_type ON market_outcomes (market_type);

    -- Fase 4: Stripe subscription users
    CREATE TABLE IF NOT EXISTS users (
        wallet_address        TEXT PRIMARY KEY,
        stripe_customer_id    TEXT,
        stripe_subscription_id TEXT,
        plan                  TEXT NOT NULL DEFAULT 'free',
        billing_email         TEXT,
        plan_updated_at       TIMESTAMPTZ DEFAULT now(),
        created_at            TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_users_plan ON users (plan);
    CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users (stripe_customer_id);

    -- Fase 3: Telegram bot subscribers
    CREATE TABLE IF NOT EXISTS telegram_users (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        chat_id        bigint NOT NULL UNIQUE,
        username       text,
        edge_threshold float DEFAULT 0.10,
        active         boolean DEFAULT true,
        created_at     timestamptz DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_telegram_users_active ON telegram_users (active);
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 8  # seconds


def _headers(anon_key: str) -> dict:
    return {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
    }


def save_scan(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
    alert_count: int,
    total_markets: int,
    alerts_summary: list,
) -> bool:
    """
    Insert a scan record into the Supabase `scans` table.

    Args:
        supabase_url: e.g. "https://xxxx.supabase.co"
        anon_key: Supabase anon (public) API key
        wallet_address: connected wallet address, or "anonymous"
        alert_count: number of alerts in this scan
        total_markets: total markets analyzed
        alerts_summary: compact list of dicts [{city, edge, ev, question}]

    Returns:
        True on success, False on any error.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/scans"
    payload = {
        "wallet_address": wallet_address or "anonymous",
        "alert_count": alert_count,
        "total_markets": total_markets,
        "alerts_summary": alerts_summary,
    }
    try:
        resp = requests.post(
            url,
            headers={**_headers(anon_key), "Prefer": "return=minimal"},
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            logger.debug("Scan saved to Supabase (alerts=%d)", alert_count)
            return True
        logger.warning("Supabase save failed: HTTP %d — %s", resp.status_code, resp.text[:200])
        return False
    except requests.RequestException as exc:
        logger.warning("Supabase save error: %s", exc)
        return False


def get_scan_history(
    supabase_url: str,
    anon_key: str,
    wallet_address: Optional[str] = None,
    limit: int = 30,
) -> list:
    """
    Fetch past scan records from Supabase, ordered newest first.

    Args:
        supabase_url: e.g. "https://xxxx.supabase.co"
        anon_key: Supabase anon key
        wallet_address: filter by wallet (None or empty → all records)
        limit: max rows to return

    Returns:
        List of scan dicts, or [] on error.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/scans"
    params = {
        "select": "id,created_at,wallet_address,alert_count,total_markets,alerts_summary",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if wallet_address:
        params["wallet_address"] = f"eq.{wallet_address}"

    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Supabase history fetch failed: HTTP %d", resp.status_code)
        return []
    except requests.RequestException as exc:
        logger.warning("Supabase history error: %s", exc)
        return []


def build_alerts_summary(results: list) -> list:
    """
    Convert OpportunityResult list to compact dicts for Supabase storage.
    Stores only alert-flagged results with the minimal fields needed for display.
    Works for all market types (weather, crypto, sports, politics).
    """
    def _label(m) -> str:
        mtype = getattr(m, "market_type", "weather")
        if mtype == "crypto":
            d = "≥" if m.direction == "above" else "≤"
            return f"{m.asset} {d} ${m.threshold_usd:,.0f}"
        if mtype == "sports":
            return f"{m.home_team} vs {m.away_team}"
        if mtype == "politics":
            return m.topic[:80]
        bucket_sym = {"above": "≥", "below": "≤", "exact": "="}
        return f"{m.city} {bucket_sym.get(m.bucket_type,'')} {m.threshold_celsius:.0f}°C"

    summary = []
    for r in results:
        if not r.alert:
            continue
        m = r.market
        res_date = getattr(m, "resolution_date", None)
        summary.append({
            "label":            _label(m),
            "question":         getattr(m, "question", "")[:120],
            "market_type":      getattr(m, "market_type", "weather"),
            "edge":             round(r.edge, 4),
            "ev":               round(r.expected_value, 4),
            "resolution_date":  res_date.strftime("%Y-%m-%d") if res_date else "",
            "market_prob":      round(m.market_implied_prob, 3),
            "model_prob":       round(r.forecast.model_probability, 3),
        })
    return summary


# ─── Backtesting ──────────────────────────────────────────────────────────────

def save_prediction(
    supabase_url: str,
    anon_key: str,
    market_id: str,
    condition_id: str,
    question: str,
    market_type: str,
    model_prob: float,
    market_prob: float,
    edge: float,
    resolution_date,            # datetime or date
) -> bool:
    """
    Upsert one prediction into market_outcomes.
    Silently ignores duplicates (UNIQUE on market_id).
    Returns True on success.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/market_outcomes"
    res_str = (
        resolution_date.strftime("%Y-%m-%d")
        if hasattr(resolution_date, "strftime")
        else str(resolution_date)
    )
    payload = {
        "market_id":       market_id,
        "condition_id":    condition_id,
        "question":        question[:200],
        "market_type":     market_type,
        "model_prob":      round(float(model_prob), 4),
        "market_prob":     round(float(market_prob), 4),
        "edge":            round(float(edge), 4),
        "resolution_date": res_str,
    }
    try:
        resp = requests.post(
            url,
            headers={**_headers(anon_key), "Prefer": "resolution=ignore,return=minimal"},
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        )
        return resp.status_code in (200, 201)
    except requests.RequestException as exc:
        logger.warning("save_prediction error: %s", exc)
        return False


def get_unresolved_predictions(
    supabase_url: str,
    anon_key: str,
    limit: int = 200,
) -> list:
    """
    Fetch predictions whose resolution_date has passed but resolved_yes is still NULL.
    These are candidates to check against the Polymarket CLOB API.
    """
    from datetime import date
    url = f"{supabase_url.rstrip('/')}/rest/v1/market_outcomes"
    today_str = date.today().isoformat()
    params = {
        "select":           "id,market_id,condition_id,question,market_type",
        "resolved_yes":     "is.null",
        "resolution_date":  f"lte.{today_str}",
        "order":            "resolution_date.asc",
        "limit":            str(limit),
    }
    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("get_unresolved_predictions HTTP %d", resp.status_code)
        return []
    except requests.RequestException as exc:
        logger.warning("get_unresolved_predictions error: %s", exc)
        return []


def mark_resolved(
    supabase_url: str,
    anon_key: str,
    prediction_id: str,
    resolved_yes: bool,
) -> bool:
    """
    Set resolved_yes on a market_outcomes row by its UUID.
    Returns True on success.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/market_outcomes"
    params = {"id": f"eq.{prediction_id}"}
    payload = {"resolved_yes": resolved_yes}
    try:
        resp = requests.patch(
            url,
            headers={**_headers(anon_key), "Prefer": "return=minimal"},
            params=params,
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        )
        return resp.status_code in (200, 204)
    except requests.RequestException as exc:
        logger.warning("mark_resolved error: %s", exc)
        return False


def get_backtesting_data(
    supabase_url: str,
    anon_key: str,
    market_type: Optional[str] = None,
    limit: int = 1000,
) -> list:
    """
    Fetch all resolved predictions for calibration / Brier score computation.
    Returns list of dicts with keys: model_prob, market_prob, edge, resolved_yes, market_type.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/market_outcomes"
    params = {
        "select":       "model_prob,market_prob,edge,resolved_yes,market_type,question,resolution_date",
        "resolved_yes": "not.is.null",
        "order":        "resolution_date.desc",
        "limit":        str(limit),
    }
    if market_type:
        params["market_type"] = f"eq.{market_type}"
    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("get_backtesting_data HTTP %d", resp.status_code)
        return []
    except requests.RequestException as exc:
        logger.warning("get_backtesting_data error: %s", exc)
        return []


# ─── Phase 2 — Alert configs & history ────────────────────────────────────────

def upsert_alert_config(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
    edge_threshold: float,
    categories: list,
    notify_email: str,
) -> bool:
    """
    Insert or update per-wallet alert configuration.
    Returns True on success.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/alert_configs"
    payload = {
        "wallet_address": wallet_address,
        "edge_threshold": round(float(edge_threshold), 4),
        "categories": categories,
        "notify_email": notify_email or None,
        "active": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = requests.post(
            url,
            headers={**_headers(anon_key), "Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        )
        return resp.status_code in (200, 201)
    except requests.RequestException as exc:
        logger.warning("upsert_alert_config error: %s", exc)
        return False


def get_alert_config(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
) -> dict:
    """
    Fetch alert config for a wallet. Returns {} if not found or on error.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/alert_configs"
    params = {
        "select": "edge_threshold,categories,notify_email,active",
        "wallet_address": f"eq.{wallet_address}",
        "limit": "1",
    }
    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            rows = resp.json()
            return rows[0] if rows else {}
        logger.warning("get_alert_config HTTP %d", resp.status_code)
        return {}
    except requests.RequestException as exc:
        logger.warning("get_alert_config error: %s", exc)
        return {}


def save_alert_history(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
    alerts: list,
) -> int:
    """
    Bulk-insert alert results for a wallet. Skips duplicates via UNIQUE(wallet_address, market_id).
    alerts is a list of OpportunityResult with r.alert == True.
    Returns count of rows in the batch (approximate; batch is all-or-nothing).
    """
    if not alerts:
        return 0
    url = f"{supabase_url.rstrip('/')}/rest/v1/alert_history"
    rows = []
    for r in alerts:
        m = r.market
        res_date = getattr(m, "resolution_date", None)
        rows.append({
            "wallet_address":  wallet_address,
            "market_id":       getattr(m, "market_id", "") or getattr(m, "condition_id", ""),
            "condition_id":    getattr(m, "condition_id", ""),
            "question":        getattr(m, "question", "")[:200],
            "market_type":     getattr(m, "market_type", "weather"),
            "model_prob":      round(float(r.forecast.model_probability), 4),
            "market_prob":     round(float(m.market_implied_prob), 4),
            "edge":            round(float(r.edge), 4),
            "resolution_date": res_date.strftime("%Y-%m-%d") if hasattr(res_date, "strftime") else None,
        })
    try:
        resp = requests.post(
            url,
            headers={**_headers(anon_key), "Prefer": "resolution=ignore,return=minimal"},
            data=json.dumps(rows),
            timeout=_TIMEOUT,
        )
        return len(rows) if resp.status_code in (200, 201) else 0
    except requests.RequestException as exc:
        logger.warning("save_alert_history error: %s", exc)
        return 0


# ─── Fase 4 — Subscription plan helpers ──────────────────────────────────────

def get_user_plan(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
) -> str:
    """
    Return the subscription plan for a wallet address.
    Returns "free" if the user is not found or on any error.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/users"
    params = {
        "select": "plan",
        "wallet_address": f"eq.{wallet_address.lower()}",
        "limit": "1",
    }
    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0].get("plan", "free")
        return "free"
    except requests.RequestException:
        return "free"


def upsert_user_plan(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
    plan: str,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
) -> bool:
    """
    Insert or update subscription data for a wallet address.
    Returns True on success, False on any error.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/users"
    payload: dict = {
        "wallet_address": wallet_address.lower(),
        "plan": plan,
        "plan_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if stripe_customer_id:
        payload["stripe_customer_id"] = stripe_customer_id
    if stripe_subscription_id:
        payload["stripe_subscription_id"] = stripe_subscription_id
    try:
        resp = requests.post(
            url,
            headers={**_headers(anon_key), "Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        )
        return resp.status_code in (200, 201)
    except requests.RequestException as exc:
        logger.warning("upsert_user_plan error: %s", exc)
        return False


def get_stripe_customer_id(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
) -> Optional[str]:
    """
    Return the Stripe customer ID for a wallet, or None if not set.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/users"
    params = {
        "select": "stripe_customer_id",
        "wallet_address": f"eq.{wallet_address.lower()}",
        "limit": "1",
    }
    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0].get("stripe_customer_id") or None
        return None
    except requests.RequestException:
        return None


def get_alert_history(
    supabase_url: str,
    anon_key: str,
    wallet_address: str,
    limit: int = 50,
) -> list:
    """
    Fetch alert history for a wallet, newest first.
    Returns list of dicts matching alert_history columns.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/alert_history"
    params = {
        "select": "id,created_at,market_id,condition_id,question,market_type,"
                  "model_prob,market_prob,edge,resolved_yes,resolution_date",
        "wallet_address": f"eq.{wallet_address}",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    try:
        resp = requests.get(url, headers=_headers(anon_key), params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("get_alert_history HTTP %d", resp.status_code)
        return []
    except requests.RequestException as exc:
        logger.warning("get_alert_history error: %s", exc)
        return []
