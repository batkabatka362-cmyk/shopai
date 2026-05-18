"""Tests for ``alert_quarantine.find_pause_candidates`` +
``shopai approvals alert-pause-candidates`` CLI.

Dry-run preview of the auto-pause bridge. Mirrors the existing
``alert-release-candidates`` surface but for the OPPOSITE
direction: which engines WOULD be auto-paused if the bridge ran
right now, regardless of whether the env var is set.
"""
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


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _disable_alert_history_test_guard():
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=False,
    ):
        yield


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
        threshold=None, window_days=None, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeAlert:
    def __init__(self, engine):
        self.engine = engine
        self.drop = 0.3
        self.recent_score = 0.4
        self.baseline_score = 0.7


def _seed_days(engine, days, now):
    """Record one firing per distinct day for `days` days
    leading up to `now`."""
    from core.approval import alert_history
    day = 86400.0
    for i in range(days):
        alert_history.record_alerts(
            [_FakeAlert(engine)], now=now - day * (days - i - 1),
        )


# ─── Module behaviour ────────────────────────────────────────


class TestFindPauseCandidatesModule:

    def test_empty_when_no_alerts(self, data_dir):
        from core.approval import alert_quarantine
        assert alert_quarantine.find_pause_candidates() == []

    def test_above_threshold_surfaces(self, data_dir):
        from core.approval import alert_quarantine
        day = 86400.0
        now = 10 * day
        _seed_days("loyalty", 3, now)
        out = alert_quarantine.find_pause_candidates(
            threshold=3, window_seconds=7 * day, now=now,
        )
        assert len(out) == 1
        assert out[0]["engine"] == "loyalty"
        assert out[0]["consecutive_days"] == 3
        assert out[0]["blocked_by"] is None

    def test_below_threshold_excluded(self, data_dir):
        from core.approval import alert_quarantine
        day = 86400.0
        now = 10 * day
        _seed_days("loyalty", 2, now)
        out = alert_quarantine.find_pause_candidates(
            threshold=3, window_seconds=7 * day, now=now,
        )
        assert out == []

    def test_exempt_engine_blocked_label(self, data_dir):
        from core.approval import alert_quarantine, quarantine
        quarantine.exempt_engine("loyalty")
        day = 86400.0
        now = 10 * day
        _seed_days("loyalty", 5, now)
        out = alert_quarantine.find_pause_candidates(
            threshold=3, window_seconds=7 * day, now=now,
        )
        assert len(out) == 1
        assert out[0]["blocked_by"] == "exempt"

    def test_already_paused_blocked_label(self, data_dir):
        from core.approval import alert_quarantine, quarantine
        quarantine.add_alert_pause("loyalty")
        day = 86400.0
        now = 10 * day
        _seed_days("loyalty", 5, now)
        out = alert_quarantine.find_pause_candidates(
            threshold=3, window_seconds=7 * day, now=now,
        )
        assert len(out) == 1
        assert out[0]["blocked_by"] == "already_alert_paused"

    def test_sorted_highest_streak_first(self, data_dir):
        from core.approval import alert_quarantine
        day = 86400.0
        now = 15 * day
        _seed_days("loyalty", 3, now)
        _seed_days("affiliate", 5, now)
        _seed_days("orphan", 4, now)
        out = alert_quarantine.find_pause_candidates(
            threshold=3, window_seconds=10 * day, now=now,
        )
        engines = [c["engine"] for c in out]
        assert engines == ["affiliate", "orphan", "loyalty"]

    def test_works_when_bridge_disabled(
        self, data_dir, monkeypatch,
    ):
        """Critical: even with the env var OFF, this function
        ALWAYS computes -- it's the preview."""
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        from core.approval import alert_quarantine
        day = 86400.0
        now = 10 * day
        _seed_days("loyalty", 3, now)
        out = alert_quarantine.find_pause_candidates(
            threshold=3, window_seconds=7 * day, now=now,
        )
        assert len(out) == 1

    def test_default_threshold_uses_env(
        self, data_dir, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "5")
        from core.approval import alert_quarantine
        day = 86400.0
        now = 10 * day
        # 4 days -- below 5 -- excluded
        _seed_days("loyalty", 4, now)
        out = alert_quarantine.find_pause_candidates(
            window_seconds=7 * day, now=now,
        )
        assert out == []
        # 5 days -- meets threshold
        from core.approval import alert_history
        alert_history.clear()
        _seed_days("loyalty", 5, now)
        out = alert_quarantine.find_pause_candidates(
            window_seconds=7 * day, now=now,
        )
        assert len(out) == 1


# ─── CLI surface ─────────────────────────────────────────────


class TestCLI:

    def test_empty_no_candidates(self, cli, data_dir, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        out = _capture(
            cli._cmd_approvals_alert_pause_candidates, _ns(),
        )
        assert "Alert-pause candidates" in out
        assert "(no engines at or above" in out

    def test_text_render_with_candidates(
        self, cli, data_dir, monkeypatch,
    ):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        day = 86400.0
        now = time.time()
        _seed_days("loyalty", 4, now)
        out = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=3),
        )
        assert "loyalty" in out
        # Bridge-off footer hint
        assert "Bridge is OFF" in out
        assert "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS" in out

    def test_text_render_bridge_on_omits_footer(
        self, cli, data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        day = 86400.0
        now = time.time()
        _seed_days("loyalty", 4, now)
        out = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=3),
        )
        assert "bridge=on" in out
        # No "Bridge is OFF" prompt
        assert "Bridge is OFF" not in out

    def test_json_envelope_shape(self, cli, data_dir):
        day = 86400.0
        now = time.time()
        _seed_days("loyalty", 4, now)
        out = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=3, json=True),
        )
        data = json.loads(out)
        assert "bridge_enabled" in data
        assert "threshold_days" in data
        assert "window_days" in data
        assert "candidates" in data
        assert data["threshold_days"] == 3
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["engine"] == "loyalty"

    def test_threshold_override(self, cli, data_dir):
        day = 86400.0
        now = time.time()
        _seed_days("loyalty", 4, now)
        # threshold=5 -> 4 days not enough
        out = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=5, json=True),
        )
        assert json.loads(out)["candidates"] == []

    def test_window_days_override(self, cli, data_dir):
        """Narrow window shrinks the visible streak."""
        from core.approval import alert_history
        day = 86400.0
        now = time.time()
        _seed_days("loyalty", 5, now)
        # 7-day window: all 5 days visible -> 5d streak
        out_7 = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=3, window_days=7.0, json=True),
        )
        assert json.loads(out_7)["candidates"][0][
            "consecutive_days"
        ] == 5

        # 2-day window: only last 2 days visible -> 2d streak
        # -> below threshold of 3
        out_2 = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=3, window_days=2.0, json=True),
        )
        assert json.loads(out_2)["candidates"] == []

    def test_module_failure_renders_empty(
        self, cli, data_dir,
    ):
        with patch(
            "core.approval.alert_quarantine."
            "find_pause_candidates",
            side_effect=RuntimeError("disk corrupt"),
        ):
            out = _capture(
                cli._cmd_approvals_alert_pause_candidates,
                _ns(),
            )
        assert "(no engines at or above" in out

    def test_blocked_engines_shown_with_label(
        self, cli, data_dir,
    ):
        from core.approval import quarantine
        day = 86400.0
        now = time.time()
        quarantine.exempt_engine("loyalty")
        _seed_days("loyalty", 5, now)
        out = _capture(
            cli._cmd_approvals_alert_pause_candidates,
            _ns(threshold=3, json=True),
        )
        data = json.loads(out)
        assert data["candidates"][0]["blocked_by"] == "exempt"
