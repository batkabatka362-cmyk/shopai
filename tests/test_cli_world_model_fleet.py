"""Tests for ``shopai world-model fleet`` -- empire-scale
multi-store snapshot view.

Runs ``WorldModel().snapshot()`` for every registered store and
renders a compact comparison table.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

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
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(json=False, skip_live=True)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm(stores):
    sm = MagicMock()
    sm.list_stores.return_value = stores
    return sm


def _snap(store_id, **kwargs):
    """Build a fake snapshot dict in the WorldModel.snapshot()
    shape, with sane defaults that the fleet renderer reads."""
    default = {
        "store_id": store_id,
        "fetched_at": 1234567890.0,
        "store": {"niche": "general"},
        "stats": {
            "products": 10, "orders": 5,
            "customers": 3, "total_revenue": 100.0,
        },
        "sync": {
            "last_sync_at": None,
            "last_sync_status": None,
            "age_seconds": 3600.0,
        },
        "connection": {"checked": False},
        "config": {"checked": True, "planned_writes": 0, "has_drift": False},
        "design": {"checked": True, "estimated_conversion_lift": 0.10},
        "approvals": {
            "checked": True, "scope": "per_store",
            "pending_total": 0, "pending_by_engine": {},
        },
        "decisions": {"checked": True, "recent_count": 0},
    }
    default.update(kwargs)
    return default


# ─── Empty fleet ─────────────────────────────────────────────


class TestEmptyFleet:

    def test_empty_text(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out = _capture(cli._cmd_world_model_fleet, _ns())
        assert "No stores configured" in out

    def test_empty_json(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out = _capture(
                cli._cmd_world_model_fleet, _ns(json=True),
            )
        data = json.loads(out)
        assert data["stores"] == []


# ─── Row population ──────────────────────────────────────────


class TestRowPopulation:

    def test_one_store_renders(self, cli):
        sm = _fake_sm([{"store_id": "a", "shop_url": "x"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.return_value = _snap("a")
            out = _capture(cli._cmd_world_model_fleet, _ns())
        assert "a " in out
        assert "general" in out
        assert "$    100.00" in out

    def test_two_stores_render_both(self, cli):
        sm = _fake_sm([
            {"store_id": "store-a", "shop_url": "x"},
            {"store_id": "store-b", "shop_url": "y"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.side_effect = [
                _snap("store-a", stats={
                    "products": 10, "orders": 5,
                    "customers": 0, "total_revenue": 100.0,
                }),
                _snap("store-b", stats={
                    "products": 20, "orders": 8,
                    "customers": 0, "total_revenue": 200.0,
                }),
            ]
            out = _capture(cli._cmd_world_model_fleet, _ns())
        assert "store-a" in out
        assert "store-b" in out
        assert "$300.00 revenue" in out  # total

    def test_skip_live_flag_threads_through(self, cli):
        sm = _fake_sm([{"store_id": "a", "shop_url": "x"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.return_value = _snap("a")
            _capture(
                cli._cmd_world_model_fleet,
                _ns(skip_live=False),
            )
        # The snapshot call received skip_live=False
        wm_cls.return_value.snapshot.assert_called_once_with(
            "a", skip_live=False,
        )


# ─── Aggregates ──────────────────────────────────────────────


class TestAggregates:

    def test_totals_sum_correctly(self, cli):
        sm = _fake_sm([
            {"store_id": "a"},
            {"store_id": "b"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.side_effect = [
                _snap("a",
                      stats={"products": 1, "orders": 0,
                             "customers": 0, "total_revenue": 50.0},
                      approvals={"checked": True, "scope": "per_store",
                                 "pending_total": 3}),
                _snap("b",
                      stats={"products": 1, "orders": 0,
                             "customers": 0, "total_revenue": 75.0},
                      approvals={"checked": True, "scope": "per_store",
                                 "pending_total": 2}),
            ]
            out = _capture(cli._cmd_world_model_fleet, _ns())
        assert "$125.00 revenue" in out  # 50 + 75
        assert "5 pending" in out  # 3 + 2


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_snapshot_error_surfaces_inline(self, cli):
        sm = _fake_sm([{"store_id": "broken"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.side_effect = (
                RuntimeError("snapshot failed")
            )
            out = _capture(cli._cmd_world_model_fleet, _ns())
        assert "snapshot error" in out
        assert "snapshot failed" in out


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        sm = _fake_sm([{"store_id": "a"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.return_value = _snap("a")
            out = _capture(
                cli._cmd_world_model_fleet, _ns(json=True),
            )
        data = json.loads(out)
        assert "skip_live" in data
        assert "stores" in data
        assert len(data["stores"]) == 1
        assert data["stores"][0]["store_id"] == "a"


# --- Fleet engine-health rollup -------------------------------


def _snap_with_health(
    store_id, *, verdict_counts=None, sickest=None,
    avg_score=8.0, checked=True,
):
    """Build a snapshot dict that includes a fleet_health
    section in the form ``_section_fleet_health`` produces."""
    snap = _snap(store_id)
    snap["fleet_health"] = {
        "checked": checked,
        "verdict_counts": verdict_counts or {
            "healthy": 3, "warning": 1, "unhealthy": 0,
        },
        "sickest": sickest or [],
        "average_score": avg_score,
        "total_engines": 4,
    }
    return snap


class TestFleetHealthLine:

    def test_renders_summary_line(self, cli):
        sm = _fake_sm([{"store_id": "a"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.return_value = (
                _snap_with_health("a")
            )
            out = _capture(
                cli._cmd_world_model_fleet, _ns(),
            )
        assert "Engine health:" in out
        assert "avg=8.0/10" in out
        assert "healthy=3" in out
        assert "warning=1" in out
        assert "unhealthy=0" in out

    def test_sickest_shown_when_unhealthy(self, cli):
        sm = _fake_sm([{"store_id": "a"}])
        snap = _snap_with_health(
            "a",
            verdict_counts={
                "healthy": 1, "warning": 0, "unhealthy": 2,
            },
            sickest=[
                {"engine": "loyalty", "score": 3,
                 "verdict": "unhealthy"},
                {"engine": "cart_recovery", "score": 4,
                 "verdict": "unhealthy"},
            ],
            avg_score=5.5,
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.return_value = snap
            out = _capture(
                cli._cmd_world_model_fleet, _ns(),
            )
        assert "Sickest:" in out
        assert "loyalty(3/10)" in out
        assert "cart_recovery(4/10)" in out

    def test_sickest_hidden_when_all_healthy(self, cli):
        sm = _fake_sm([{"store_id": "a"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.return_value = (
                _snap_with_health(
                    "a",
                    verdict_counts={
                        "healthy": 4,
                        "warning": 0,
                        "unhealthy": 0,
                    },
                )
            )
            out = _capture(
                cli._cmd_world_model_fleet, _ns(),
            )
        assert "Engine health:" in out
        # No Sickest line when zero unhealthy
        assert "Sickest:" not in out

    def test_no_fleet_health_when_unchecked(self, cli):
        """If fleet_health is absent / checked=False, no line."""
        sm = _fake_sm([{"store_id": "a"}])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            # Default snap doesn't have fleet_health at all
            wm_cls.return_value.snapshot.return_value = _snap("a")
            out = _capture(
                cli._cmd_world_model_fleet, _ns(),
            )
        assert "Engine health:" not in out

    def test_picks_first_checked_store(self, cli):
        """fleet_health is GLOBAL so it's the same across all
        per-store snapshots. The renderer should pick the first
        store whose snapshot includes it (skipping snapshot
        errors)."""
        sm = _fake_sm([
            {"store_id": "broken"},
            {"store_id": "good"},
        ])
        # Snapshot raises for 'broken', returns valid for 'good'
        snapshot_map = {
            "good": _snap_with_health("good"),
        }

        def _snap_side(store_id, skip_live=True):
            if store_id == "broken":
                raise RuntimeError("snapshot dead")
            return snapshot_map[store_id]

        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls:
            wm_cls.return_value.snapshot.side_effect = _snap_side
            out = _capture(
                cli._cmd_world_model_fleet, _ns(),
            )
        # broken store row shows the error inline
        assert "broken" in out
        assert "Engine health:" in out
