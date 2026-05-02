"""Tiny in-memory share store with TTL.

Used by /share to hand out short-lived IDs that the Leaflet viewer can
fetch back. NOT durable — restarts wipe everything, and there's no
disk/Redis backend. Fine for personal/demo use; swap for a real KV store
if you ever publish a multi-instance deployment.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, Optional

DEFAULT_TTL_S = 60 * 60 * 24 * 7   # 7 days
MAX_ENTRIES = 1024


class ShareStore:
    def __init__(self, ttl_s: int = DEFAULT_TTL_S, max_entries: int = MAX_ENTRIES):
        self._ttl_s = ttl_s
        self._max = max_entries
        self._lock = threading.Lock()
        self._items: Dict[str, tuple[float, dict[str, Any]]] = {}

    def put(self, value: dict[str, Any]) -> str:
        share_id = secrets.token_urlsafe(8)
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            if len(self._items) >= self._max:
                # Drop the oldest entry to bound memory.
                oldest = min(self._items.items(), key=lambda kv: kv[1][0])[0]
                self._items.pop(oldest, None)
            self._items[share_id] = (now, value)
        return share_id

    def get(self, share_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            entry = self._items.get(share_id)
            if entry is None:
                return None
            created_at, value = entry
            if time.time() - created_at > self._ttl_s:
                self._items.pop(share_id, None)
                return None
            return value

    def ttl_seconds(self) -> int:
        return self._ttl_s

    # --- internal -----------------------------------------------------------

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._ttl_s
        expired = [sid for sid, (ts, _) in self._items.items() if ts < cutoff]
        for sid in expired:
            self._items.pop(sid, None)
