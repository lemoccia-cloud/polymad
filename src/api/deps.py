"""
FastAPI shared dependencies.

The primary dependency here is `get_current_address`, which validates the
Bearer JWT and returns the wallet address.  All authenticated routes
depend on this via `Depends(get_current_address)`.

SECURITY: The address returned here is the ONLY source of truth for the
authenticated user.  Route handlers MUST NOT accept a wallet address from
query parameters, request body, or any other user-controlled source.
"""
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.api.security.jwt_handler import decode_access_token, decode_access_token_full
from src.api.security.nonce_store import nonce_store, NonceStore

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_address(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency — extract and validate the Bearer JWT.

    Returns the authenticated wallet address (lowercase).
    Raises HTTP 401 if the token is absent, malformed, expired, or invalid.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    address = decode_access_token(credentials.credentials)
    if address is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return address


def get_current_address_and_plan(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Tuple[str, str]:
    """
    FastAPI dependency — extract and validate the Bearer JWT.

    Returns (wallet_address, plan) for the authenticated user.
    Raises HTTP 401 if the token is absent, malformed, expired, or invalid.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = decode_access_token_full(credentials.credentials)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return result


def get_nonce_store() -> NonceStore:
    """Return the module-level nonce store singleton."""
    return nonce_store
