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
