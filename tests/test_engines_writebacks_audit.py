"""Tests for the engines-writebacks audit + CLI surface.

Catalogs Phase 6/7 writeback wireup state per engine
(wired / advisory / partial). Operator-facing visibility on
the autonomous loop's reach.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
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
    defaults = dict(filter="all", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _make_engine_dir(
    root: Path,
    name: str,
    *,
    has_flow: bool = True,
    writers: list[str] | None = None,
    opt_ins: list[str] | None = None,
) -> Path:
    """Build a synthetic engine directory for audit fixtures."""
    engine_dir = root / name
    engine_dir.mkdir(parents=True, exist_ok=True)
    if has_flow:
        # Flow.py body inlines any opt-in flags so the regex picks
        # them up
        flag_lines = "\n".join(
            f'    if data.get("{flag}") is True: pass'
            for flag in (opt_ins or [])
        )
        flow_body = (
            "def run(data):\n"
            f"{flag_lines or '    pass'}\n"
        )
        (engine_dir / "flow.py").write_text(
            flow_body, encoding="utf-8",
        )
    for w in writers or []:
        (engine_dir / w).write_text(
            "def go(): pass\n", encoding="utf-8",
        )
    return engine_dir


# ─── Audit module ──────────────────────────────────────────────


class TestAuditCoverage:

    def test_empty_root_returns_zero(self, tmp_path):
        from engines._writeback_audit import audit_writeback_coverage
        report = audit_writeback_coverage(tmp_path)
        assert report.total_engines == 0
        assert report.wired_count == 0

    def test_missing_root_returns_empty_report(self, tmp_path):
        from engines._writeback_audit import audit_writeback_coverage
        report = audit_writeback_coverage(tmp_path / "nonexistent")
        assert report.total_engines == 0
        assert report.engines == []

    def test_wired_engine(self, tmp_path):
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            writers=["my_applier.py"],
            opt_ins=["apply_myaction"],
        )
        report = audit_writeback_coverage(tmp_path)
        assert report.wired_count == 1
        assert report.engines[0].status == "wired"
        assert report.engines[0].name == "myengine"
        assert "my_applier.py" in report.engines[0].writer_files
        assert "apply_myaction" in report.engines[0].opt_in_flags

    def test_advisory_engine(self, tmp_path):
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(tmp_path, "myengine")
        report = audit_writeback_coverage(tmp_path)
        assert report.advisory_count == 1
        assert report.engines[0].status == "advisory"

    def test_partial_engine_writer_only(self, tmp_path):
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            writers=["my_applier.py"],
            # No opt_ins
        )
        report = audit_writeback_coverage(tmp_path)
        assert report.partial_count == 1
        assert report.engines[0].status == "partial"

    def test_partial_engine_opt_in_only(self, tmp_path):
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            opt_ins=["apply_myaction"],
        )
        report = audit_writeback_coverage(tmp_path)
        assert report.partial_count == 1
        assert report.engines[0].status == "partial"

    def test_no_flow_excluded(self, tmp_path):
        """A directory under engines/ without a flow.py is
        infrastructure — base/, _writeback_recorder, helper
        modules — and shouldn't count as an engine."""
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(tmp_path, "infra", has_flow=False)
        report = audit_writeback_coverage(tmp_path)
        # Infra dir was excluded
        assert report.total_engines == 0

    def test_memory_writer_doesnt_count(self, tmp_path):
        """The audit's pattern set deliberately excludes
        ``_writer.py`` because every engine has a
        ``memory_writer.py`` for internal LearningLoop
        persistence — different concern from Shopify writebacks."""
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            writers=["memory_writer.py"],
        )
        report = audit_writeback_coverage(tmp_path)
        # memory_writer.py doesn't match *_applier/_minter/_payer
        # → no writer detected → advisory
        assert report.advisory_count == 1
        assert report.engines[0].status == "advisory"

    def test_private_dirs_skipped(self, tmp_path):
        """Directories starting with _ are skipped (e.g.
        engines/_writeback_recorder.py is a helper, not an
        engine)."""
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(tmp_path, "_private")
        _make_engine_dir(tmp_path, ".dotted")
        _make_engine_dir(tmp_path, "real_engine")
        report = audit_writeback_coverage(tmp_path)
        names = [s.name for s in report.engines]
        assert "real_engine" in names
        assert "_private" not in names
        assert ".dotted" not in names

    def test_require_approval_flag_detected(self, tmp_path):
        """``data.get("require_approval")`` is a legitimate
        opt-in flag (gates the immediate-mint vs approval-queue
        path in writers like wholesale_b2b)."""
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            writers=["my_applier.py"],
            opt_ins=["require_approval"],
        )
        report = audit_writeback_coverage(tmp_path)
        assert report.engines[0].status == "wired"
        assert "require_approval" in report.engines[0].opt_in_flags

    def test_minter_writer_pattern(self, tmp_path):
        """``*_minter.py`` is the Phase 6 discount-mint pattern
        (loyalty, cart_recovery, etc.)."""
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            writers=["discount_minter.py"],
            opt_ins=["apply_rewards"],
        )
        report = audit_writeback_coverage(tmp_path)
        assert report.engines[0].status == "wired"

    def test_payer_writer_pattern(self, tmp_path):
        """``*_payer.py`` is the affiliate commission pattern."""
        from engines._writeback_audit import audit_writeback_coverage
        _make_engine_dir(
            tmp_path, "myengine",
            writers=["commission_payer.py"],
            opt_ins=["apply_commissions"],
        )
        report = audit_writeback_coverage(tmp_path)
        assert report.engines[0].status == "wired"


