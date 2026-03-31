"""
Supabase helpers for Telegram bot subscriber management.

Separated from main supabase_client.py to keep bot self-contained.
Reads SUPABASE_URL and SUPABASE_ANON_KEY from os.environ (not Streamlit secrets).
All functions return gracefully on error — bot never crashes due to DB issues.
"""
import json
import logging
import os
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)
_TIMEOUT = 8


def _creds() -> Optional[Tuple[str, str]]:
    """Return (supabase_url, anon_key) or None if not configured."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    return (url.rstrip("/"), key) if url and key else None


def _headers(anon_key: str) -> dict:
    return {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
    }


def upsert_subscriber(
    chat_id: int,
    username: str = "",
    edge_threshold: float = 0.10,
) -> bool:
    """
    Insert or update a Telegram subscriber.
    Returns True on success, False on any error.
    """
    creds = _creds()
    if not creds:
        logger.warning("bot._supabase: SUPABASE_URL/KEY not set — skip upsert_subscriber")
        return False
    url, key = creds
    payload = {
        "chat_id": chat_id,
        "username": username,
        "edge_threshold": round(edge_threshold, 4),
        "active": True,
    }
    try:
        resp = requests.post(
            f"{url}/rest/v1/telegram_users",
            headers={
                **_headers(key),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        )
        ok = resp.status_code in (200, 201)
        if not ok:
            logger.warning(
                "bot._supabase: upsert_subscriber HTTP %d: %s",
                resp.status_code, resp.text[:200],
            )
        return ok
    except requests.RequestException as exc:
        logger.warning("bot._supabase: upsert_subscriber error: %s", exc)
        return False


def deactivate_subscriber(chat_id: int) -> bool:
    """
    Mark a subscriber as inactive (soft delete).
    Returns True on success, False on any error.
    """
    creds = _creds()
    if not creds:
        return False
    url, key = creds
    try:
        resp = requests.patch(
            f"{url}/rest/v1/telegram_users",
            params={"chat_id": f"eq.{chat_id}"},
            headers={**_headers(key), "Prefer": "return=minimal"},
            data=json.dumps({"active": False}),
            timeout=_TIMEOUT,
        )
        return resp.status_code in (200, 204)
    except requests.RequestException as exc:
        logger.warning("bot._supabase: deactivate_subscriber error: %s", exc)
        return False


def get_active_subscribers() -> List[dict]:
    """
    Fetch all active Telegram subscribers.
    Returns list of dicts with keys: chat_id, username, edge_threshold.
    Returns empty list on any error.
    """
    creds = _creds()
    if not creds:
        return []
    url, key = creds
    try:
        resp = requests.get(
            f"{url}/rest/v1/telegram_users",
            params={"active": "eq.true", "select": "chat_id,username,edge_threshold"},
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json() or []
        logger.warning(
            "bot._supabase: get_active_subscribers HTTP %d",
            resp.status_code,
        )
        return []
    except requests.RequestException as exc:
        logger.warning("bot._supabase: get_active_subscribers error: %s", exc)
        return []
