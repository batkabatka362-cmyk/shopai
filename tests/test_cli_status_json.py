"""Tests for ``shopai status --json`` and the underlying
``_build_status_dict`` helper.

The default text view is operator-friendly but monitoring tools
need a parseable representation. The --json flag swaps the table
render for ``json.dumps`` of the same payload, so a single
command works for both human and machine consumers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── _build_status_dict ──────────────────────────────────────────


class TestBuildStatusDict:

    def test_returns_known_shape(self, cli):
        """Payload exposes the top-level keys downstream consumers
        will depend on. Schema is part of the contract."""
        payload = cli._build_status_dict()
        for key in (
            "engines",
            "stores_count",
            "active_store",
            "stores",
            "auto_sync_running",
            "sync_stores",
        ):
            assert key in payload, f"missing key: {key}"

    def test_engines_is_int(self, cli):
        payload = cli._build_status_dict()
        assert isinstance(payload["engines"], int)
        assert payload["engines"] > 0

    def test_stores_is_list_of_dicts(self, cli):
        payload = cli._build_status_dict()
        assert isinstance(payload["stores"], list)
        for s in payload["stores"]:
            for key in (
                "store_id", "active", "products",
                "orders", "customers", "total_revenue",
            ):
                assert key in s

    def test_sync_age_computed(self, cli):
        """When a store has a last_sync timestamp, the payload
        includes the age in seconds — saves consumers from
        re-computing now()-last_sync."""
        payload = cli._build_status_dict()
        for si in payload["sync_stores"]:
            if si["last_sync"] is not None:
                assert si["last_sync_age_seconds"] is not None
                assert si["last_sync_age_seconds"] >= 0


# ─── _cmd_status JSON mode ──────────────────────────────────────


class TestStatusJsonMode:

    def test_json_flag_emits_valid_json(self, cli):
        ns = argparse.Namespace(json=True)
        out = _capture(cli._cmd_status, ns)
        # Must round-trip cleanly
        data = json.loads(out)
        assert "engines" in data
        assert "stores" in data

    def test_json_flag_no_table_text(self, cli):
        """JSON mode emits ONLY JSON — no human-readable headers
        before/after. A monitoring tool piping the output to jq
        must not get garbage prefix."""
        ns = argparse.Namespace(json=True)
        out = _capture(cli._cmd_status, ns)
        # First non-whitespace char is '{' (or '[')
        first_char = out.strip()[0]
        assert first_char in ("{", "[")
        # No human banner text
        assert "ShopAI System Status" not in out
        assert "Store Data:" not in out

    def test_json_flag_explicit_false_falls_to_text(self, cli):
        ns = argparse.Namespace(json=False)
        out = _capture(cli._cmd_status, ns)
        # Human table view
        assert "ShopAI System Status" in out


# ─── _cmd_status text mode ──────────────────────────────────────


class TestStatusTextMode:

    def test_no_args_renders_table(self, cli):
        """Default invocation with no args still works — backward
        compat with callers that don't pass a Namespace."""
        out = _capture(cli._cmd_status)
        assert "ShopAI System Status" in out

    def test_text_view_unchanged(self, cli):
        """Text view's headers + format should match the
        original output."""
        out = _capture(cli._cmd_status, None)
        # Key sections still present
        assert "Engines:" in out
        assert "Stores:" in out
        assert "Active:" in out
        assert "Auto-sync:" in out


# ─── Phase 6/7 wiring snapshot (PR follows #216) ─────────────


