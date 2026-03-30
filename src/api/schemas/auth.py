"""
Pydantic request/response schemas for the authentication endpoints.

All inputs are validated and normalised before reaching any business logic.
Validation errors return HTTP 422 — never 500.
"""
import re
from typing import Annotated

from pydantic import BaseModel, field_validator, Field

# Ethereum address: 0x + exactly 40 hex characters
_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
# EIP-712 signature: 0x + 130 hex characters (v + r + s, 65 bytes)
_SIGNATURE_RE = re.compile(r"^0x[0-9a-fA-F]{130}$")
# token_urlsafe(32) produces 43 base64url characters; accept 20–60 for safety
_NONCE_RE = re.compile(r"^[A-Za-z0-9_\-]{20,60}$")
# ISO-8601 UTC timestamp (basic sanity — not full ISO parser)
_ISSUED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _validate_eth_address(v: str) -> str:
    v = v.strip()
    if not _ETH_ADDRESS_RE.match(v):
        raise ValueError("Invalid Ethereum address format (expected 0x + 40 hex chars)")
    return v.lower()


# ---------------------------------------------------------------------------
# /auth/nonce
# ---------------------------------------------------------------------------

class NonceRequest(BaseModel):
    address: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        return _validate_eth_address(v)


class NonceResponse(BaseModel):
    nonce: str
    expires_in: int = Field(default=300, description="Seconds until nonce expires")


# ---------------------------------------------------------------------------
# /auth/verify
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    address: str
    signature: str
    nonce: str
    issued_at: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        return _validate_eth_address(v)

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        v = v.strip()
        if not _SIGNATURE_RE.match(v):
            raise ValueError("Invalid signature format (expected 0x + 130 hex chars)")
        return v

    @field_validator("nonce")
    @classmethod
    def validate_nonce(cls, v: str) -> str:
        v = v.strip()
        if not _NONCE_RE.match(v):
            raise ValueError("Invalid nonce format")
        return v

    @field_validator("issued_at")
    @classmethod
    def validate_issued_at(cls, v: str) -> str:
        v = v.strip()
        if not _ISSUED_AT_RE.match(v):
            raise ValueError("issued_at must be ISO-8601 UTC (e.g. 2024-01-01T00:00:00Z)")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str = Field(description="ISO-8601 UTC expiry timestamp")
