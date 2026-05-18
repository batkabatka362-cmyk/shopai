"""Tests for ``shopai approvals quarantine-simulate``.

Dry-run the quarantine evaluator for a given (engine,
store_id) pair without actually enqueueing anything.
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


@pytest.fixture
def quarantine_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(engine="loyalty", store=None, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestSimulate:

    def test_missing_engine_errors(
        self, cli, quarantine_data_dir, queue,
    ):
        out = _capture(
            cli._cmd_approvals_quarantine_simulate, _ns(engine=""),
        )
        assert "Error" in out
        assert "engine name is required" in out

    def test_clean_engine_would_proceed(
        self, cli, quarantine_data_dir, queue,
    ):
        out = _capture(
            cli._cmd_approvals_quarantine_simulate, _ns(),
        )
        assert "would proceed" in out
        assert "loyalty" in out

    def test_clean_engine_json(
        self, cli, quarantine_data_dir, queue,
    ):
        out = _capture(
            cli._cmd_approvals_quarantine_simulate,
            _ns(json=True),
        )
        data = json.loads(out)
        assert data["engine"] == "loyalty"
        assert data["store_id"] is None
        assert data["verdict"] == "would_proceed"
        assert data["should_quarantine"] is False
        assert data["state"]["alert_paused"] is False

    def test_alert_paused_engine_would_be_rejected(
        self, cli, quarantine_data_dir, queue,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")  # fleet-wide
        out = _capture(
            cli._cmd_approvals_quarantine_simulate,
            _ns(json=True),
        )
        data = json.loads(out)
        assert data["verdict"] == "would_be_quarantined"
        assert data["should_quarantine"] is True
        assert data["state"]["alert_paused"] is True
        assert "auto_quarantine_from_alerts" in data["reason"]

    def test_per_store_pause_only_matches_that_store(
        self, cli, quarantine_data_dir, queue,
    ):
        """Per-store pause for store_a doesn't quarantine
        store_b's simulated enqueue."""
        from core.approval import quarantine
        quarantine.add_alert_pause(
            "loyalty", store_id="store_a",
        )
        out_a = _capture(
            cli._cmd_approvals_quarantine_simulate,
            _ns(store="store_a", json=True),
        )
        out_b = _capture(
            cli._cmd_approvals_quarantine_simulate,
            _ns(store="store_b", json=True),
        )
        data_a = json.loads(out_a)
        data_b = json.loads(out_b)
        assert data_a["verdict"] == "would_be_quarantined"
        assert data_b["verdict"] == "would_proceed"

    def test_exempt_engine_would_proceed_even_with_pause(
        self, cli, quarantine_data_dir, queue,
    ):
        """Exempt beats alert_paused -- operator intent wins."""
        from core.approval import quarantine
        quarantine.exempt_engine("loyalty")
        quarantine.add_alert_pause("loyalty")
        out = _capture(
            cli._cmd_approvals_quarantine_simulate,
            _ns(json=True),
        )
        data = json.loads(out)
        assert data["verdict"] == "would_proceed"
        assert "engine_exempt" in data["reason"]

    def test_text_render_shows_state_block(
        self, cli, quarantine_data_dir, queue,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        out = _capture(
            cli._cmd_approvals_quarantine_simulate, _ns(),
        )
        assert "State for this engine:" in out
        assert "alert_paused: True" in out

    def test_evaluate_failure_exits_1(
        self, cli, quarantine_data_dir, queue,
    ):
        with patch(
            "core.approval.quarantine.evaluate",
            side_effect=RuntimeError("db gone"),
        ):
            out = _capture(
                cli._cmd_approvals_quarantine_simulate, _ns(),
            )
        assert "Error" in out
        assert "db gone" in out
