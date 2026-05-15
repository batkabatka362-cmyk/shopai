"""Tests for the dispatcher coverage audit.

The audit closes Pattern K (CLAUDE.md): the approval queue accepts any
string action_type at enqueue time, but only registered dispatchers
can execute. A missing dispatcher fails silently at execute time, not
at enqueue. PR #102 found 12 such gaps; this audit preempts the next
one.

Two surfaces:

  1. ``core.approval.coverage_audit.audit_coverage`` — pure function,
     returns AuditReport with missing / orphaned lists.
  2. ``shopai approvals audit`` — CLI wrapper, exits 1 on gaps.
"""
from __future__ import annotations

import argparse
import importlib.util
import textwrap
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


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _make_engine(root: Path, name: str, body: str) -> Path:
    """Create a fake engine module at ``root/<name>/__init__.py``
    with ``body`` as its source. Returns the file path."""
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    init = pkg / "__init__.py"
    init.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return init


# ─── find_enqueue_call_sites ─────────────────────────────────────


class TestFindEnqueueCallSites:

    def test_extracts_literal_action_type(self, tmp_path):
        from core.approval.coverage_audit import find_enqueue_call_sites

        _make_engine(tmp_path, "engine_a", """
            def main():
                queue.enqueue(
                    engine="engine_a",
                    action_type="mint_thing",
                    capability="X",
                    params={},
                )
        """)
        sites = find_enqueue_call_sites(tmp_path)
        assert len(sites) == 1
        assert sites[0].action_type == "mint_thing"
        assert sites[0].line > 0

    def test_skips_non_enqueue_calls(self, tmp_path):
        from core.approval.coverage_audit import find_enqueue_call_sites

        _make_engine(tmp_path, "engine_a", """
            def main():
                queue.fetch(action_type="not_an_enqueue")
                random_call(action_type="also_not")
        """)
        assert find_enqueue_call_sites(tmp_path) == []

    def test_skips_dynamic_action_type(self, tmp_path):
        """Non-literal kwargs (variables, f-strings) are intentionally
        skipped — the audit only catches the prevailing engine
        convention. A dynamic action_type would be a separate bug."""
        from core.approval.coverage_audit import find_enqueue_call_sites

        _make_engine(tmp_path, "engine_a", """
            def main():
                at = "computed"
                queue.enqueue(action_type=at)
                queue.enqueue(action_type=f"prefix_{x}")
        """)
        assert find_enqueue_call_sites(tmp_path) == []

    def test_multiple_files(self, tmp_path):
        from core.approval.coverage_audit import find_enqueue_call_sites

        _make_engine(tmp_path, "a", """
            queue.enqueue(action_type="ax")
        """)
        _make_engine(tmp_path, "b", """
            queue.enqueue(action_type="bx")
        """)
        sites = find_enqueue_call_sites(tmp_path)
        assert {s.action_type for s in sites} == {"ax", "bx"}

    def test_syntax_error_skipped(self, tmp_path):
        from core.approval.coverage_audit import find_enqueue_call_sites

        good = tmp_path / "good"
        good.mkdir()
        (good / "__init__.py").write_text(
            'queue.enqueue(action_type="good")', encoding="utf-8",
        )
        # Broken file shouldn't crash the audit
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "__init__.py").write_text(
            "def x(::: SYNTAX BROKEN", encoding="utf-8",
        )
        sites = find_enqueue_call_sites(tmp_path)
        assert {s.action_type for s in sites} == {"good"}


# ─── audit_coverage ──────────────────────────────────────────────


