"""Tests for engines._spend_cap."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines._spend_cap import (
    CapBreach,
    SpendRollup,
    check_caps,
    daily_cap_usd,
    is_enabled,
    maybe_auto_pause_on_overspend,
    weekly_cap_usd,
)


class TestEnvGates:

    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", raising=False,
        )
        assert is_enabled() is False

    def test_enabled_with_env(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", "1",
        )
        assert is_enabled() is True

    def test_daily_cap_unset(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_SPEND_CAP_DAILY_USD",
                           raising=False)
        assert daily_cap_usd() is None

    def test_daily_cap_parsed(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SPEND_CAP_DAILY_USD", "50.0")
        assert daily_cap_usd() == 50.0

    def test_daily_cap_invalid_returns_none(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SPEND_CAP_DAILY_USD", "junk")
        assert daily_cap_usd() is None

    def test_zero_cap_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SPEND_CAP_DAILY_USD", "0")
        assert daily_cap_usd() is None

    def test_weekly_cap_parsed(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SPEND_CAP_WEEKLY_USD", "200")
        assert weekly_cap_usd() == 200.0


class TestSpendRollup:

    def test_top_spender_empty(self):
        r = SpendRollup(
            store_id="x", window_label="daily",
            window_hours=24.0,
        )
        assert r.top_spender is None

    def test_top_spender_returns_max(self):
        r = SpendRollup(
            store_id="x", window_label="daily",
            window_hours=24.0,
            contributing_engines={
                "loyalty": 50.0,
                "discount_strategy": 200.0,
                "email_marketing": 10.0,
            },
        )
        assert r.top_spender == "discount_strategy"


class TestCheckCaps:

    def test_no_caps_set_returns_empty(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SPEND_CAP_WEEKLY_USD", raising=False,
        )
        assert check_caps() == []

    def test_breach_when_spend_exceeds(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", "50.0",
        )
        with patch(
            "engines._spend_cap.daily_spend",
            return_value=SpendRollup(
                store_id="A", window_label="daily",
                window_hours=24.0, total_spend=120.0,
                contributing_engines={"discount_strategy": 120.0},
            ),
        ):
            breaches = check_caps(store_id="A")
        assert len(breaches) == 1
        b = breaches[0]
        assert b.window_label == "daily"
        assert b.cap_usd == 50.0
        assert b.actual_spend == 120.0
        assert b.over_by == 70.0

    def test_no_breach_when_under(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", "100.0",
        )
        with patch(
            "engines._spend_cap.daily_spend",
            return_value=SpendRollup(
                store_id="A", window_label="daily",
                window_hours=24.0, total_spend=50.0,
            ),
        ):
            breaches = check_caps(store_id="A")
        assert breaches == []

    def test_both_caps_breach(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", "50.0",
        )
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_WEEKLY_USD", "200.0",
        )
        with patch(
            "engines._spend_cap.daily_spend",
            return_value=SpendRollup(
                store_id="A", window_label="daily",
                window_hours=24.0, total_spend=120.0,
            ),
        ), patch(
            "engines._spend_cap.weekly_spend",
            return_value=SpendRollup(
                store_id="A", window_label="weekly",
                window_hours=168.0, total_spend=500.0,
            ),
        ):
            breaches = check_caps(store_id="A")
        assert len(breaches) == 2
        labels = {b.window_label for b in breaches}
        assert labels == {"daily", "weekly"}


class TestMaybeAutoPause:

    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", raising=False,
        )
        assert maybe_auto_pause_on_overspend() == []

    def test_pytest_guard_returns_empty(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", "1",
        )
        # PYTEST_CURRENT_TEST is auto-set under pytest
        assert maybe_auto_pause_on_overspend() == []

    def test_no_breaches_returns_empty(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", "1",
        )
        with patch(
            "engines._spend_cap._is_test_environment",
            return_value=False,
        ), patch(
            "engines._spend_cap.check_caps",
            return_value=[],
        ):
            paused = maybe_auto_pause_on_overspend()
        assert paused == []

    def test_breach_pauses_spend_engines(self, monkeypatch):
        from core.approval import quarantine
        from core.approval.quarantine import QuarantineState
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", "1",
        )
        breach = CapBreach(
            store_id="A", window_label="daily",
            cap_usd=50.0, actual_spend=120.0, over_by=70.0,
            contributing_engines={"discount_strategy": 120.0},
        )
        empty_state = QuarantineState(
            exemptions=frozenset(),
            released=frozenset(),
            alert_paused=frozenset(),
        )
        pause_calls: list[tuple] = []
        with patch(
            "engines._spend_cap._is_test_environment",
            return_value=False,
        ), patch(
            "engines._spend_cap.check_caps",
            return_value=[breach],
        ), patch.object(
            quarantine, "load_state",
            return_value=empty_state,
        ), patch.object(
            quarantine, "add_alert_pause",
            side_effect=lambda engine, store_id=None: (
                pause_calls.append((engine, store_id))
            ),
        ):
            paused = maybe_auto_pause_on_overspend(
                store_id="A",
            )
        # All spend-class engines paused for store A
        assert len(paused) > 0
        assert "discount_strategy" in paused
        assert "email_marketing" in paused
        # Per-store scope honored
        for engine, store_id in pause_calls:
            assert store_id == "A"

    def test_already_paused_engines_skipped(self, monkeypatch):
        from core.approval import quarantine
        from core.approval.quarantine import QuarantineState
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", "1",
        )
        breach = CapBreach(
            store_id="A", window_label="daily",
            cap_usd=50.0, actual_spend=120.0, over_by=70.0,
            contributing_engines={},
        )
        # discount_strategy ALREADY paused for store A
        state = QuarantineState(
            exemptions=frozenset(),
            released=frozenset(),
            alert_paused=frozenset([
                ("discount_strategy", "A"),
            ]),
        )
        with patch(
            "engines._spend_cap._is_test_environment",
            return_value=False,
        ), patch(
            "engines._spend_cap.check_caps",
            return_value=[breach],
        ), patch.object(
            quarantine, "load_state", return_value=state,
        ), patch.object(
            quarantine, "add_alert_pause",
        ) as mock_add:
            paused = maybe_auto_pause_on_overspend(
                store_id="A",
            )
        # discount_strategy NOT in newly_paused
        assert "discount_strategy" not in paused
        # But email_marketing IS (not already paused)
        assert "email_marketing" in paused
