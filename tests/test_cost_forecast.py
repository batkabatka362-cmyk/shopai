"""Tests for the per-caller cost forecaster — Upgrade 3.

The forecaster builds on CostLedger but stays separate so the
ledger's hot path isn't slowed. These tests cover:

* Construction validation — bad args raise
* ``sample()`` pulls from the ledger, handles missing deps
* Forecasts below ``min_samples`` return empty
* Linear extrapolation: current + burn_rate × horizon
* Negative burn (ledger reset) is clamped to 0
* Spike detection: short-window burn >= spike_ratio × long-window
* Caller filter restricts output
* Spike ratio of 1.0 when there's no baseline
* ``snapshot`` reports counters
* Singleton + reset_cost_forecaster lifecycle
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from core.adapters.cost_forecast import (
    CostForecaster,
    get_cost_forecaster,
    reset_cost_forecaster,
)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _mock_ledger(total: float, callers: list[dict]):
    """Return a mock CostLedger with given totals + per-caller rows."""
    ledger = MagicMock()
    ledger.total_usd.return_value = total
    ledger.per_caller.return_value = callers
    return ledger


class TestValidation:
    def test_bad_max_samples(self):
        with pytest.raises(ValueError):
            CostForecaster(max_samples=1)

    def test_bad_window_sec(self):
        with pytest.raises(ValueError):
            CostForecaster(window_sec=0)

    def test_bad_min_samples(self):
        with pytest.raises(ValueError):
            CostForecaster(min_samples=1)

    def test_forecast_bad_horizon(self):
        f = CostForecaster()
        with pytest.raises(ValueError):
            f.forecast(horizon_hours=0)


class TestSample:
    def test_sample_records_from_ledger(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=10.0,
            callers=[{"caller": "brain", "total_usd": 10.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            assert f.sample() is True
        snap = f.snapshot()
        assert snap["samples"] == 1
        assert snap["newest_ts"] == clock.now

    def test_sample_ledger_import_failure(self):
        f = CostForecaster()
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger"
        ) as gcl:
            gcl.side_effect = ImportError("no ledger")
            assert f.sample() is False
        assert f.snapshot()["sample_failures"] == 1

    def test_sample_ledger_read_failure(self):
        f = CostForecaster()
        led = MagicMock()
        led.total_usd.side_effect = RuntimeError("boom")
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            assert f.sample() is False
        assert f.snapshot()["sample_failures"] == 1

    def test_sample_skips_invalid_rows(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=10.0,
            callers=[
                {"caller": "", "total_usd": 1.0},       # empty caller
                {"caller": "brain", "total_usd": "bad"},  # bad usd
                {"caller": "controller", "total_usd": 5.0},
            ],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        clock.advance(3600)
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=1)
        names = [c.caller for c in report.per_caller]
        assert "controller" in names
        assert "brain" not in names  # bad usd row was skipped


class TestForecast:
    def test_insufficient_samples_returns_empty(self):
        f = CostForecaster()
        report = f.forecast(horizon_hours=1)
        assert report.samples == 0
        assert report.per_caller == []

    def test_linear_extrapolation(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=10.0,
            callers=[{"caller": "brain", "total_usd": 10.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        clock.advance(3600)  # +1 hour
        led.total_usd.return_value = 20.0
        led.per_caller.return_value = [
            {"caller": "brain", "total_usd": 20.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=24)
        assert len(report.per_caller) == 1
        cf = report.per_caller[0]
        assert cf.caller == "brain"
        assert cf.current_usd == pytest.approx(20.0)
        assert cf.burn_rate_usd_per_hour == pytest.approx(10.0)
        # Projection: current (20) + burn (10) × 24 = 260
        assert cf.projected_usd == pytest.approx(260.0)

    def test_negative_burn_clamped_to_zero(self):
        """Ledger reset or caller folded into overflow may cause
        the per-caller total to drop between samples. The forecaster
        must clamp the burn rate to 0, not project into the past."""
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=100.0,
            callers=[{"caller": "brain", "total_usd": 100.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        clock.advance(3600)
        led.total_usd.return_value = 50.0
        led.per_caller.return_value = [
            {"caller": "brain", "total_usd": 50.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=24)
        cf = report.per_caller[0]
        assert cf.burn_rate_usd_per_hour == 0.0
        assert cf.projected_usd == pytest.approx(50.0)

    def test_sorted_by_projected_descending(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=0.0,
            callers=[
                {"caller": "brain", "total_usd": 0.0},
                {"caller": "ui", "total_usd": 0.0},
            ],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        clock.advance(3600)
        led.total_usd.return_value = 30.0
        led.per_caller.return_value = [
            {"caller": "brain", "total_usd": 1.0},
            {"caller": "ui", "total_usd": 29.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=1)
        assert report.per_caller[0].caller == "ui"
        assert report.per_caller[1].caller == "brain"

    def test_caller_filter_restricts(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=0.0,
            callers=[
                {"caller": "brain", "total_usd": 0.0},
                {"caller": "ui", "total_usd": 0.0},
            ],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        clock.advance(3600)
        led.per_caller.return_value = [
            {"caller": "brain", "total_usd": 1.0},
            {"caller": "ui", "total_usd": 1.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=1, callers=["brain"])
        assert [c.caller for c in report.per_caller] == ["brain"]


class TestSpikeDetection:
    def test_spike_when_short_window_burn_exceeds_long(self):
        """Three samples over 3h: flat for 2h, then doubled for 1h.
        Short window should show a much higher burn rate than
        the long baseline → spike."""
        clock = FakeClock()
        # Narrow window_sec so only the last sample pair is used
        # for short burn; the full history remains the long baseline.
        f = CostForecaster(clock=clock, window_sec=3700, spike_ratio=1.5)
        led = _mock_ledger(
            total=0.0,
            callers=[{"caller": "brain", "total_usd": 0.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        # 1h later: +$1
        clock.advance(3600)
        led.per_caller.return_value = [
            {"caller": "brain", "total_usd": 1.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        # 2h later: +$10 (spike)
        clock.advance(3600)
        led.per_caller.return_value = [
            {"caller": "brain", "total_usd": 11.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=1)
        cf = report.per_caller[0]
        # short burn ≈ $10/hr (last hour), long burn ≈ $5.5/hr (2h avg)
        assert cf.spike_ratio > 1.5
        assert cf.is_spike is True
        assert "brain" in report.spikes

    def test_no_spike_when_rates_match(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock, spike_ratio=2.0)
        led = _mock_ledger(
            total=0.0,
            callers=[{"caller": "brain", "total_usd": 0.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        for i in range(1, 4):
            clock.advance(3600)
            led.per_caller.return_value = [
                {"caller": "brain", "total_usd": float(i)},
            ]
            with patch(
                "core.adapters.cost_ledger.get_cost_ledger",
                return_value=led,
            ):
                f.sample()
        report = f.forecast(horizon_hours=1)
        cf = report.per_caller[0]
        # Constant $1/hr → ratio ≈ 1.0
        assert cf.is_spike is False
        assert report.spikes == []


class TestNoFalseSpikeOnNewCaller:
    """Self-critique fix: a caller that appears mid-stream used to
    look like an infinite spike because the first absolute sample
    had them at $0 by definition. The long-burn baseline must
    anchor on the caller's FIRST APPEARANCE, and the short/long
    coverage ratio must exceed 2× before a spike can fire."""

    def test_new_caller_no_spike_when_short_equals_long(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock, spike_ratio=2.0)
        # Sample 1: only 'legacy' is present.
        led = _mock_ledger(
            total=0.0,
            callers=[{"caller": "legacy", "total_usd": 0.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        # Sample 2 (1h later): a NEW caller joins.
        clock.advance(3600)
        led.per_caller.return_value = [
            {"caller": "legacy", "total_usd": 1.0},
            {"caller": "newbie", "total_usd": 5.0},
        ]
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        report = f.forecast(horizon_hours=1)
        # newbie must NOT be flagged as a spike — there's no
        # baseline yet.
        newbie = next(c for c in report.per_caller if c.caller == "newbie")
        assert newbie.is_spike is False
        assert newbie.spike_ratio == 1.0
        assert "newbie" not in report.spikes


class TestSnapshot:
    def test_snapshot_reports_state(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        snap = f.snapshot()
        assert snap["samples"] == 0
        assert snap["sample_failures"] == 0
        assert snap["window_sec"] == 3600.0

    def test_reset_clears_state(self):
        clock = FakeClock()
        f = CostForecaster(clock=clock)
        led = _mock_ledger(
            total=0.0,
            callers=[{"caller": "brain", "total_usd": 0.0}],
        )
        with patch(
            "core.adapters.cost_ledger.get_cost_ledger",
            return_value=led,
        ):
            f.sample()
        assert f.snapshot()["samples"] == 1
        f.reset()
        assert f.snapshot()["samples"] == 0


class TestSingleton:
    def test_singleton_persists(self):
        reset_cost_forecaster()
        f1 = get_cost_forecaster()
        f2 = get_cost_forecaster()
        assert f1 is f2

    def test_reset_clears_singleton(self):
        f1 = get_cost_forecaster()
        reset_cost_forecaster()
        f2 = get_cost_forecaster()
        assert f1 is not f2
