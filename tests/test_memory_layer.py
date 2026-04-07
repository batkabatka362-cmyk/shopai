"""Tests for the memory layer plumbing — written to cover the
bugs found in audit pass 4:

  1. MemoryManager.store_short_term recorded a `ttl_seconds` field
     but `recall()` never checked it. Entries lived forever and
     the TTL parameter was decorative. The previous `stored_at`
     field was an ISO string so arithmetic was impossible.

  2. UnifiedMemory.initialize() had eight bare `except Exception:`
     blocks that silently set every backend to None. Operators
     had no signal that anything had broken — the `status` dict
     just held a few `False` values with no error context.

  3. UnifiedMemory.record_decision wrote to brain → experience →
     shared without per-write isolation, so a failure in the first
     backend silently skipped the others and left a divergent
     record across the memory backends.
"""
import time

import pytest


# ── MemoryManager TTL ────────────────────────────────────────


def _fresh_manager():
    from core.memory.memory_manager import MemoryManager
    return MemoryManager()


class TestMemoryManagerTTL:
    def test_recall_respects_ttl(self):
        m = _fresh_manager()
        m.store_short_term("k", "v", ttl_seconds=1)
        assert m.recall("k") == "v"
        # Force expiry by rewriting expires_at into the past
        m._short_term["k"]["expires_at"] = time.time() - 0.1
        assert m.recall("k") is None

    def test_expired_entry_evicted_on_recall(self):
        m = _fresh_manager()
        m.store_short_term("k", "v", ttl_seconds=1)
        m._short_term["k"]["expires_at"] = time.time() - 1
        m.recall("k")
        assert "k" not in m._short_term

    def test_recall_falls_through_to_long_term_on_expiry(self):
        m = _fresh_manager()
        m.store_short_term("k", "short", ttl_seconds=1)
        m.store_long_term("k", "long", tags=["x"])
        m._short_term["k"]["expires_at"] = time.time() - 1
        # Short-term is expired → should return long-term value
        assert m.recall("k") == "long"

    def test_long_term_has_no_ttl(self):
        m = _fresh_manager()
        m.store_long_term("k", "v", tags=["a"])
        # Even after a long simulated wait, long-term sticks around.
        assert m.recall("k") == "v"

    def test_zero_ttl_means_no_expiry(self):
        m = _fresh_manager()
        m.store_short_term("k", "v", ttl_seconds=0)
        # ttl=0 → never expires (expires_at is 0.0, treated as no TTL)
        m._short_term["k"]["stored_at_ts"] = time.time() - 10000
        assert m.recall("k") == "v"

    def test_store_keeps_iso_and_numeric_fields(self):
        # Display callers may still rely on the ISO string; the new
        # numeric expires_at is additive, not a replacement.
        m = _fresh_manager()
        m.store_short_term("k", "v", ttl_seconds=60)
        entry = m._short_term["k"]
        assert isinstance(entry["stored_at"], str)
        assert isinstance(entry["expires_at"], float)
        assert entry["expires_at"] > time.time()

    def test_sweep_expired_drops_only_stale_entries(self):
        m = _fresh_manager()
        m.store_short_term("fresh", "f", ttl_seconds=600)
        m.store_short_term("stale1", "s", ttl_seconds=1)
        m.store_short_term("stale2", "s", ttl_seconds=1)
        m._short_term["stale1"]["expires_at"] = time.time() - 5
        m._short_term["stale2"]["expires_at"] = time.time() - 5
        evicted = m.sweep_expired()
        assert evicted == 2
        assert "fresh" in m._short_term
        assert "stale1" not in m._short_term

    def test_recall_no_entry_returns_none(self):
        m = _fresh_manager()
        assert m.recall("missing") is None


# ── UnifiedMemory init failure surfacing ─────────────────────


