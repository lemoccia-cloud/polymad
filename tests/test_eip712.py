"""
Unit tests for EIP-712 signature verification.

Uses eth_account to generate real key pairs and produce verifiable test vectors.
All tests are deterministic — the test private key is hardcoded and well-known.
"""
import pytest

# Hardcoded test key (Hardhat/Foundry default account #0 — NEVER use in production)
TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
TEST_NONCE = "test-nonce-abc123"
TEST_ISSUED_AT = "2024-01-01T00:00:00Z"

# Some tests require eth_account; skip gracefully if not installed
eth_account = pytest.importorskip("eth_account", reason="eth_account not installed")


def _sign_eip712(address: str, nonce: str, issued_at: str, private_key: str) -> str:
    """Helper: sign EIP-712 typed data with a local private key (test use only)."""
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    from eth_utils import to_checksum_address
    from src.api.security.eip712 import EIP712_DOMAIN, EIP712_TYPES, EIP712_PRIMARY_TYPE

    structured_data = {
        "domain": EIP712_DOMAIN,
        "types": EIP712_TYPES,
        "primaryType": EIP712_PRIMARY_TYPE,
        "message": {
            "wallet":   to_checksum_address(address),
            "nonce":    nonce,
            "issuedAt": issued_at,
            "appName":  "polyMad",
        },
    }
    signable = encode_typed_data(full_message=structured_data)
    signed = Account.sign_message(signable, private_key=private_key)
    return signed.signature.hex() if not isinstance(signed.signature, str) else signed.signature


# ── Signature verification ────────────────────────────────────────────────────

class TestVerifyEip712Signature:
    def test_valid_signature_returns_true(self):
        from src.api.security.eip712 import verify_eip712_signature
        sig = _sign_eip712(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT, TEST_PRIVATE_KEY)
        result = verify_eip712_signature(
            address=TEST_ADDRESS,
            nonce=TEST_NONCE,
            issued_at=TEST_ISSUED_AT,
            signature=sig,
        )
        assert result is True

    def test_wrong_address_returns_false(self):
        from src.api.security.eip712 import verify_eip712_signature
        sig = _sign_eip712(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT, TEST_PRIVATE_KEY)
        wrong_address = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"
        result = verify_eip712_signature(
            address=wrong_address,
            nonce=TEST_NONCE,
            issued_at=TEST_ISSUED_AT,
            signature=sig,
        )
        assert result is False

    def test_tampered_nonce_returns_false(self):
        from src.api.security.eip712 import verify_eip712_signature
        sig = _sign_eip712(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT, TEST_PRIVATE_KEY)
        result = verify_eip712_signature(
            address=TEST_ADDRESS,
            nonce="tampered-nonce",
            issued_at=TEST_ISSUED_AT,
            signature=sig,
        )
        assert result is False

    def test_tampered_issued_at_returns_false(self):
        from src.api.security.eip712 import verify_eip712_signature
        sig = _sign_eip712(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT, TEST_PRIVATE_KEY)
        result = verify_eip712_signature(
            address=TEST_ADDRESS,
            nonce=TEST_NONCE,
            issued_at="2099-01-01T00:00:00Z",
            signature=sig,
        )
        assert result is False

    def test_malformed_signature_returns_false(self):
        from src.api.security.eip712 import verify_eip712_signature
        result = verify_eip712_signature(
            address=TEST_ADDRESS,
            nonce=TEST_NONCE,
            issued_at=TEST_ISSUED_AT,
            signature="0xdeadbeef",
        )
        assert result is False

    def test_empty_signature_returns_false(self):
        from src.api.security.eip712 import verify_eip712_signature
        result = verify_eip712_signature(
            address=TEST_ADDRESS,
            nonce=TEST_NONCE,
            issued_at=TEST_ISSUED_AT,
            signature="",
        )
        assert result is False

    def test_empty_address_returns_false(self):
        from src.api.security.eip712 import verify_eip712_signature
        sig = _sign_eip712(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT, TEST_PRIVATE_KEY)
        result = verify_eip712_signature(
            address="",
            nonce=TEST_NONCE,
            issued_at=TEST_ISSUED_AT,
            signature=sig,
        )
        assert result is False

    def test_case_insensitive_address_comparison(self):
        from src.api.security.eip712 import verify_eip712_signature
        sig = _sign_eip712(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT, TEST_PRIVATE_KEY)
        # Address provided in lowercase
        result = verify_eip712_signature(
            address=TEST_ADDRESS.lower(),
            nonce=TEST_NONCE,
            issued_at=TEST_ISSUED_AT,
            signature=sig,
        )
        assert result is True

    def test_never_raises_on_garbage_input(self):
        from src.api.security.eip712 import verify_eip712_signature
        # Should return False, not raise any exception
        result = verify_eip712_signature(
            address="not-an-address",
            nonce="",
            issued_at="not-a-timestamp",
            signature="garbage",
        )
        assert result is False


# ── build_eip712_message ──────────────────────────────────────────────────────

class TestBuildEip712Message:
    def test_returns_dict_with_required_keys(self):
        from src.api.security.eip712 import build_eip712_message
        msg = build_eip712_message(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT)
        assert "domain" in msg
        assert "types" in msg
        assert "primaryType" in msg
        assert "message" in msg

    def test_message_contains_nonce(self):
        from src.api.security.eip712 import build_eip712_message
        msg = build_eip712_message(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT)
        assert msg["message"]["nonce"] == TEST_NONCE

    def test_message_contains_app_name(self):
        from src.api.security.eip712 import build_eip712_message
        msg = build_eip712_message(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT)
        assert msg["message"]["appName"] == "polyMad"

    def test_domain_has_no_chain_id(self):
        """chainId is intentionally absent — auth messages are chain-agnostic."""
        from src.api.security.eip712 import build_eip712_message, EIP712_DOMAIN
        msg = build_eip712_message(TEST_ADDRESS, TEST_NONCE, TEST_ISSUED_AT)
        assert "chainId" not in msg["domain"]
        assert "verifyingContract" not in msg["domain"]
