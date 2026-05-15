"""Tests for ``ApprovalQueue.stats_by_engine`` and the
``shopai approvals stats --by-engine`` CLI flag.

The flat ``stats()`` view answered "how big is the queue overall."
``stats_by_engine()`` answers the more useful operator question:
"which engines are generating the most proposals, and which engines
have growing rejection/expiry rates" — a triage signal.
"""
from __future__ import annotations

import argparse
import importlib.util
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


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── ApprovalQueue.stats_by_engine ───────────────────────────────


class TestStatsByEngine:

    def test_empty_queue(self, isolated_queue):
        assert isolated_queue.stats_by_engine() == {}

    def test_single_engine_pending(self, isolated_queue):
        isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        result = isolated_queue.stats_by_engine()
        assert "cart_recovery" in result
        assert result["cart_recovery"]["pending"] == 1
        assert result["cart_recovery"]["approved"] == 0

    def test_multiple_engines_isolated(self, isolated_queue):
        isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        isolated_queue.enqueue(
            engine="loyalty", action_type="x",
            capability="X", params={}, narrative="",
        )
        result = isolated_queue.stats_by_engine()
        assert result["cart_recovery"]["pending"] == 1
        assert result["loyalty"]["pending"] == 1
        # Each engine has its own per-status dict
        assert result["cart_recovery"]["approved"] == 0
        assert result["loyalty"]["approved"] == 0

    def test_status_transitions_reflected(self, isolated_queue):
        a = isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        b = isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        isolated_queue.reject(b.id)

        result = isolated_queue.stats_by_engine()
        assert result["cart_recovery"]["approved"] == 1
        assert result["cart_recovery"]["rejected"] == 1
        assert result["cart_recovery"]["pending"] == 0

    def test_all_status_keys_present(self, isolated_queue):
        """Every present engine gets every status key, with 0 for
        absent statuses — so dashboards don't KeyError on
        ``stats['executed']``."""
        isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        result = isolated_queue.stats_by_engine()
        expected_keys = {
            "pending", "approved", "rejected",
            "executed", "failed", "expired",
        }
        assert set(result["x"].keys()) == expected_keys


# ─── shopai approvals stats --by-engine ───────────────────────────


class TestStatsCLI:

    def test_flat_stats_default(self, cli, isolated_queue):
        isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        out = _capture(
            cli._cmd_approvals_stats,
            argparse.Namespace(by_engine=False),
        )
        assert "Approval queue stats:" in out
        assert "pending" in out
        # No table header
        assert "Approval queue by engine" not in out

    def test_by_engine_table(self, cli, isolated_queue):
        a = isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        out = _capture(
            cli._cmd_approvals_stats,
            argparse.Namespace(by_engine=True),
        )
        assert "Approval queue by engine:" in out
        # Engine name + per-status columns present
        assert "cart_recovery" in out
        assert "pending" in out
        assert "approved" in out
        # The approved row has a 1
        lines = [l for l in out.splitlines() if "cart_recovery" in l]
        assert lines
        # ... and the right cell carries the count
        assert "1" in lines[0]

    def test_by_engine_empty_message(self, cli, isolated_queue):
        out = _capture(
            cli._cmd_approvals_stats,
            argparse.Namespace(by_engine=True),
        )
        assert "Approval queue is empty" in out

    def test_engines_sorted_alphabetically(self, cli, isolated_queue):
        for name in ["zeta", "alpha", "mu"]:
            isolated_queue.enqueue(
                engine=name, action_type="x", capability="X",
                params={}, narrative="",
            )
        out = _capture(
            cli._cmd_approvals_stats,
            argparse.Namespace(by_engine=True),
        )
        # First engine row is alpha, last is zeta
        engine_rows = [
            l for l in out.splitlines()
            if any(e in l for e in ("alpha", "mu", "zeta"))
        ]
        assert "alpha" in engine_rows[0]
        assert "zeta" in engine_rows[-1]
