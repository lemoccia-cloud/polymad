"""
Authentication endpoints.

POST /auth/nonce   — issue a one-time EIP-712 nonce for a wallet address
POST /auth/verify  — verify the EIP-712 signature and issue a JWT

Security controls per endpoint:
  /auth/nonce   — rate-limited 10 req/min per IP, input validated by Pydantic
  /auth/verify  — rate-limited 5 req/min per IP, generic 401 on ALL failures
                  (timing-safe: always runs to completion regardless of fail reason)
"""
import logging
import os
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.deps import get_nonce_store
from src.api.schemas.auth import NonceRequest, NonceResponse, TokenResponse, VerifyRequest
from src.api.security.eip712 import verify_eip712_signature
from src.api.security.jwt_handler import create_access_token
from src.api.security.nonce_store import NonceStore
from src.data.supabase_client import get_user_plan, upsert_user_plan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/nonce",
    response_model=NonceResponse,
    summary="Request an EIP-712 sign-in nonce",
)
def request_nonce(
    request: Request,
    body: NonceRequest,
    store: NonceStore = Depends(get_nonce_store),
) -> NonceResponse:
    """
    Generate and store a one-time nonce for the given wallet address.
    The client must sign this nonce with MetaMask (eth_signTypedData_v4)
    and submit the signature to /auth/verify within 5 minutes.

    Rate limit: 10 requests per minute per IP.
    """
    nonce = store.create(body.address)
    # Log only the address prefix — never the full address
    addr_prefix = body.address[:8] if len(body.address) >= 8 else "0x?"
    logger.info("auth.nonce issued addr_prefix=%s", addr_prefix)
    return NonceResponse(nonce=nonce, expires_in=300)


@router.post(
    "/verify",
    response_model=TokenResponse,
    summary="Verify EIP-712 signature and issue JWT",
)
def verify_signature(
    request: Request,
    body: VerifyRequest,
    store: NonceStore = Depends(get_nonce_store),
) -> TokenResponse:
    """
    Verify the EIP-712 signature over the nonce previously issued to this address.

    On success: returns a 1-hour Bearer JWT.
    On failure: always returns HTTP 401 with a generic message.
               The specific failure reason is intentionally NOT revealed to
               prevent oracle attacks (nonce expired vs. bad signature vs.
               unknown address all look identical to the caller).

    Rate limit: 5 requests per minute per IP.
    """
    addr_prefix = body.address[:8] if len(body.address) >= 8 else "0x?"

    # Step 1: consume the nonce atomically BEFORE checking the signature.
    # This ensures the nonce cannot be replayed even if a slow attacker
    # sends two concurrent requests with the same valid signature.
    nonce_valid = store.consume(body.address, body.nonce)

    # Step 2: verify the EIP-712 signature.
    # Run this even if nonce_valid is False to maintain constant-time behaviour.
    sig_valid = verify_eip712_signature(
        address=body.address,
        nonce=body.nonce,
        issued_at=body.issued_at,
        signature=body.signature,
    )

    # Step 3: only grant access if BOTH checks passed.
    if not (nonce_valid and sig_valid):
        logger.warning("auth.verify failed addr_prefix=%s", addr_prefix)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Step 4: look up (or create) the user's subscription plan.
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_ANON_KEY", "")
    plan = "free"
    if supabase_url and supabase_key:
        plan = get_user_plan(supabase_url, supabase_key, body.address)
        # Ensure user row exists in users table (upsert preserves existing plan)
        upsert_user_plan(supabase_url, supabase_key, body.address, plan)

    token, expiry = create_access_token(body.address, plan=plan)
    expires_at = expiry.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info("auth.verify success addr_prefix=%s plan=%s", addr_prefix, plan)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
        plan=plan,
    )
