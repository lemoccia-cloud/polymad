"""
JWT creation and validation for polyMad authentication.

Tokens are HS256-signed, 1-hour access tokens.
The secret is read from the JWT_SECRET_KEY environment variable and validated
at startup — missing or short secrets cause a hard RuntimeError before any
request is served.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from jose import jwt, JWTError

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
_MIN_SECRET_LEN = 32  # bytes (64 hex chars if hex-encoded, 32 raw chars minimum)


# ---------------------------------------------------------------------------
# Secret management
# ---------------------------------------------------------------------------

def _get_secret() -> str:
    """
    Read JWT_SECRET_KEY from the environment.
    Raises RuntimeError at startup if absent or too short.
    This is intentional: a missing secret is a deployment error, not a
    recoverable condition.
    """
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret or len(secret) < _MIN_SECRET_LEN:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set and at least 32 characters. "
            "Generate a secure value with:\n"
            "  python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return secret


def _get_previous_secret() -> Optional[str]:
    """
    Read JWT_SECRET_KEY_PREVIOUS for grace-period key rotation.
    Returns None if not set or too short.
    """
    secret = os.environ.get("JWT_SECRET_KEY_PREVIOUS", "")
    if secret and len(secret) >= _MIN_SECRET_LEN:
        return secret
    return None


# ---------------------------------------------------------------------------
# Token operations
# ---------------------------------------------------------------------------

def create_access_token(address: str, plan: str = "free") -> Tuple[str, datetime]:
    """
    Create a signed JWT access token for the given wallet address.

    Returns:
        (token_string, expiry_datetime_utc)

    Claims:
        sub  — wallet address (lowercased)
        plan — subscription plan ("free" | "pro" | "trader")
        iat  — issued-at (unix timestamp)
        exp  — expiry (unix timestamp, now + 60 min)
        jti  — unique token ID (prevents token confusion)
        typ  — "access" (prevents refresh tokens being used as access tokens)
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": address.lower(),
        "plan": plan if plan in ("free", "pro", "trader") else "free",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    token = jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)
    return token, exp


def decode_access_token(token: str) -> Optional[str]:
    """
    Decode and validate a JWT access token.

    Returns the wallet address (sub claim, lowercase) if the token is valid,
    or None on any error (expired, wrong secret, malformed, wrong typ).
    Never raises.
    """
    secrets_to_try = [_get_secret()]
    previous = _get_previous_secret()
    if previous:
        secrets_to_try.append(previous)

    for secret in secrets_to_try:
        try:
            payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
            if payload.get("typ") != "access":
                return None
            sub = payload.get("sub")
            if not sub or not isinstance(sub, str):
                return None
            return sub.lower()
        except JWTError:
            continue
    return None


def decode_access_token_full(token: str) -> Optional[Tuple[str, str]]:
    """
    Decode and validate a JWT access token, returning both address and plan.

    Returns (address, plan) if the token is valid, or None on any error.
    Plan defaults to "free" if the claim is absent (backward compat with old tokens).
    Never raises.
    """
    secrets_to_try = [_get_secret()]
    previous = _get_previous_secret()
    if previous:
        secrets_to_try.append(previous)

    for secret in secrets_to_try:
        try:
            payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
            if payload.get("typ") != "access":
                return None
            sub = payload.get("sub")
            if not sub or not isinstance(sub, str):
                return None
            plan = payload.get("plan", "free")
            if plan not in ("free", "pro", "trader"):
                plan = "free"
            return sub.lower(), plan
        except JWTError:
            continue
    return None
