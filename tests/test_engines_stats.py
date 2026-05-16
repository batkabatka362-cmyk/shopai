"""Tests for ``shopai engines-stats`` -- aggregate engine
activity across queue + wiring.

Combines three signals per engine:
  - Wiring status (wired / advisory / partial)
  - Queue activity (pending/approved/rejected/executed/failed/expired)
  - Total registered engine count

The "which engines are pulling weight?" daily-glance command.
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
def seeded_queue(tmp_path: Path, monkeypatch):
    """Fresh in-temp queue with one action enqueued.

    Tests that assert behaviour around the active/idle split
    need a predictable queue state -- the live SQLite store
    varies between dev machines and CI (CI starts empty, my
    laptop has 17+ actions in residence). Seeding via this
    fixture keeps the assertions deterministic.
    """
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    # Seed a single action on a known engine so the "active"
    # bucket has exactly one entry.
    fresh.enqueue(
        engine="tag_management",
        action_type="apply_tags",
        capability="SHOPIFY_UPDATE_PRODUCT",
        params={
            "product_id": "p1",
            "merged_tags": ["seed"],
        },
        narrative="seeded for engines-stats test",
        confidence=0.9,
    )
    yield fresh
    fresh._conn.close()


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
    defaults = dict(json=False, top=10, filter="all")
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Live render ─────────────────────────────────────────────


class TestLiveRender:

    def test_renders_summary_header(self, cli):
        out, code = _capture(cli._cmd_engines_stats, _ns())
        assert code == 0
        assert "ShopAI Engine Activity Stats" in out
        assert "Total engines:" in out
        # Each summary line
        assert "wired:" in out
        assert "advisory:" in out
        assert "active:" in out
        assert "idle:" in out

    def test_top_n_respected(self, cli):
        out_3, _ = _capture(cli._cmd_engines_stats, _ns(top=3))
        out_10, _ = _capture(cli._cmd_engines_stats, _ns(top=10))
        # More rows in top-10 than top-3 (live registry has
        # plenty of engines)
        rows_3 = [
            ln for ln in out_3.splitlines()
            if ln.startswith("  ") and ln[2].isalpha()
        ]
        rows_10 = [
            ln for ln in out_10.splitlines()
            if ln.startswith("  ") and ln[2].isalpha()
        ]
        # Approximate -- not exact because header rows count too
        assert len(rows_10) > len(rows_3)

    def test_filter_active_only_shows_active_engines(
        self, cli, seeded_queue,
    ):
        """Seeded queue guarantees at least one active engine
        so the filter line + ranking renders. Otherwise CI
        (which starts with an empty queue) hits the
        empty-result short-circuit and the test was brittle."""
        out, _ = _capture(
            cli._cmd_engines_stats,
            _ns(filter="active", top=50),
        )
        assert "Filtered to active" in out
        # The seeded engine appears in the active list
        assert "tag_management" in out

    def test_filter_idle_excludes_active(self, cli, seeded_queue):
        out, _ = _capture(
            cli._cmd_engines_stats,
            _ns(filter="idle", top=5),
        )
        assert "Filtered to idle" in out
        # The seeded active engine should NOT appear in the
        # idle list
        assert "tag_management" not in out


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_summary_keys_present(self, cli):
        out, _ = _capture(
            cli._cmd_engines_stats, _ns(json=True),
        )
        data = json.loads(out)
        for key in (
            "total_engines",
            "wired",
            "advisory",
            "partial",
            "active",
            "idle",
        ):
            assert key in data["summary"]

    def test_engines_list_sorted_by_activity(self, cli):
        out, _ = _capture(
            cli._cmd_engines_stats, _ns(json=True, top=20),
        )
        data = json.loads(out)
        engines = data["engines"]
        if len(engines) >= 2:
            # Sorted descending by total_actions
            totals = [e["total_actions"] for e in engines]
            assert totals == sorted(totals, reverse=True)

    def test_per_engine_keys(self, cli):
        out, _ = _capture(
            cli._cmd_engines_stats, _ns(json=True, top=1),
        )
        data = json.loads(out)
        e = data["engines"][0]
        for key in (
            "name",
            "wiring",
            "writers",
            "pending",
            "approved",
            "rejected",
            "executed",
            "failed",
            "expired",
            "total_actions",
            "successful_actions",
        ):
            assert key in e

    def test_active_engines_count_matches_active_summary(
        self, cli, seeded_queue,
    ):
        """Seeded queue ensures at least one active engine, so
        the cross-reference assertion exercises real data (not
        the trivial 0==0 case)."""
        out, _ = _capture(
            cli._cmd_engines_stats,
            _ns(json=True, top=200, filter="active"),
        )
        data = json.loads(out)
        # At least one active engine post-seed
        assert data["summary"]["active"] >= 1
        # Every engine in the filtered list has activity > 0
        for e in data["engines"]:
            assert e["total_actions"] > 0
        # And the count matches the summary's active count
        assert len(data["engines"]) == data["summary"]["active"]


# ─── Wiring + queue cross-reference ─────────────────────────


class TestWiringCrossRef:

    def test_wired_engines_marked_wired(self, cli):
        """An engine in the wired set has wiring='wired' in
        the stats output. Cross-references the writeback audit."""
        from engines._writeback_audit import audit_writeback_coverage
        wb = audit_writeback_coverage("engines")
        wired_names = {
            s.name for s in wb.engines if s.status == "wired"
        }
        out, _ = _capture(
            cli._cmd_engines_stats, _ns(json=True, top=200),
        )
        data = json.loads(out)
        for e in data["engines"]:
            if e["name"] in wired_names:
                assert e["wiring"] == "wired"

    def test_writers_listed_for_wired_engine(self, cli):
        out, _ = _capture(
            cli._cmd_engines_stats, _ns(json=True, top=200),
        )
        data = json.loads(out)
        # At least one wired engine has writer files listed
        wired_with_writers = [
            e for e in data["engines"]
            if e["wiring"] == "wired" and e["writers"]
        ]
        assert len(wired_with_writers) > 0


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_queue_failure_doesnt_break_command(self, cli):
        """A broken approval queue probe surfaces as
        empty per-engine activity but doesn't crash."""
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            out, code = _capture(
                cli._cmd_engines_stats, _ns(),
            )
        assert code == 0
        assert "Total engines:" in out

    def test_writeback_audit_failure_doesnt_break_command(self, cli):
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_engines_stats, _ns(),
            )
        assert code == 0
        # Total engines still shown (from registry)
        assert "Total engines:" in out

    def test_registry_failure_yields_empty(self, cli):
        with patch(
            "engines.registry.list_engines",
            side_effect=RuntimeError("registry broken"),
        ):
            out, code = _capture(
                cli._cmd_engines_stats, _ns(),
            )
        assert code == 0
        # Total engines is 0 since registry probe failed
        assert "Total engines: 0" in out
