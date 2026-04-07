"""Tests for the TTL+LRU LLMCache."""
import threading
import time

import pytest


def _cache(**kwargs):
    from core.system.llm_cache import LLMCache
    kwargs.setdefault("max_entries", 10)
    kwargs.setdefault("ttl_s", 60.0)
    return LLMCache(**kwargs)


class _FakeResponse:
    def __init__(self, text="ok", success=True):
        self.text = text
        self.success = success


# ── Basic cache mechanics ────────────────────────────────────


class TestGetPut:
    def test_miss_returns_none(self):
        c = _cache()
        assert c.get("role", "prompt") is None

    def test_put_then_get(self):
        c = _cache()
        resp = _FakeResponse("hello")
        c.put("role", "prompt", "system", resp)
        cached = c.get("role", "prompt", "system")
        assert cached is resp

    def test_different_role_different_entry(self):
        c = _cache()
        c.put("a", "p", "s", _FakeResponse("for a"))
        c.put("b", "p", "s", _FakeResponse("for b"))
        assert c.get("a", "p", "s").text == "for a"
        assert c.get("b", "p", "s").text == "for b"

    def test_different_system_prompt_different_entry(self):
        c = _cache()
        c.put("r", "p", "s1", _FakeResponse("first"))
        c.put("r", "p", "s2", _FakeResponse("second"))
        assert c.get("r", "p", "s1").text == "first"
        assert c.get("r", "p", "s2").text == "second"

    def test_overwrite_same_key(self):
        c = _cache()
        c.put("r", "p", "s", _FakeResponse("v1"))
        c.put("r", "p", "s", _FakeResponse("v2"))
        assert c.get("r", "p", "s").text == "v2"

    def test_skip_failed_responses(self):
        c = _cache()
        c.put("r", "p", "s", _FakeResponse("oops", success=False))
        assert c.get("r", "p", "s") is None

    def test_skip_none_response(self):
        c = _cache()
        c.put("r", "p", "s", None)  # type: ignore
        assert c.get("r", "p", "s") is None


# ── TTL expiration ───────────────────────────────────────────


class TestTTL:
    def test_entry_expires(self):
        c = _cache(ttl_s=0.05)
        c.put("r", "p", "s", _FakeResponse("now"))
        assert c.get("r", "p", "s") is not None
        time.sleep(0.06)
        assert c.get("r", "p", "s") is None

    def test_expired_entry_increments_expirations(self):
        c = _cache(ttl_s=0.01)
        c.put("r", "p", "s", _FakeResponse())
        time.sleep(0.02)
        c.get("r", "p", "s")
        assert c.stats().expirations == 1

    def test_per_call_ttl_override(self):
        c = _cache(ttl_s=10.0)
        # Override TTL to be very short for one entry
        c.put("r", "p", "s", _FakeResponse(), ttl_s=0.01)
        time.sleep(0.02)
        assert c.get("r", "p", "s") is None


# ── LRU eviction ─────────────────────────────────────────────


class TestLRU:
    def test_oldest_evicted_when_full(self):
        c = _cache(max_entries=3)
        c.put("r", "p1", "", _FakeResponse("v1"))
        c.put("r", "p2", "", _FakeResponse("v2"))
        c.put("r", "p3", "", _FakeResponse("v3"))
        c.put("r", "p4", "", _FakeResponse("v4"))  # evicts p1
        assert c.get("r", "p1", "") is None
        assert c.get("r", "p2", "").text == "v2"
        assert c.get("r", "p4", "").text == "v4"

    def test_get_promotes_to_recent(self):
        c = _cache(max_entries=3)
        c.put("r", "p1", "", _FakeResponse())
        c.put("r", "p2", "", _FakeResponse())
        c.put("r", "p3", "", _FakeResponse())
        # Touch p1 → it's now most recent
        c.get("r", "p1", "")
        c.put("r", "p4", "", _FakeResponse())  # evicts p2 (oldest now)
        assert c.get("r", "p1", "") is not None
        assert c.get("r", "p2", "") is None
        assert c.get("r", "p4", "") is not None

    def test_evictions_counted(self):
        c = _cache(max_entries=2)
        c.put("r", "p1", "", _FakeResponse())
        c.put("r", "p2", "", _FakeResponse())
        c.put("r", "p3", "", _FakeResponse())  # 1 eviction
        c.put("r", "p4", "", _FakeResponse())  # 1 more eviction
        assert c.stats().evictions == 2


# ── Stats ────────────────────────────────────────────────────


