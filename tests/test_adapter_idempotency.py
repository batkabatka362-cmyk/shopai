"""Idempotency cache tests — Option V phase 1.

Covers policy validation, key derivation stability, get/store with
TTL expiry, LRU eviction, invalidation by adapter/capability, the
snapshot rollup, thread-safety, and the singleton.
"""
from __future__ import annotations

import threading

import pytest

from core.adapters.base import AdapterResult, Capability
from core.adapters.idempotency import (
    DEFAULT_POLICIES,
    IdempotencyCache,
    IdempotencyPolicy,
    get_idempotency_cache,
    reset_idempotency_cache,
)


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _ok(adapter="a", cap=Capability.CHAT_COMPLETE, text="hi"):
    return AdapterResult.success(
        adapter=adapter, capability=cap.value, data={"text": text},
    )


def _fail(adapter="a", cap=Capability.CHAT_COMPLETE):
    from core.adapters.errors import AdapterError
    return AdapterResult.failure(
        adapter, cap.value, AdapterError(adapter, "boom"),
    )


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_idempotency_cache()
    yield
    reset_idempotency_cache()


class TestPolicy:
    def test_negative_ttl_rejected(self):
        with pytest.raises(ValueError):
            IdempotencyPolicy(ttl_s=-1.0)

    def test_zero_ttl_is_disabled(self):
        p = IdempotencyPolicy(ttl_s=0.0)
        assert p.enabled is False

    def test_positive_ttl_is_enabled(self):
        assert IdempotencyPolicy(ttl_s=5.0).enabled is True


class TestKeyDerivation:
    def test_same_params_same_key(self):
        c = IdempotencyCache()
        h1 = c._hash_params({"a": 1, "b": 2})
        h2 = c._hash_params({"b": 2, "a": 1})  # reordered
        assert h1 == h2

    def test_different_params_different_keys(self):
        c = IdempotencyCache()
        assert c._hash_params({"x": 1}) != c._hash_params({"x": 2})

    def test_non_json_safe_falls_back_to_repr(self):
        class Weird:
            pass
        c = IdempotencyCache()
        # Must not raise — cache is allowed to under-hit.
        h = c._hash_params({"obj": Weird()})
        assert isinstance(h, str) and len(h) > 0

    def test_key_respects_sharing_scope(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.WEB_SEARCH: IdempotencyPolicy(
                    ttl_s=10.0, shared_across_adapters=True,
                ),
            },
            clock=clk,
        )
        # Scope uses "*" → both adapters produce the same key.
        k1 = c._key_for(
            "a", Capability.WEB_SEARCH, {"q": "x"},
            c.get_policy(Capability.WEB_SEARCH),
        )
        k2 = c._key_for(
            "b", Capability.WEB_SEARCH, {"q": "x"},
            c.get_policy(Capability.WEB_SEARCH),
        )
        assert k1 == k2


class TestGetStore:
    def test_miss_returns_none(self):
        c = IdempotencyCache()
        assert c.get("a", Capability.CHAT_COMPLETE, {"p": 1}) is None

    def test_store_then_hit(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            },
            clock=clk,
        )
        result = _ok(text="hello")
        assert c.store("a", Capability.CHAT_COMPLETE, {"p": 1}, result)
        hit = c.get("a", Capability.CHAT_COMPLETE, {"p": 1})
        assert hit is result
        assert c.snapshot()["hits"] == 1

    def test_without_policy_is_noop(self):
        c = IdempotencyCache(policies={})
        assert c.store("a", Capability.CHAT_COMPLETE, {"p": 1}, _ok()) is False
        assert c.get("a", Capability.CHAT_COMPLETE, {"p": 1}) is None
        assert c.snapshot()["skipped"] >= 1

    def test_failure_not_cached(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            },
            clock=clk,
        )
        assert c.store("a", Capability.CHAT_COMPLETE, {}, _fail()) is False
        assert c.size() == 0

    def test_different_adapters_isolated_by_default(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {"p": 1}, _ok(adapter="a"))
        # Same cap + params but adapter="b" → separate cache entry.
        assert c.get("b", Capability.CHAT_COMPLETE, {"p": 1}) is None

    def test_shared_scope_crosses_adapters(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.WEB_SEARCH: IdempotencyPolicy(
                    ttl_s=60.0, shared_across_adapters=True,
                ),
            },
            clock=clk,
        )
        c.store("a", Capability.WEB_SEARCH, {"q": "x"}, _ok(adapter="a"))
        hit = c.get("b", Capability.WEB_SEARCH, {"q": "x"})
        assert hit is not None and hit.adapter == "a"


