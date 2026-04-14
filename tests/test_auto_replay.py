"""Tests for the auto-replay coordinator — Upgrade 2.

The coordinator scans the dead-letter ledger, classifies entries
by current adapter health, and optionally calls a registered
callback for each READY entry. These tests cover:

* Empty ledger → empty report
* Healthy adapter + old entry → READY
* Open breaker → DEGRADED with reason=breaker
* Penalised route-weight → DEGRADED with reason=route_weight
* Age floor: recent entries are skipped_recent
* Idempotency: mark_replayed prevents re-classification
* LRU eviction when replayed table hits cap
* Per-scan rate limit (max_ready_per_scan)
* Registered callback is invoked once per READY entry
* Callback failure is counted and does not crash the scan
* Defensive imports: missing deps return an empty report
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.auto_replay import (
    AutoReplayCoordinator,
    ReplayCandidate,
    get_auto_replay_coordinator,
    reset_auto_replay_coordinator,
)


def _entry(
    eid="e1", adapter="alpha", capability="chat_complete",
    ts=None, attempts=3,
):
    """Build a dead-letter-entry-like object the coordinator
    accepts (any object with the right attributes works)."""
    if ts is None:
        ts = time.time() - 300  # 5 minutes ago
    return SimpleNamespace(
        id=eid,
        adapter=adapter,
        capability=capability,
        timestamp=ts,
        attempts=attempts,
        params_snapshot={"model": "gpt-4"},
    )


@pytest.fixture(autouse=True)
def _reset():
    reset_auto_replay_coordinator()
    # Also reset route weights so we start from a clean slate.
    try:
        from core.adapters.route_weights import reset_route_weight_ledger
        reset_route_weight_ledger()
    except Exception:
        pass
    yield
    reset_auto_replay_coordinator()


def _patch_ledger(entries):
    """Patch the dead-letter ledger's singleton .recent() call."""
    return patch(
        "core.adapters.deadletter.get_dead_letter_ledger",
        return_value=MagicMock(recent=MagicMock(return_value=entries)),
    )


def _patch_router_breakers(breaker_map):
    """Patch the router singleton to return a chosen breaker map."""
    fake_router = SimpleNamespace(
        breaker_snapshot=lambda: breaker_map,
    )
    return patch(
        "core.adapters.router._router", fake_router, create=True,
    )


class TestEmpty:
    def test_empty_ledger(self):
        c = AutoReplayCoordinator()
        with _patch_ledger([]), _patch_router_breakers({}):
            report = c.scan()
        assert report.ready == []
        assert report.degraded == []
        assert report.replayed == []
        assert report.skipped_recent == 0


