"""Unit tests for NonceStore — thread-safe in-memory nonce lifecycle."""
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from src.api.security.nonce_store import NonceStore, NONCE_TTL_SECONDS


def make_store() -> NonceStore:
    return NonceStore()


# ── Create ────────────────────────────────────────────────────────────────────

class TestNonceCreate:
    def test_returns_nonempty_string(self):
        store = make_store()
        nonce = store.create("0xabcdef1234567890abcdef1234567890abcdef12")
        assert isinstance(nonce, str)
        assert len(nonce) > 20

    def test_each_call_produces_unique_nonce(self):
        store = make_store()
        addr = "0xabcdef1234567890abcdef1234567890abcdef12"
        n1 = store.create(addr)
        n2 = store.create(addr)
        assert n1 != n2

    def test_overrides_previous_nonce_for_same_address(self):
        store = make_store()
        addr = "0xabcdef1234567890abcdef1234567890abcdef12"
        old_nonce = store.create(addr)
        store.create(addr)  # override
        # old nonce should no longer be consumable
        assert store.consume(addr, old_nonce) is False

    def test_different_addresses_independent(self):
        store = make_store()
        addr1 = "0x" + "a" * 40
        addr2 = "0x" + "b" * 40
        n1 = store.create(addr1)
        n2 = store.create(addr2)
        assert store.consume(addr1, n1) is True
        assert store.consume(addr2, n2) is True

    def test_len_increases(self):
        store = make_store()
        assert len(store) == 0
        store.create("0x" + "a" * 40)
        assert len(store) == 1
        store.create("0x" + "b" * 40)
        assert len(store) == 2


# ── Consume ───────────────────────────────────────────────────────────────────

class TestNonceConsume:
    def test_valid_nonce_returns_true(self):
        store = make_store()
        addr = "0x" + "a" * 40
        nonce = store.create(addr)
        assert store.consume(addr, nonce) is True

    def test_wrong_nonce_returns_false(self):
        store = make_store()
        addr = "0x" + "a" * 40
        store.create(addr)
        assert store.consume(addr, "wrong-nonce") is False

    def test_used_nonce_cannot_be_replayed(self):
        store = make_store()
        addr = "0x" + "a" * 40
        nonce = store.create(addr)
        assert store.consume(addr, nonce) is True
        assert store.consume(addr, nonce) is False  # replay blocked

    def test_unknown_address_returns_false(self):
        store = make_store()
        assert store.consume("0x" + "a" * 40, "anything") is False

    def test_case_insensitive_address_matching(self):
        store = make_store()
        addr_lower = "0x" + "a" * 40
        addr_upper = "0x" + "A" * 40
        nonce = store.create(addr_lower)
        # consume with uppercase variant should work
        assert store.consume(addr_upper, nonce) is True

    def test_entry_deleted_after_consume(self):
        store = make_store()
        addr = "0x" + "a" * 40
        nonce = store.create(addr)
        assert len(store) == 1
        store.consume(addr, nonce)
        assert len(store) == 0

    def test_expired_nonce_returns_false(self):
        store = make_store()
        addr = "0x" + "a" * 40
        nonce = store.create(addr)
        # Simulate the nonce being created 10 minutes ago
        past = datetime.now(timezone.utc) - timedelta(seconds=NONCE_TTL_SECONDS + 60)
        with store._lock:
            store._store[addr.lower()].created_at = past
        assert store.consume(addr, nonce) is False

    def test_expired_nonce_is_removed_from_store(self):
        store = make_store()
        addr = "0x" + "a" * 40
        nonce = store.create(addr)
        past = datetime.now(timezone.utc) - timedelta(seconds=NONCE_TTL_SECONDS + 60)
        with store._lock:
            store._store[addr.lower()].created_at = past
        store.consume(addr, nonce)
        assert len(store) == 0


# ── Purge ─────────────────────────────────────────────────────────────────────

class TestNoncePurge:
    def test_purge_removes_expired_entries(self):
        store = make_store()
        addr = "0x" + "a" * 40
        store.create(addr)
        past = datetime.now(timezone.utc) - timedelta(seconds=NONCE_TTL_SECONDS + 60)
        with store._lock:
            store._store[addr.lower()].created_at = past
        removed = store.purge_expired()
        assert removed == 1
        assert len(store) == 0

    def test_purge_leaves_fresh_entries(self):
        store = make_store()
        store.create("0x" + "a" * 40)
        store.create("0x" + "b" * 40)
        removed = store.purge_expired()
        assert removed == 0
        assert len(store) == 2

    def test_purge_returns_count(self):
        store = make_store()
        past = datetime.now(timezone.utc) - timedelta(seconds=NONCE_TTL_SECONDS + 60)
        for suffix in ("a", "b", "c"):
            addr = "0x" + suffix * 40
            store.create(addr)
            with store._lock:
                store._store[addr.lower()].created_at = past
        removed = store.purge_expired()
        assert removed == 3