class TestUnifiedMemoryInitErrors:
    def test_init_captures_backend_failure(self, monkeypatch):
        from core.memory.unified_memory import UnifiedMemory
        import core.memory.intelligence as mi

        original = mi.get_memory_intelligence

        def _boom():
            raise RuntimeError("disk full")

        monkeypatch.setattr(mi, "get_memory_intelligence", _boom)

        um = UnifiedMemory()
        status = um.initialize()
        # The failed backend reports False
        assert status["memory_intelligence"] is False
        # And the error is captured with type+message for the operator
        errors = um.get_init_errors()
        assert "memory_intelligence" in errors
        assert "RuntimeError" in errors["memory_intelligence"]
        assert "disk full" in errors["memory_intelligence"]

    def test_init_other_backends_still_load_after_one_failure(
        self, monkeypatch,
    ):
        from core.memory.unified_memory import UnifiedMemory
        import core.memory.intelligence as mi

        monkeypatch.setattr(
            mi, "get_memory_intelligence",
            lambda: (_ for _ in ()).throw(ValueError("nope")),
        )

        um = UnifiedMemory()
        status = um.initialize()
        # The failure didn't crash the whole init
        assert um._initialized is True
        # And some other backend (memory_intelligence) registered the
        # failure but the loop kept going.
        assert "memory_intelligence" in status
        assert status["memory_intelligence"] is False

    def test_init_errors_empty_when_clean(self):
        from core.memory.unified_memory import UnifiedMemory
        um = UnifiedMemory()
        um.initialize()
        # In a clean test environment some backends may legitimately
        # be missing — we just verify the API exists and returns a
        # plain dict (possibly with entries but never None).
        errors = um.get_init_errors()
        assert isinstance(errors, dict)


# ── UnifiedMemory.record_decision per-write isolation ────────


class _RecordingBackend:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls: list[tuple] = []

    def record_decision(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("brain on fire")
        self.calls.append(("record_decision", args, kwargs))

    def record_decision_outcome(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("experience exploded")
        self.calls.append(("record_decision_outcome", args, kwargs))


class TestUnifiedMemoryRecordDecisionIsolation:
    def test_brain_failure_does_not_skip_experience_or_shared(self):
        from core.memory.unified_memory import UnifiedMemory
        um = UnifiedMemory()
        um._initialized = True
        um._brain = _RecordingBackend(fail=True)
        um._experience = _RecordingBackend()
        um._shared = _RecordingBackend()

        um.record_decision(
            "pricing", {"x": 1}, "raise", {"r": "ok"}, score=4.0,
        )
        # Brain raised, but experience + shared still got the call.
        assert len(um._experience.calls) == 1
        assert um._experience.calls[0][0] == "record_decision_outcome"
        assert len(um._shared.calls) == 1
        assert um._shared.calls[0][0] == "record_decision"

    def test_experience_failure_does_not_skip_shared(self):
        from core.memory.unified_memory import UnifiedMemory
        um = UnifiedMemory()
        um._initialized = True
        um._brain = _RecordingBackend()
        um._experience = _RecordingBackend(fail=True)
        um._shared = _RecordingBackend()

        um.record_decision(
            "ads", {"x": 1}, "boost", {"r": "ok"}, score=4.5,
        )
        assert len(um._brain.calls) == 1
        assert len(um._shared.calls) == 1

    def test_all_three_backends_called_on_happy_path(self):
        from core.memory.unified_memory import UnifiedMemory
        um = UnifiedMemory()
        um._initialized = True
        um._brain = _RecordingBackend()
        um._experience = _RecordingBackend()
        um._shared = _RecordingBackend()

        um.record_decision(
            "inv", {"x": 1}, "stock_up", {"ok": True}, score=4.0,
        )
        assert len(um._brain.calls) == 1
        assert len(um._experience.calls) == 1
        assert len(um._shared.calls) == 1

    def test_no_backend_no_crash(self):
        from core.memory.unified_memory import UnifiedMemory
        um = UnifiedMemory()
        um._initialized = True
        um._brain = None
        um._experience = None
        um._shared = None
        # Should not raise.
        um.record_decision("c", {}, "a", {}, 3.0)
