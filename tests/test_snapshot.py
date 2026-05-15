"""Tests for ``shopai snapshot`` -- the capstone JSON artifact
that bundles every audit, doctor, and catalog into a single
committable file.

Tests cover:
  - Stdout default emits a deterministic JSON envelope
  - --output FILE writes to disk
  - --force overwrites; without --force, existing files are
    refused (exit 1)
  - The envelope has every expected top-level key
  - Audit summaries (pattern_k/y/i/j + oauth) all surface
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


def _ns(tmp_path=None, **kw):
    defaults = dict(
        output=None,
        force=False,
        skip_live=True,
        # for the doctor section collectors:
        stale_pending_hours=24.0,
        failure_rate_warn=0.25,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Stdout (default) ────────────────────────────────────────


class TestStdout:

    def test_default_emits_json_envelope_to_stdout(self, cli):
        out, code = _capture(cli._cmd_snapshot, _ns())
        assert code == 0
        data = json.loads(out)
        assert "generated_at" in data
        assert data["schema_version"] == 1
        assert "engine_counts" in data
        assert "catalog" in data
        assert "audits" in data
        assert "doctor_shopify" in data
        assert "doctor_approvals" in data
        assert "overall_ok" in data

    def test_engine_counts_shape(self, cli):
        out, _ = _capture(cli._cmd_snapshot, _ns())
        data = json.loads(out)
        ec = data["engine_counts"]
        assert ec["total"] > 100
        assert ec["wired"] >= 20
        assert ec["advisory"] >= 0

    def test_catalog_entries_present(self, cli):
        out, _ = _capture(cli._cmd_snapshot, _ns())
        data = json.loads(out)
        catalog = data["catalog"]
        assert catalog["total_dispatchers"] > 0
        assert isinstance(catalog["entries"], list)
        # Each entry has expected keys
        e = catalog["entries"][0]
        assert "action_type" in e
        assert "capabilities" in e
        assert "adapters" in e
        assert "emitting_engines" in e

    def test_all_audits_summarised(self, cli):
        out, _ = _capture(cli._cmd_snapshot, _ns())
        data = json.loads(out)
        audits = data["audits"]
        assert set(audits.keys()) >= {
            "pattern_k", "oauth_scopes", "pattern_y",
            "pattern_i", "pattern_j",
        }
        # Each audit's ok flag is present
        for name, payload in audits.items():
            assert "ok" in payload or "error" in payload

    def test_overall_ok_is_true_on_clean_baseline(self, cli):
        out, _ = _capture(cli._cmd_snapshot, _ns())
        data = json.loads(out)
        # Live baseline passes both doctors when --skip-live is set
        assert data["overall_ok"] is True


# ─── --output FILE ───────────────────────────────────────────


class TestOutputFile:

    def test_writes_to_disk(self, cli, tmp_path):
        target = tmp_path / "snapshot.json"
        out, code = _capture(
            cli._cmd_snapshot, _ns(output=str(target)),
        )
        assert code == 0
        assert target.exists()
        # Confirm content is a valid JSON envelope
        body = target.read_text(encoding="utf-8")
        data = json.loads(body)
        assert data["schema_version"] == 1
        # CLI reports the write
        assert "Wrote" in out

    def test_existing_file_refused_without_force(self, cli, tmp_path):
        target = tmp_path / "snapshot.json"
        target.write_text("# previous\n", encoding="utf-8")
        out, code = _capture(
            cli._cmd_snapshot, _ns(output=str(target)),
        )
        assert code == 1
        assert "Refusing to overwrite" in out
        # File untouched
        assert target.read_text(encoding="utf-8") == "# previous\n"

    def test_existing_file_overwritten_with_force(self, cli, tmp_path):
        target = tmp_path / "snapshot.json"
        target.write_text("# stale\n", encoding="utf-8")
        _, code = _capture(
            cli._cmd_snapshot,
            _ns(output=str(target), force=True),
        )
        assert code == 0
        body = target.read_text(encoding="utf-8")
        assert "# stale" not in body
        # Real JSON now
        data = json.loads(body)
        assert "generated_at" in data


# ─── Schema durability ───────────────────────────────────────


class TestSchema:

    def test_two_consecutive_snapshots_share_shape(self, cli):
        """Two back-to-back snapshots must have identical top-
        level keys (timestamps differ but structure doesn't).
        Operators committing snapshots can diff cleanly."""
        out_a, _ = _capture(cli._cmd_snapshot, _ns())
        out_b, _ = _capture(cli._cmd_snapshot, _ns())
        a = json.loads(out_a)
        b = json.loads(out_b)
        assert set(a.keys()) == set(b.keys())
        assert set(a["audits"].keys()) == set(b["audits"].keys())


# ─── --diff mode ─────────────────────────────────────────────


class TestDiff:

    def _make_baseline(self, cli, tmp_path):
        """Capture a fresh baseline, write it to tmp_path/base.json,
        and return the path."""
        out, _ = _capture(cli._cmd_snapshot, _ns())
        base_path = tmp_path / "base.json"
        base_path.write_text(out, encoding="utf-8")
        return base_path

    def test_diff_against_self_is_clean(self, cli, tmp_path):
        """A diff against a fresh baseline (no drift) reports
        has_changes=false and exits 0."""
        base_path = self._make_baseline(cli, tmp_path)
        out, code = _capture(
            cli._cmd_snapshot,
            _ns(diff=str(base_path)),
        )
        data = json.loads(out)
        assert data["has_changes"] is False
        assert data["changes"] == {}
        assert code == 0

    def test_diff_against_mutated_baseline_exits_1(
        self, cli, tmp_path,
    ):
        """A baseline with a missing catalog entry shows the
        entry as 'added' in the diff and exits 1 (drift)."""
        base_path = self._make_baseline(cli, tmp_path)
        baseline = json.loads(
            base_path.read_text(encoding="utf-8"),
        )
        # Drop the first catalog entry to simulate a removed
        # dispatcher in the baseline (so the current snapshot
        # appears to have ADDED it)
        if baseline["catalog"]["entries"]:
            dropped = baseline["catalog"]["entries"][0]["action_type"]
            baseline["catalog"]["entries"] = (
                baseline["catalog"]["entries"][1:]
            )
            base_path.write_text(
                json.dumps(baseline, indent=2),
                encoding="utf-8",
            )
        out, code = _capture(
            cli._cmd_snapshot,
            _ns(diff=str(base_path)),
        )
        assert code == 1
        data = json.loads(out)
        assert data["has_changes"] is True
        assert dropped in data["changes"]["catalog"]["added"]

    def test_diff_writes_to_output_file(self, cli, tmp_path):
        """--diff + --output emits the diff to the file."""
        base_path = self._make_baseline(cli, tmp_path)
        out_path = tmp_path / "drift.json"
        # The synthetic clean case has no diff -> the file is
        # written with an empty changes dict and exits 0.
        out, code = _capture(
            cli._cmd_snapshot,
            _ns(diff=str(base_path), output=str(out_path)),
        )
        assert code == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["has_changes"] is False

    def test_diff_missing_baseline_exits_1(self, cli, tmp_path):
        out, code = _capture(
            cli._cmd_snapshot,
            _ns(diff=str(tmp_path / "does_not_exist.json")),
        )
        assert code == 1
        assert "not found" in out

    def test_diff_invalid_baseline_exits_1(self, cli, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        out, code = _capture(
            cli._cmd_snapshot, _ns(diff=str(bad)),
        )
        assert code == 1
        assert "not valid JSON" in out

    def test_audit_flip_surfaces_in_diff(self, cli, tmp_path):
        """Flip pattern_k.ok from True to False in a synthetic
        baseline -> the audit flip surfaces in the diff."""
        base_path = self._make_baseline(cli, tmp_path)
        baseline = json.loads(
            base_path.read_text(encoding="utf-8"),
        )
        baseline["audits"]["pattern_k"]["ok"] = False
        base_path.write_text(
            json.dumps(baseline, indent=2), encoding="utf-8",
        )
        out, code = _capture(
            cli._cmd_snapshot, _ns(diff=str(base_path)),
        )
        data = json.loads(out)
        assert code == 1
        # The flip is surfaced under audits.pattern_k
        assert (
            data["changes"]["audits"]["pattern_k"]["baseline"]
            is False
        )
        assert (
            data["changes"]["audits"]["pattern_k"]["current"]
            is True
        )


# ─── _diff_snapshots() unit tests ─────────────────────────────


class TestDiffUnit:

    def test_overall_ok_flip_detected(self, cli):
        a = {"overall_ok": True}
        b = {"overall_ok": False}
        d = cli._diff_snapshots(a, b)
        assert d["has_changes"] is True
        assert d["changes"]["overall_ok"]["baseline"] is True
        assert d["changes"]["overall_ok"]["current"] is False

    def test_catalog_added_removed_classified(self, cli):
        a = {
            "catalog": {
                "entries": [
                    {"action_type": "x", "capabilities": ["A"]},
                ],
            },
        }
        b = {
            "catalog": {
                "entries": [
                    {"action_type": "y", "capabilities": ["B"]},
                ],
            },
        }
        d = cli._diff_snapshots(a, b)
        assert d["changes"]["catalog"]["added"] == ["y"]
        assert d["changes"]["catalog"]["removed"] == ["x"]

    def test_catalog_changed_capability_surfaces(self, cli):
        a = {
            "catalog": {
                "entries": [
                    {
                        "action_type": "x",
                        "capabilities": ["OLD_CAP"],
                        "aggregate_scopes": ["read"],
                        "emitting_engines": ["engine_a"],
                        "adapters": [{"name": "shopify_x"}],
                    },
                ],
            },
        }
        b = {
            "catalog": {
                "entries": [
                    {
                        "action_type": "x",
                        "capabilities": ["NEW_CAP"],
                        "aggregate_scopes": ["read"],
                        "emitting_engines": ["engine_a"],
                        "adapters": [{"name": "shopify_x"}],
                    },
                ],
            },
        }
        d = cli._diff_snapshots(a, b)
        changed = d["changes"]["catalog"]["changed"]
        assert len(changed) == 1
        assert changed[0]["action_type"] == "x"
        assert (
            changed[0]["changes"]["capabilities"]["baseline"]
            == ["OLD_CAP"]
        )

    def test_no_changes_returns_empty(self, cli):
        snap = {
            "overall_ok": True,
            "engine_counts": {"total": 100},
            "catalog": {"entries": []},
            "audits": {"pattern_k": {"ok": True}},
        }
        d = cli._diff_snapshots(snap, dict(snap))
        assert d["has_changes"] is False
        assert d["changes"] == {}
