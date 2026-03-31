"""
Unit tests for src/bot/_supabase.py

Tests Telegram subscriber CRUD helpers — all HTTP calls are mocked.
No network, no Supabase credentials required.
"""
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot._supabase import (
    upsert_subscriber,
    deactivate_subscriber,
    get_active_subscribers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, json_body=None):
    """Build a minimal requests.Response mock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    resp.json.return_value = json_body or []
    return resp


def _env(monkeypatch):
    """Inject fake Supabase credentials via monkeypatch."""
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "fakekey123")


# ---------------------------------------------------------------------------
# _creds helper (indirect — tested via public functions)
# ---------------------------------------------------------------------------

class TestCredsResolution:
    def test_returns_false_when_no_env(self):
        """All public functions return False/[] when credentials are missing."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any lingering env vars
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
            assert upsert_subscriber(123) is False
            assert deactivate_subscriber(123) is False
            assert get_active_subscribers() == []


# ---------------------------------------------------------------------------
# upsert_subscriber
# ---------------------------------------------------------------------------

class TestUpsertSubscriber:
    def test_success_on_201(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post") as mock_post:
            mock_post.return_value = _mock_response(201)
            result = upsert_subscriber(chat_id=111, username="alice", edge_threshold=0.10)
        assert result is True

    def test_success_on_200(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post") as mock_post:
            mock_post.return_value = _mock_response(200)
            result = upsert_subscriber(chat_id=222)
        assert result is True

    def test_failure_on_4xx(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post") as mock_post:
            mock_post.return_value = _mock_response(400)
            result = upsert_subscriber(chat_id=333)
        assert result is False

    def test_failure_on_network_error(self, monkeypatch):
        import requests as _req
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post", side_effect=_req.RequestException("timeout")):
            result = upsert_subscriber(chat_id=444)
        assert result is False

    def test_payload_contains_chat_id(self, monkeypatch):
        """POST body must include chat_id and active=True."""
        import json
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post") as mock_post:
            mock_post.return_value = _mock_response(201)
            upsert_subscriber(chat_id=555, username="bob", edge_threshold=0.15)
        call_kwargs = mock_post.call_args
        body = json.loads(call_kwargs.kwargs.get("data") or call_kwargs.args[1]
                          if len(call_kwargs.args) > 1 else call_kwargs.kwargs["data"])
        assert body["chat_id"] == 555
        assert body["active"] is True
        assert body["edge_threshold"] == 0.15

    def test_edge_threshold_rounded(self, monkeypatch):
        import json
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post") as mock_post:
            mock_post.return_value = _mock_response(201)
            upsert_subscriber(chat_id=666, edge_threshold=0.123456789)
        call_kwargs = mock_post.call_args
        body = json.loads(call_kwargs.kwargs["data"])
        assert body["edge_threshold"] == round(0.123456789, 4)

    def test_uses_merge_duplicates_prefer_header(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.post") as mock_post:
            mock_post.return_value = _mock_response(201)
            upsert_subscriber(chat_id=777)
        headers = mock_post.call_args.kwargs.get("headers", {})
        assert "merge-duplicates" in headers.get("Prefer", "")


# ---------------------------------------------------------------------------
# deactivate_subscriber
# ---------------------------------------------------------------------------

class TestDeactivateSubscriber:
    def test_success_on_204(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.patch") as mock_patch:
            mock_patch.return_value = _mock_response(204)
            result = deactivate_subscriber(chat_id=100)
        assert result is True

    def test_success_on_200(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.patch") as mock_patch:
            mock_patch.return_value = _mock_response(200)
            result = deactivate_subscriber(chat_id=101)
        assert result is True

    def test_failure_on_5xx(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.patch") as mock_patch:
            mock_patch.return_value = _mock_response(500)
            result = deactivate_subscriber(chat_id=102)
        assert result is False

    def test_failure_on_network_error(self, monkeypatch):
        import requests as _req
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.patch", side_effect=_req.RequestException("conn")):
            result = deactivate_subscriber(chat_id=103)
        assert result is False

    def test_sets_active_false(self, monkeypatch):
        import json
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.patch") as mock_patch:
            mock_patch.return_value = _mock_response(204)
            deactivate_subscriber(chat_id=104)
        body = json.loads(mock_patch.call_args.kwargs["data"])
        assert body["active"] is False

    def test_filters_by_chat_id(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.patch") as mock_patch:
            mock_patch.return_value = _mock_response(204)
            deactivate_subscriber(chat_id=105)
        params = mock_patch.call_args.kwargs.get("params", {})
        assert params.get("chat_id") == "eq.105"

    def test_returns_false_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
            assert deactivate_subscriber(999) is False


# ---------------------------------------------------------------------------
# get_active_subscribers
# ---------------------------------------------------------------------------

class TestGetActiveSubscribers:
    def test_returns_list_on_success(self, monkeypatch):
        _env(monkeypatch)
        fake_data = [
            {"chat_id": 1, "username": "alice", "edge_threshold": 0.10},
            {"chat_id": 2, "username": "bob",   "edge_threshold": 0.15},
        ]
        with patch("src.bot._supabase.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, fake_data)
            result = get_active_subscribers()
        assert len(result) == 2
        assert result[0]["chat_id"] == 1

    def test_returns_empty_on_404(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.get") as mock_get:
            mock_get.return_value = _mock_response(404)
            result = get_active_subscribers()
        assert result == []

    def test_returns_empty_on_network_error(self, monkeypatch):
        import requests as _req
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.get", side_effect=_req.RequestException("dns")):
            result = get_active_subscribers()
        assert result == []

    def test_returns_empty_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
            assert get_active_subscribers() == []

    def test_filters_active_true(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, [])
            get_active_subscribers()
        params = mock_get.call_args.kwargs.get("params", {})
        assert params.get("active") == "eq.true"

    def test_selects_correct_columns(self, monkeypatch):
        _env(monkeypatch)
        with patch("src.bot._supabase.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, [])
            get_active_subscribers()
        params = mock_get.call_args.kwargs.get("params", {})
        assert "chat_id" in params.get("select", "")
        assert "edge_threshold" in params.get("select", "")

    def test_handles_null_json_response(self, monkeypatch):
        """Supabase may return null instead of [] — must handle gracefully."""
        _env(monkeypatch)
        resp = _mock_response(200)
        resp.json.return_value = None
        with patch("src.bot._supabase.requests.get", return_value=resp):
            result = get_active_subscribers()
        assert result == []
