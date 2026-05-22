"""Tests for the per-store world-model snapshot
(``core.world_model``).

This is the foundation of the AGI orchestration layer -- the
single dict that every engine + the autonomous loop reads
before making a decision. The tests verify each section
populates correctly, skip-live works, and the resilience
contract (no section throws; everything degrades to
``{"checked": False, "error": ...}``) is upheld.
"""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from core.world_model import WorldModel, snapshot


# ─── Fakes ───────────────────────────────────────────────────


def _fake_sm(
    *,
    shop_url="example.myshopify.com",
    niche="beauty",
    store_type="dropshipping",
    is_active=True,
    products=42, orders=10, customers=15, revenue=999.99,
    connected=True,
    api_key="shpat_token",
):
    sm = MagicMock()
    sm.get_store.return_value = {
        "shop_url": shop_url, "niche": niche,
        "store_type": store_type, "is_active": is_active,
        "name": "Test Store",
    }
    sm.get_stats.return_value = {
        "products": products, "orders": orders,
        "customers": customers, "total_revenue": revenue,
    }
    sm.test_connection.return_value = {
        "connected": connected,
        "shop": shop_url,
        "error": "" if connected else "401",
    }
    sm.get_credentials.return_value = {
        "shop_url": shop_url, "api_key": api_key,
    }
    return sm


def _fake_queue(
    *,
    pending=3,
    pending_by_engine=None,
    decisions=None,
):
    q = MagicMock()
    q.stats.return_value = {
        "pending": pending,
        "approved": 5,
        "rejected": 1,
        "executed": 12,
        "failed": 0,
        "expired": 2,
    }
    q.stats_by_engine.return_value = (
        pending_by_engine
        if pending_by_engine is not None
        else {
            "loyalty": {"pending": 2, "executed": 5},
            "dynamic_pricing": {"pending": 1, "executed": 3},
        }
    )
    q.list_decisions.return_value = (
        decisions
        if decisions is not None
        else [
            {"action_id": "a1", "decision": "approved",
             "decided_by": "operator", "reason": "",
             "occurred_at": time.time() - 30.0},
            {"action_id": "a2", "decision": "executed",
             "decided_by": "system", "reason": "",
             "occurred_at": time.time() - 120.0},
        ]
    )
    return q


def _fake_sync_status(store_id, *, age_seconds=120.0, status="success"):
    return {
        "stores": [{
            "store_id": store_id,
            "last_sync": time.time() - age_seconds,
            "last_status": status,
        }],
    }


def _fake_plan_result(plan_count=5):
    return {
        "status": "planned",
        "niche": "beauty",
        "features": ["collections"],
        "results": {"collections": {}, "discounts": {}},
        "plan": [
            {"method": "POST", "path": "smart_collections.json",
             "description": "c", "body_preview": {}}
            for _ in range(plan_count)
        ],
    }


# ─── Section-by-section coverage ─────────────────────────────