class TestTTL:
    def test_expired_entry_is_dropped(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=1.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {}, _ok())
        clk.advance(2.0)
        assert c.get("a", Capability.CHAT_COMPLETE, {}) is None
        # Lazy eviction on the expired read.
        assert c.snapshot()["evictions"] >= 1
        assert c.size() == 0

    def test_not_yet_expired_hit(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {}, _ok())
        clk.advance(4.9)
        assert c.get("a", Capability.CHAT_COMPLETE, {}) is not None


class TestLRU:
    def test_eviction_when_full(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
            },
            max_entries=3,
            clock=clk,
        )
        for i in range(5):
            c.store("a", Capability.CHAT_COMPLETE, {"i": i}, _ok(text=str(i)))
        assert c.size() == 3
        # Oldest two (i=0, i=1) should be gone.
        assert c.get("a", Capability.CHAT_COMPLETE, {"i": 0}) is None
        assert c.get("a", Capability.CHAT_COMPLETE, {"i": 4}) is not None

    def test_touch_moves_to_end(self):
        """Reading an entry should keep it alive even as newer
        entries arrive — classic LRU semantics."""
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
            },
            max_entries=3,
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {"i": 1}, _ok())
        c.store("a", Capability.CHAT_COMPLETE, {"i": 2}, _ok())
        c.store("a", Capability.CHAT_COMPLETE, {"i": 3}, _ok())
        # Touch i=1 to make it recent.
        c.get("a", Capability.CHAT_COMPLETE, {"i": 1})
        # New entry should evict the oldest remaining (i=2).
        c.store("a", Capability.CHAT_COMPLETE, {"i": 4}, _ok())
        assert c.get("a", Capability.CHAT_COMPLETE, {"i": 1}) is not None
        assert c.get("a", Capability.CHAT_COMPLETE, {"i": 2}) is None

    def test_max_entries_validation(self):
        with pytest.raises(ValueError):
            IdempotencyCache(max_entries=0)


