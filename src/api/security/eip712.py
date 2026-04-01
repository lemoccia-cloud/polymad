"""
EIP-712 typed structured data signature verification.

The domain separator binds signatures to this specific application and chain,
preventing cross-app and cross-chain replay attacks.
"""
from typing import Any

# ---------------------------------------------------------------------------
# EIP-712 Domain & Types
# ---------------------------------------------------------------------------

EIP712_DOMAIN: dict[str, Any] = {
    "name": "polyMad",
    "version": "1",
    # chainId intentionally omitted: this is a sign-in message, not a transaction.
    # MetaMask requires chainId to match the active network, which would break
    # users on any chain other than Polygon. The nonce provides replay protection.
}

EIP712_TYPES: dict[str, Any] = {
    "EIP712Domain": [
        {"name": "name",    "type": "string"},
        {"name": "version", "type": "string"},
    ],
    "Authentication": [
        {"name": "wallet",   "type": "address"},
        {"name": "nonce",    "type": "string"},
        {"name": "issuedAt", "type": "string"},
        {"name": "appName",  "type": "string"},
    ],
}

EIP712_PRIMARY_TYPE = "Authentication"


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def verify_eip712_signature(
    address: str,
    nonce: str,
    issued_at: str,
    signature: str,
) -> bool:
    """
    Recover the signer from an EIP-712 typed-data signature and compare
    to the claimed address.

    Returns True only when the recovered signer matches `address`
    (case-insensitive).  Returns False on ANY error or mismatch —
    never raises.

    Args:
        address:    Claimed wallet address (0x-prefixed hex, 40 chars).
        nonce:      The server-issued nonce that was embedded in the message.
        issued_at:  ISO-8601 UTC timestamp embedded in the signed message.
        signature:  0x-prefixed hex EIP-712 signature from MetaMask.
    """
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        from eth_utils import to_checksum_address

        structured_data: dict[str, Any] = {
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
        recovered: str = Account.recover_message(signable, signature=signature)
        return recovered.lower() == address.lower()
    except Exception:
        return False


def build_eip712_message(address: str, nonce: str, issued_at: str) -> dict[str, Any]:
    """
    Build the full EIP-712 typed-data object to send to the browser for signing.
    The JavaScript side passes this to eth_signTypedData_v4.
    """
    try:
        from eth_utils import to_checksum_address
        checksum_addr = to_checksum_address(address)
    except Exception:
        checksum_addr = address

    return {
        "domain": EIP712_DOMAIN,
        "types": EIP712_TYPES,
        "primaryType": EIP712_PRIMARY_TYPE,
        "message": {
            "wallet":   checksum_addr,
            "nonce":    nonce,
            "issuedAt": issued_at,
            "appName":  "polyMad",
        },
    }