class TestWiringSnapshot:

    def test_payload_includes_wired_advisory_dispatchers(self, cli):
        """The status dict now exposes Phase 6/7 wiring counts
        + dispatcher count for daily-glance visibility."""
        payload = cli._build_status_dict()
        for key in (
            "engines_wired",
            "engines_advisory",
            "dispatchers",
        ):
            assert key in payload

    def test_wired_count_matches_writeback_audit(self, cli):
        from engines._writeback_audit import audit_writeback_coverage
        payload = cli._build_status_dict()
        wb = audit_writeback_coverage("engines")
        assert payload["engines_wired"] == wb.wired_count
        assert payload["engines_advisory"] == wb.advisory_count

    def test_dispatcher_count_matches_registry(self, cli):
        from core.approval.executor import (
            _ensure_dispatchers_loaded,
            list_registered_action_types,
        )
        _ensure_dispatchers_loaded()
        payload = cli._build_status_dict()
        assert payload["dispatchers"] == len(
            list_registered_action_types(),
        )

    def test_text_view_renders_wired_line(self, cli):
        out = _capture(cli._cmd_status, None)
        # Wired/advisory line surfaces under "Engines:"
        assert "wired:" in out.lower()
        assert "advisory:" in out.lower()
        # Dispatcher line
        assert "Dispatchers:" in out

    def test_payload_resilient_to_writeback_audit_failure(
        self, cli,
    ):
        """A broken writeback audit surfaces as None (not a
        crash). The status command still works for the rest."""
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            payload = cli._build_status_dict()
        assert payload["engines_wired"] is None
        assert payload["engines_advisory"] is None
        # Other fields still populated
        assert payload["engines"] > 0
        assert payload["dispatchers"] is not None

    def test_payload_resilient_to_dispatcher_probe_failure(
        self, cli,
    ):
        with patch(
            "core.approval.executor._ensure_dispatchers_loaded",
            side_effect=RuntimeError("loader broken"),
        ):
            payload = cli._build_status_dict()
        # Dispatcher probe failed but other fields intact
        assert payload["dispatchers"] is None
        assert payload["engines_wired"] is not None

    def test_text_view_omits_wiring_line_on_failure(self, cli):
        """When the writeback audit fails, the wired/advisory
        line is absent (not rendered with None values)."""
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out = _capture(cli._cmd_status, None)
        # Engines header still appears
        assert "Engines:" in out
        # Wired/advisory line absent
        assert "wired:" not in out.lower()
        # Dispatcher line still rendered (independent collector)
        assert "Dispatchers:" in out


class TestHealthSections:
    """``shopai status`` augments the original status output
    with substrate/cycle/bridge health sections."""

    def test_build_health_sections_shape(self, cli):
        sections = cli._build_health_sections()
        assert "fleet" in sections
        assert "substrate" in sections
        assert "cycle" in sections
        assert "bridge" in sections
        assert sections["overall"] in (
            "ok", "warn", "error", "unknown",
        )

    def test_health_in_json_envelope(self, cli):
        ns = argparse.Namespace(json=True)
        out = _capture(cli._cmd_status, ns)
        data = json.loads(out)
        assert "health" in data
        assert "fleet" in data["health"]
        assert "substrate" in data["health"]
        assert "cycle" in data["health"]
        assert "bridge" in data["health"]
        assert "overall" in data["health"]

    def test_text_view_renders_health_block(self, cli):
        out = _capture(cli._cmd_status, None)
        # Health header + per-section labels
        assert "Health" in out
        assert "Fleet:" in out
        assert "Substrate:" in out
        assert "Cycle:" in out
        assert "Bridge:" in out

    def test_overall_warn_when_cycle_alerts_fire(self, cli):
        from core.autonomous.cycle_alerts import CycleAlert
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[
                CycleAlert(
                    kind="stale_cycle",
                    detail="48h ago",
                ),
            ],
        ):
            sections = cli._build_health_sections()
        assert sections["overall"] == "warn"
        assert sections["cycle"]["alert_count"] == 1

    def test_overall_ok_when_quiet(self, cli):
        # All subsystems checked, no alerts, no thrashing
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote_history."
            "find_thrashing",
            return_value=[],
        ):
            sections = cli._build_health_sections()
        assert sections["overall"] == "ok"

    def test_health_render_failure_doesnt_break_status(
        self, cli,
    ):
        """If the health builder explodes, status still
        prints (we don't want a new feature breaking the
        main command)."""
        with patch.object(
            cli, "_build_health_sections",
            side_effect=RuntimeError("simulated"),
        ):
            out = _capture(cli._cmd_status, None)
        # Existing status output still rendered
        assert "Engines:" in out
