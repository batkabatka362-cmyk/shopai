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

    def test_cycle_threshold_block_appears(self, cli):
        sections = cli._build_health_sections()
        assert "threshold" in sections["cycle"]
        thr = sections["cycle"]["threshold"]
        assert "effective" in thr
        assert "override_set" in thr
        assert "auto_relax_enabled" in thr

    def test_revenue_trend_in_health_envelope(self, cli):
        sections = cli._build_health_sections()
        # cycle section should carry revenue_trend_7d
        assert "revenue_trend_7d" in sections["cycle"]

    def test_revenue_trend_renders_in_text(self, cli):
        with patch(
            "core.autonomous.cycle_revenue_history."
            "revenue_trend",
            return_value={
                "snapshots": 5,
                "first_revenue": 1000.0,
                "last_revenue": 1500.0,
                "delta": 500.0,
                "delta_pct": 50.0,
                "first_at": 0,
                "last_at": 0,
            },
        ):
            out = _capture(cli._cmd_status, None)
        assert "rev 7d: +$500" in out
        assert "+50.0%" in out

    def test_revenue_trend_silent_with_single_snapshot(
        self, cli,
    ):
        """When there's only 1 snapshot the delta is
        meaningless -- the line is suppressed."""
        with patch(
            "core.autonomous.cycle_revenue_history."
            "revenue_trend",
            return_value={
                "snapshots": 1,
                "first_revenue": 1000.0,
                "last_revenue": 1000.0,
                "delta": 0.0,
                "delta_pct": 0.0,
                "first_at": 0,
                "last_at": 0,
            },
        ):
            out = _capture(cli._cmd_status, None)
        # No "rev 7d:" line
        assert "rev 7d:" not in out

    def test_audit_data_returns_envelope(
        self, cli, tmp_path, monkeypatch,
    ):
        # Change cwd so the auditor looks at tmp_path
        monkeypatch.chdir(tmp_path)
        import argparse as _ap
        ns = _ap.Namespace(
            json=True, audit_data=True,
            watch=False, interval=30, iterations=0,
        )
        out = _capture(cli._cmd_status, ns)
        data = json.loads(out)
        assert "files" in data
        assert "overall" in data
        # Every known file label is in the audit
        labels = {f["label"] for f in data["files"]}
        for expected in (
            "cycle_history",
            "cycle_alert_history",
            "auto_demote_history",
            "auto_promote_history",
            "auto_relax_history",
            "transfer_history",
            "cycle_overrides",
            "capability_overrides",
            "plan_history",
            "plan_templates",
        ):
            assert expected in labels

    def test_audit_data_detects_corrupt(
        self, cli, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        # Create a corrupt cycle_history.json
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "cycle_history.json").write_text(
            "not json{",
        )
        import argparse as _ap
        ns = _ap.Namespace(
            json=True, audit_data=True,
            watch=False, interval=30, iterations=0,
        )
        out = _capture(cli._cmd_status, ns)
        data = json.loads(out)
        # Overall should flag error
        assert data["overall"] == "error"
        # Specific file marked
        ch = next(
            f for f in data["files"]
            if f["label"] == "cycle_history"
        )
        assert ch["schema_ok"] is False
        assert "json_decode" in (ch.get("error") or "")

    def test_health_score_perfect_on_clean(self, cli):
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
        assert sections["health_score"] == 100

    def test_health_score_penalized_for_alerts(
        self, cli,
    ):
        from core.autonomous.cycle_alerts import CycleAlert
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[
                CycleAlert(
                    kind="stale_cycle", detail="x",
                ),
            ],
        ):
            sections = cli._build_health_sections()
        # Score < 100 because 1 alert
        assert sections["health_score"] < 100

    def test_health_score_clamped_to_zero(self, cli):
        """Many problems together still clamp at 0."""
        from core.autonomous.cycle_alerts import CycleAlert
        import time as _t
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[
                CycleAlert(kind=f"a{i}", detail="x")
                for i in range(20)
            ],
        ), patch(
            "core.capability_planner.auto_demote_history."
            "find_thrashing",
            return_value=[
                {"capability": f"c{i}"}
                for i in range(20)
            ],
        ), patch(
            "core.autonomous.cycle_pause.get_pause_state",
            return_value={
                "active": True,
                "paused_until_at": _t.time() + 3600,
                "reason": "x",
                "paused_at": _t.time(),
            },
        ):
            sections = cli._build_health_sections()
        assert sections["health_score"] >= 0
        # Should be MUCH lower than 100
        assert sections["health_score"] < 50

    def test_line_format_ok(self, cli):
        import argparse as _ap
        with patch.object(
            cli, "_build_health_sections",
            return_value={
                "overall": "ok",
                "fleet": {
                    "checked": True,
                    "store_count": 3,
                },
                "substrate": {
                    "checked": True,
                    "demote_candidates": 0,
                },
                "cycle": {
                    "checked": True,
                    "runs_24h": 10,
                    "alert_count": 0,
                    "pause": {"active": False},
                    "revenue_trend_7d": {
                        "snapshots": 5,
                        "delta_pct": 5.0,
                    },
                },
                "bridge": {
                    "checked": True,
                    "thrashing_count": 0,
                },
            },
        ):
            buf = StringIO()
            code = 0
            try:
                with patch("sys.stdout", buf):
                    cli._cmd_status(_ap.Namespace(
                        json=False,
                        quiet=False,
                        line=True,
                        watch=False,
                        interval=30,
                        iterations=0,
                        audit_data=False,
                        cleanup_history=False,
                        older_than_days=180,
                        yes=False,
                    ))
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
        line = buf.getvalue().strip()
        assert line.startswith("[OK]")
        assert "stores=3" in line
        assert "cycle_runs_24h=10" in line
        assert "paused=no" in line
        assert "revenue_7d=+5.0%" in line
        assert code == 0

    def test_line_format_warn_exits_1(self, cli):
        import argparse as _ap
        with patch.object(
            cli, "_build_health_sections",
            return_value={
                "overall": "warn",
                "fleet": {"checked": True, "store_count": 1},
                "substrate": {
                    "checked": True,
                    "demote_candidates": 0,
                },
                "cycle": {
                    "checked": True,
                    "runs_24h": 5,
                    "alert_count": 2,
                    "pause": {"active": True},
                    "revenue_trend_7d": None,
                },
                "bridge": {
                    "checked": True,
                    "thrashing_count": 0,
                },
            },
        ):
            buf = StringIO()
            code = 0
            try:
                with patch("sys.stdout", buf):
                    cli._cmd_status(_ap.Namespace(
                        json=False,
                        quiet=False,
                        line=True,
                        watch=False,
                        interval=30,
                        iterations=0,
                        audit_data=False,
                        cleanup_history=False,
                        older_than_days=180,
                        yes=False,
                    ))
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
        line = buf.getvalue().strip()
        assert line.startswith("[WARN]")
        assert "paused=yes" in line
        assert "alerts=2" in line
        assert code == 1

    def test_quiet_silent_when_ok(self, cli):
        """--quiet exits silently with code 0 when verdict
        is OK. Cron-friendly: no email noise on healthy
        runs."""
        import argparse as _ap
        with patch.object(
            cli, "_build_health_sections",
            return_value={
                "overall": "ok",
                "fleet": {"checked": True},
                "substrate": {"checked": True},
                "cycle": {"checked": True},
                "bridge": {"checked": True},
            },
        ):
            buf = StringIO()
            code = 0
            try:
                with patch("sys.stdout", buf):
                    cli._cmd_status(_ap.Namespace(
                        json=False,
                        quiet=True,
                        watch=False,
                        interval=30,
                        iterations=0,
                        audit_data=False,
                        cleanup_history=False,
                        older_than_days=180,
                        yes=False,
                    ))
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
        # No output, exit 0
        assert buf.getvalue() == ""
        assert code == 0

    def test_quiet_renders_and_exits_1_on_warn(
        self, cli,
    ):
        import argparse as _ap
        with patch.object(
            cli, "_build_health_sections",
            return_value={
                "overall": "warn",
                "fleet": {"checked": True},
                "substrate": {"checked": True},
                "cycle": {
                    "checked": True,
                    "runs_24h": 0,
                    "executed_runs_24h": 0,
                    "last_run_age_hours": None,
                    "alert_count": 0,
                    "alert_kinds": [],
                    "threshold": None,
                    "transfers_24h": 0,
                    "revenue_trend_7d": None,
                    "pause": {"active": False},
                },
                "bridge": {"checked": True},
            },
        ):
            buf = StringIO()
            code = 0
            try:
                with patch("sys.stdout", buf):
                    cli._cmd_status(_ap.Namespace(
                        json=False,
                        quiet=True,
                        watch=False,
                        interval=30,
                        iterations=0,
                        audit_data=False,
                        cleanup_history=False,
                        older_than_days=180,
                        yes=False,
                    ))
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
        # WARN -> output rendered + exit 1
        assert "Health" in buf.getvalue()
        assert code == 1

    def test_paused_triggers_warn_verdict(self, cli):
        import time as _t
        with patch(
            "core.autonomous.cycle_pause.get_pause_state",
            return_value={
                "active": True,
                "paused_until_at": _t.time() + 3600,
                "reason": "maintenance",
                "paused_at": _t.time(),
            },
        ):
            sections = cli._build_health_sections()
        assert sections["overall"] == "warn"
        assert (
            sections["cycle"]["pause"]["active"] is True
        )

    def test_paused_renders_marker_in_text(self, cli):
        import time as _t
        with patch(
            "core.autonomous.cycle_pause.get_pause_state",
            return_value={
                "active": True,
                "paused_until_at": _t.time() + 3600,
                "reason": "test",
                "paused_at": _t.time(),
            },
        ):
            out = _capture(cli._cmd_status, None)
        assert "[PAUSED]" in out

    def test_cleanup_history_dry_run(
        self, cli, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        import argparse as _ap
        ns = _ap.Namespace(
            json=True,
            cleanup_history=True,
            older_than_days=180,
            yes=False,
            watch=False,
            interval=30,
            iterations=0,
            audit_data=False,
        )
        with patch(
            "core.autonomous.history_cleanup.prune_all",
            return_value={
                "older_than_days": 180,
                "dry_run": True,
                "total_pruned": 5,
                "files": [
                    {
                        "label": "demote",
                        "path": "x",
                        "total": 10,
                        "kept": 5,
                        "pruned": 5,
                        "pruned_size_bytes": 1024,
                        "error": None,
                    },
                ],
            },
        ):
            out = _capture(cli._cmd_status, ns)
        data = json.loads(out)
        assert data["total_pruned"] == 5
        assert data["dry_run"] is True

    def test_cleanup_history_text_render(
        self, cli, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        import argparse as _ap
        ns = _ap.Namespace(
            json=False,
            cleanup_history=True,
            older_than_days=180,
            yes=False,
            watch=False,
            interval=30,
            iterations=0,
            audit_data=False,
        )
        with patch(
            "core.autonomous.history_cleanup.prune_all",
            return_value={
                "older_than_days": 180,
                "dry_run": True,
                "total_pruned": 3,
                "files": [
                    {
                        "label": "demote",
                        "path": "x",
                        "total": 10,
                        "kept": 7,
                        "pruned": 3,
                        "pruned_size_bytes": 512,
                        "error": None,
                    },
                ],
            },
        ):
            out = _capture(cli._cmd_status, ns)
        assert "DRY-RUN" in out
        assert "Total events to prune: 3" in out
        assert "Re-run with --yes" in out

    def test_audit_data_text_render(
        self, cli, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        import argparse as _ap
        ns = _ap.Namespace(
            json=False, audit_data=True,
            watch=False, interval=30, iterations=0,
        )
        out = _capture(cli._cmd_status, ns)
        assert "Data file audit" in out
        # Files missing render as [.]
        assert "(not present)" in out

    def test_watch_mode_runs_iterations(self, cli):
        """--watch with --iterations limits the loop."""
        import argparse as _ap
        ns = _ap.Namespace(
            json=False,
            watch=True,
            interval=5,
            iterations=2,
        )
        # No sleep -- patch it so the test doesn't actually
        # wait
        with patch(
            "time.sleep",
        ) as mock_sleep:
            out = _capture(cli._cmd_status, ns)
        # The watch header should appear at least once
        assert "watching" in out
        # The inner _cmd_status is called per iteration, so
        # we should see Engines: rendered (multiple times)
        assert out.count("Engines:") >= 2
        # Sleep called between iterations (1 between 2
        # iterations)
        assert mock_sleep.call_count >= 1

    def test_threshold_with_override_renders_marker(
        self, cli,
    ):
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.7,
        ), patch(
            "core.autonomous.cycle_overrides."
            "load_overrides",
            return_value={"auto_execute_threshold": 0.7},
        ), patch(
            "core.autonomous.auto_relax.is_enabled",
            return_value=True,
        ):
            out = _capture(cli._cmd_status, None)
        # The * marks an active override, "(auto-relax ON)"
        # marks the bridge gate
        assert "threshold 0.70" in out
        assert "*" in out  # override marker
        assert "(auto-relax ON)" in out
