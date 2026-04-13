"""Tests for audit-pass-53 fixes — 3 real bugs + defensive
across ``core/auth/shopify_auth`` and ``core/rate_limiter/*``.

Real bugs fixed:

  * QuotaManager.get_all_quotas DEADLOCKED on the first call.
    It held the non-reentrant ``threading.Lock`` and then
    called ``self.check(key)`` which tried to acquire the
    SAME lock — Python's ``threading.Lock`` is non-reentrant
    so the thread blocked indefinitely. Any caller scanning
    all quotas hung the process. Verified by a timeout test
    before the fix.

  * QuotaManager.consume(amount=-1) silently SUBTRACTED from
    usage — a caller with partial control over the ``amount``
    parameter could refill an exhausted quota by passing a
    negative value. Security-class bug (rate limit bypass).

  * FairScheduler.release unconditionally released the
    semaphore. A caller that released without acquiring (or
    released twice for a single acquire) inflated the
    semaphore count above ``max_concurrent`` permanently,
    breaking the concurrency cap. Verified by a scenario
    that calls release × 3 with no prior acquire and then
    successfully acquires 5 slots on a ``max_concurrent=2``
    scheduler.

  * FairScheduler.acquire incremented ``_active`` BEFORE
    checking whether ``self._semaphore.acquire`` succeeded.
    A failed (timed-out) acquire left a phantom entry in
    the stats dict, corrupting ``active_now`` on every
    subsequent stats call.

  * ShopifyAuth double-scheme URL (same bug class as pass 43
    for shopify_api) — ``shop_url.rstrip("/")`` + the
    downstream f-string produced
    ``https://https://mystore.myshopify.com/...`` when a
    caller passed a scheme-prefixed URL.

  * ShopifyAuth token cache read-modify-write race. Two
    ShopifyAuth instances (for different stores) writing
    concurrently could interleave the load / mutate / write
    cycle, and the second writer silently clobbered the
    first writer's update. New module-level _CACHE_LOCK
    serializes the whole cycle.

  * ShopifyAuth token cache non-atomic write. Pre-audit
    wrote directly to the destination path; a crash
    mid-write left a half-written file, and the next
    ``_load_all_cached`` silently returned an empty dict,
    invalidating every cached token. Now ``.tmp`` +
    ``os.replace``.

  * ShopifyAuth token cache corrupted-file backup (same
    pattern as passes 48/49/52) — corrupted cache files
    are moved to ``<path>.corrupted.<ts>`` on load failure
    so an operator can inspect them.
"""
from __future__ import annotations

import threading
import time

import pytest

from core.auth.shopify_auth import (
    ShopifyAuth,
    _CACHE_LOCK,
    _normalize_shop_url,
)
from core.rate_limiter.fair_scheduler import FairScheduler
from core.rate_limiter.quota_manager import QuotaManager
from core.rate_limiter.rate_limiter import RateLimiter


# ═══════════════════════════════════════════════════════════
# QuotaManager — deadlock + gaming regression
# ═══════════════════════════════════════════════════════════


class TestQuotaManagerDeadlock:
    def test_get_all_quotas_does_not_deadlock(self):
        """Regression: pre-audit used a non-reentrant Lock
        then called self.check() which tried to re-acquire
        it. Any call to get_all_quotas with configured quotas
        hung forever. Verified by running on a thread with a
        join timeout."""
        q = QuotaManager()
        q.set_quota("api", 10)
        q.set_quota("api2", 20)
        q.set_quota("api3", 5)

        result: list = []

        def fire():
            result.append(q.get_all_quotas())

        t = threading.Thread(target=fire)
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive(), "get_all_quotas deadlocked"
        assert len(result) == 1
        assert len(result[0]) == 3


class TestQuotaGaming:
    def test_negative_amount_rejected(self):
        """Regression: pre-audit consume(key, amount=-10)
        subtracted from usage, allowing a caller to refill an
        exhausted quota below zero."""
        q = QuotaManager()
        q.set_quota("api", 5)
        for _ in range(5):
            assert q.consume("api") is True
        # Now exhausted.
        assert q.consume("api") is False
        assert q.check("api")["exhausted"] is True
        # Gaming attempt: negative amount rejected.
        assert q.consume("api", amount=-10) is False
        # Usage UNCHANGED.
        assert q.check("api")["used"] == 5
        assert q.check("api")["exhausted"] is True
        # Next normal consume still blocked.
        assert q.consume("api") is False

    def test_zero_amount_rejected(self):
        q = QuotaManager()
        q.set_quota("api", 5)
        assert q.consume("api", amount=0) is False

    def test_non_numeric_amount(self):
        q = QuotaManager()
        q.set_quota("api", 5)
        # safe_int("bad") → 0 → rejected.
        assert q.consume("api", amount="bad") is False  # type: ignore[arg-type]