class TestStats:
    def test_hit_rate_calculation(self):
        c = _cache()
        # 2 misses, 3 hits → 60%
        c.get("r", "x")
        c.get("r", "y")
        c.put("r", "z", "", _FakeResponse())
        c.get("r", "z")
        c.get("r", "z")
        c.get("r", "z")
        s = c.stats()
        assert s.hits == 3
        assert s.misses == 2
        assert s.hit_rate == 0.6

    def test_size_tracked(self):
        c = _cache()
        c.put("r", "a", "", _FakeResponse())
        c.put("r", "b", "", _FakeResponse())
        assert c.stats().size == 2

    def test_stats_to_dict(self):
        c = _cache()
        c.put("r", "p", "", _FakeResponse())
        c.get("r", "p")
        d = c.stats().to_dict()
        assert d["hits"] == 1
        assert d["puts"] == 1
        assert "hit_rate" in d


# ── Invalidation ─────────────────────────────────────────────


class TestInvalidation:
    def test_invalidate_role_drops_only_that_role(self):
        c = _cache()
        c.put("a", "p1", "", _FakeResponse())
        c.put("a", "p2", "", _FakeResponse())
        c.put("b", "p1", "", _FakeResponse())
        dropped = c.invalidate_role("a")
        assert dropped == 2
        assert c.get("a", "p1", "") is None
        assert c.get("b", "p1", "") is not None

    def test_clear_all(self):
        c = _cache()
        c.put("r", "p", "", _FakeResponse())
        c.clear()
        assert len(c) == 0


# ── Convenience cached_ask ───────────────────────────────────


class TestCachedAsk:
    def test_first_call_miss_then_hit(self):
        from core.system.llm_cache import cached_ask, LLMCache

        calls = {"n": 0}

        class FakeAdapter:
            def ask(self, role, prompt, context=None, system_prompt=""):
                calls["n"] += 1
                return _FakeResponse(f"answer {calls['n']}")

        cache = LLMCache()
        a = FakeAdapter()
        # First call → miss → adapter called
        r1 = cached_ask(a, "r", "what?", cache=cache)
        # Second call same prompt → hit → adapter NOT called
        r2 = cached_ask(a, "r", "what?", cache=cache)
        assert r1 is r2
        assert calls["n"] == 1
        assert cache.stats().hits == 1
        assert cache.stats().misses == 1

    def test_different_context_different_cache_entry(self):
        from core.system.llm_cache import cached_ask, LLMCache

        calls = {"n": 0}

        class FakeAdapter:
            def ask(self, role, prompt, context=None, system_prompt=""):
                calls["n"] += 1
                return _FakeResponse(f"answer {calls['n']}")

        cache = LLMCache()
        a = FakeAdapter()
        cached_ask(a, "r", "what?", context={"x": 1}, cache=cache)
        cached_ask(a, "r", "what?", context={"x": 2}, cache=cache)
        # Different contexts → 2 separate cache entries
        assert calls["n"] == 2

    def test_failure_not_cached(self):
        from core.system.llm_cache import cached_ask, LLMCache

        calls = {"n": 0}

        class FakeAdapter:
            def ask(self, role, prompt, context=None, system_prompt=""):
                calls["n"] += 1
                return _FakeResponse("err", success=False)

        cache = LLMCache()
        a = FakeAdapter()
        cached_ask(a, "r", "what?", cache=cache)
        cached_ask(a, "r", "what?", cache=cache)
        # Failure isn't cached → adapter called twice
        assert calls["n"] == 2


# ── Concurrency ──────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_puts_and_gets(self):
        c = _cache(max_entries=100)
        errors: list[str] = []

        def worker(i: int):
            try:
                for j in range(50):
                    c.put("r", f"p{i}-{j}", "", _FakeResponse(f"{i}-{j}"))
                    c.get("r", f"p{i}-{j}", "")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        # Some entries are present (LRU eviction may have dropped some)
        assert c.stats().puts == 250


# ── Singleton ────────────────────────────────────────────────


class TestSingleton:
    def test_get_llm_cache_caches(self):
        from core.system.llm_cache import get_llm_cache, reset_llm_cache_for_tests
        reset_llm_cache_for_tests()
        a = get_llm_cache()
        b = get_llm_cache()
        assert a is b

    def test_reset_for_tests(self):
        from core.system.llm_cache import get_llm_cache, reset_llm_cache_for_tests
        a = get_llm_cache()
        reset_llm_cache_for_tests()
        b = get_llm_cache()
        assert a is not b
