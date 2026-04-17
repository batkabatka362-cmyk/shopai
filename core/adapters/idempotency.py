"""Adapter idempotency / result cache — Option V.

The router already has four gates (breaker → rate-limit → budget →
retry). This module adds a short-lived result cache *in front* of
all of them so a duplicate call doesn't trip any gate at all. In
practice the dashboard polls LLMs for the same summary three times
in five seconds, retries replay a just-succeeded call, and two
subagents independently ask the same research question — every one
of those pays cost + latency today for a result that is almost
certainly identical to the last one.

Design constraints:

* **Opt-in per capability** — the default policy dict is empty. A
  capability with no TTL declared is never cached. PAYMENT_CHARGE,
  EMAIL_SEND, and any other side-effecting op is safe by default.
* **Deterministic key** — ``(adapter_name, capability, params)``
  hashed with a canonical JSON serialization so reordered dict keys
  still produce the same key. Non-JSON-safe values fall back to
  ``repr()`` — the cache may thrash but never crash.
* **Bounded memory** — a size-limited LRU. Eviction keeps the most
  recent N entries; expired entries are removed lazily on read.
* **Only store successes** — a failure probably varies per call
  (auth error today ≠ rate-limit tomorrow), and caching it would
  turn a transient problem into a permanent one.
* **Thread-safe** — one ``RLock`` covers the LRU map; reads are
  short and don't block the adapter call itself.

The module exposes a process-wide singleton + a reset helper for
tests. Router integration is a three-line wrapper around each
dispatch.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .base import AdapterResult, Capability

logger = logging.getLogger(__name__)


# ── Policy ─────────────────────────────────────────────────────


@dataclass
class IdempotencyPolicy:
    """Per-capability TTL + scope declaration.

    ``ttl_s`` == 0 disables caching. ``shared_across_adapters`` is
    rare but useful for deterministic lookups (e.g. a product catalog
    fetch returns the same answer regardless of which adapter
    retrieves it). Default scope is per-adapter so two providers
    don't accidentally cross-contaminate.
    """

    ttl_s: float = 0.0
    shared_across_adapters: bool = False

    def __post_init__(self) -> None:
        if self.ttl_s < 0:
            raise ValueError("ttl_s must be >= 0")

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ttl_s": self.ttl_s,
            "shared_across_adapters": self.shared_across_adapters,
        }


#: Conservative defaults — only the capabilities that are both
#: read-only and expensive get a TTL. Anything with side effects
#: (payments, sends, writes) must NOT appear here.
DEFAULT_POLICIES: dict[Capability, IdempotencyPolicy] = {
    # Chat/LLM completions — short TTL protects "same question asked
    # twice in the same breath" without ever serving a stale answer
    # after prompts drift.
    Capability.CHAT_COMPLETE:   IdempotencyPolicy(ttl_s=5.0),
    Capability.EMBED_TEXT:      IdempotencyPolicy(ttl_s=600.0),
    # Search — results barely change inside a minute; longer TTL
    # turns a burst of research queries into a single vendor call.
    Capability.WEB_SEARCH:      IdempotencyPolicy(
        ttl_s=300.0, shared_across_adapters=True,
    ),
}


# ── Entry ──────────────────────────────────────────────────────


@dataclass
class _CacheEntry:
    """Single cached result + its lifetime bookkeeping."""
    result: AdapterResult
    stored_at: float
    ttl_s: float
    hits: int = 0

    def is_expired(self, now: float) -> bool:
        return (now - self.stored_at) >= self.ttl_s


# ── Stats ──────────────────────────────────────────────────────


@dataclass
class _Counters:
    """Process-wide hit/miss counters for the dashboard."""
    hits: int = 0
    misses: int = 0
    stores: int = 0
    evictions: int = 0
    skipped: int = 0  # capability had no policy / ttl=0


# ── Cache ──────────────────────────────────────────────────────


class IdempotencyCache:
    """LRU + TTL cache of ``AdapterResult`` values.

    Keyed by ``(capability, params_hash)`` when the policy is shared,
    otherwise by ``(adapter, capability, params_hash)``. ``get`` is
    a read-through: expired entries are removed atomically so the
    caller never sees a stale result. ``store`` is the only writer —
    called by the router after a successful adapter call.

    ``max_entries`` is the total number of keys held across every
    capability. Once full, the LRU evicts the oldest entry on each
    new insert. Default 1024 is a few MB worst-case and covers the
    dashboard + brain + retries scenarios comfortably.
    """

    def __init__(
        self,
        policies: dict[Capability, IdempotencyPolicy] | None = None,
        *,
        max_entries: int = 1024,
        clock=time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._policies: dict[Capability, IdempotencyPolicy] = dict(
            policies if policies is not None else DEFAULT_POLICIES
        )
        self._max_entries = max_entries
        self._clock = clock
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._counters = _Counters()

    # ── policy management ────────────────────────────────

    def set_policy(
        self, capability: Capability, policy: IdempotencyPolicy,
    ) -> None:
        """Register or replace the policy for ``capability``."""
        with self._lock:
            self._policies[capability] = policy

    def get_policy(
        self, capability: Capability,
    ) -> IdempotencyPolicy | None:
        return self._policies.get(capability)

    def policies(self) -> dict[Capability, IdempotencyPolicy]:
        with self._lock:
            return dict(self._policies)

    # ── key derivation ───────────────────────────────────

    @staticmethod
    def _hash_params(params: dict[str, Any] | None) -> str:
        """Stable hash of a parameter dict.

        JSON-serializable values go through ``sort_keys=True`` so
        dict ordering doesn't matter. Non-JSON-safe values fall
        back to ``repr`` — the cache may under-hit (two calls with
        the same custom object compare equal but hash differently)
        but it will never crash and it will never over-hit.
        """
        try:
            payload = json.dumps(
                params or {}, sort_keys=True, default=repr,
            )
        except Exception:  # noqa: BLE001
            payload = repr(params)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _key_for(
        self,
        adapter: str,
        capability: Capability,
        params: dict[str, Any] | None,
        policy: IdempotencyPolicy,
    ) -> str:
        """Build the cache key respecting the policy's sharing scope."""
        scope = "*" if policy.shared_across_adapters else adapter
        return f"{scope}::{capability.value}::{self._hash_params(params)}"

    # ── core API ─────────────────────────────────────────

    def get(
        self,
        adapter: str,
        capability: Capability,
        params: dict[str, Any] | None,
    ) -> AdapterResult | None:
        """Return a cached result or ``None``.

        Side effects (all under one lock):
          * increments hit / miss / skipped counters
          * marks the entry as recently used (LRU touch)
          * drops the entry if it has expired

        ``None`` is also returned when the capability has no policy
        registered — so the caller can just unconditionally check.
        """
        policy = self._policies.get(capability)
        if policy is None or not policy.enabled:
            with self._lock:
                self._counters.skipped += 1
            return None

        key = self._key_for(adapter, capability, params, policy)
        now = self._clock()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._counters.misses += 1
                return None
            if entry.is_expired(now):
                # Lazy eviction — drop the stale entry on read so
                # memory doesn't accumulate for keys we've stopped
                # requesting.
                self._store.pop(key, None)
                self._counters.misses += 1
                self._counters.evictions += 1
                return None
            # LRU touch — most recently used moves to the end.
            self._store.move_to_end(key)
            entry.hits += 1
            self._counters.hits += 1
            return entry.result

    def store(
        self,
        adapter: str,
        capability: Capability,
        params: dict[str, Any] | None,
        result: AdapterResult,
    ) -> bool:
        """Insert a successful result. Returns True if cached.

        Refuses to cache when:
          * no policy / ttl=0 for this capability
          * the result is not ``ok`` (don't persist failures)
        """
        policy = self._policies.get(capability)
        if policy is None or not policy.enabled:
            return False
        if not getattr(result, "ok", False):
            return False

        key = self._key_for(adapter, capability, params, policy)
        now = self._clock()
        with self._lock:
            self._store[key] = _CacheEntry(
                result=result,
                stored_at=now,
                ttl_s=policy.ttl_s,
            )
            self._store.move_to_end(key)
            self._counters.stores += 1
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)
                self._counters.evictions += 1
            return True

    # ── invalidation ─────────────────────────────────────

    def invalidate(
        self,
        adapter: str | None = None,
        capability: Capability | None = None,
    ) -> int:
        """Drop matching entries. Returns the number removed.

        With no arguments, the cache is cleared. With just
        ``capability``, every adapter's entries for that capability
        are cleared. Useful when a write (e.g. product update)
        invalidates a dependent read.
        """
        with self._lock:
            if adapter is None and capability is None:
                n = len(self._store)
                self._store.clear()
                return n
            prefix_a = adapter if adapter is not None else ""
            cap = capability.value if capability is not None else ""
            to_drop: list[str] = []
            for key in self._store:
                # Keys are "<scope>::<cap>::<hash>".
                parts = key.split("::", 2)
                if len(parts) < 3:
                    continue
                scope, this_cap, _ = parts
                if capability is not None and this_cap != cap:
                    continue
                if adapter is not None and scope not in (prefix_a, "*"):
                    continue
                to_drop.append(key)
            for key in to_drop:
                self._store.pop(key, None)
            return len(to_drop)

    # ── introspection ─────────────────────────────────────

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe counters + per-capability live entry counts."""
        now = self._clock()
        with self._lock:
            per_cap: dict[str, int] = {}
            live = 0
            for key, entry in self._store.items():
                if entry.is_expired(now):
                    continue
                live += 1
                cap = key.split("::", 2)[1] if "::" in key else key
                per_cap[cap] = per_cap.get(cap, 0) + 1
            total_lookups = self._counters.hits + self._counters.misses
            hit_rate = (
                self._counters.hits / total_lookups
                if total_lookups > 0 else 0.0
            )
            return {
                "hits": self._counters.hits,
                "misses": self._counters.misses,
                "stores": self._counters.stores,
                "evictions": self._counters.evictions,
                "skipped": self._counters.skipped,
                "size": len(self._store),
                "live": live,
                "max_entries": self._max_entries,
                "hit_rate": round(hit_rate, 4),
                "per_capability": per_cap,
                "policies": {
                    cap.value: pol.to_dict()
                    for cap, pol in self._policies.items()
                },
            }

    def reset(self) -> None:
        """Test helper — wipe cache + counters."""
        with self._lock:
            self._store.clear()
            self._counters = _Counters()


# ── Process-wide singleton ─────────────────────────────────────


_default_cache: IdempotencyCache | None = None
_default_lock = threading.Lock()


def get_idempotency_cache() -> IdempotencyCache:
    """Return the process-wide cache singleton.

    Populated with ``DEFAULT_POLICIES`` on first access so common
    LLM / search capabilities are deduped without any bootstrap
    code. Tests should call ``reset_idempotency_cache()`` between
    cases to start from a known state.
    """
    global _default_cache
    if _default_cache is None:
        with _default_lock:
            if _default_cache is None:
                _default_cache = IdempotencyCache()
    return _default_cache


def reset_idempotency_cache() -> None:
    """Drop the singleton so the next ``get`` rebuilds it."""
    global _default_cache
    with _default_lock:
        _default_cache = None
