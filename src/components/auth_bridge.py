"""
Streamlit ↔ FastAPI authentication bridge.

This module is the ONLY place in the Streamlit code that communicates
with the FastAPI backend.  All calls are made server-side (Python → HTTP),
never from the browser directly.

The JWT is stored exclusively in st.session_state under the key
`_auth_token`.  It is never written to query params, cookies, or any
browser-accessible storage.

Public API:
    request_nonce(address)          → nonce string or None on error
    verify_signature(address, sig, nonce, issued_at) → bool
    get_portfolio()                 → dict or None
    get_positions(include_closed)   → list or None
    is_authenticated()              → bool
    get_authenticated_address()     → str or None
    clear_auth()                    → None
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import streamlit as st

logger = logging.getLogger(__name__)

# FastAPI base URL — internal loopback; not exposed publicly
_FASTAPI_BASE = os.environ.get("FASTAPI_INTERNAL_URL", "http://localhost:8000")
_TIMEOUT = 10.0  # seconds

# Session state keys — prefixed with _ to signal internal/private use
_TOKEN_KEY = "_auth_token"
_TOKEN_EXP_KEY = "_auth_token_expires_at"
_ADDRESS_KEY = "_auth_address"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_token() -> Optional[str]:
    """Return the stored JWT or None if not authenticated."""
    return st.session_state.get(_TOKEN_KEY)


def _auth_headers() -> dict[str, str]:
    """Build Authorization header from stored JWT. Raises if not authenticated."""
    token = _get_token()
    if not token:
        raise ValueError("Not authenticated — call verify_signature first")
    return {"Authorization": f"Bearer {token}"}


def _post(path: str, json: dict) -> Optional[dict]:
    """POST to FastAPI. Returns parsed JSON or None on any error."""
    try:
        resp = httpx.post(
            f"{_FASTAPI_BASE}{path}",
            json=json,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("auth_bridge POST %s → %d", path, exc.response.status_code)
        return None
    except Exception:
        logger.error("auth_bridge POST %s failed", path)
        return None


def _get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    """Authenticated GET to FastAPI. Returns parsed JSON or None on any error."""
    try:
        resp = httpx.get(
            f"{_FASTAPI_BASE}{path}",
            params=params,
            headers=_auth_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("auth_bridge GET %s → %d", path, exc.response.status_code)
        return None
    except Exception:
        logger.error("auth_bridge GET %s failed", path)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def request_nonce(address: str) -> Optional[str]:
    """
    Request a one-time EIP-712 nonce for the given address from FastAPI.
    Returns the nonce string, or None if the request failed.
    """
    data = _post("/auth/nonce", {"address": address})
    if data and "nonce" in data:
        return data["nonce"]
    return None


def verify_signature(
    address: str,
    signature: str,
    nonce: str,
    issued_at: str,
) -> bool:
    """
    Submit the EIP-712 signature to FastAPI for verification.

    On success: stores the JWT in st.session_state and returns True.
    On failure: returns False. Does NOT store anything.

    Args:
        address:    Wallet address (0x-prefixed).
        signature:  EIP-712 signature from MetaMask (0x-prefixed, 130 hex chars).
        nonce:      The nonce previously obtained from request_nonce().
        issued_at:  ISO-8601 UTC timestamp used when building the EIP-712 message.
    """
    data = _post("/auth/verify", {
        "address": address,
        "signature": signature,
        "nonce": nonce,
        "issued_at": issued_at,
    })
    if data and "access_token" in data:
        st.session_state[_TOKEN_KEY] = data["access_token"]
        st.session_state[_TOKEN_EXP_KEY] = data.get("expires_at", "")
        st.session_state[_ADDRESS_KEY] = address.lower()
        logger.info("auth_bridge: authentication successful")
        return True
    return False


def is_authenticated() -> bool:
    """
    Return True if there is a non-expired JWT in session state.
    Does NOT make a network call — checks expiry locally.
    """
    token = _get_token()
    if not token:
        return False
    expires_at_str = st.session_state.get(_TOKEN_EXP_KEY, "")
    if not expires_at_str:
        return True  # token present but no expiry info — trust it
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < expires_at
    except (ValueError, TypeError):
        return True


def get_authenticated_address() -> Optional[str]:
    """
    Return the authenticated wallet address (lowercase) or None.
    Only valid when is_authenticated() is True.
    """
    if not is_authenticated():
        return None
    return st.session_state.get(_ADDRESS_KEY)


def clear_auth() -> None:
    """Remove all authentication state from session_state (sign-out)."""
    for key in (_TOKEN_KEY, _TOKEN_EXP_KEY, _ADDRESS_KEY):
        st.session_state.pop(key, None)


def get_portfolio() -> Optional[dict]:
    """
    Fetch aggregated portfolio data for the authenticated wallet.
    Returns the portfolio dict or None if unauthenticated or on error.
    """
    if not is_authenticated():
        return None
    return _get("/api/portfolio")


def get_positions(include_closed: bool = False) -> Optional[list]:
    """
    Fetch positions for the authenticated wallet.
    Returns a list of position dicts or None if unauthenticated or on error.
    """
    if not is_authenticated():
        return None
    data = _get("/api/positions", params={"include_closed": str(include_closed).lower()})
    if data and "positions" in data:
        return data["positions"]
    return None
