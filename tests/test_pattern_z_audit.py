"""Tests for the Pattern Z writer-recorder parity audit + CLI.

Pattern Z catches the bug class fixed live in PR #205: writer
modules (``*_applier.py`` / ``*_minter.py`` / ``*_payer.py``)
that call a Shopify mutation but skip ``record_writeback``. The
minted/applied changes are real on Shopify, but Phase 8
(MemoryIntelligence / DataArchitecture / LearningLoop) never
sees them -- the recommender and EMA undercount those engines.

Tests cover:
  - Live baseline (regression guard): every writer in engines/
    has both signals (or legitimately neither)
  - Synthetic-tree classification: writer with mutation + no
    recorder -> missing
  - Writer with no mutation -> skipped (queue-only writer)
  - Writer with both -> clean
  - Non-writer files skipped entirely
  - CLI text + JSON + remediation hint surface
  - Consolidated audit includes pattern_z
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
    defaults = dict(json=False, only=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Live baseline ────────────────────────────────────────────


class TestLiveBaseline:

    def test_live_audit_is_clean(self):
        """The repo's current writer modules all have
        record_writeback (or legitimately don't call mutations).
        New writer PRs that skip the recorder land here as
        failures."""
        from engines._pattern_z_audit import audit_pattern_z
        report = audit_pattern_z()
        assert report.has_violations is False, (
            f"missing_recorder: "
            f"{[s.file for s in report.missing_recorder]}"
        )
        assert report.scanned_writers > 20
        assert len(report.clean_writers) >= 20

    def test_scanned_count_matches_glob(self):
        """Sanity check that we find every writer file: scan
        count == glob count."""
        from engines._pattern_z_audit import audit_pattern_z
        engines_root = (
            Path(__file__).resolve().parent.parent / "engines"
        )
        glob_count = sum(
            1 for suffix in ("_applier.py", "_minter.py", "_payer.py")
            for _ in engines_root.glob(f"*/*{suffix}")
        )
        report = audit_pattern_z()
        assert report.scanned_writers == glob_count


# ─── Synthetic-tree classification ────────────────────────────


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestSyntheticTree:

    def test_writer_with_mutation_no_recorder_flagged(self, tmp_path):
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "bad_engine/foo_applier.py", (
            "def f():\n"
            "    return router.execute(cap, params)\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        assert len(report.missing_recorder) == 1
        site = report.missing_recorder[0]
        assert site.file == "bad_engine/foo_applier.py"
        assert "execute" in site.mutation_calls
        assert site.has_recorder_import is False
        assert report.has_violations is True

    def test_writer_with_both_signals_is_clean(self, tmp_path):
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "good_engine/foo_applier.py", (
            "from engines._writeback_recorder import record_writeback\n"
            "def f():\n"
            "    result = router.execute(cap, params)\n"
            "    record_writeback(engine='good', action_type='x',\n"
            "                     capability='Y', params={},\n"
            "                     success=True)\n"
            "    return result\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        assert report.has_violations is False
        assert "good_engine/foo_applier.py" in report.clean_writers

    def test_writer_with_no_mutation_is_skipped(self, tmp_path):
        """A writer that only enqueues (no direct mutation) is
        legitimately exempt -- the queue path's recorder is the
        executor's responsibility."""
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "queue_engine/foo_applier.py", (
            "def f():\n"
            "    return queue.enqueue(\n"
            "        engine='queue', action_type='x',\n"
            "        capability='Y', params={},\n"
            "        narrative='',\n"
            "    )\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        assert report.has_violations is False
        assert (
            "queue_engine/foo_applier.py"
            in report.skipped_no_mutation
        )

    def test_recorder_imported_but_not_called_still_fails(
        self, tmp_path,
    ):
        """An import without an actual call is a half-fix; the
        audit must still flag it (with the
        ``has_recorder_import`` hint)."""
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "half_engine/foo_applier.py", (
            "from engines._writeback_recorder import record_writeback\n"
            "def f():\n"
            "    return router.execute(cap, params)\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        assert len(report.missing_recorder) == 1
        site = report.missing_recorder[0]
        assert site.has_recorder_import is True

    def test_non_writer_file_skipped(self, tmp_path):
        """Files not ending in _applier.py / _minter.py /
        _payer.py are out of scope -- even if they call
        router.execute."""
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "x/some_other.py", (
            "def f():\n"
            "    return router.execute(cap, params)\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        # Not in any bucket
        assert report.scanned_writers == 0

    def test_mint_recovery_code_counts_as_mutation(self, tmp_path):
        """The shared mint helper is a mutation call -- a minter
        that calls it without record_writeback must be flagged
        (this is exactly the PR #205 bug class)."""
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "bad_minter/discount_minter.py", (
            "def mint():\n"
            "    return mint_recovery_code(\n"
            "        token='x', code_prefix='X', value=10,\n"
            "        value_kind='percentage', ttl_days=7,\n"
            "    )\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        assert len(report.missing_recorder) == 1
        assert (
            "mint_recovery_code"
            in report.missing_recorder[0].mutation_calls
        )

    def test_payer_files_in_scope(self, tmp_path):
        """``*_payer.py`` files (e.g. commission_payer) are in
        scope -- they pay out gift cards via the router."""
        from engines._pattern_z_audit import audit_pattern_z
        _write(tmp_path, "affiliate/commission_payer.py", (
            "def pay():\n"
            "    return router.execute(cap, params)\n"
        ))
        report = audit_pattern_z(engines_root=tmp_path)
        assert len(report.missing_recorder) == 1
        assert (
            report.missing_recorder[0].file
            == "affiliate/commission_payer.py"
        )


# ─── CLI ──────────────────────────────────────────────────────


class TestCli:

    def test_live_audit_text_exits_0(self, cli):
        out, code = _capture(cli._cmd_pattern_z_audit, _ns())
        assert code == 0
        assert "Pattern Z OK" in out

    def test_json_envelope(self, cli):
        out, code = _capture(
            cli._cmd_pattern_z_audit, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert "scanned_writers" in data
        assert data["missing_recorder"] == []

    def test_failure_renders_remediation(self, cli):
        from engines._pattern_z_audit import (
            PatternZReport,
            WriterAuditSite,
        )
        bad = PatternZReport(
            scanned_writers=5,
            clean_writers=["a", "b", "c", "d"],
            missing_recorder=[
                WriterAuditSite(
                    file="engines/bad/foo_applier.py",
                    mutation_calls=("execute",),
                    has_recorder_import=False,
                ),
            ],
            skipped_no_mutation=[],
        )
        with patch(
            "engines._pattern_z_audit.audit_pattern_z",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_pattern_z_audit, _ns())
        assert code == 1
        assert "FAILED" in out
        assert "engines/bad/foo_applier.py" in out
        # Remediation hint surfaces
        assert "record_writeback" in out
        assert "engines._writeback_recorder" in out

    def test_module_failure_is_resilient(self, cli):
        with patch(
            "engines._pattern_z_audit.audit_pattern_z",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(cli._cmd_pattern_z_audit, _ns())
        assert "unavailable" in out.lower()
        assert code == 0  # unavailable is not a fatal failure


# ─── Consolidated audit integration ──────────────────────────


class TestConsolidatedAuditIntegration:

    def test_pattern_z_runs_in_consolidated_audit(self, cli):
        out, _ = _capture(
            cli._cmd_audit_all, _ns(json=True),
        )
        data = json.loads(out)
        assert "pattern_z" in data["audits"]
        # Default state is clean
        assert data["audits"]["pattern_z"]["ok"] is True

    def test_pattern_z_only_filter(self, cli):
        out, code = _capture(
            cli._cmd_audit_all, _ns(only="pattern_z"),
        )
        assert code == 0
        assert "Pattern Z" in out

    def test_pattern_z_failure_fails_consolidated(self, cli):
        from engines._pattern_z_audit import (
            PatternZReport,
            WriterAuditSite,
        )
        bad = PatternZReport(
            scanned_writers=1,
            clean_writers=[],
            missing_recorder=[
                WriterAuditSite(
                    file="x/foo_applier.py",
                    mutation_calls=("execute",),
                    has_recorder_import=False,
                ),
            ],
            skipped_no_mutation=[],
        )
        with patch(
            "engines._pattern_z_audit.audit_pattern_z",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_audit_all, _ns())
        assert code == 1
        assert "[FAIL] Pattern Z" in out
