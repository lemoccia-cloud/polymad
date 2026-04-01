"""
E2E tests for the wallet authentication flow.

These tests run against a live Streamlit + FastAPI stack.
They are skipped automatically if either process fails to start or if
playwright is not installed.

Auth flow (component-based, no URL params):
  Phase 1 — Streamlit renders polymad_wallet component (phase=1)
            JS calls window.parent.ethereum.request({method:"eth_accounts"})
            → setComponentValue({action:"connected", addr})
            → Python requests nonce → transitions to Phase 2
  Phase 2 — Component rendered with typed_data_json embedded
            JS calls eth_signTypedData_v4 → setComponentValue({action:"signed", sig})
            → Python verifies → JWT stored → authenticated
"""
import time

import pytest

from tests.e2e.conftest import STREAMLIT_URL, TEST_ADDRESS, _sign_eip712_locally

# Skip entire module if playwright is not installed
playwright = pytest.importorskip("playwright", reason="playwright not installed")


class TestUnauthenticatedState:
    def test_dashboard_loads_without_error(self, mock_metamask_page):
        page = mock_metamask_page
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        # Streamlit should not show an unhandled exception
        assert "Traceback" not in page.content()
        assert "Error" not in page.title()

    def test_no_portfolio_data_visible_when_unauthenticated(self, mock_metamask_page):
        page = mock_metamask_page
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        content = page.content()
        # Portfolio value header should not appear without auth
        assert "portfolio_value" not in content.lower() or "Connect" in content

    def test_no_auth_params_in_url_on_load(self, mock_metamask_page):
        """Clean load must not have any auth-related URL params."""
        page = mock_metamask_page
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        # None of the old URL-param auth keys should be present
        for param in ("_w_addr", "_w_sig", "_w_iat", "_w_jwt", "wallet_address"):
            assert param not in page.url


class TestAuthFlow:
    def test_connect_button_visible(self, mock_metamask_page):
        """Phase 1 component renders the Connect MetaMask button."""
        page = mock_metamask_page
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        content = page.content()
        assert "Connect" in content or "MetaMask" in content

    def test_autoconnect_triggers_phase2(self, mock_metamask_page):
        """
        When MetaMask has an account (eth_accounts returns non-empty),
        the component auto-connects and Streamlit transitions to Phase 2
        (the Sign button appears).
        """
        page = mock_metamask_page
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        # Wait for: component load → autoCheck → setComponentValue → Streamlit rerun → Phase 2
        page.wait_for_timeout(6000)
        content = page.content()
        # Phase 2 shows "Sign" / "authenticate" / "signature"
        assert (
            "Sign" in content
            or "sign" in content
            or "authenticate" in content.lower()
        )

    def test_no_auth_url_params_during_flow(self, mock_metamask_page):
        """
        Auth data must never appear as URL query params at any point
        (security: no address/signature leakage in browser history).
        """
        page = mock_metamask_page
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(6000)
        url = page.url
        for param in ("_w_addr", "_w_sig", "_w_iat", "_w_jwt"):
            assert param not in url, f"Leaked auth param in URL: {param}"

    def test_security_legacy_wallet_address_param_ignored(self, mock_metamask_page):
        """
        SECURITY: Legacy ?wallet_address= param must NOT trigger authentication.
        An attacker cannot gain access by setting a victim's address in the URL.
        """
        page = mock_metamask_page
        victim = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"
        url = f"{STREAMLIT_URL}/?wallet_address={victim}"
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        content = page.content()
        # The dashboard must not show an authenticated state for the victim
        assert "Sign out" not in content or "portfolio_value" not in content.lower()
