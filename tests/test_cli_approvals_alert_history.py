"""Tests for ``shopai approvals alert-history`` CLI."""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
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


@pytest.fixture(autouse=True)
def _disable_alert_history_test_guard():
    """Pattern J guard prevents alert_history writes under
    pytest; flip it off for this whole file."""
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(
        engine=None, since_days=7.0, clear=False,
        prune_older_than_days=None, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeAlert:
    def __init__(self, engine):
        self.engine = engine
        self.drop = 0.3
        self.recent_score = 0.4
        self.baseline_score = 0.7


# ─── Text mode ───────────────────────────────────────────────


class TestTextMode:

    def test_empty_history_message(self, cli, data_dir):
        out = _capture(cli._cmd_approvals_alert_history, _ns())
        assert "No alert firings" in out

    def test_empty_with_engine_filter(self, cli, data_dir):
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(engine="loyalty"),
        )
        assert "No alert firings" in out
        assert "loyalty" in out

    def test_populated_shows_event_count(self, cli, data_dir):
        from core.approval import alert_history
        now = time.time()
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - 100,
        )
        out = _capture(cli._cmd_approvals_alert_history, _ns())
        assert "Alert history" in out
        assert "1 event(s)" in out
        assert "loyalty" in out

    def test_populated_shows_consecutive_count(
        self, cli, data_dir,
    ):
        from core.approval import alert_history
        day = 86400.0
        now = time.time()
        # Three firings on three days
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 2,
        )
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 1,
        )
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - 100,
        )
        out = _capture(cli._cmd_approvals_alert_history, _ns())
        assert "Per-engine bucket-day count" in out
        assert "loyalty" in out
        assert "3 day(s)" in out

    def test_engine_filter_text(self, cli, data_dir):
        from core.approval import alert_history
        now = time.time()
        alert_history.record_alerts(
            [_FakeAlert("loyalty"), _FakeAlert("affiliate")],
            now=now - 100,
        )
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(engine="loyalty"),
        )
        assert "loyalty" in out
        assert "affiliate" not in out


# ─── JSON mode ───────────────────────────────────────────────


class TestJsonMode:

    def test_empty_envelope(self, cli, data_dir):
        out = _capture(
            cli._cmd_approvals_alert_history, _ns(json=True),
        )
        data = json.loads(out)
        assert data["event_count"] == 0
        assert data["events"] == []
        assert data["consecutive_days_by_engine"] == {}

    def test_populated_envelope(self, cli, data_dir):
        from core.approval import alert_history
        now = time.time()
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - 100,
        )
        out = _capture(
            cli._cmd_approvals_alert_history, _ns(json=True),
        )
        data = json.loads(out)
        assert data["event_count"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["engine"] == "loyalty"
        assert data["events"][0]["drop"] == 0.3
        assert "loyalty" in data["consecutive_days_by_engine"]

    def test_since_days_narrows_window(self, cli, data_dir):
        from core.approval import alert_history
        day = 86400.0
        now = time.time()
        # Old firing (10 days back), recent firing (yesterday)
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 10,
        )
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 1,
        )
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(json=True, since_days=2.0),
        )
        data = json.loads(out)
        # Only the recent firing is in the 2-day window
        assert data["event_count"] == 1


# ─── Clear escape hatch ──────────────────────────────────────


class TestClear:

    def test_clear_wipes_history(self, cli, data_dir):
        from core.approval import alert_history
        now = time.time()
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - 100,
        )
        assert len(alert_history.recent_history(now=now)) == 1

        out = _capture(
            cli._cmd_approvals_alert_history, _ns(clear=True),
        )
        assert "wiped" in out.lower()
        assert alert_history.recent_history(now=now) == []

    def test_clear_json(self, cli, data_dir):
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(clear=True, json=True),
        )
        data = json.loads(out)
        assert data["status"] == "success"
        assert data["cleared"] is True

    def test_clear_failure_exits_1(self, cli, data_dir):
        with patch(
            "core.approval.alert_history.clear",
            side_effect=OSError("disk full"),
        ):
            out = _capture(
                cli._cmd_approvals_alert_history,
                _ns(clear=True),
            )
        assert "Error" in out
        assert "disk full" in out


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_read_failure_exits_cleanly(self, cli, data_dir):
        with patch(
            "core.approval.alert_history.recent_history",
            side_effect=RuntimeError("io error"),
        ):
            out = _capture(
                cli._cmd_approvals_alert_history, _ns(),
            )
        assert "Error" in out

    def test_read_failure_json_envelope(self, cli, data_dir):
        with patch(
            "core.approval.alert_history.recent_history",
            side_effect=RuntimeError("io error"),
        ):
            out = _capture(
                cli._cmd_approvals_alert_history,
                _ns(json=True),
            )
        data = json.loads(out)
        assert data["status"] == "error"
        assert "io error" in data["error"]


# ─── Prune ───────────────────────────────────────────────────


class TestPrune:
    """``--prune-older-than-days N`` drops events older than
    N days while preserving newer events. Finer scalpel than
    ``--clear``."""

    def test_prune_removes_old_events(self, cli, data_dir):
        from core.approval import alert_history
        day = 86400.0
        now = time.time()
        # 3 old events, 2 recent
        alert_history.record_alerts(
            [_FakeAlert("a"), _FakeAlert("b"), _FakeAlert("c")],
            now=now - day * 30,
        )
        alert_history.record_alerts(
            [_FakeAlert("d"), _FakeAlert("e")],
            now=now - day * 1,
        )
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(prune_older_than_days=14.0),
        )
        assert "Pruned 3 event(s)" in out
        # Recent events survive
        remaining = alert_history.recent_history(
            since_seconds=day * 100, now=now,
        )
        assert len(remaining) == 2

    def test_prune_json_envelope(self, cli, data_dir):
        from core.approval import alert_history
        day = 86400.0
        now = time.time()
        alert_history.record_alerts(
            [_FakeAlert("old")], now=now - day * 50,
        )
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(prune_older_than_days=14.0, json=True),
        )
        data = json.loads(out)
        assert data["status"] == "success"
        assert data["removed_count"] == 1
        assert data["older_than_days"] == 14.0

    def test_prune_zero_does_nothing_to_recent(
        self, cli, data_dir,
    ):
        from core.approval import alert_history
        now = time.time()
        # Only fresh events
        alert_history.record_alerts(
            [_FakeAlert("fresh")], now=now - 100,
        )
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(prune_older_than_days=7.0),
        )
        assert "Pruned 0 event(s)" in out
        remaining = alert_history.recent_history(now=now)
        assert len(remaining) == 1

    def test_prune_invalid_value_errors(self, cli, data_dir):
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(prune_older_than_days=0.0),
        )
        assert "must be positive" in out

    def test_prune_invalid_value_json_envelope(
        self, cli, data_dir,
    ):
        out = _capture(
            cli._cmd_approvals_alert_history,
            _ns(prune_older_than_days=-1.0, json=True),
        )
        data = json.loads(out)
        assert data["status"] == "error"
        assert "must be positive" in data["error"]

    def test_prune_module_failure(self, cli, data_dir):
        with patch(
            "core.approval.alert_history.prune",
            side_effect=OSError("disk full"),
        ):
            out = _capture(
                cli._cmd_approvals_alert_history,
                _ns(prune_older_than_days=14.0),
            )
        assert "Error" in out
        assert "disk full" in out
