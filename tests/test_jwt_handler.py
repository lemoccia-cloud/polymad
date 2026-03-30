"""Unit tests for JWT creation, decoding, and secret validation."""
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from jose import jwt as jose_jwt

# Use a 32-char test secret — meets minimum length requirement
TEST_SECRET = "a" * 32
TEST_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"

# Set at module level so _get_secret() passes on import
os.environ["JWT_SECRET_KEY"] = TEST_SECRET


def _patch_secret(secret: str = TEST_SECRET):
    """Context manager / decorator that patches JWT_SECRET_KEY env var."""
    return patch.dict(os.environ, {"JWT_SECRET_KEY": secret})


# ── Secret validation ─────────────────────────────────────────────────────────

class TestGetSecret:
    def test_missing_secret_raises(self):
        from src.api.security.jwt_handler import _get_secret
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("JWT_SECRET_KEY", None)
            with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
                _get_secret()

    def test_short_secret_raises(self):
        from src.api.security.jwt_handler import _get_secret
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "tooshort"}):
            with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
                _get_secret()

    def test_valid_secret_returns_string(self):
        from src.api.security.jwt_handler import _get_secret
        with _patch_secret():
            result = _get_secret()
            assert result == TEST_SECRET


# ── Create access token ───────────────────────────────────────────────────────

class TestCreateAccessToken:
    def test_returns_string_and_expiry(self):
        from src.api.security.jwt_handler import create_access_token
        with _patch_secret():
            token, expiry = create_access_token(TEST_ADDRESS)
        assert isinstance(token, str)
        assert len(token) > 10
        assert isinstance(expiry, datetime)

    def test_expiry_is_approx_60_minutes(self):
        from src.api.security.jwt_handler import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
        with _patch_secret():
            _, expiry = create_access_token(TEST_ADDRESS)
        now = datetime.now(timezone.utc)
        delta = (expiry - now).total_seconds()
        assert abs(delta - ACCESS_TOKEN_EXPIRE_MINUTES * 60) < 5

    def test_address_is_lowercased_in_sub(self):
        from src.api.security.jwt_handler import create_access_token
        mixed_addr = "0xF39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        with _patch_secret():
            token, _ = create_access_token(mixed_addr)
            payload = jose_jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["sub"] == mixed_addr.lower()

    def test_typ_claim_is_access(self):
        from src.api.security.jwt_handler import create_access_token
        with _patch_secret():
            token, _ = create_access_token(TEST_ADDRESS)
            payload = jose_jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["typ"] == "access"

    def test_jti_is_unique_per_token(self):
        from src.api.security.jwt_handler import create_access_token
        with _patch_secret():
            t1, _ = create_access_token(TEST_ADDRESS)
            t2, _ = create_access_token(TEST_ADDRESS)
            p1 = jose_jwt.decode(t1, TEST_SECRET, algorithms=["HS256"])
            p2 = jose_jwt.decode(t2, TEST_SECRET, algorithms=["HS256"])
        assert p1["jti"] != p2["jti"]


# ── Decode access token ───────────────────────────────────────────────────────

class TestDecodeAccessToken:
    def test_valid_token_returns_address(self):
        from src.api.security.jwt_handler import create_access_token, decode_access_token
        with _patch_secret():
            token, _ = create_access_token(TEST_ADDRESS)
            result = decode_access_token(token)
        assert result == TEST_ADDRESS

    def test_malformed_token_returns_none(self):
        from src.api.security.jwt_handler import decode_access_token
        with _patch_secret():
            assert decode_access_token("not.a.jwt") is None

    def test_wrong_secret_returns_none(self):
        from src.api.security.jwt_handler import create_access_token, decode_access_token
        with _patch_secret():
            token, _ = create_access_token(TEST_ADDRESS)
        # Decode with a different secret
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "b" * 32}):
            assert decode_access_token(token) is None

    def test_wrong_typ_returns_none(self):
        from src.api.security.jwt_handler import decode_access_token
        payload = {
            "sub": TEST_ADDRESS,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            "typ": "refresh",  # wrong type
        }
        with _patch_secret():
            token = jose_jwt.encode(payload, TEST_SECRET, algorithm="HS256")
            result = decode_access_token(token)
        assert result is None

    def test_expired_token_returns_none(self):
        from src.api.security.jwt_handler import decode_access_token
        payload = {
            "sub": TEST_ADDRESS,
            "iat": int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()),
            "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),  # past
            "typ": "access",
        }
        with _patch_secret():
            token = jose_jwt.encode(payload, TEST_SECRET, algorithm="HS256")
            result = decode_access_token(token)
        assert result is None

    def test_previous_secret_accepted_during_rotation(self):
        """Tokens signed with the previous secret are accepted during rotation grace period."""
        from src.api.security.jwt_handler import create_access_token, decode_access_token
        old_secret = "c" * 32
        new_secret = "d" * 32
        with patch.dict(os.environ, {"JWT_SECRET_KEY": old_secret}):
            token, _ = create_access_token(TEST_ADDRESS)
        # Now rotate: new secret current, old in PREVIOUS
        with patch.dict(os.environ, {
            "JWT_SECRET_KEY": new_secret,
            "JWT_SECRET_KEY_PREVIOUS": old_secret,
        }):
            result = decode_access_token(token)
        assert result == TEST_ADDRESS
