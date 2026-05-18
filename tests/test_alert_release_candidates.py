"""Tests for ``alert_quarantine.find_release_candidates`` +
``shopai approvals alert-release-candidates`` CLI.

Sister surface to ``quarantine-release-candidates`` (which is
outcome-based). This one is alert-based: alert-paused engines
whose degradation alerts have gone quiet are safe-to-release
candidates.
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
    defaults = dict(quiet_days=None, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeAlert:
    def __init__(self, engine):
        self.engine = engine
        self.drop = 0.3
        self.recent_score = 0.4
        self.baseline_score = 0.7


# ─── Module behaviour ────────────────────────────────────────


class TestFindReleaseCandidatesModule:

    def test_empty_when_nothing_paused(self, data_dir):
        from core.approval import alert_quarantine
        assert alert_quarantine.find_release_candidates() == []

    def test_paused_engine_with_no_history_is_candidate(
        self, data_dir,
    ):
        """An engine paused before alert_history was written
        (or after a clear) has no events to check -- still a
        valid release candidate."""
        from core.approval import quarantine, alert_quarantine
        quarantine.add_alert_pause("loyalty")
        out = alert_quarantine.find_release_candidates(
            quiet_days=7.0, now=1000.0,
        )
        assert len(out) == 1
        assert out[0]["engine"] == "loyalty"
        assert out[0]["days_since_last_alert"] is None
        assert out[0]["last_alert_at"] is None

    def test_recently_fired_engine_excluded(self, data_dir):
        """Paused engine that fired within the quiet window
        is NOT a candidate."""
        from core.approval import (
            quarantine, alert_quarantine, alert_history,
        )
        day = 86400.0
        now = 10 * day
        quarantine.add_alert_pause("loyalty")
        # Fired 1 day ago -- well within the 7-day quiet window
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day,
        )
        out = alert_quarantine.find_release_candidates(
            quiet_days=7.0, now=now,
        )
        assert out == []

    def test_old_event_outside_window_is_candidate(
        self, data_dir,
    ):
        """Paused engine that fired 10 days ago (outside the
        7-day quiet window) IS a candidate."""
        from core.approval import (
            quarantine, alert_quarantine, alert_history,
        )
        day = 86400.0
        now = 20 * day
        quarantine.add_alert_pause("loyalty")
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 10,
        )
        out = alert_quarantine.find_release_candidates(
            quiet_days=7.0, now=now,
        )
        assert len(out) == 1
        assert out[0]["engine"] == "loyalty"
        assert 9.5 < out[0]["days_since_last_alert"] < 10.5

    def test_engines_without_pause_ignored(self, data_dir):
        """Even with old alert history, an engine NOT in
        alert_paused isn't a candidate (nothing to release)."""
        from core.approval import (
            alert_quarantine, alert_history,
        )
        day = 86400.0
        now = 10 * day
        alert_history.record_alerts(
            [_FakeAlert("affiliate")], now=now - day * 100,
        )
        out = alert_quarantine.find_release_candidates(
            quiet_days=7.0, now=now,
        )
        assert out == []

    def test_sorted_longest_quiet_first(self, data_dir):
        from core.approval import (
            quarantine, alert_quarantine, alert_history,
        )
        day = 86400.0
        now = 30 * day
        quarantine.add_alert_pause("loyalty")
        quarantine.add_alert_pause("affiliate")
        quarantine.add_alert_pause("orphan")
        # loyalty fired 15 days ago, affiliate fired 25 days ago,
        # orphan has no history.
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 15,
        )
        alert_history.record_alerts(
            [_FakeAlert("affiliate")], now=now - day * 25,
        )
        out = alert_quarantine.find_release_candidates(
            quiet_days=7.0, now=now,
        )
        engines = [c["engine"] for c in out]
        # orphan first (None = max), then affiliate (25d), then
        # loyalty (15d)
        assert engines == ["orphan", "affiliate", "loyalty"]

    def test_default_quiet_uses_window_days(self, data_dir):
        from core.approval import alert_quarantine
        # No quiet_days arg -- defaults to window_days() = 7
        with patch.object(
            alert_quarantine, "window_days", return_value=14,
        ):
            from core.approval import quarantine, alert_history
            day = 86400.0
            now = 20 * day
            quarantine.add_alert_pause("loyalty")
            # Fired 10 days ago -- within the 14-day default
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=now - day * 10,
            )
            out = alert_quarantine.find_release_candidates(now=now)
        assert out == []


# ─── CLI surface ─────────────────────────────────────────────


class TestCLI:

    def test_empty_no_candidates(self, cli, data_dir):
        out = _capture(
            cli._cmd_approvals_alert_release_candidates, _ns(),
        )
        assert "No alert-release candidates" in out

    def test_populated_text_render(self, cli, data_dir):
        from core.approval import quarantine, alert_history
        day = 86400.0
        now = time.time()
        quarantine.add_alert_pause("loyalty")
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 15,
        )
        out = _capture(
            cli._cmd_approvals_alert_release_candidates,
            _ns(quiet_days=7.0),
        )
        assert "Alert-release candidates" in out
        assert "loyalty" in out
        assert "release-alert" in out  # remediation hint

    def test_populated_json_render(self, cli, data_dir):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        out = _capture(
            cli._cmd_approvals_alert_release_candidates,
            _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["engine"] == "loyalty"
        # No history -> days_since_last_alert is None
        assert data[0]["days_since_last_alert"] is None

    def test_quiet_days_override(self, cli, data_dir):
        """Custom --quiet-days narrows the silence window."""
        from core.approval import quarantine, alert_history
        day = 86400.0
        now = time.time()
        quarantine.add_alert_pause("loyalty")
        # Fired 5 days ago
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=now - day * 5,
        )
        # 3-day quiet window -- 5d ago is outside, so candidate
        out_3d = _capture(
            cli._cmd_approvals_alert_release_candidates,
            _ns(quiet_days=3.0, json=True),
        )
        assert json.loads(out_3d)[0]["engine"] == "loyalty"

        # 10-day quiet window -- 5d ago is INSIDE, so excluded
        out_10d = _capture(
            cli._cmd_approvals_alert_release_candidates,
            _ns(quiet_days=10.0, json=True),
        )
        assert json.loads(out_10d) == []

    def test_module_failure_renders_empty(self, cli, data_dir):
        with patch(
            "core.approval.alert_quarantine.find_release_candidates",
            side_effect=RuntimeError("disk corrupt"),
        ):
            out = _capture(
                cli._cmd_approvals_alert_release_candidates,
                _ns(),
            )
        assert "No alert-release candidates" in out