# ─── Live audit ────────────────────────────────────────────────


class TestLiveAudit:

    def test_live_audit_returns_known_wired_engines(self):
        """The actual engines/ directory has known wired
        engines (loyalty, cart_recovery, etc. from PRs #43-#49,
        product_optimization from #185). Regression guard."""
        from engines._writeback_audit import audit_writeback_coverage
        report = audit_writeback_coverage("engines")
        wired_names = {
            s.name for s in report.engines if s.status == "wired"
        }
        # Subset of the known-wired engines must surface
        assert "loyalty" in wired_names
        assert "cart_recovery" in wired_names
        assert "product_optimization" in wired_names
        # Coverage is non-zero
        assert report.wired_count >= 20


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_default_renders_summary_and_table(self, cli):
        out, code = _capture(
            cli._cmd_engines_writebacks, _ns(),
        )
        assert code == 0
        assert "Engine writeback coverage" in out
        # Live audit has wired engines
        assert "loyalty" in out
        assert "wired" in out

    def test_filter_wired(self, cli):
        out, _ = _capture(
            cli._cmd_engines_writebacks, _ns(filter="wired"),
        )
        # Header still present
        assert "Engine writeback coverage" in out
        # Filter line surfaces
        assert "Filtered to status='wired'" in out

    def test_filter_advisory_includes_advisory_engines(self, cli):
        out, _ = _capture(
            cli._cmd_engines_writebacks, _ns(filter="advisory"),
        )
        assert "Filtered to status='advisory'" in out
        # Some known-advisory engine appears in output
        assert "accounting" in out or "report_dashboard" in out

    def test_filter_partial_empty_today(self, cli):
        """Currently no engines are partially wired (audit's
        clean baseline). The filter should render the friendly
        no-match message."""
        out, _ = _capture(
            cli._cmd_engines_writebacks, _ns(filter="partial"),
        )
        # Either no results message OR partial engines listed —
        # both are valid depending on state
        assert (
            "No engines match" in out
            or "Filtered to status='partial'" in out
        )

    def test_json_envelope(self, cli):
        out, _ = _capture(
            cli._cmd_engines_writebacks, _ns(json=True),
        )
        data = json.loads(out)
        assert "summary" in data
        assert "engines" in data
        assert data["summary"]["total_engines"] >= 100
        assert data["summary"]["wired"] >= 20

    def test_json_filter_respected(self, cli):
        out, _ = _capture(
            cli._cmd_engines_writebacks,
            _ns(json=True, filter="wired"),
        )
        data = json.loads(out)
        assert data["filter"] == "wired"
        # Every entry is wired
        assert all(
            e["status"] == "wired"
            for e in data["engines"]
        )

    def test_audit_failure_renders_unavailable(self, cli):
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_engines_writebacks, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_audit_failure_json_error(self, cli):
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, _ = _capture(
                cli._cmd_engines_writebacks, _ns(json=True),
            )
        data = json.loads(out)
        assert "error" in data

    def test_wired_first_sort_order(self, cli):
        """Wired engines render before advisory ones within
        --filter=all."""
        out, _ = _capture(
            cli._cmd_engines_writebacks, _ns(),
        )
        # Find positions of a known-wired vs a known-advisory engine
        wired_pos = out.find("loyalty")
        advisory_pos = out.find("accounting")
        if wired_pos > 0 and advisory_pos > 0:
            assert wired_pos < advisory_pos