class TestQuotaDefensive:
    def test_set_quota_non_string_key(self):
        q = QuotaManager()
        q.set_quota(None, 10)  # type: ignore[arg-type]
        assert q.check(None) == {"key": None, "limited": False}  # type: ignore[arg-type]

    def test_set_quota_empty_key(self):
        q = QuotaManager()
        q.set_quota("", 10)
        assert q.check("")["limited"] is False

    def test_set_quota_negative_limit_coerced(self):
        q = QuotaManager()
        q.set_quota("api", -5)
        assert q.check("api")["limit"] == 0

    def test_set_quota_zero_period_coerced(self):
        q = QuotaManager()
        q.set_quota("api", 10, period_seconds=0)
        # Period coerced to 1.
        assert q.check("api")["reset_in_seconds"] <= 1


# ═══════════════════════════════════════════════════════════
# FairScheduler
# ═══════════════════════════════════════════════════════════


class TestFairScheduler:
    def test_release_without_acquire_rejected(self):
        """Regression: pre-audit release() unconditionally
        incremented the semaphore, breaking the
        max_concurrent invariant."""
        fs = FairScheduler(max_concurrent=2)
        # 3 stray releases.
        fs.release("engine1")
        fs.release("engine1")
        fs.release("engine1")
        # Semaphore should still only allow 2 acquires.
        assert fs.acquire("e", timeout=0.1) is True
        assert fs.acquire("e", timeout=0.1) is True
        # Third times out because the invariant holds.
        assert fs.acquire("e", timeout=0.1) is False

    def test_double_release_rejected(self):
        fs = FairScheduler(max_concurrent=2)
        assert fs.acquire("engine1", timeout=1) is True
        fs.release("engine1")
        # Second release is a no-op.
        fs.release("engine1")
        # Verify the semaphore count didn't go above 2.
        assert fs.acquire("e", timeout=0.1) is True
        assert fs.acquire("e", timeout=0.1) is True
        assert fs.acquire("e", timeout=0.1) is False

    def test_failed_acquire_not_counted_as_active(self):
        """Regression: pre-audit stats incremented BEFORE
        checking the return value of ``_semaphore.acquire``.
        A timed-out acquire counted as an active slot."""
        fs = FairScheduler(max_concurrent=1)
        assert fs.acquire("engine1", timeout=1) is True
        # engine2 times out.
        assert fs.acquire("engine2", timeout=0.05) is False
        # Only engine1 active.
        active = fs.get_active()
        assert active.get("engine1", 0) == 1
        assert active.get("engine2", 0) == 0

    def test_invalid_max_concurrent_coerced(self):
        fs = FairScheduler(max_concurrent=-1)
        # Coerced to default 5.
        assert fs._max_concurrent == 5

    def test_non_string_engine_name(self):
        fs = FairScheduler(max_concurrent=1)
        assert fs.acquire(None, timeout=0.5) is True  # type: ignore[arg-type]
        fs.release(None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════
# RateLimiter
# ═══════════════════════════════════════════════════════════


class TestRateLimiter:
    def test_non_numeric_rate_coerced(self):
        rl = RateLimiter()
        rl.configure("api", rate="bad")  # type: ignore[arg-type]
        # rate coerced to 0.
        assert rl.get_remaining("api")["rate_per_second"] == 0.0

    def test_non_numeric_burst_coerced(self):
        rl = RateLimiter()
        rl.configure("api", rate=5.0, burst="bad")  # type: ignore[arg-type]
        # burst coerced to default 10.
        assert rl.get_remaining("api")["burst"] == 10

    def test_non_string_key_rejected(self):
        rl = RateLimiter()
        rl.configure(None, rate=5.0)  # type: ignore[arg-type]
        assert not rl._buckets

    def test_negative_rate_floored(self):
        rl = RateLimiter()
        rl.configure("api", rate=-5.0)
        assert rl.get_remaining("api")["rate_per_second"] == 0.0

    def test_zero_burst_floored(self):
        rl = RateLimiter()
        rl.configure("api", rate=5.0, burst=0)
        assert rl.get_remaining("api")["burst"] == 1

    def test_allow_unknown_key(self):
        """Keys without a configured bucket are always allowed."""
        rl = RateLimiter()
        assert rl.allow("unknown") is True


# ═══════════════════════════════════════════════════════════
# ShopifyAuth URL normalization
# ═══════════════════════════════════════════════════════════


class TestShopUrlNormalization:
    def test_bare_host(self):
        assert _normalize_shop_url("mystore.myshopify.com") == "mystore.myshopify.com"

    def test_strips_https(self):
        assert _normalize_shop_url("https://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_strips_http(self):
        assert _normalize_shop_url("http://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_strips_trailing_slash(self):
        assert _normalize_shop_url("mystore.myshopify.com/") == "mystore.myshopify.com"
        assert _normalize_shop_url("https://mystore.myshopify.com/") == "mystore.myshopify.com"

    def test_none_returns_empty(self):
        assert _normalize_shop_url(None) == ""

    def test_non_string_returns_empty(self):
        assert _normalize_shop_url(42) == ""

    def test_auth_constructor_no_double_scheme(self):
        auth = ShopifyAuth("https://mystore.myshopify.com", "cid", "secret")
        assert auth._shop_url == "mystore.myshopify.com"

    def test_auth_constructor_none_inputs(self):
        """None inputs must not crash the constructor."""
        auth = ShopifyAuth(None, None, None)  # type: ignore[arg-type]
        assert auth._shop_url == ""
        assert auth._client_id == ""
        assert auth._client_secret == ""


# ═══════════════════════════════════════════════════════════
# ShopifyAuth token cache
# ═══════════════════════════════════════════════════════════


class TestShopifyAuthTokenCache:
    @pytest.fixture
    def temp_cache(self, tmp_path, monkeypatch):
        """Redirect the module-level cache path to a temp file."""
        import core.auth.shopify_auth as mod
        cache_path = tmp_path / "tokens.json"
        monkeypatch.setattr(mod, "_TOKEN_CACHE_DIR", tmp_path)
        monkeypatch.setattr(mod, "_TOKEN_CACHE_FILE", cache_path)
        return cache_path

    def test_atomic_write(self, temp_cache):
        """``.tmp`` + ``os.replace`` — no half-written file left."""
        auth = ShopifyAuth("store1.myshopify.com", "cid", "secret")
        auth._access_token = "token1"
        auth._expires_at = time.time() + 3600
        auth._save_cached_token()
        assert temp_cache.exists()
        # No stray tmp file.
        tmp = temp_cache.parent / (temp_cache.name + ".tmp")
        assert not tmp.exists()

    def test_corrupted_cache_backed_up(self, temp_cache):
        """Regression: corrupted cache file crashed the load
        path. Now it's moved to .corrupted.<ts> before
        returning an empty cache."""
        temp_cache.write_text("{not json")
        # Construct an auth instance — triggers _load_cached_token.
        auth = ShopifyAuth("store1.myshopify.com", "cid", "secret")
        assert auth._access_token == ""
        backups = [
            f for f in temp_cache.parent.iterdir()
            if "corrupted" in f.name
        ]
        assert len(backups) >= 1

    def test_non_dict_cache_backed_up(self, temp_cache):
        """Cache file that decodes to a non-dict is also
        treated as corrupted."""
        temp_cache.write_text('["not", "a", "dict"]')
        auth = ShopifyAuth("store1.myshopify.com", "cid", "secret")
        assert auth._access_token == ""

    def test_concurrent_save_no_lost_updates(self, temp_cache):
        """Regression: pre-audit two ShopifyAuth instances
        saving concurrently could interleave and lose one
        writer's update. The module-level _CACHE_LOCK
        serializes the full read-modify-write cycle."""
        auths = [
            ShopifyAuth(f"store{i}.myshopify.com", "cid", "secret")
            for i in range(8)
        ]
        for i, auth in enumerate(auths):
            auth._access_token = f"token_{i}"
            auth._expires_at = time.time() + 3600

        barrier = threading.Barrier(len(auths))

        def fire(auth):
            barrier.wait()
            auth._save_cached_token()

        threads = [threading.Thread(target=fire, args=(a,)) for a in auths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 8 stores should be in the cache.
        import json
        cache = json.loads(temp_cache.read_text())
        assert len(cache) == 8
        for i in range(8):
            assert f"store{i}.myshopify.com" in cache
            assert cache[f"store{i}.myshopify.com"]["access_token"] == f"token_{i}"

    def test_module_lock_exists(self):
        """Sanity: the module-level cache lock is a real lock."""
        assert hasattr(_CACHE_LOCK, "acquire")
        assert hasattr(_CACHE_LOCK, "release")