class TestInvalidate:
    def test_clear_all(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {"i": 1}, _ok())
        c.store("b", Capability.CHAT_COMPLETE, {"i": 2}, _ok())
        assert c.invalidate() == 2
        assert c.size() == 0

    def test_invalidate_by_capability(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
                Capability.EMBED_TEXT:   IdempotencyPolicy(ttl_s=60.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {}, _ok(cap=Capability.CHAT_COMPLETE))
        c.store("a", Capability.EMBED_TEXT, {}, _ok(cap=Capability.EMBED_TEXT))
        assert c.invalidate(capability=Capability.CHAT_COMPLETE) == 1
        assert c.get("a", Capability.CHAT_COMPLETE, {}) is None
        assert c.get("a", Capability.EMBED_TEXT, {}) is not None

    def test_invalidate_by_adapter(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {"i": 1}, _ok(adapter="a"))
        c.store("b", Capability.CHAT_COMPLETE, {"i": 2}, _ok(adapter="b"))
        assert c.invalidate(adapter="a") == 1
        assert c.get("a", Capability.CHAT_COMPLETE, {"i": 1}) is None
        assert c.get("b", Capability.CHAT_COMPLETE, {"i": 2}) is not None


class TestSnapshot:
    def test_counters_and_hit_rate(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {"p": 1}, _ok())
        c.get("a", Capability.CHAT_COMPLETE, {"p": 1})   # hit
        c.get("a", Capability.CHAT_COMPLETE, {"p": 1})   # hit
        c.get("a", Capability.CHAT_COMPLETE, {"p": 2})   # miss
        snap = c.snapshot()
        assert snap["hits"] == 2
        assert snap["misses"] == 1
        assert snap["stores"] == 1
        assert snap["size"] == 1
        assert snap["live"] == 1
        # 2/3 rounded.
        assert snap["hit_rate"] == pytest.approx(0.6667, abs=1e-3)

    def test_per_capability_counts(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
                Capability.EMBED_TEXT:    IdempotencyPolicy(ttl_s=60.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {"i": 1}, _ok(cap=Capability.CHAT_COMPLETE))
        c.store("a", Capability.EMBED_TEXT, {"i": 1}, _ok(cap=Capability.EMBED_TEXT))
        snap = c.snapshot()
        assert snap["per_capability"][Capability.CHAT_COMPLETE.value] == 1
        assert snap["per_capability"][Capability.EMBED_TEXT.value] == 1

    def test_expired_entries_excluded_from_live(self):
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=1.0),
            },
            clock=clk,
        )
        c.store("a", Capability.CHAT_COMPLETE, {}, _ok())
        clk.advance(2.0)
        snap = c.snapshot()
        # Entry still in the underlying map (lazy eviction) but
        # ``live`` excludes expired rows.
        assert snap["live"] == 0
        assert snap["size"] == 1


class TestPolicyManagement:
    def test_set_replaces(self):
        c = IdempotencyCache(policies={})
        c.set_policy(Capability.CHAT_COMPLETE, IdempotencyPolicy(ttl_s=10.0))
        assert c.get_policy(Capability.CHAT_COMPLETE).ttl_s == 10.0
        c.set_policy(Capability.CHAT_COMPLETE, IdempotencyPolicy(ttl_s=20.0))
        assert c.get_policy(Capability.CHAT_COMPLETE).ttl_s == 20.0

    def test_policies_returns_copy(self):
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            },
        )
        snap = c.policies()
        snap[Capability.EMBED_TEXT] = IdempotencyPolicy(ttl_s=99.0)
        assert Capability.EMBED_TEXT not in c.policies()


class TestDefaults:
    def test_chat_has_default_policy(self):
        assert Capability.CHAT_COMPLETE in DEFAULT_POLICIES

    def test_search_shared_across_adapters(self):
        pol = DEFAULT_POLICIES.get(Capability.WEB_SEARCH)
        assert pol is not None
        assert pol.shared_across_adapters is True

    def test_no_side_effect_capabilities_in_defaults(self):
        # Hard rule: side-effecting capabilities must not appear.
        dangerous = {
            Capability.PAYMENT_REFUND,
            Capability.PAYMENT_CAPTURE,
        }
        for cap in dangerous:
            assert cap not in DEFAULT_POLICIES


class TestSingleton:
    def test_get_returns_same_instance(self):
        a = get_idempotency_cache()
        b = get_idempotency_cache()
        assert a is b

    def test_reset_drops_singleton(self):
        a = get_idempotency_cache()
        reset_idempotency_cache()
        b = get_idempotency_cache()
        assert a is not b


class TestThreadSafety:
    def test_concurrent_store_and_get(self):
        """Stress test: 50 threads hammering the cache must not
        crash and the final size must honour max_entries."""
        clk = _Clock()
        c = IdempotencyCache(
            policies={
                Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
            },
            max_entries=20,
            clock=clk,
        )

        def worker(i: int):
            for j in range(20):
                c.store("a", Capability.CHAT_COMPLETE, {"i": i, "j": j}, _ok())
                c.get("a", Capability.CHAT_COMPLETE, {"i": i, "j": j})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.size() <= 20
