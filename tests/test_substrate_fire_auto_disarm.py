"""Tests for substrate_fire_auto_disarm (W854)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.automation.autonomy_armed import ArmedEntry, ArmedState
from core.automation.payload_discoverer import _DISCOVERERS
from core.automation.substrate_fire_auto_disarm import (
    AutoDisarmDecision,
    AutoDisarmReport,
    maybe_auto_disarm,
    _bridge_enabled,
    _consecutive_days_threshold,
    _window_days,
)


@pytest.fixture(autouse=True)
def _isolate():
    """Lift pytest guards + isolate the armed state."""
    state_ref = {"s": ArmedState()}

    def fake_load():
        return ArmedState(entries=list(state_ref["s"].entries))

    def fake_save(s):
        state_ref["s"] = ArmedState(entries=list(s.entries))

    snapshot = dict(_DISCOVERERS)
    with patch(
        "core.automation.substrate_fire_auto_disarm."
        "_is_test_environment",
        return_value=False,
    ), patch(
        "core.automation.autonomy_armed._load_state",
        side_effect=fake_load,
    ), patch(
        "core.automation.autonomy_armed._save_state",
        side_effect=fake_save,
    ):
        yield state_ref
    _DISCOVERERS.clear()
    _DISCOVERERS.update(snapshot)


class TestEnvKnobs:

    def test_bridge_off_by_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_DISARM_FROM_ALERTS", raising=False,
        )
        assert not _bridge_enabled()

    def test_bridge_on_when_set(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_FROM_ALERTS", "1",
        )
        assert _bridge_enabled()

    def test_threshold_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_DISARM_CONSECUTIVE_DAYS",
            raising=False,
        )
        assert _consecutive_days_threshold() == 3

    def test_window_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_DISARM_WINDOW_DAYS", raising=False,
        )
        assert _window_days() == 7


class TestMaybeAutoDisarm:

    def test_no_armed_no_decisions(self, _isolate):
        with patch(
            "core.automation.substrate_fire_alert_history."
            "consecutive_critical_days",
            return_value=0,
        ):
            r = maybe_auto_disarm()
        assert r.decisions == []
        assert r.disarmed_count == 0

    def test_armed_clean_domain_no_decision(
        self, _isolate, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm
        arm("shipping_alert", reason="test")
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_FROM_ALERTS", "1",
        )
        with patch(
            "core.automation.substrate_fire_alert_history."
            "consecutive_critical_days",
            return_value=1,  # below threshold
        ):
            r = maybe_auto_disarm()
        assert r.decisions == []

    def test_threshold_hit_with_bridge_off(
        self, _isolate, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm, is_armed
        arm("shipping_alert", reason="test")
        monkeypatch.delenv(
            "SHOPAI_AUTO_DISARM_FROM_ALERTS", raising=False,
        )
        with patch(
            "core.automation.substrate_fire_alert_history."
            "consecutive_critical_days",
            return_value=5,
        ):
            r = maybe_auto_disarm()
        # Bridge OFF -> would_disarm=True but not disarmed
        assert r.would_disarm_count == 1
        assert r.disarmed_count == 0
        # Domain still armed
        assert is_armed("shipping_alert")
        # Reason mentions bridge off
        assert "bridge OFF" in r.decisions[0].reason

    def test_threshold_hit_with_bridge_on(
        self, _isolate, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm, is_armed
        arm("shipping_alert", reason="test")
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_FROM_ALERTS", "1",
        )
        with patch(
            "core.automation.substrate_fire_alert_history."
            "consecutive_critical_days",
            return_value=5,
        ):
            r = maybe_auto_disarm()
        assert r.disarmed_count == 1
        # Domain no longer armed
        assert not is_armed("shipping_alert")

    def test_disarm_raise_captured(
        self, _isolate, monkeypatch,
    ):
        from core.automation.autonomy_armed import arm
        arm("shipping_alert", reason="test")
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_FROM_ALERTS", "1",
        )

        def explode(domain):
            raise RuntimeError("boom")

        with patch(
            "core.automation.substrate_fire_alert_history."
            "consecutive_critical_days",
            return_value=5,
        ), patch(
            "core.automation.autonomy_armed.disarm",
            side_effect=explode,
        ):
            r = maybe_auto_disarm()
        assert r.decisions
        assert "disarm raised" in r.decisions[0].reason
        assert not r.decisions[0].disarmed


class TestReportDataclass:

    def test_empty(self):
        r = AutoDisarmReport()
        assert r.disarmed_count == 0
        assert r.would_disarm_count == 0

    def test_aggregates(self):
        r = AutoDisarmReport()
        r.decisions = [
            AutoDisarmDecision(
                domain="a", consecutive_days=5,
                threshold=3, would_disarm=True,
                disarmed=True,
            ),
            AutoDisarmDecision(
                domain="b", consecutive_days=4,
                threshold=3, would_disarm=True,
                disarmed=False,
            ),
        ]
        assert r.disarmed_count == 1
        assert r.would_disarm_count == 2
