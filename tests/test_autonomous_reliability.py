"""Tests for the autonomous reliability signal collector — Option E.

The collector folds four adapter-layer telemetry streams into one
JSON-safe dict the controller embeds on ``cycle_result`` every
tick. These tests exercise:

* Empty-state — nothing registered, no crashes
* Delta accounting — deadletter/cost deltas are computed vs. the
  previous call, not the absolute cumulative total
* Alert thresholds — unhealthy adapters / new dead-letter entries
  / cost spikes each trigger the correct alert string
* Env-var overrides — thresholds can be tuned without code changes
* Defensive paths — a failing collector returns an empty rollup
  with an ``error`` key instead of crashing the cycle
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.autonomous.reliability import (
    collect_reliability_signal,
    reset_reliability_state,
)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_reliability_state()
    yield
    reset_reliability_state()


class TestEmpty:
    def test_empty_snapshot(self):
        """With every source mocked empty, the signal is
        structurally well-formed and contains no alerts.
        We mock the collectors explicitly rather than trusting
        the ambient process state because earlier tests in the
        suite may leave SLA / breaker counters populated."""
        import core.autonomous.reliability as mod
        with patch.object(mod, "_collect_health") as ch, \
             patch.object(mod, "_collect_deadletter") as cdl, \
             patch.object(mod, "_collect_cost") as cc:
            ch.return_value = {
                "totals": {}, "unhealthy": [], "degraded": [],
            }
            cdl.return_value = {
                "size": 0, "total_records": 0,
                "new_since_last": 0, "per_adapter": {},
                "write_failures": 0,
            }
            cc.return_value = {
                "total_usd": 0.0, "delta_usd": 0.0,
                "top_caller": "", "caller_count": 0,
            }
            signal = mod.collect_reliability_signal()
        assert "health" in signal
        assert "deadletter" in signal
        assert "cost" in signal
        assert signal["alerts"] == []
        assert signal["health"]["unhealthy"] == []
        assert signal["cost"]["total_usd"] == 0.0

    def test_timestamp_set(self):
        signal = collect_reliability_signal()
        assert signal["timestamp"] > 0


class TestDeltaAccounting:
    def test_deadletter_new_since_last_first_call(self):
        # First call primes the baseline silently — delta is 0
        # even if the ledger already has entries, so a process
        # that starts up with a populated ledger doesn't fire
        # a false "N new entries!" alert on cycle 1.
        with patch(
            "core.adapters.deadletter.get_dead_letter_ledger"
        ) as gdl:
            gdl.return_value.snapshot.return_value = {
                "size": 3, "total_records": 5, "write_failures": 0,
            }
            signal = collect_reliability_signal()
        assert signal["deadletter"]["total_records"] == 5
        assert signal["deadletter"]["new_since_last"] == 0

    def test_deadletter_delta_between_calls(self):
        with patch(
            "core.adapters.deadletter.get_dead_letter_ledger"
        ) as gdl:
            gdl.return_value.snapshot.return_value = {
                "size": 3, "total_records": 5, "write_failures": 0,
            }
            collect_reliability_signal()  # baseline = 5
            gdl.return_value.snapshot.return_value = {
                "size": 5, "total_records": 7, "write_failures": 0,
            }
            signal = collect_reliability_signal()
        assert signal["deadletter"]["new_since_last"] == 2

    def test_cost_delta_between_calls(self):
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger"
        ) as gcl:
            ledger = gcl.return_value
            ledger.total_usd.return_value = 1.5
            ledger.per_caller.return_value = [
                {"caller": "brain", "total_usd": 1.5, "calls": 3},
            ]
            signal0 = collect_reliability_signal()  # primes + baseline
            assert signal0["cost"]["delta_usd"] == 0.0
            ledger.total_usd.return_value = 2.25
            signal = collect_reliability_signal()
        assert signal["cost"]["delta_usd"] == pytest.approx(0.75)
        assert signal["cost"]["top_caller"] == "brain"

    def test_first_call_no_cost_spike_alert(self, monkeypatch):
        """A process that starts with an already-populated cost
        ledger must NOT fire a cost-spike alert on cycle 1 for
        spend that happened before the controller even booted."""
        monkeypatch.setenv("SHOPAI_RELIABILITY_COST_SPIKE_USD", "0.50")
        import importlib
        import core.autonomous.reliability as mod
        importlib.reload(mod)

        with patch(
            "core.adapters.cost_ledger.get_cost_ledger"
        ) as gcl:
            ledger = gcl.return_value
            ledger.total_usd.return_value = 100.0
            ledger.per_caller.return_value = [
                {"caller": "startup", "total_usd": 100.0, "calls": 1},
            ]
            signal = mod.collect_reliability_signal()
        assert not any("cost spike" in a for a in signal["alerts"])


class TestAlerts:
    def test_unhealthy_alert(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_RELIABILITY_UNHEALTHY_AT", "1")
        # Reload module to pick up env override
        import importlib
        import core.autonomous.reliability as mod
        importlib.reload(mod)
        from core.autonomous.reliability import (
            collect_reliability_signal,
            reset_reliability_state,
        )
        reset_reliability_state()

        with patch.object(mod, "_collect_health") as ch:
            ch.return_value = {
                "totals": {"unhealthy": 2, "degraded": 0,
                           "healthy": 3, "unknown": 0},
                "unhealthy": ["brave", "shopify_risk"],
                "degraded": [],
            }
            signal = collect_reliability_signal()
        assert len(signal["alerts"]) == 1
        assert "unhealthy" in signal["alerts"][0]
        assert "brave" in signal["alerts"][0]

    def test_deadletter_alert(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_RELIABILITY_DEADLETTER_AT", "1")
        import importlib
        import core.autonomous.reliability as mod
        importlib.reload(mod)

        with patch.object(mod, "_collect_deadletter") as cdl:
            cdl.return_value = {
                "size": 1, "total_records": 1,
                "new_since_last": 3, "per_adapter": {},
                "write_failures": 0,
            }
            signal = mod.collect_reliability_signal()
        assert any("dead-letter" in a for a in signal["alerts"])

    def test_cost_spike_alert(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_RELIABILITY_COST_SPIKE_USD", "0.50")
        import importlib
        import core.autonomous.reliability as mod
        importlib.reload(mod)

        with patch.object(mod, "_collect_cost") as cc:
            cc.return_value = {
                "total_usd": 10.0, "delta_usd": 0.75,
                "top_caller": "controller", "caller_count": 1,
            }
            signal = mod.collect_reliability_signal()
        assert any("cost spike" in a for a in signal["alerts"])
        assert any("controller" in a for a in signal["alerts"])

    def test_no_alerts_below_threshold(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_RELIABILITY_UNHEALTHY_AT", "5")
        monkeypatch.setenv("SHOPAI_RELIABILITY_DEADLETTER_AT", "5")
        monkeypatch.setenv("SHOPAI_RELIABILITY_COST_SPIKE_USD", "100")
        import importlib
        import core.autonomous.reliability as mod
        importlib.reload(mod)

        with patch.object(mod, "_collect_health") as ch, \
             patch.object(mod, "_collect_deadletter") as cdl, \
             patch.object(mod, "_collect_cost") as cc:
            ch.return_value = {
                "totals": {}, "unhealthy": ["one"], "degraded": [],
            }
            cdl.return_value = {
                "size": 0, "total_records": 1,
                "new_since_last": 1, "per_adapter": {},
                "write_failures": 0,
            }
            cc.return_value = {
                "total_usd": 0.0, "delta_usd": 0.1,
                "top_caller": "", "caller_count": 0,
            }
            signal = mod.collect_reliability_signal()
        assert signal["alerts"] == []


class TestDefensive:
    def test_deadletter_snapshot_failure_returns_empty(self):
        with patch(
            "core.adapters.deadletter.get_dead_letter_ledger"
        ) as gdl:
            gdl.return_value.snapshot.side_effect = RuntimeError("boom")
            signal = collect_reliability_signal()
        assert signal["deadletter"]["total_records"] == 0
        assert "error" in signal["deadletter"]

    def test_cost_ledger_failure_returns_empty(self):
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger"
        ) as gcl:
            gcl.return_value.total_usd.side_effect = RuntimeError("boom")
            signal = collect_reliability_signal()
        assert signal["cost"]["total_usd"] == 0.0
        assert "error" in signal["cost"]


class TestState:
    def test_reset_reliability_state(self):
        from core.autonomous.reliability import (
            _STATE, reset_reliability_state,
        )
        _STATE.last_deadletter_total = 42
        _STATE.last_cost_total_usd = 1.23
        reset_reliability_state()
        assert _STATE.last_deadletter_total == 0
        assert _STATE.last_cost_total_usd == 0.0
