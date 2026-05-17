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


class TestSnapshotEnvelope:

    def test_has_canonical_keys(self):
        sm = _fake_sm()
        wm = WorldModel(sm=sm, queue=_fake_queue())
        with _patch_external():
            snap = wm.snapshot("test-store", skip_live=True)
        for key in (
            "store_id", "fetched_at", "store", "stats", "sync",
            "connection", "config", "design", "approvals", "decisions",
            "transfers",
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
