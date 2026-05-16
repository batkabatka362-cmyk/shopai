"""Tests for ``shopai store report`` -- the one-shot per-store
summary that bundles stats + sync + connection + drift + design
lift.

The command is read-only and operator-facing. It also functions
as the foundation for the per-store world-model layer in the
AGI roadmap: every section maps to a slice of state the
orchestrator needs at decision time.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(store_id=None, json=False, skip_live=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_store_manager(
    *,
    active="test-store",
    shop_url="example.myshopify.com",
    niche="beauty",
    store_type="dropshipping",
    is_active=True,
    products=42, orders=10, customers=15, revenue=999.99,
    connected=True,
    api_key="shpat_token",
):
    sm = MagicMock()
    sm.active_store_id = active
    sm.get_stats.return_value = {
        "products": products, "orders": orders,
        "customers": customers, "total_revenue": revenue,
    }
    sm.get_store.return_value = {
        "shop_url": shop_url, "niche": niche,
        "store_type": store_type, "is_active": is_active,
        "name": active,
    }
    sm.test_connection.return_value = {
        "connected": connected, "shop": shop_url,
    }
    sm.get_credentials.return_value = {
        "shop_url": shop_url, "api_key": api_key,
    }
    return sm


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
        "results": {"collections": {}},
        "plan": [
            {"method": "POST", "path": "smart_collections.json",
             "description": "c", "body_preview": {}}
            for _ in range(plan_count)
        ],
    }


# ─── Text render ─────────────────────────────────────────────


class TestTextRender:

    def test_renders_all_sections(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=60.0)
            )
            configurator_cls.return_value.configure.return_value = (
                _fake_plan_result(plan_count=3)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {
                    "estimated_conversion_lift": 0.15,
                    "layout_recommendations": [1, 2],
                    "mobile_optimizations": [1, 2, 3],
                },
                "meta": {}, "error": None,
            }
            out, code = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store"),
            )
        assert code == 0
        # Header + 4 sections + verdict
        assert "Store report: test-store" in out
        assert "Stats:" in out
        assert "Sync:" in out
        assert "Live probes:" in out
        assert "[ok  ] connection" in out
        assert "[drift]" in out or "[ok  ] drift" in out
        assert "[ok  ] design" in out
        assert "Verdict:" in out

    def test_verdict_healthy_when_no_drift(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=60.0)
            )
            configurator_cls.return_value.configure.return_value = (
                _fake_plan_result(plan_count=0)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {"estimated_conversion_lift": 0.1},
                "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store"),
            )
        assert "Verdict: healthy" in out

    def test_verdict_flags_drift(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=60.0)
            )
            configurator_cls.return_value.configure.return_value = (
                _fake_plan_result(plan_count=12)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {"estimated_conversion_lift": 0.1},
                "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store"),
            )
        assert "attention needed" in out
        assert "12 drift" in out

    def test_verdict_flags_stale_sync(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=200_000.0)
            )
            configurator_cls.return_value.configure.return_value = (
                _fake_plan_result(plan_count=0)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {"estimated_conversion_lift": 0.1},
                "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store"),
            )
        assert "sync stale" in out

    def test_skip_live_skips_probes(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=60.0)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {"estimated_conversion_lift": 0.1},
                "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store", skip_live=True),
            )
        # Both live sections appear as [skip]
        assert "[skip] connection" in out
        assert "[skip] drift" in out
        # Design is cheap (no live call), still rendered
        assert "[ok  ] design" in out


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store")
            )
            configurator_cls.return_value.configure.return_value = (
                _fake_plan_result(plan_count=4)
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {
                    "estimated_conversion_lift": 0.15,
                    "layout_recommendations": [1, 2, 3],
                    "mobile_optimizations": [1],
                },
                "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store", json=True),
            )
        data = json.loads(out)
        assert data["store_id"] == "test-store"
        assert data["shop_url"] == "example.myshopify.com"
        assert data["niche"] == "beauty"
        assert data["stats"]["products"] == 42
        assert data["last_sync_at"] is not None
        assert data["connection"]["checked"] is True
        assert data["connection"]["connected"] is True
        assert data["drift"]["checked"] is True
        assert data["drift"]["planned_writes"] == 4
        assert data["drift"]["has_drift"] is True
        assert data["design"]["checked"] is True
        assert data["design"]["estimated_conversion_lift"] == 0.15
        assert data["design"]["layout_recommendations_count"] == 3

    def test_no_store_envelope(self, cli):
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_store_report, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert data["error"] == "no_store_selected"

    def test_skip_live_envelope_marks_unchecked(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store")
            )
            design_cls.return_value.run.return_value = {
                "status": "success",
                "data": {"estimated_conversion_lift": 0.1},
                "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store", json=True, skip_live=True),
            )
        data = json.loads(out)
        assert data["connection"]["checked"] is False
        assert data["drift"]["checked"] is False


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_failed_connection_skips_drift(self, cli):
        """If connection fails, drift probe is skipped (would be
        wasted GraphQL hops)."""
        sm = _fake_store_manager(connected=False)
        sm.test_connection.return_value = {
            "connected": False, "error": "401 Unauthorized",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            design_cls.return_value.run.return_value = {
                "status": "success", "data": {}, "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store"),
            )
        assert "[fail] connection" in out
        # drift skipped because connection failed
        assert "[skip] drift" in out

    def test_design_engine_failure_doesnt_break(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "engines.store_design.flow.StoreDesignEngine",
            side_effect=RuntimeError("engine down"),
        ):
            sync_cls.return_value.get_status.return_value = {"stores": []}
            configurator_cls.return_value.configure.return_value = (
                _fake_plan_result(plan_count=0)
            )
            out, code = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store"),
            )
        assert code == 0
        # Report still rendered, just no design line
        assert "Store report" in out

    def test_drift_probe_failure_envelope(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "execution.store_configurator.StoreConfigurator",
            side_effect=RuntimeError("configurator broke"),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as design_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store")
            )
            design_cls.return_value.run.return_value = {
                "status": "success", "data": {}, "meta": {}, "error": None,
            }
            out, _ = _capture(
                cli._cmd_store_report,
                _ns(store_id="test-store", json=True),
            )
        data = json.loads(out)
        # Drift section marked checked but with error
        assert data["drift"]["checked"] is True
        assert "error" in data["drift"]


# ─── Drift-feature counting helper ───────────────────────────


class TestDriftFeatureCounter:

    def test_counts_distinct_features(self, cli):
        plan = [
            {"path": "smart_collections.json", "method": "POST"},
            {"path": "smart_collections.json", "method": "POST"},
            {"path": "price_rules.json", "method": "POST"},
            {"path": "shipping_zones.json", "method": "POST"},
        ]
        # 3 distinct features: collections, discounts, shipping
        assert cli._drift_feature_count(plan) == 3

    def test_empty_plan_returns_0(self, cli):
        assert cli._drift_feature_count([]) == 0
