"""
Thread-safe in-memory nonce store for EIP-712 authentication.

Each nonce is single-use and expires after NONCE_TTL_SECONDS.
Replay attacks are blocked atomically under a threading.Lock.
"""
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

NONCE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class _NonceEntry:
    nonce: str
    address: str        # always lowercase
    created_at: datetime
    used: bool = field(default=False)


class NonceStore:
    """
    Thread-safe in-memory nonce store.
    One active nonce per address at a time — requesting a new nonce
    overwrites the previous one for that address.
    """

    def __init__(self) -> None:
        self._store: dict[str, _NonceEntry] = {}
        self._lock = threading.Lock()

    def create(self, address: str) -> str:
        """
        Generate and store a cryptographically secure nonce for the given address.
        Any existing (unused) nonce for this address is discarded.
        Returns the new nonce string.
        """
        nonce = secrets.token_urlsafe(32)
        entry = _NonceEntry(
            nonce=nonce,
            address=address.lower(),
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._store[address.lower()] = entry
        return nonce

    def consume(self, address: str, nonce: str) -> bool:
        """
        Validate and atomically consume a nonce.

        Returns True only when ALL conditions hold:
          - an entry exists for this address
          - the stored nonce matches the provided nonce
          - the nonce has not been used before
          - the nonce has not expired (< NONCE_TTL_SECONDS old)

        On True: the entry is permanently deleted (single use).
        On False: the entry is left unchanged (except expiry → delete).
        Never raises — all error paths return False.
        """
        addr_key = address.lower()
        with self._lock:
            entry = self._store.get(addr_key)
            if entry is None:
                return False
            if entry.used:
                return False
            if entry.nonce != nonce:
                return False
            age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
            if age > NONCE_TTL_SECONDS:
                del self._store[addr_key]
                return False
            # All checks passed — consume and delete
            del self._store[addr_key]
            return True

    def purge_expired(self) -> int:
        """
        Remove all expired entries. Safe to call periodically from a background task.
        Returns the number of entries removed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=NONCE_TTL_SECONDS)
        with self._lock:
            expired_keys = [k for k, v in self._store.items() if v.created_at < cutoff]
            for k in expired_keys:
                del self._store[k]
        return len(expired_keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Module-level singleton shared across the FastAPI app lifetime
nonce_store = NonceStore()
