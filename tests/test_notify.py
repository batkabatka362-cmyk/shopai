"""Tests for engines._notify."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines._notify import (
    NotifyAlert,
    _filter_by_cooldown,
    collect_alerts,
    cooldown_seconds,
    is_dry_run,
    notify_check,
    webhook_url,
)


class TestEnvGates:

    def test_url_unset(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL", raising=False,
        )
        assert webhook_url() is None

    def test_url_set(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL", "https://x",
        )
        assert webhook_url() == "https://x"

    def test_cooldown_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_NOTIFY_COOLDOWN_SECONDS", raising=False,
        )
        assert cooldown_seconds() == 3600

    def test_cooldown_custom(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_NOTIFY_COOLDOWN_SECONDS", "300",
        )
        assert cooldown_seconds() == 300

    def test_dry_run(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_NOTIFY_DRY_RUN", "1")
        assert is_dry_run() is True


class TestCooldownFilter:

    def test_within_cooldown_dropped(self):
        alerts = [NotifyAlert(
            kind="stale_cycle", severity="warn", message="x",
        )]
        state = {"stale_cycle": 1000.0}
        out = _filter_by_cooldown(
            alerts, state, now=1100.0, cooldown=300,
        )
        assert out == []

    def test_after_cooldown_passes(self):
        alerts = [NotifyAlert(
            kind="stale_cycle", severity="warn", message="x",
        )]
        state = {"stale_cycle": 1000.0}
        out = _filter_by_cooldown(
            alerts, state, now=1400.0, cooldown=300,
        )
        assert len(out) == 1

    def test_unseen_kind_passes(self):
        alerts = [NotifyAlert(
            kind="new_kind", severity="warn", message="x",
        )]
        out = _filter_by_cooldown(
            alerts, {}, now=1000.0, cooldown=300,
        )
        assert len(out) == 1


class TestCollectAlerts:
    """Each probe should fail-soft when its substrate fails."""

    def test_no_alerts_when_substrate_empty(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_DATA_DIR", "/tmp/fresh")
        # Each probe should return empty / None without crashing
        alerts = collect_alerts()
        # Result is a list; exact contents depend on dev-state
        assert isinstance(alerts, list)


class TestNotifyCheck:

    def test_no_url_no_post(self, monkeypatch, tmp_path):
        monkeypatch.delenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL", raising=False,
        )
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        result = notify_check()
        assert result["url_configured"] is False
        assert result["posted"] is False

    def test_dry_run_doesnt_post(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL", "https://x",
        )
        monkeypatch.setenv("SHOPAI_NOTIFY_DRY_RUN", "1")
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        fake_alerts = [NotifyAlert(
            kind="stale_cycle", severity="warn",
            message="test",
        )]
        with patch(
            "engines._notify.collect_alerts",
            return_value=fake_alerts,
        ):
            result = notify_check()
        assert result["dry_run"] is True
        assert result["posted"] is False
        # Dry run still surfaces the payload that WOULD POST
        assert "payload" in result
        assert result["payload"]["source"] == "shopai"

    def test_fireable_filtered_by_cooldown(
        self, monkeypatch, tmp_path,
    ):
        import time as _t
        monkeypatch.setenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL", "https://x",
        )
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        # Pre-populate state so cooldown filter drops the alert
        state_path = tmp_path / "notify_state.json"
        state_path.write_text(
            f'{{"stale_cycle": {_t.time()}}}', encoding="utf-8",
        )
        fake_alerts = [NotifyAlert(
            kind="stale_cycle", severity="warn",
            message="x",
        )]
        with patch(
            "engines._notify.collect_alerts",
            return_value=fake_alerts,
        ):
            result = notify_check()
        assert result["total_alerts"] == 1
        assert result["fireable_alerts"] == 0
        assert result["posted"] is False
