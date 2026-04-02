"""
Email/password authentication endpoints.

POST /auth/email/register  — register a new user with email + password
POST /auth/email/login     — login and receive a polyMad JWT

Authentication is delegated to Supabase Auth (handles password hashing,
email verification, rate limiting, account lockout). On success, this
endpoint issues a polyMad JWT in exactly the same format as MetaMask auth,
so the rest of the system (plan gating, session state) is unaffected.

Security:
  - Supabase Auth enforces its own rate limits and brute-force protection.
  - Passwords are never stored or logged by polyMad — only Supabase sees them.
  - Generic error messages prevent user enumeration.
"""
import logging
import os
from typing import Tuple

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr

from src.api.schemas.auth import TokenResponse
from src.api.security.jwt_handler import create_access_token
from src.data.supabase_client import (
    supabase_auth_login,
    supabase_auth_signup,
    get_user_by_supabase_id,
    upsert_email_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/email", tags=["auth-email"])


def _supabase_creds() -> Tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service not configured",
        )
    return url, key


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = ""


class RegisterResponse(BaseModel):
    message: str


class EmailLoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register with email and password",
)
def register(request: Request, body: RegisterRequest) -> RegisterResponse:
    """
    Register a new polyMad account using email and password.

    Supabase Auth creates the user and sends a verification email.
    The user must verify their email before they can log in.

    On success: returns a confirmation message.
    On failure: returns 400 with a generic error (no user enumeration).
    """
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    sb_url, sb_key = _supabase_creds()
    result = supabase_auth_signup(sb_url, sb_key, str(body.email), body.password)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed. The email may already be in use.",
        )

    # Pre-create user row so plan/display_name are ready when they first log in
    upsert_email_user(
        sb_url, sb_key,
        supabase_user_id=result["user_id"],
        email=str(body.email),
        display_name=body.display_name,
        plan="free",
    )

    logger.info("auth_email.register: new user registered email_prefix=%s", str(body.email)[:4])
    return RegisterResponse(
        message="Account created. Please check your email to verify your address before logging in."
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
)
def login(request: Request, body: EmailLoginRequest) -> TokenResponse:
    """
    Authenticate with email and password. Returns a polyMad JWT identical
    in format to the MetaMask JWT — same session state, same plan gating.

    On success: returns access_token, expires_at, plan.
    On failure: always returns HTTP 401 with a generic message.
    """
    sb_url, sb_key = _supabase_creds()
    auth_result = supabase_auth_login(sb_url, sb_key, str(body.email), body.password)

    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supabase_user_id = auth_result["user_id"]

    # Ensure user row exists and get current plan
    user_row = get_user_by_supabase_id(sb_url, sb_key, supabase_user_id)
    if user_row:
        plan = user_row.get("plan", "free")
    else:
        # First login after registration — create the row
        upsert_email_user(sb_url, sb_key, supabase_user_id, str(body.email), plan="free")
        plan = "free"

    # wallet_address for email users is 'email:<supabase_user_id>'
    wallet_address = f"email:{supabase_user_id}"

    token, expires_at = create_access_token(wallet_address, plan)
    logger.info("auth_email.login: success email_prefix=%s plan=%s", str(body.email)[:4], plan)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at.isoformat(),
        plan=plan,
    )
