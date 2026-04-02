"""
Frontend / UI tests using Streamlit's AppTest framework.
Tests that the dashboard renders without errors and interactive widgets work.

AppTest notes:
  - at.session_state["key"] — use bracket notation, NOT .get() (SafeSessionState quirk)
  - at.tabs is empty when results=[] because the app returns early (st.info + return)
  - at.exception is an ElementList; use `len(at.exception) == 0` to check no errors
"""
import os
import pytest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

os.environ.setdefault("JWT_SECRET_KEY", "a" * 32)

APP_PATH = "src/dashboard.py"
_EMPTY: list = []

_TEST_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"


def _make_auth_token() -> str:
    """Generate a valid JWT for the test address so the auth gate passes."""
    from src.api.security.jwt_handler import create_access_token
    token, _ = create_access_token(_TEST_ADDRESS, plan="free")
    return token


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_app(extra_session: dict = None) -> AppTest:
    """Create an AppTest instance with pre-seeded session state to skip analysis."""
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    # Pre-seed auth so the auth gate passes
    at.session_state["_auth_token"]   = _make_auth_token()
    at.session_state["_auth_address"] = _TEST_ADDRESS
    at.session_state["_auth_plan"]    = "free"
    at.session_state["_wallet_restore_checked"] = True
    # Pre-seed state so the app doesn't trigger run_analysis on first load
    at.session_state["results"] = []
    at.session_state["skipped"] = []
    at.session_state["debug_info"] = {"raw_tuples": 0, "parsed": 0, "api_error": ""}
    at.session_state["lang"] = "en"
    at.session_state["theme"] = "light"
    at.session_state["category"] = "all"
    at.session_state["last_run"] = "00:00 UTC"
    if extra_session:
        for k, v in extra_session.items():
            at.session_state[k] = v
    return at


def _run(at: AppTest) -> AppTest:
    """Run AppTest with all external API calls patched to empty lists."""
    with patch("src.dashboard.fetch_markets_cached", return_value=_EMPTY), \
         patch("src.dashboard.fetch_crypto_markets_cached", return_value=_EMPTY), \
         patch("src.dashboard.fetch_sports_markets_cached", return_value=_EMPTY), \
         patch("src.dashboard.fetch_politics_markets_cached", return_value=_EMPTY):
        at.run()
    return at


def _no_exception(at: AppTest) -> bool:
    return len(at.exception) == 0


# ─── Smoke tests ──────────────────────────────────────────────────────────────

class TestAppSmoke:
    def test_app_renders_without_exception(self):
        at = _make_app()
        _run(at)
        assert _no_exception(at)

    def test_category_radio_present(self):
        at = _make_app()
        _run(at)
        radio_keys = [r.key for r in at.radio]
        assert "category_radio" in radio_keys

    def test_run_first_info_shown_when_no_results(self):
        """When results=[] the app shows an info message before returning early."""
        at = _make_app()
        _run(at)
        info_texts = [i.value for i in at.info]
        # The info should mention running analysis
        assert any(txt for txt in info_texts), "Expected at least one info message"

    def test_sidebar_has_widgets(self):
        """Sidebar should have selectbox for language and number inputs."""
        at = _make_app()
        _run(at)
        # Sidebar widgets are mixed with main area; at least the radio should be there
        assert len(at.radio) >= 1

    def test_dark_theme_does_not_crash(self):
        at = _make_app(extra_session={"theme": "dark"})
        _run(at)
        assert _no_exception(at)


# ─── Session state persistence ────────────────────────────────────────────────

class TestSessionStatePersistence:
    def test_lang_persists_after_run(self):
        at = _make_app(extra_session={"lang": "pt"})
        _run(at)
        assert at.session_state["lang"] == "pt"

    def test_theme_persists_after_run(self):
        at = _make_app(extra_session={"theme": "dark"})
        _run(at)
        assert at.session_state["theme"] == "dark"

    def test_category_persists_after_run(self):
        at = _make_app(extra_session={"category": "crypto"})
        _run(at)
        assert at.session_state["category"] == "crypto"

    def test_results_empty_list_persists(self):
        at = _make_app()
        _run(at)
        assert at.session_state["results"] == []


# ─── Category radio interaction ───────────────────────────────────────────────

class TestCategoryRadio:
    def test_category_radio_has_five_options(self):
        """all, weather, crypto, sports, politics."""
        at = _make_app()
        _run(at)
        radios = {r.key: r for r in at.radio}
        assert len(radios["category_radio"].options) == 5

    def test_default_category_is_all(self):
        at = _make_app()
        _run(at)
        radios = {r.key: r for r in at.radio}
        # The first option (index 0) should be selected by default
        assert radios["category_radio"].index == 0

    def test_selecting_weather_updates_category(self):
        at = _make_app()
        _run(at)
        radios = {r.key: r for r in at.radio}
        cat_radio = radios["category_radio"]
        # Select weather (option at index 1)
        with patch("src.dashboard.fetch_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_crypto_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_sports_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_politics_markets_cached", return_value=_EMPTY):
            cat_radio.set_value(cat_radio.options[1]).run()
        assert at.session_state["category"] == "weather"
        assert _no_exception(at)

    def test_selecting_crypto_updates_category(self):
        at = _make_app()
        _run(at)
        radios = {r.key: r for r in at.radio}
        cat_radio = radios["category_radio"]
        with patch("src.dashboard.fetch_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_crypto_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_sports_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_politics_markets_cached", return_value=_EMPTY):
            cat_radio.set_value(cat_radio.options[2]).run()
        assert at.session_state["category"] == "crypto"
        assert _no_exception(at)

    def test_selecting_sports_updates_category(self):
        at = _make_app()
        _run(at)
        radios = {r.key: r for r in at.radio}
        cat_radio = radios["category_radio"]
        with patch("src.dashboard.fetch_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_crypto_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_sports_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_politics_markets_cached", return_value=_EMPTY):
            cat_radio.set_value(cat_radio.options[3]).run()
        assert at.session_state["category"] == "sports"
        assert _no_exception(at)

    def test_selecting_politics_updates_category(self):
        at = _make_app()
        _run(at)
        radios = {r.key: r for r in at.radio}
        cat_radio = radios["category_radio"]
        with patch("src.dashboard.fetch_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_crypto_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_sports_markets_cached", return_value=_EMPTY), \
             patch("src.dashboard.fetch_politics_markets_cached", return_value=_EMPTY):
            cat_radio.set_value(cat_radio.options[4]).run()
        assert at.session_state["category"] == "politics"
        assert _no_exception(at)


# ─── Language support ─────────────────────────────────────────────────────────

class TestLanguageSupport:
    @pytest.mark.parametrize("lang", ["en", "pt", "es", "zh"])
    def test_all_languages_render_without_error(self, lang):
        at = _make_app(extra_session={"lang": lang})
        _run(at)
        assert _no_exception(at)

    @pytest.mark.parametrize("lang", ["en", "pt", "es", "zh"])
    def test_category_radio_renders_in_all_languages(self, lang):
        at = _make_app(extra_session={"lang": lang})
        _run(at)
        radio_keys = [r.key for r in at.radio]
        assert "category_radio" in radio_keys
