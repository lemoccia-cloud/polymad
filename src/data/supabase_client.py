"""
Supabase REST client for polyMad scan history.

Uses plain HTTP requests — no extra SDK required.
All functions return gracefully on error (never raise to caller).

Required Streamlit secrets:
    SUPABASE_URL      = "https://<project-ref>.supabase.co"
    SUPABASE_ANON_KEY = "eyJ..."

Supabase table DDL (run once in the Supabase SQL editor):
    CREATE TABLE scans (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at     timestamptz DEFAULT now(),
        wallet_address text,
        alert_count    int,
        total_markets  int,
        alerts_summary jsonb
    );
    CREATE INDEX ON scans (wallet_address, created_at DESC);
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
    """
    summary = []
    for r in results:
        if not r.alert:
            continue
        summary.append({
            "city": r.market.city,
            "question": r.market.question[:120],
            "edge": round(r.edge, 4),
            "ev": round(r.expected_value, 4),
            "direction": r.market.direction,
            "threshold": r.market.threshold_celsius,
            "resolution_date": r.market.resolution_date.strftime("%Y-%m-%d"),
            "market_prob": round(r.market.market_implied_prob, 3),
            "model_prob": round(r.forecast.model_probability, 3),
        })
    return summary
