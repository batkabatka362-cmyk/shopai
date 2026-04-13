"""LLMCache — TTL + LRU cache for LLM responses.

LLM tokens are expensive (and slow). Many cognitive cycles ask
near-identical questions repeatedly:

    - Reflection on the same N episodes
    - Imagination scoring the same plan twice
    - Curiosity asking "what should I explore" with the same
      capability set

A cache that returns the previous answer in microseconds saves
real money on API providers and real latency on local Ollama.

Design:

    - Key: SHA1 of (role, model, system_prompt, user_prompt)
      so different roles / system prompts don't collide
    - Value: the full LLMResponse dataclass (text, tokens, etc.)
    - TTL per entry (default 1 hour)
    - LRU eviction when the cache exceeds max_entries (default 256)
    - Thread-safe via an internal RLock
    - Stats: hits, misses, evictions, hit_rate

The cache is OPT-IN. Cognitive modules that want it call
`get_llm_cache()` and check before sending the request:

    cache = get_llm_cache()
    cached = cache.get(role, prompt, system_prompt)
    if cached is not None:
        return cached
    response = llm.ask(role, prompt, system_prompt=system_prompt)
    cache.put(role, prompt, system_prompt, response)
    return response

For convenience, `cached_ask(adapter, role, prompt, ...)` wraps
the pattern in one call.

Cache invalidation: there's no model-of-the-world, so the cache
is intentionally simple. Callers that need fresh data should
either bypass the cache or call `invalidate_role(role)` after a
known state change.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("llm.cache")


# ── Tunables ──────────────────────────────────────────────────

DEFAULT_MAX_ENTRIES = 256
DEFAULT_TTL_S = 3600.0  # 1 hour


@dataclass
class CacheEntry:
    response: Any  # an LLMResponse-shaped object
    expires_at: float
    role: str
    created_at: float = field(default_factory=time.time)
    hits: int = 0


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    puts: int = 0
    evictions: int = 0
    expirations: int = 0
    size: int = 0
    max_entries: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "puts": self.puts,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "size": self.size,
            "max_entries": self.max_entries,
            "hit_rate": round(self.hit_rate, 3),
        }


class LLMCache:
    """TTL + LRU cache for LLM responses."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_s: float = DEFAULT_TTL_S,
    ) -> None:
        self._max_entries = max(1, int(max_entries))
        self._ttl_s = float(ttl_s)
        self._entries: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats(max_entries=self._max_entries)

    # ── Key ───────────────────────────────────────────────────

    @staticmethod
    def _make_key(role: str, prompt: str, system_prompt: str = "",
                  model: str = "") -> str:
        """SHA1 of the salient inputs. Stable + collision-resistant."""
        h = hashlib.sha1()
        h.update(role.encode("utf-8"))
        h.update(b"\x00")
        h.update(model.encode("utf-8"))
        h.update(b"\x00")
        h.update(system_prompt.encode("utf-8"))
        h.update(b"\x00")
        h.update(prompt.encode("utf-8"))
        return h.hexdigest()

    # ── Get ───────────────────────────────────────────────────

    def get(
        self,
        role: str,
        prompt: str,
        system_prompt: str = "",
        *,
        model: str = "",
    ) -> Optional[Any]:
        """Look up a cached response.

        Returns the cached response object (an LLMResponse-shaped
        object) or None on miss / expiration. Hits move the entry
        to the most-recently-used end of the LRU.
        """
        key = self._make_key(role, prompt, system_prompt, model)
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            if entry.expires_at <= now:
                # Expired
                del self._entries[key]
                self._stats.expirations += 1
                self._stats.misses += 1
                self._stats.size = len(self._entries)
                return None
            # Hit — move to end (most recently used) and bump hit count
            self._entries.move_to_end(key)
            entry.hits += 1
            self._stats.hits += 1
            return entry.response

    # ── Put ───────────────────────────────────────────────────

    def put(
        self,
        role: str,
        prompt: str,
        system_prompt: str,
        response: Any,
        *,
        model: str = "",
        ttl_s: Optional[float] = None,
    ) -> None:
        """Cache an LLM response. Skips when the response indicates a
        failure (success=False) so we don't cache errors."""
        if response is None:
            return
        if getattr(response, "success", True) is False:
            return

        key = self._make_key(role, prompt, system_prompt, model)
        ttl = ttl_s if ttl_s is not None else self._ttl_s
        entry = CacheEntry(
            response=response,
            expires_at=time.time() + ttl,
            role=role,
        )
        with self._lock:
            # Insert / overwrite at the most-recent end
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = entry
            self._stats.puts += 1
            # LRU eviction
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                self._stats.evictions += 1
            self._stats.size = len(self._entries)

    # ── Invalidation ──────────────────────────────────────────

    def invalidate_role(self, role: str) -> int:
        """Drop every cached entry for a given role. Returns count."""
        with self._lock:
            keys = [k for k, e in self._entries.items() if e.role == role]
            for k in keys:
                del self._entries[k]
            self._stats.size = len(self._entries)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._stats.size = 0

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> CacheStats:
        with self._lock:
            self._stats.size = len(self._entries)
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                puts=self._stats.puts,
                evictions=self._stats.evictions,
                expirations=self._stats.expirations,
                size=self._stats.size,
                max_entries=self._stats.max_entries,
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: tuple[str, str, str]) -> bool:
        """Convenience for tests: `(role, prompt, system_prompt) in cache`."""
        if isinstance(key, tuple) and len(key) >= 2:
            role, prompt = key[0], key[1]
            system_prompt = key[2] if len(key) > 2 else ""
            return self.get(role, prompt, system_prompt) is not None
        return False


# ── Convenience: cache-aware ask ──────────────────────────────


def cached_ask(
    adapter: Any,
    role: str,
    prompt: str,
    *,
    system_prompt: str = "",
    context: Optional[dict] = None,
    cache: Optional[LLMCache] = None,
    ttl_s: Optional[float] = None,
) -> Any:
    """Cache-aware wrapper around adapter.ask().

    1. Build the same key the adapter would use
    2. Check the cache
    3. Miss → call the adapter, store the result, return it
    4. Hit → return the cached response immediately

    Note: the context dict is folded into the prompt by the adapter,
    so we include a hash of the context in the cache key by
    appending it to the prompt before hashing. The actual call to
    the adapter still passes the original prompt + context.
    """
    if cache is None:
        cache = get_llm_cache()
    # Build a cache-key prompt that includes the context hash so
    # different contexts don't collide
    key_prompt = prompt
    if context:
        try:
            import json as _json
            ctx_str = _json.dumps(context, sort_keys=True, default=str)[:2000]
            key_prompt = prompt + "\n#ctx:" + ctx_str
        except Exception as exc:  # noqa: BLE001
            logger.debug("cache key context serialisation failed: %s", exc)

    cached = cache.get(role, key_prompt, system_prompt)
    if cached is not None:
        return cached

    response = adapter.ask(role, prompt, context=context, system_prompt=system_prompt)
    cache.put(role, key_prompt, system_prompt, response, ttl_s=ttl_s)
    return response


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[LLMCache] = None
_instance_lock = threading.Lock()


def get_llm_cache() -> LLMCache:
    """Process-wide LLMCache singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LLMCache()
    return _instance


def reset_llm_cache_for_tests() -> None:
    """Drop the singleton — only call from tests."""
    global _instance
    _instance = None