class TestAuditCoverage:

    def test_no_gaps_when_everything_registered(self, tmp_path):
        from core.approval.coverage_audit import audit_coverage
        from core.approval.executor import register_dispatcher

        _make_engine(tmp_path, "engine_a", """
            queue.enqueue(action_type="probe_xyz_unique_a")
        """)
        register_dispatcher("probe_xyz_unique_a")(
            lambda params: (True, {}),
        )
        try:
            report = audit_coverage(tmp_path)
            assert "probe_xyz_unique_a" not in report.missing
        finally:
            # Cleanup test-only registration
            from core.approval.executor import _DISPATCHERS
            _DISPATCHERS.pop("probe_xyz_unique_a", None)

    def test_missing_dispatcher_flagged(self, tmp_path):
        from core.approval.coverage_audit import audit_coverage

        _make_engine(tmp_path, "engine_a", """
            queue.enqueue(action_type="totally_unregistered_xyz")
        """)
        report = audit_coverage(tmp_path)
        assert "totally_unregistered_xyz" in report.missing
        assert report.has_gaps

    def test_orphaned_dispatchers_reported(self, tmp_path):
        from core.approval.coverage_audit import audit_coverage
        from core.approval.executor import register_dispatcher, _DISPATCHERS

        register_dispatcher("orphan_test_xyz")(
            lambda params: (True, {}),
        )
        try:
            # Empty engines dir → orphan_test_xyz is registered
            # but unused
            report = audit_coverage(tmp_path)
            assert "orphan_test_xyz" in report.orphaned
        finally:
            _DISPATCHERS.pop("orphan_test_xyz", None)

    def test_empty_engines_dir(self, tmp_path):
        from core.approval.coverage_audit import audit_coverage

        report = audit_coverage(tmp_path)
        assert report.enqueued == []
        # Missing is empty (nothing's enqueued), has_gaps False
        assert report.missing == []
        assert not report.has_gaps


# ─── shopai approvals audit ──────────────────────────────────────


class TestAuditCLI:

    def test_passes_when_coverage_complete(self, cli, tmp_path):
        from core.approval.coverage_audit import AuditReport

        clean_report = AuditReport(
            enqueued=[], registered=["x"], missing=[], orphaned=[],
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=clean_report,
        ):
            out, code = _capture(
                cli._cmd_approvals_audit,
                _ns(engines_root=str(tmp_path)),
            )
        assert code == 0
        assert "Coverage OK" in out

    def test_fails_when_missing(self, cli, tmp_path):
        from core.approval.coverage_audit import (
            AuditReport, EnqueueCall,
        )

        gap_report = AuditReport(
            enqueued=[EnqueueCall(
                action_type="mint_x", file_path="engines/a.py", line=42,
            )],
            registered=[],
            missing=["mint_x"],
            orphaned=[],
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=gap_report,
        ):
            out, code = _capture(
                cli._cmd_approvals_audit,
                _ns(engines_root=str(tmp_path)),
            )
        assert code == 1
        assert "Missing dispatchers" in out
        assert "mint_x" in out
        assert "engines/a.py:42" in out
        assert "Audit failed" in out

    def test_orphaned_reported_but_passes(self, cli, tmp_path):
        """Orphaned dispatchers are informational, not a failure —
        dead code is annoying but not a Pattern K bug."""
        from core.approval.coverage_audit import AuditReport

        orphan_report = AuditReport(
            enqueued=[], registered=["dead_x"],
            missing=[], orphaned=["dead_x"],
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=orphan_report,
        ):
            out, code = _capture(
                cli._cmd_approvals_audit,
                _ns(engines_root=str(tmp_path)),
            )
        assert code == 0  # Passes — orphans don't fail
        assert "Orphaned" in out
        assert "dead_x" in out

    def test_live_audit_against_real_engines(self, cli):
        """The real engines/ tree must always pass the audit on a
        clean main — this test fails if a future PR adds an enqueue
        site without a matching dispatcher.

        Currently SKIPPED because PR #102 (the 12-dispatcher fix) is
        still open; once merged, flip this to assert exit 0.
        """
        # Run against the real engines/ — soft-check, not a hard
        # assertion until PR #102 merges. We still want the audit to
        # exit cleanly when there are no gaps.
        from core.approval.coverage_audit import audit_coverage

        report = audit_coverage(Path("engines"))
        # All currently-known gaps are tracked in PR #102.
        known_gaps = {
            "apply_bundle_product", "apply_inventory_tags",
            "apply_landing_page", "apply_legal_document",
            "apply_segment_tag", "apply_shipping_strategy",
            "apply_strategic_price", "mint_browse_recovery_code",
            "mint_campaign_code", "mint_cart_recovery_code",
            "mint_wholesale_code", "tag_return_decision",
        }
        # Any *new* gap (one not in known_gaps) is a regression —
        # CI must reject it. Known gaps are tolerated until #102
        # lands.
        new_gaps = set(report.missing) - known_gaps
        assert not new_gaps, (
            f"New Pattern K gap(s) detected: {new_gaps}. "
            "Register matching dispatchers in core/approval/dispatchers.py."
        )