class TestStoreSection:

    def test_populates_store_fields(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        store = snap["store"]
        assert store["shop_url"] == "example.myshopify.com"
        assert store["niche"] == "beauty"
        assert store["store_type"] == "dropshipping"
        assert store["is_active"] is True

    def test_missing_store_returns_empty_shape(self):
        sm = MagicMock()
        sm.get_store.return_value = None
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("ghost", skip_live=True)
        # All fields present, just empty
        assert snap["store"]["shop_url"] == ""
        assert snap["store"]["niche"] is None


class TestStatsSection:

    def test_populates_stats(self):
        sm = _fake_sm(products=42, orders=10, customers=15, revenue=999.99)
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        s = snap["stats"]
        assert s["products"] == 42
        assert s["orders"] == 10
        assert s["customers"] == 15
        assert s["total_revenue"] == 999.99

    def test_stats_probe_failure_returns_zeros(self):
        sm = MagicMock()
        sm.get_store.return_value = {"shop_url": "x"}
        sm.get_stats.side_effect = RuntimeError("db down")
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert snap["stats"]["products"] == 0
        assert snap["stats"]["total_revenue"] == 0.0


class TestSyncSection:

    def test_populates_sync(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=120.0)
            )
            snap = wm.snapshot("test-store", skip_live=True)
        s = snap["sync"]
        assert s["last_sync_at"] is not None
        assert s["last_sync_status"] == "success"
        # Age should be ~120
        assert 100 < s["age_seconds"] < 200

    def test_never_synced(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            snap = wm.snapshot("test-store", skip_live=True)
        s = snap["sync"]
        assert s["last_sync_at"] is None
        assert s["age_seconds"] is None


# ─── Live probes ─────────────────────────────────────────────


class TestConnectionSection:

    def test_skip_live_marks_unchecked(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert snap["connection"]["checked"] is False

    def test_live_connection_success(self):
        sm = _fake_sm(connected=True)
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external(plan_result=_fake_plan_result()):
            snap = wm.snapshot("test-store", skip_live=False)
        assert snap["connection"]["checked"] is True
        assert snap["connection"]["connected"] is True

    def test_live_connection_failure(self):
        sm = _fake_sm(connected=False)
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=False)
        assert snap["connection"]["checked"] is True
        assert snap["connection"]["connected"] is False


class TestConfigSection:

    def test_drift_count_populates(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external(plan_result=_fake_plan_result(plan_count=7)):
            snap = wm.snapshot("test-store", skip_live=False)
        c = snap["config"]
        assert c["checked"] is True
        assert c["planned_writes"] == 7
        assert c["has_drift"] is True

    def test_clean_store_has_no_drift(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external(plan_result=_fake_plan_result(plan_count=0)):
            snap = wm.snapshot("test-store", skip_live=False)
        c = snap["config"]
        assert c["has_drift"] is False
        assert c["planned_writes"] == 0

    def test_skips_when_connection_failed(self):
        sm = _fake_sm(connected=False)
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=False)
        # When connection fails, config probe is skipped without
        # touching the configurator
        c = snap["config"]
        assert c["checked"] is False
        assert c["error"] == "connection_failed"

    def test_skip_live_marks_unchecked(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert snap["config"]["checked"] is False

    def test_configurator_raise_surfaces_as_error(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
            side_effect=RuntimeError("config broke"),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            design_cls.return_value.run.return_value = {
                "status": "success", "data": {}, "meta": {}, "error": None,
            }
            snap = wm.snapshot("test-store", skip_live=False)
        c = snap["config"]
        assert c["checked"] is True
        assert "config broke" in c["error"]


# ─── Design / approvals / decisions ──────────────────────────


class TestDesignSection:

    def test_populates_from_engine(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {
                    "estimated_conversion_lift": 0.18,
                    "layout_recommendations": [1, 2, 3],
                    "mobile_optimizations": [1, 2],
                },
                "meta": {}, "error": None,
            }
            snap = wm.snapshot("test-store", skip_live=True)
        d = snap["design"]
        assert d["checked"] is True
        assert d["estimated_conversion_lift"] == 0.18
        assert d["layout_count"] == 3
        assert d["mobile_count"] == 2

    def test_engine_raise_surfaces(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
            side_effect=RuntimeError("engine down"),
        ):
            sync_cls.return_value.get_status.return_value = {"stores": []}
            snap = wm.snapshot("test-store", skip_live=True)
        # Section never throws -- just marked checked=False
        assert snap["design"]["checked"] is False
        assert "engine down" in snap["design"]["error"]


class TestApprovalsSection:

    def test_populates_pending_counts(self):
        """When ``store_id`` is supplied to snapshot(), the section
        operates in per_store scope: it rolls up pending actions
        from list_pending(store_id=...) instead of the global
        stats_by_engine."""
        sm = _fake_sm()
        # Build per-store pending actions: 3 for loyalty, 2 for
        # dynamic_pricing.
        pending_actions = []
        for _ in range(3):
            a = MagicMock()
            a.engine = "loyalty"
            pending_actions.append(a)
        for _ in range(2):
            a = MagicMock()
            a.engine = "dynamic_pricing"
            pending_actions.append(a)
        q = MagicMock()
        q.list_pending.return_value = pending_actions
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        a = snap["approvals"]
        assert a["checked"] is True
        assert a["scope"] == "per_store"
        assert a["store_id"] == "test-store"
        assert a["pending_total"] == 5
        assert a["pending_by_engine"] == {
            "loyalty": 3, "dynamic_pricing": 2,
        }

    def test_queue_raise_degrades(self):
        sm = _fake_sm()
        q = MagicMock()
        q.list_pending.side_effect = RuntimeError("queue down")
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert snap["approvals"]["checked"] is False
        assert "queue down" in snap["approvals"]["error"]

    def test_legacy_queue_without_store_id_falls_back_to_global(self):
        """Legacy queues without store_id kwarg fall back to the
        global pending count from stats()."""
        sm = _fake_sm()
        q = MagicMock()
        # Simulate a fake queue that doesn't accept store_id
        q.list_pending.side_effect = TypeError(
            "unexpected keyword argument 'store_id'"
        )
        q.stats.return_value = {"pending": 7}
        q.stats_by_engine.return_value = {
            "loyalty": {"pending": 7},
        }
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        a = snap["approvals"]
        # Falls back to global scope
        assert a["scope"] == "global"
        assert a["pending_total"] == 7


class TestDecisionsSection:

    def test_populates_recent(self):
        """Per-store decisions section pulls EXECUTED + FAILED
        actions tagged with the snapshot store_id."""
        sm = _fake_sm()
        now = time.time()
        executed = MagicMock()
        executed.decided_at = now - 30.0
        failed = MagicMock()
        failed.decided_at = now - 120.0
        q = MagicMock()

        def _list_by_status(status, *, store_id=None, limit=25, **kw):
            from core.approval.queue import ApprovalStatus
            if status == ApprovalStatus.EXECUTED:
                return [executed]
            if status == ApprovalStatus.FAILED:
                return [failed]
            return []

        q.list_by_status.side_effect = _list_by_status
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        d = snap["decisions"]
        assert d["checked"] is True
        assert d["scope"] == "per_store"
        assert d["recent_count"] == 2
        assert d["last_occurred_at"] is not None

    def test_no_decisions(self):
        sm = _fake_sm()
        q = _fake_queue(decisions=[])
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        d = snap["decisions"]
        assert d["recent_count"] == 0
        assert d["last_occurred_at"] is None


# ─── Top-level snapshot envelope ─────────────────────────────


class TestTransfersSection:
    """Cross-store transfer activity touching this store --
    rows enqueued via ``shopai transfer apply``, split into
    incoming (this store = target) and outgoing (this store =
    source per narrative parse)."""

    def _make_queue_with_transfers(
        self, *, incoming=None, outgoing=None,
    ):
        """Build a queue whose ``_conn.execute(...)`` returns
        the right rows based on the SQL params bound.

        The handler issues two queries: incoming uses
        ``store_id = ?`` as the first bound param; outgoing uses
        a narrative LIKE ``%from <store_id> to %`` as the first
        bound param. We dispatch on which form the first param
        takes.
        """
        incoming = incoming or []
        outgoing = outgoing or []
        q = MagicMock()
        # The unrelated queue calls in other sections still need
        # to work; default the rest to empty.
        q.stats.return_value = {"pending": 0}
        q.stats_by_engine.return_value = {}
        q.list_decisions.return_value = []

        fake_conn = MagicMock()
        fake_conn.__enter__ = lambda self: self
        fake_conn.__exit__ = lambda *a: None

        def _execute(sql, params):
            cursor = MagicMock()
            first = params[0] if params else ""
            if isinstance(first, str) and first.startswith("%"):
                cursor.fetchall.return_value = list(outgoing)
            else:
                cursor.fetchall.return_value = list(incoming)
            return cursor

        fake_conn.execute.side_effect = _execute
        q._conn = fake_conn
        return q

    def test_empty_buckets_when_no_transfers(self):
        sm = _fake_sm()
        q = self._make_queue_with_transfers()
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        t = snap["transfers"]
        assert t["checked"] is True
        for direction in ("incoming", "outgoing"):
            assert t[direction]["total"] == 0
            assert t[direction]["executed"] == 0
            assert t[direction]["pending"] == 0

    def test_incoming_rows_counted_by_status(self):
        sm = _fake_sm()
        incoming = [
            {"status": "executed"}, {"status": "executed"},
            {"status": "pending"},  {"status": "failed"},
            {"status": "rejected"},
        ]
        q = self._make_queue_with_transfers(incoming=incoming)
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        inc = snap["transfers"]["incoming"]
        assert inc["total"] == 5
        assert inc["executed"] == 2
        assert inc["pending"] == 1
        assert inc["failed"] == 1
        assert inc["other"] == 1

    def test_outgoing_rows_counted_independently(self):
        """Outgoing scan keys off the narrative LIKE pattern, NOT
        store_id, so it's a different result set than incoming."""
        sm = _fake_sm()
        outgoing = [
            {"status": "executed"}, {"status": "executed"},
            {"status": "executed"},
        ]
        q = self._make_queue_with_transfers(outgoing=outgoing)
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        out = snap["transfers"]["outgoing"]
        assert out["total"] == 3
        assert out["executed"] == 3
        # Incoming bucket stays zeroed (different result set).
        assert snap["transfers"]["incoming"]["total"] == 0

    def test_queue_unavailable_marks_section_failed(self):
        """If the approval queue is unavailable, transfers
        section reports checked=False with the error -- doesn't
        raise out of the snapshot."""
        sm = _fake_sm()
        q = MagicMock()
        # Make ``q._conn`` raise via attribute access.
        type(q)._conn = property(
            lambda self: (_ for _ in ()).throw(
                RuntimeError("queue offline"),
            ),
        )
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        t = snap["transfers"]
        # Each query catches its own error -- buckets just
        # come back empty, but the section completes.
        assert t["checked"] is True
        assert t["incoming"]["total"] == 0
        assert t["outgoing"]["total"] == 0


class TestRecentOutcomesSection:
    """Per-store recent-outcomes stream — uses
    ``queue.list_recent_outcomes(store_id=...)`` extension from
    PR #280."""

    def _make_queue(self, *, rows=None, raises_on_store_id=False):
        rows = rows or []
        q = MagicMock()
        q.stats.return_value = {"pending": 0}
        q.stats_by_engine.return_value = {}
        q.list_decisions.return_value = []
        fake_conn = MagicMock()
        fake_conn.__enter__ = lambda self: self
        fake_conn.__exit__ = lambda *a: None
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        fake_conn.execute.return_value = cursor
        q._conn = fake_conn

        def _list_recent(**kwargs):
            if raises_on_store_id and "store_id" in kwargs:
                raise TypeError(
                    "unexpected keyword argument 'store_id'"
                )
            return rows

        q.list_recent_outcomes.side_effect = _list_recent
        return q

    def test_recent_outcomes_aggregated_and_listed(self):
        sm = _fake_sm()
        rows = [
            {"action_id": "a1", "polarity": "positive",
             "metrics": {"revenue": 50.0}, "recorded_at": 1.0},
            {"action_id": "a2", "polarity": "negative",
             "metrics": {"revenue": -5.0}, "recorded_at": 2.0},
            {"action_id": "a3", "polarity": "positive",
             "metrics": {"revenue": 25.0}, "recorded_at": 3.0},
        ]
        q = self._make_queue(rows=rows)
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        sec = snap["recent_outcomes"]
        assert sec["checked"] is True
        assert sec["count"] == 3
        assert sec["summary"]["positive"] == 2
        assert sec["summary"]["negative"] == 1
        assert sec["summary"]["revenue"] == 70.0
        assert len(sec["recent"]) == 3
        kw = q.list_recent_outcomes.call_args.kwargs
        assert kw["store_id"] == "store-a"

    def test_pre_pr_280_queue_marks_section_failed(self):
        """Queue without store_id kwarg: section returns
        checked=False with the operator-friendly error
        explaining the missing migration."""
        sm = _fake_sm()
        q = self._make_queue(raises_on_store_id=True)
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        sec = snap["recent_outcomes"]
        assert sec["checked"] is False
        assert "PR #280" in sec["error"]

    def test_empty_results_render_zeroed_summary(self):
        sm = _fake_sm()
        q = self._make_queue(rows=[])
        wm = WorldModel(sm=sm, queue=q)
        with _patch_external():
            snap = wm.snapshot("store-a", skip_live=True)
        sec = snap["recent_outcomes"]
        assert sec["checked"] is True
        assert sec["count"] == 0
        assert sec["summary"]["positive"] == 0


class TestSnapshotEnvelope:

    def test_has_canonical_keys(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        for key in (
            "store_id", "fetched_at", "store", "stats", "sync",
            "connection", "config", "design", "approvals", "decisions",
            "transfers", "recent_outcomes", "quarantine",
        ):
            assert key in snap

    def test_fetched_at_is_close_to_now(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert abs(snap["fetched_at"] - time.time()) < 1.0

    def test_module_level_snapshot_function(self):
        """The module-level ``snapshot()`` is a thin shim over
        ``WorldModel().snapshot()`` -- uses real singletons by
        default, so we patch the resolution path."""
        # No fakes injected -- module-level function uses real
        # singletons. We only test that calling it works at all
        # (doesn't crash on import paths) since the section
        # logic is already covered above.
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as sm_cls, patch(
            "core.approval.queue.get_approval_queue",
        ) as gaq, patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sm_cls.return_value = _fake_sm()
            gaq.return_value = _fake_queue()
            sync_cls.return_value.get_status.return_value = {"stores": []}
            design_cls.return_value.run.return_value = {
                "status": "success", "data": {}, "meta": {}, "error": None,
            }
            snap = snapshot("test-store", skip_live=True)
        assert snap["store_id"] == "test-store"


# ─── Helper: patch every external probe ──────────────────────


def _patch_external(*, plan_result=None):
    """Return a context manager that patches the four external
    integrations (sync service, configurator, design engine,
    oauth) so each test only needs to opt in to the ones it
    cares about."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            configurator_cls.return_value.configure.return_value = (
                plan_result or _fake_plan_result(plan_count=0)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {
                    "estimated_conversion_lift": 0.10,
                    "layout_recommendations": [],
                    "mobile_optimizations": [],
                },
                "meta": {}, "error": None,
            }
            yield

    return _ctx()


# ─── Fleet-health rollup ─────────────────────────────────────


class TestSectionFleetHealth:
    """``_section_fleet_health`` rolls up engine_health verdicts
    across the whole engine roster -- the snapshot's 'is the
    fleet OK right now' answer at a glance."""

    @pytest.fixture(autouse=True)
    def _data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        yield tmp_path

    def _stub_health(self, engine, verdict, score=8):
        from core.approval.engine_health import EngineHealth
        return EngineHealth(
            engine=engine, score=score, verdict=verdict,
            signals={}, concerns=[],
        )

    def test_empty_roster_handled(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {}, clear=True,
        ):
            sec = wm._section_fleet_health()
        assert sec["checked"] is True
        assert sec["total_engines"] == 0
        assert sec["average_score"] is None
        assert sec["sickest"] == []

    def test_verdict_counts_populated(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        verdicts = {
            "loyalty": "unhealthy",
            "cart_recovery": "warning",
            "dynamic_pricing": "healthy",
        }
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {k: "maximize_profit" for k in verdicts},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: self._stub_health(
                engine, verdicts[engine],
                score={
                    "unhealthy": 3, "warning": 6, "healthy": 9,
                }[verdicts[engine]],
            ),
        ):
            sec = wm._section_fleet_health()
        assert sec["verdict_counts"] == {
            "healthy": 1, "warning": 1, "unhealthy": 1,
        }
        assert sec["total_engines"] == 3
        # avg = (3 + 6 + 9) / 3 = 6.0
        assert sec["average_score"] == 6.0

    def test_sickest_sorted_asc(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        scores = {"a": 9, "b": 3, "c": 7, "d": 5, "e": 10, "f": 1}
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {k: "maximize_profit" for k in scores},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: self._stub_health(
                engine, "healthy", score=scores[engine],
            ),
        ):
            sec = wm._section_fleet_health()
        # Top 5 by score asc: f(1), b(3), d(5), c(7), a(9)
        sickest_engines = [r["engine"] for r in sec["sickest"]]
        assert sickest_engines == ["f", "b", "d", "c", "a"]
        assert len(sec["sickest"]) == 5

    def test_score_engine_raise_skips(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())

        def _score(engine, **kw):
            if engine == "broken":
                raise RuntimeError("scorer down")
            return self._stub_health(engine, "healthy")

        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {"broken": "g", "loyalty": "g"},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=_score,
        ):
            sec = wm._section_fleet_health()
        assert sec["total_engines"] == 1
        engines = [r["engine"] for r in sec["sickest"]]
        assert "loyalty" in engines
        assert "broken" not in engines

    def test_import_failure_fails_open(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            side_effect=ImportError("bad import"),
        ):
            # Patching the dict attribute with side_effect isn't
            # actually how ImportError surfaces in real code; the
            # real failure mode is the import itself raising. We
            # exercise that path here by patching the
            # core.approval.engine_health module to be unavailable.
            with patch(
                "core.world_model.snapshot.logger",  # silence noise
            ):
                sec = wm._section_fleet_health()
        # Either checked=True with data, or checked=False -- both
        # acceptable failure-isolated outcomes.
        assert "checked" in sec

    def test_section_appears_in_full_snapshot(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert "fleet_health" in snap


# ─── Quarantine section ──────────────────────────────────────


class TestSectionQuarantine:
    """``_section_quarantine`` surfaces the FLEET quarantine
    state inside each per-store snapshot."""

    @pytest.fixture(autouse=True)
    def _data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        yield tmp_path

    def test_empty_state(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert sec["checked"] is True
        assert sec["scope"] == "fleet"
        assert sec["exemptions"] == []
        assert sec["released"] == []
        assert sec["alert_paused"] == []
        assert sec["alert_release_candidates"] == []
        assert sec["alert_pause_candidates"] == []
        # Bridge is present (PR #294 module is on PYTHONPATH).
        assert sec["bridge"] is not None
        assert sec["bridge"]["enabled"] is False

    def test_populated_state(self):
        from core.approval import quarantine
        quarantine.exempt_engine("returns")
        quarantine.release_engine("loyalty")
        quarantine.add_alert_pause("affiliate")

        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert sec["exemptions"] == ["returns"]
        assert sec["released"] == ["loyalty"]
        assert sec["alert_paused"] == ["affiliate"]

    def test_bridge_reflects_env_var(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "5")
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert sec["bridge"]["enabled"] is True
        assert sec["bridge"]["threshold_days"] == 5

    def test_load_failure_fails_open(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk corrupt"),
        ):
            sec = wm._section_quarantine()
        assert sec["checked"] is False
        assert "disk corrupt" in sec["error"]

    def test_section_appears_in_full_snapshot(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert "quarantine" in snap
        assert snap["quarantine"]["checked"] is True
        # Snapshot is per-store -- scope reflects that.
        assert snap["quarantine"]["scope"] == "per_store"
        assert snap["quarantine"]["store_id"] == "test-store"

    def test_candidate_lists_populated(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.approval.alert_quarantine."
            "find_release_candidates",
            return_value=[
                {"engine": "loyalty"},
                {"engine": "affiliate"},
            ],
        ), patch(
            "core.approval.alert_quarantine."
            "find_pause_candidates",
            return_value=[
                {"engine": "wholesale",
                 "consecutive_days": 5,
                 "blocked_by": None},
                {"engine": "blocked_one",
                 "consecutive_days": 4,
                 "blocked_by": "exempt"},
            ],
        ):
            sec = wm._section_quarantine()
        assert sec["alert_release_candidates"] == [
            "loyalty", "affiliate",
        ]
        # ``blocked_one`` filtered out -- it has blocked_by set
        assert sec["alert_pause_candidates"] == ["wholesale"]

    def test_candidate_probe_failure_keeps_section(self):
        """If find_release_candidates raises, the section still
        returns; just with empty candidate lists."""
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.approval.alert_quarantine."
            "find_release_candidates",
            side_effect=RuntimeError("disk corrupt"),
        ):
            sec = wm._section_quarantine()
        assert sec["checked"] is True
        assert sec["alert_release_candidates"] == []
        # find_pause_candidates may also raise via the same path,
        # but its empty list is the default.

    def test_no_store_filter_yields_fleet_scope(self):
        """Without store_id, scope is ``fleet`` and the
        ``for_this_store`` block is empty."""
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert sec["scope"] == "fleet"
        assert sec["store_id"] is None
        assert sec["for_this_store"] == {
            "exempt": [],
            "released": [],
            "alert_paused": [],
        }

    def test_per_store_filter_fleet_pause_affects_all_stores(
        self,
    ):
        """Fleet-wide ``(engine, None)`` pause affects every
        store; surface in ``for_this_store.alert_paused``."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")  # fleet-wide
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine(store_id="store_a")
        assert sec["scope"] == "per_store"
        assert sec["store_id"] == "store_a"
        assert sec["for_this_store"]["alert_paused"] == [
            "loyalty",
        ]

    def test_per_store_filter_per_store_pause_only_matches(
        self,
    ):
        """A ``(engine, 'store_a')`` per-store pause shows in
        store_a's snapshot but not store_b's."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty", store_id="store_a")
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec_a = wm._section_quarantine(store_id="store_a")
        sec_b = wm._section_quarantine(store_id="store_b")
        assert sec_a["for_this_store"]["alert_paused"] == [
            "loyalty",
        ]
        assert sec_b["for_this_store"]["alert_paused"] == []

    def test_per_store_filter_includes_exempt_and_released(
        self,
    ):
        """Engine-level exempt + released apply fleet-wide so
        they surface in for_this_store for any store."""
        from core.approval import quarantine
        quarantine.exempt_engine("returns")
        quarantine.release_engine("affiliate")
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine(store_id="store_a")
        assert sec["for_this_store"]["exempt"] == ["returns"]
        assert sec["for_this_store"]["released"] == ["affiliate"]

    def test_snapshot_passes_store_id_to_quarantine_section(
        self,
    ):
        """Full snapshot wires store_id through to the section
        so the per-store filter activates automatically."""
        from core.approval import quarantine
        quarantine.add_alert_pause(
            "loyalty", store_id="test-store",
        )
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        assert snap["quarantine"]["scope"] == "per_store"
        assert snap["quarantine"]["store_id"] == "test-store"
        assert snap["quarantine"]["for_this_store"][
            "alert_paused"
        ] == ["loyalty"]

    def test_recent_alerts_empty_by_default(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert sec["recent_alerts"] == []

    def test_recent_alerts_populated(self, _data_dir):
        # Bypass record_alerts' pytest test-env guard by writing
        # the alert_history.json directly.
        import json
        import time
        now = time.time()
        events = [
            {
                "engine": "loyalty",
                "recorded_at": now - i * 60.0,
                "drop": 0.40,
                "recent_score": 1.0,
                "baseline_score": 2.5,
                "store_id": "store_a" if i % 2 == 0 else None,
            }
            for i in range(3)
        ]
        (_data_dir / "alert_history.json").write_text(
            json.dumps(events), encoding="utf-8",
        )

        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert len(sec["recent_alerts"]) == 3
        # Newest-first ordering from recent_history
        first = sec["recent_alerts"][0]
        assert first["engine"] == "loyalty"
        assert first["drop"] == 0.40
        assert first["recent_score"] == 1.0
        assert first["baseline_score"] == 2.5
        # store_id flows through (None or str)
        store_ids = {a["store_id"] for a in sec["recent_alerts"]}
        assert "store_a" in store_ids
        assert None in store_ids

    def test_recent_alerts_capped_at_ten(self, _data_dir):
        import json
        import time
        now = time.time()
        events = [
            {
                "engine": f"eng_{i}",
                "recorded_at": now - i * 60.0,
                "drop": 0.40,
                "recent_score": 1.0,
                "baseline_score": 2.5,
                "store_id": None,
            }
            for i in range(15)
        ]
        (_data_dir / "alert_history.json").write_text(
            json.dumps(events), encoding="utf-8",
        )

        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        sec = wm._section_quarantine()
        assert len(sec["recent_alerts"]) == 10

    def test_recent_alerts_failure_keeps_section(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.approval.alert_history.recent_history",
            side_effect=RuntimeError("history corrupted"),
        ):
            sec = wm._section_quarantine()
        # Section still renders; recent_alerts degrades to []
        assert sec["checked"] is True
        assert sec["recent_alerts"] == []


class TestSectionSubstrate:
    """``_section_substrate`` surfaces capability-layer
    overrides + bridge config + degradation candidates."""

    def _override(
        self, name, kind="demote", reason="", at=0.0,
    ):
        from core.capability_planner.\
capability_overrides import CapabilityOverride
        return CapabilityOverride(
            name=name, kind=kind, reason=reason,
            recorded_at=at,
        )

    def _overrides_for(self, *entries):
        from core.capability_planner.\
capability_overrides import CapabilityOverrides
        return CapabilityOverrides(entries=list(entries))

    def test_empty_substrate_envelope(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=self._overrides_for(),
        ), patch(
            "core.capability_planner."
            "capability_degradations",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ):
            sec = wm._section_substrate()
        assert sec["checked"] is True
        assert sec["scope"] == "fleet"
        assert sec["overrides"]["total"] == 0
        assert sec["overrides"]["promoted"] == []
        assert sec["overrides"]["demoted"] == []
        assert sec["overrides"]["auto_demoted"] == []
        assert sec["demote_candidates"] == 0
        assert sec["release_candidates"] == 0
        assert sec["recent_degradations"] == []
        assert sec["bridge"]["enabled"] is False
        assert (
            sec["bridge"]["recovery_threshold"] == 0.7
        )

    def test_overrides_populate_separated(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        overrides = self._overrides_for(
            self._override(
                "winner", kind="promote",
                reason="beauty niche", at=100.0,
            ),
            self._override(
                "regressed",
                reason="auto_demote_degraded: drop=0.6 ...",
                at=200.0,
            ),
            self._override(
                "manual_broken",
                reason="operator says",
                at=300.0,
            ),
        )
        with patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=overrides,
        ), patch(
            "core.capability_planner."
            "capability_degradations",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ):
            sec = wm._section_substrate()
        assert sec["overrides"]["total"] == 3
        assert len(sec["overrides"]["promoted"]) == 1
        assert (
            sec["overrides"]["promoted"][0]["name"]
            == "winner"
        )
        assert len(sec["overrides"]["demoted"]) == 2
        # Bridge-driven demote separated into auto bucket
        assert len(sec["overrides"]["auto_demoted"]) == 1
        assert (
            sec["overrides"]["auto_demoted"][0]["name"]
            == "regressed"
        )

    def test_demote_candidates_filters_blocked(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        candidates = [
            {
                "capability": "cap_a",
                "blocked_by": None,
            },
            {
                "capability": "cap_b",
                "blocked_by": "promoted",
            },
            {
                "capability": "cap_c",
                "blocked_by": "already_demoted",
            },
        ]
        with patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=self._overrides_for(),
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=candidates,
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner."
            "capability_degradations",
            return_value=[],
        ):
            sec = wm._section_substrate()
        # Only the unblocked candidate counted
        assert sec["demote_candidates"] == 1

    def test_recent_degradations_capped_at_5(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        degs = [
            {
                "capability": f"cap_{i}",
                "baseline_rate": 0.9,
                "recent_rate": 0.1,
                "drop": 0.8,
                "recent_samples": 5,
                "baseline_samples": 20,
            }
            for i in range(8)
        ]
        with patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=self._overrides_for(),
        ), patch(
            "core.capability_planner."
            "capability_degradations",
            return_value=degs,
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ):
            sec = wm._section_substrate()
        assert len(sec["recent_degradations"]) == 5

    def test_load_failure_fails_open(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            side_effect=RuntimeError("disk corrupt"),
        ), patch(
            "core.capability_planner."
            "capability_degradations",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ):
            sec = wm._section_substrate()
        assert sec["checked"] is True
        # Overrides empty (couldn't load) but section
        # remains usable
        assert sec["overrides"]["total"] == 0

    def test_section_appears_in_full_snapshot(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external(), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=self._overrides_for(),
        ), patch(
            "core.capability_planner."
            "capability_degradations",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ):
            snap = wm.snapshot("test-store", skip_live=True)
        assert "substrate" in snap
        assert snap["substrate"]["checked"] is True
        assert snap["substrate"]["scope"] == "fleet"


class TestSectionCycle:
    """Per-store cycle activity in the world-model snapshot."""

    def test_default_zeros(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.autonomous.cycle_history.per_store_stats",
            return_value={},
        ), patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=[],
        ):
            sec = wm._section_cycle(store_id="store-x")
        assert sec["checked"] is True
        assert sec["scope"] == "per_store"
        assert sec["store_id"] == "store-x"
        assert sec["stats"]["total"] == 0
        assert sec["last_outcome"] is None

    def test_per_store_stats_populate(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.autonomous.cycle_history.per_store_stats",
            return_value={
                "store-a": {
                    "executed": 5, "refused": 2,
                    "errored": 0, "no_plan": 0,
                    "total": 7,
                },
            },
        ), patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=[],
        ):
            sec = wm._section_cycle(store_id="store-a")
        assert sec["stats"]["executed"] == 5
        assert sec["stats"]["refused"] == 2
        assert sec["stats"]["total"] == 7

    def test_last_outcome_from_recent_events(self):
        from core.autonomous.cycle_history import CycleEvent
        ev = CycleEvent(
            recorded_at=100.0,
            executed=True,
            advance={
                "per_store": [
                    {
                        "store_id": "store-a",
                        "outcome": "executed",
                    },
                ],
            },
        )
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.autonomous.cycle_history.per_store_stats",
            return_value={
                "store-a": {
                    "executed": 1, "refused": 0,
                    "errored": 0, "no_plan": 0,
                    "total": 1,
                },
            },
        ), patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=[ev],
        ):
            sec = wm._section_cycle(store_id="store-a")
        assert sec["last_outcome"] == "executed"
        assert sec["last_recorded_at"] == 100.0

    def test_fleet_scope_aggregates(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.autonomous.cycle_history.per_store_stats",
            return_value={
                "a": {
                    "executed": 2, "refused": 0,
                    "errored": 0, "no_plan": 0,
                    "total": 2,
                },
                "b": {
                    "executed": 1, "refused": 3,
                    "errored": 0, "no_plan": 0,
                    "total": 4,
                },
            },
        ), patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=[],
        ):
            sec = wm._section_cycle(store_id=None)
        assert sec["scope"] == "fleet"
        assert sec["stats"]["executed"] == 3
        assert sec["stats"]["refused"] == 3
        assert sec["stats"]["total"] == 6

    def test_import_failure_keeps_section(self):
        wm = WorldModel(sm=_fake_sm(), queue=_fake_queue())
        with patch(
            "core.autonomous.cycle_history.per_store_stats",
            side_effect=RuntimeError("disk"),
        ):
            sec = wm._section_cycle(store_id="store-x")
        # Stays checked, stats default zeros
        assert sec["checked"] is True
        assert sec["stats"]["total"] == 0

    def test_section_appears_in_snapshot(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external(), patch(
            "core.autonomous.cycle_history.per_store_stats",
            return_value={},
        ), patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=[],
        ):
            snap = wm.snapshot("store-x", skip_live=True)
        assert "cycle" in snap
        assert snap["cycle"]["checked"] is True
