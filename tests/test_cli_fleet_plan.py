"""Tests for ``shopai fleet-plan``.

Empire-scale planning surface. For each store in the fleet,
runs the planner (goal mode or audit-driven) and emits a
per-store + fleet-rollup summary.

Coverage:
  - Goal mode: phrase supplied -> planner runs per store
  - Audit-driven mode: phrase omitted -> audit + plan per
    store
  - Empty fleet: 0 stores -> empty output
  - Per-store raise -> entry carries error, other stores
    still render
  - JSON output shape
  - Text view rollup line
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


@pytest.fixture(autouse=True)
def _registry_isolation():
    from core.capability_registry.bootstrap import (
        reset_for_tests,
    )
    reset_for_tests()
    yield
    reset_for_tests()


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
    defaults = dict(goal="", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm(stores):
    sm = MagicMock()
    sm.list_stores.return_value = stores
    return sm


class TestGoalMode:

    def test_phrase_supplied_planner_runs_per_store(self, cli):
        sm = _fake_sm([
            {"store_id": "a", "shop_url": "ax",
             "niche": "beauty"},
            {"store_id": "b", "shop_url": "bx",
             "niche": "fashion"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_fleet_plan,
                _ns(goal="mobile design"),
            )
        assert code == 0
        # Header includes goal
        assert "goal: mobile design" in out
        # Each store renders
        assert "a:" in out
        assert "b:" in out

    def test_json_output(self, cli):
        sm = _fake_sm([
            {"store_id": "a", "shop_url": "ax"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_fleet_plan,
                _ns(goal="launch store", json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["goal"] == "launch store"
        assert data["rollup"]["stores_total"] == 1
        assert len(data["stores"]) == 1
        assert data["stores"][0]["store_id"] == "a"
        # Plan dict present
        assert data["stores"][0]["plan"] is not None


class TestAuditDriven:

    def test_no_phrase_runs_audit_per_store(self, cli):
        sm = _fake_sm([
            {"store_id": "a", "shop_url": "ax"},
        ])
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": [], "fix_hint": ""},
            ],
            "ready_to_launch": False,
            "completion_pct": 50,
            "missing_summary": "...",
            "next_action": "...",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ) as audit_mock:
            out, code = _capture(
                cli._cmd_fleet_plan, _ns(),
            )
        assert code == 0
        # Audit was called per store
        audit_mock.assert_called_once()
        # Goal label says audit-driven
        assert "(audit-driven)" in out


class TestEmptyFleet:

    def test_no_stores(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_fleet_plan,
                _ns(goal="x", json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["rollup"]["stores_total"] == 0
        assert data["stores"] == []


class TestPerStoreErrorIsolation:

    def test_one_store_raise_doesnt_break_others(self, cli):
        sm = _fake_sm([
            {"store_id": "good", "shop_url": "x"},
            {"store_id": "broken", "shop_url": "y"},
        ])

        def _audit(store_id=None, **_kw):
            if store_id == "broken":
                raise RuntimeError("network")
            return {
                "checks": [], "ready_to_launch": True,
                "completion_pct": 100,
                "missing_summary": "",
                "next_action": "",
            }

        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=_audit,
        ):
            out, code = _capture(
                cli._cmd_fleet_plan, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        stores = {s["store_id"]: s for s in data["stores"]}
        # Good store rendered with plan
        assert stores["good"]["plan"] is not None
        # Broken store carries error
        assert "broken" in stores
        assert "network" in stores["broken"].get("error", "")


class TestRollup:

    def test_rollup_counts_stores_with_plan(self, cli):
        sm = _fake_sm([
            {"store_id": "needs-action", "shop_url": "x"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_fleet_plan,
                _ns(goal="launch store", json=True),
            )
        assert code == 0
        data = json.loads(out)
        # The goal "launch store" matches launch_store, so
        # the planner returns steps -> stores_with_plan = 1
        assert data["rollup"]["stores_with_plan"] == 1
