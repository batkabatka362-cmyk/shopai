"""Dashboard multi-store support — Option N.

Covers:

* ``_collect_stores_snapshot`` — merges the ``StoreRegistry`` rows with
  the scheduler's active rotation list so the selector shows every
  store the operator might care about.
* ``GET /api/stores`` endpoint envelope.
* ``GET /api/cycle?store_id=...`` — narrows the recent summaries to one
  store and swaps the "latest" pointer when the global latest belongs
  to a different store.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _collect_stores_snapshot,
)


def _handler(path: str = "/api/stores") -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = path
    return h


class _FakeRegistry:
    def __init__(self, rows):
        self._rows = rows

    def list_stores(self):
        return list(self._rows)


class _FakeScheduler:
    def __init__(self, stores):
        self._stores = stores

    def get_status(self):
        return {"stores": list(self._stores)}

    # Cycle-history helpers used by test_cycle_store_filter.
    def get_last_summary(self):
        return getattr(self, "_latest", None)

    def get_recent_summaries(self, limit=20):
        return list(getattr(self, "_recent", []))


@pytest.fixture
def patched_registry(monkeypatch):
    state = {"rows": []}

    def _install(rows):
        state["rows"] = rows

    def _fake_get_store_registry():
        return _FakeRegistry(state["rows"])

    monkeypatch.setattr(
        "core.system.store_registry.get_store_registry",
        _fake_get_store_registry,
    )
    return _install


@pytest.fixture
def patched_scheduler(monkeypatch):
    state = {"stores": [], "latest": None, "recent": []}

    def _install(*, stores=None, latest=None, recent=None):
        if stores is not None:
            state["stores"] = stores
        if latest is not None:
            state["latest"] = latest
        if recent is not None:
            state["recent"] = recent

    def _fake_get_scheduler():
        s = _FakeScheduler(state["stores"])
        s._latest = state["latest"]
        s._recent = state["recent"]
        return s

    monkeypatch.setattr(
        "core.system.auto_scheduler.get_scheduler",
        _fake_get_scheduler,
    )
    return _install


# ---------------------------------------------------------------------------
# Snapshot math
# ---------------------------------------------------------------------------


class TestStoresSnapshot:
    def test_registry_rows_surface(self, patched_registry, patched_scheduler):
        patched_registry([
            {"store_id": "deguar", "name": "Deguar", "status": "active",
             "niche": "home", "last_cycle": 0, "health_score": 85},
            {"store_id": "shop2", "name": "Shop Two", "status": "active",
             "niche": "", "last_cycle": 0, "health_score": 70},
        ])
        patched_scheduler(stores=["deguar"])
        data = _collect_stores_snapshot()
        ids = [s["store_id"] for s in data["stores"]]
        assert "deguar" in ids and "shop2" in ids
        assert data["default"] == "deguar"

    def test_scheduler_store_missing_from_registry_is_added(
        self, patched_registry, patched_scheduler,
    ):
        patched_registry([])
        patched_scheduler(stores=["live-store"])
        data = _collect_stores_snapshot()
        ids = [s["store_id"] for s in data["stores"]]
        assert "live-store" in ids
        # Synthetic rows are tagged so the UI can differentiate.
        row = next(s for s in data["stores"] if s["store_id"] == "live-store")
        assert row["status"] == "rotating"

    def test_empty_registry_and_scheduler_falls_back_to_default(
        self, patched_registry, patched_scheduler,
    ):
        patched_registry([])
        patched_scheduler(stores=[])
        data = _collect_stores_snapshot()
        assert data["default"] == "deguar"
        # The fallback row is emitted so the selector always has
        # something to render.
        assert any(s["store_id"] == "deguar" for s in data["stores"])

    def test_active_list_picks_default_when_registry_empty(
        self, patched_registry, patched_scheduler,
    ):
        patched_registry([])
        patched_scheduler(stores=["alpha", "beta"])
        data = _collect_stores_snapshot()
        assert data["default"] == "alpha"
        assert data["active"] == ["alpha", "beta"]

    def test_registry_failure_does_not_crash(
        self, patched_scheduler, monkeypatch,
    ):
        def _boom():
            raise RuntimeError("db locked")
        monkeypatch.setattr(
            "core.system.store_registry.get_store_registry", _boom,
        )
        patched_scheduler(stores=["x"])
        data = _collect_stores_snapshot()
        # Scheduler still feeds the selector.
        assert any(s["store_id"] == "x" for s in data["stores"])


# ---------------------------------------------------------------------------
# /api/stores
# ---------------------------------------------------------------------------


class TestStoresEndpoint:
    def test_returns_200(self, patched_registry, patched_scheduler):
        patched_registry([
            {"store_id": "deguar", "name": "Deguar",
             "status": "active", "niche": "home"},
        ])
        patched_scheduler(stores=["deguar"])
        h = _handler()
        h._api_stores()
        status, data = h._captured[-1]
        assert status == 200
        assert data["default"] == "deguar"
        assert len(data["stores"]) >= 1

    def test_endpoint_soft_on_total_failure(self, monkeypatch):
        def _boom():
            raise RuntimeError("catastrophic")
        monkeypatch.setattr(
            "core.system.store_registry.get_store_registry", _boom,
        )
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", _boom,
        )
        h = _handler()
        h._api_stores()
        status, data = h._captured[-1]
        # Still a 200 + envelope with a default.
        assert status == 200
        assert data["default"]


# ---------------------------------------------------------------------------
# /api/cycle?store_id=... filter
# ---------------------------------------------------------------------------


class TestCycleStoreFilter:
    def _summary(self, store_id: str, cycle_id: str) -> dict:
        return {
            "cycle_id": cycle_id,
            "store_id": store_id,
            "timestamp": 100.0,
            "duration_s": 1.0,
            "status": "ok",
        }

    def test_no_filter_returns_everything(self, patched_scheduler):
        recent = [
            self._summary("deguar", "c1"),
            self._summary("shop2", "c2"),
        ]
        patched_scheduler(stores=["deguar", "shop2"],
                          latest=recent[0], recent=recent)
        h = _handler(path="/api/cycle")
        h._api_cycle()
        _, data = h._captured[-1]
        assert len(data["recent"]) == 2
        assert data["store_filter"] == ""

    def test_store_filter_narrows_recent(self, patched_scheduler):
        recent = [
            self._summary("deguar", "c1"),
            self._summary("shop2", "c2"),
            self._summary("deguar", "c3"),
        ]
        patched_scheduler(stores=["deguar", "shop2"],
                          latest=recent[0], recent=recent)
        h = _handler(path="/api/cycle?store_id=shop2")
        h._api_cycle()
        _, data = h._captured[-1]
        assert data["store_filter"] == "shop2"
        assert len(data["recent"]) == 1
        assert data["recent"][0]["cycle_id"] == "c2"

    def test_latest_switches_when_global_latest_is_other_store(
        self, patched_scheduler,
    ):
        # Global "latest" is for store A, but we're filtering to B —
        # the endpoint should serve B's newest instead.
        global_latest = self._summary("A", "a-latest")
        recent = [
            global_latest,
            self._summary("B", "b-older"),
        ]
        patched_scheduler(stores=["A", "B"],
                          latest=global_latest, recent=recent)
        h = _handler(path="/api/cycle?store_id=B")
        h._api_cycle()
        _, data = h._captured[-1]
        assert data["latest"]["store_id"] == "B"

    def test_no_cycles_for_store_returns_empty_state(self, patched_scheduler):
        recent = [self._summary("A", "a1")]
        patched_scheduler(stores=["A"],
                          latest=recent[0], recent=recent)
        h = _handler(path="/api/cycle?store_id=nope")
        h._api_cycle()
        _, data = h._captured[-1]
        assert data["store_filter"] == "nope"
        assert data["recent"] == []
        assert data["has_data"] is False
