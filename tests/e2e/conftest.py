"""
Playwright E2E test fixtures for polyMad.

Strategy:
  - Both FastAPI (port 8000) and Streamlit (port 8501) are started as
    subprocess fixtures with scope="session".
  - MetaMask is mocked via page.add_init_script() — no real browser extension
    required.  A deterministic test private key is used so signatures are
    reproducible.
  - The test private key is Hardhat/Foundry account #0 (well-known, zero funds).

Usage:
    pytest tests/e2e/ -v
    # Requires: pip install playwright && playwright install chromium
"""
import os
import signal
import subprocess
import sys
import time
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FASTAPI_URL = "http://localhost:8000"
STREAMLIT_URL = "http://localhost:8501"

# Hardhat/Foundry test account #0 — NEVER use in production
TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# A minimal JWT_SECRET_KEY for test processes
_TEST_JWT_SECRET = "x" * 32

# ---------------------------------------------------------------------------
# Process fixtures
# ---------------------------------------------------------------------------

def _wait_for_http(url: str, timeout: int = 30) -> bool:
    """Poll url until it responds 200 or timeout (seconds)."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="session")
def fastapi_process():
    """Start the FastAPI backend for E2E tests."""
    env = {**os.environ, "JWT_SECRET_KEY": _TEST_JWT_SECRET}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app",
         "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_http(f"{FASTAPI_URL}/health"):
        proc.terminate()
        pytest.skip("FastAPI did not start in time — skipping E2E tests")
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def streamlit_process(fastapi_process):
    """Start the Streamlit dashboard for E2E tests."""
    env = {
        **os.environ,
        "JWT_SECRET_KEY": _TEST_JWT_SECRET,
        "FASTAPI_INTERNAL_URL": FASTAPI_URL,
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "src/dashboard.py",
         "--server.port=8501", "--server.headless=true",
         "--server.enableCORS=false", "--server.enableXsrfProtection=false"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_http(f"{STREAMLIT_URL}/_stcore/health"):
        proc.terminate()
        pytest.skip("Streamlit did not start in time — skipping E2E tests")
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Playwright page fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def page(streamlit_process):
    """Return a fresh Playwright page (sync API)."""
    pytest.importorskip("playwright", reason="playwright not installed")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        pg = context.new_page()
        yield pg
        context.close()
        browser.close()


def _sign_eip712_locally(address: str, nonce: str, issued_at: str) -> str:
    """
    Sign an EIP-712 message locally with the test private key.
    Used to produce a valid signature for the mock window.ethereum.
    """
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
    signed = Account.sign_message(signable, private_key=TEST_PRIVATE_KEY)
    sig = signed.signature
    return sig.hex() if isinstance(sig, bytes) else sig


@pytest.fixture
def mock_metamask_page(page):
    """
    Inject a mock window.ethereum into the page before any navigation.
    The mock auto-approves eth_requestAccounts and signs EIP-712 messages
    using the test private key via a page.evaluate call.

    The signing is delegated to a Python helper (_sign_eip712_locally) invoked
    via page.evaluate to keep the key server-side.
    """
    # The JS mock intercepts eth_signTypedData_v4 and returns a placeholder.
    # The actual signature is computed server-side and injected before calling.
    page.add_init_script(f"""
        window._testAddress = '{TEST_ADDRESS}';
        window._testSignature = null;  // will be set before signing

        window.ethereum = {{
            isMetaMask: true,
            request: async (args) => {{
                if (args.method === 'eth_requestAccounts' || args.method === 'eth_accounts') {{
                    return [window._testAddress];
                }}
                if (args.method === 'eth_signTypedData_v4') {{
                    // Return the pre-computed signature (set by the test via page.evaluate)
                    if (!window._testSignature) {{
                        throw new Error('Test signature not set — call page.evaluate to set window._testSignature');
                    }}
                    return window._testSignature;
                }}
                throw new Error('Unsupported method: ' + args.method);
            }}
        }};
    """)
    return page