class TestClassification:
    def test_healthy_entry_is_ready(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            report = c.scan()
        assert len(report.ready) == 1
        assert report.ready[0].adapter == "alpha"
        assert report.ready[0].reason == "healthy"

    def test_open_breaker_marks_degraded(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        breakers = {"alpha": {"state": "open"}}
        with _patch_ledger([_entry()]), \
             _patch_router_breakers(breakers):
            report = c.scan()
        assert report.ready == []
        assert len(report.degraded) == 1
        assert "breaker=open" in report.degraded[0].reason

    def test_penalized_weight_marks_degraded(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        from core.adapters.route_weights import get_route_weight_ledger
        get_route_weight_ledger().penalize("alpha", "chat_complete", 0.1)
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            report = c.scan()
        assert report.ready == []
        assert len(report.degraded) == 1
        assert "route_weight" in report.degraded[0].reason

    def test_mild_weight_still_ready(self):
        """Route weight >= 0.5 is not considered blocking — the
        router will prefer healthier alternatives but the entry
        can still replay through the same adapter."""
        c = AutoReplayCoordinator(min_age_sec=10.0)
        from core.adapters.route_weights import get_route_weight_ledger
        get_route_weight_ledger().penalize("alpha", "chat_complete", 0.8)
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            report = c.scan()
        assert len(report.ready) == 1

    def test_recent_entry_skipped(self):
        c = AutoReplayCoordinator(min_age_sec=60.0)
        fresh = _entry(ts=time.time() - 5)  # 5 s old
        with _patch_ledger([fresh]), _patch_router_breakers({}):
            report = c.scan()
        assert report.ready == []
        assert report.skipped_recent == 1


class TestIdempotency:
    def test_mark_replayed_prevents_re_ready(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            report1 = c.scan()
            assert len(report1.ready) == 1
            c.mark_replayed(report1.ready[0].entry_id)
            report2 = c.scan()
        assert report2.ready == []
        assert "e1" in report2.replayed

    def test_mark_replayed_is_idempotent(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        c.mark_replayed("e1")
        c.mark_replayed("e1")  # no crash
        assert c.is_replayed("e1")

    def test_lru_eviction(self):
        c = AutoReplayCoordinator(replayed_lru_max=3)
        for i in range(5):
            c.mark_replayed(f"e{i}")
        # Oldest two evicted.
        assert not c.is_replayed("e0")
        assert not c.is_replayed("e1")
        assert c.is_replayed("e4")

    def test_mark_replayed_refreshes_lru_position(self):
        c = AutoReplayCoordinator(replayed_lru_max=3)
        c.mark_replayed("e0")
        c.mark_replayed("e1")
        c.mark_replayed("e2")
        # Refresh e0 — should move it to the freshest slot.
        c.mark_replayed("e0")
        c.mark_replayed("e3")
        assert c.is_replayed("e0")  # refreshed → survived
        assert not c.is_replayed("e1")  # oldest → evicted

    def test_mark_replayed_empty_id_ignored(self):
        c = AutoReplayCoordinator()
        c.mark_replayed("")  # no crash
        assert not c.is_replayed("")


class TestRateLimit:
    def test_max_ready_per_scan_throttles(self):
        c = AutoReplayCoordinator(min_age_sec=10.0, max_ready_per_scan=2)
        entries = [_entry(eid=f"e{i}") for i in range(5)]
        with _patch_ledger(entries), _patch_router_breakers({}):
            report = c.scan()
        # Only 2 yielded — the other 3 stay for later scans.
        assert len(report.ready) == 2

    def test_subsequent_scan_picks_up_remainder(self):
        c = AutoReplayCoordinator(min_age_sec=10.0, max_ready_per_scan=2)
        entries = [_entry(eid=f"e{i}") for i in range(5)]
        with _patch_ledger(entries), _patch_router_breakers({}):
            report1 = c.scan()
            for cand in report1.ready:
                c.mark_replayed(cand.entry_id)
            report2 = c.scan()
        assert len(report2.ready) == 2


class TestCallback:
    def test_callback_invoked_per_ready(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        seen: list[str] = []
        c.register_replay_callback(lambda e: seen.append(e.id))
        entries = [_entry(eid=f"e{i}") for i in range(3)]
        with _patch_ledger(entries), _patch_router_breakers({}):
            report = c.scan()
        assert seen == ["e0", "e1", "e2"]
        assert report.callback_invocations == 3
        assert report.callback_failures == 0

    def test_callback_failure_counted(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)

        def bad_cb(e):
            raise RuntimeError("boom")
        c.register_replay_callback(bad_cb)
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            report = c.scan()
        assert report.callback_invocations == 1
        assert report.callback_failures == 1
        # Entry is still in the READY bucket so operators can
        # inspect and retry manually.
        assert len(report.ready) == 1

    def test_unregister_callback(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        c.register_replay_callback(lambda e: None)
        c.register_replay_callback(None)  # unregister
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            report = c.scan()
        assert report.callback_invocations == 0


class TestDefensive:
    def test_ledger_import_failure_returns_empty(self):
        c = AutoReplayCoordinator()
        with patch(
            "core.adapters.deadletter.get_dead_letter_ledger"
        ) as gdl:
            gdl.side_effect = ImportError("no ledger")
            report = c.scan()
        assert report.ready == []
        assert report.degraded == []

    def test_router_missing_treated_as_healthy(self):
        """Without a router singleton, we have no breaker info —
        the scan must not treat all adapters as unhealthy."""
        c = AutoReplayCoordinator(min_age_sec=10.0)
        with _patch_ledger([_entry()]):
            # Leave the router module alone — no _router attribute
            import core.adapters.router as rm
            rm._router = None  # type: ignore[attr-defined]
            report = c.scan()
        assert len(report.ready) == 1


class TestSnapshot:
    def test_snapshot_tracks_counters(self):
        c = AutoReplayCoordinator(min_age_sec=10.0)
        with _patch_ledger([_entry()]), _patch_router_breakers({}):
            c.scan()
            c.scan()
        snap = c.snapshot()
        assert snap["total_scans"] == 2
        assert snap["total_ready"] == 2  # same entry found twice
        assert snap["callback_registered"] is False

    def test_constructor_validation(self):
        with pytest.raises(ValueError):
            AutoReplayCoordinator(max_ready_per_scan=0)
        with pytest.raises(ValueError):
            AutoReplayCoordinator(replayed_lru_max=0)


class TestSingleton:
    def test_singleton_persists(self):
        c1 = get_auto_replay_coordinator()
        c1.mark_replayed("e1")
        c2 = get_auto_replay_coordinator()
        assert c1 is c2
        assert c2.is_replayed("e1")
