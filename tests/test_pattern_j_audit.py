"""Tests for the Pattern J test-pollution audit + CLI.

Pattern J (CLAUDE.md): every write to MemoryIntelligence /
DataArchitecture / LearningLoop singletons must come from the
canonical Phase 8 recorder (which gates on
``PYTEST_CURRENT_TEST``) or be in a module that defines its own
``_is_test_environment`` guard. Unguarded writes pollute on-disk
SQLite when tests exercise the path; the failure-intelligence
pipeline then auto-generates avoidance rules from test fixtures.

Tests cover:
  - The live audit passes (regression guard for the current
    baseline)
  - Synthetic-tree classifications for recorder / guarded /
    unguarded
  - Import-filter precision: a file that uses ``attach_result``
    on something OTHER than the target singletons is NOT flagged
  - CLI text + JSON output for pass and fail
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
    defaults = dict(json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Live audit ──────────────────────────────────────────────


class TestLiveAudit:

    def test_live_baseline_is_clean(self):
        """The live codebase passes the audit today (the recorder
        and explicit whitelist cover every known write-site).
        Regression guard: a new unguarded write-site lands here
        as a failure."""
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j()
        assert report.has_violations is False, (
            f"unguarded sites: {report.unguarded_sites}"
        )
        # Audit actually found the recorder + autonomous
        # controller sites
        assert len(report.recorder_sites) >= 5

    def test_scanned_module_count_positive(self):
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j()
        assert report.scanned_modules > 100


# ─── Synthetic tree ──────────────────────────────────────────


def _write_engine(tmp_path, name, body):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "flow.py").write_text(body, encoding="utf-8")


class TestSyntheticTree:

    def test_unguarded_write_surfaces(self, tmp_path):
        """A file that imports MemoryIntelligence AND calls
        create_from_decision WITHOUT a test-env guard MUST be
        flagged as unguarded."""
        _write_engine(
            tmp_path, "bad_engine",
            "from core.memory.intelligence import MemoryIntelligence\n"
            "\n"
            "def write():\n"
            "    mi = MemoryIntelligence()\n"
            "    mi.create_from_decision({})\n",
        )
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j(roots=[tmp_path])
        assert len(report.unguarded_sites) == 1
        assert report.unguarded_sites[0].method == "create_from_decision"
        assert report.has_violations is True

    def test_guarded_module_classified_correctly(self, tmp_path):
        """A module with the recognised guard idiom moves into
        the guarded bucket."""
        _write_engine(
            tmp_path, "guarded_engine",
            "import os\n"
            "from core.memory.intelligence import MemoryIntelligence\n"
            "\n"
            "def _is_test_environment():\n"
            "    return bool(os.environ.get('PYTEST_CURRENT_TEST'))\n"
            "\n"
            "def write():\n"
            "    if _is_test_environment():\n"
            "        return\n"
            "    mi = MemoryIntelligence()\n"
            "    mi.create_from_decision({})\n",
        )
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j(roots=[tmp_path])
        assert len(report.guarded_sites) == 1
        assert len(report.unguarded_sites) == 0

    def test_no_import_no_flag(self, tmp_path):
        """A file that calls ``.attach_result()`` but doesn't
        import any target singleton is NOT flagged. This is the
        false-positive guard for ApprovalQueue.attach_result and
        similar overlapping names."""
        _write_engine(
            tmp_path, "approval_queue_consumer",
            "from core.approval.queue import ApprovalQueue\n"
            "\n"
            "def f():\n"
            "    q = ApprovalQueue()\n"
            "    q.attach_result('id1', success=True, result={})\n",
        )
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j(roots=[tmp_path])
        assert report.unguarded_sites == []
        assert report.guarded_sites == []

    def test_import_alone_no_flag(self, tmp_path):
        """Importing MemoryIntelligence without calling a write
        method must not flag anything."""
        _write_engine(
            tmp_path, "import_only",
            "from core.memory.intelligence import MemoryIntelligence\n"
            "\n"
            "def read():\n"
            "    mi = MemoryIntelligence()\n"
            "    return mi.list_memories()\n",
        )
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j(roots=[tmp_path])
        assert report.unguarded_sites == []

    def test_multiple_write_methods_each_surface(self, tmp_path):
        _write_engine(
            tmp_path, "multi_write",
            "from core.memory.intelligence import MemoryIntelligence\n"
            "\n"
            "def write():\n"
            "    mi = MemoryIntelligence()\n"
            "    mi.create_from_decision({})\n"
            "    mi.record_failure({})\n",
        )
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j(roots=[tmp_path])
        methods = {s.method for s in report.unguarded_sites}
        assert methods == {"create_from_decision", "record_failure"}


# ─── CLI ─────────────────────────────────────────────────────


class TestCli:

    def test_live_audit_exits_0(self, cli):
        out, code = _capture(cli._cmd_pattern_j_audit, _ns())
        assert code == 0
        assert "Pattern J OK" in out

    def test_failure_exits_1_with_remediation(self, cli):
        from engines._pattern_j_audit import (
            PatternJReport,
            WriteSite,
        )
        bad = PatternJReport(
            recorder_sites=[],
            guarded_sites=[],
            unguarded_sites=[
                WriteSite(
                    file="engines/x/flow.py",
                    lineno=42,
                    method="create_from_decision",
                    receiver_expr="mi",
                    module_path="/abs/x/flow.py",
                ),
            ],
            scanned_modules=10,
        )
        with patch(
            "engines._pattern_j_audit.audit_pattern_j",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_pattern_j_audit, _ns())
        assert code == 1
        assert "FAILED" in out
        assert "engines/x/flow.py:42" in out
        assert "create_from_decision" in out
        # Remediation hint surfaces
        assert "_writeback_recorder" in out
        assert "_is_test_environment" in out

    def test_json_pass(self, cli):
        out, code = _capture(
            cli._cmd_pattern_j_audit, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["unguarded_sites"] == []
        assert "recorder_sites" in data

    def test_module_failure_renders_unavailable(self, cli):
        with patch(
            "engines._pattern_j_audit.audit_pattern_j",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(cli._cmd_pattern_j_audit, _ns())
        assert "unavailable" in out.lower()
        # Module failure does NOT fail the gate (best-effort)
        assert code == 0
