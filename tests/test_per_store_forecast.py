"""W963-123: cost-forecast tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engines.per_store_costs import recorder as cost_recorder
from engines.per_store_quota import (
    ForecastSnapshot,
    ForecastVerdict,
    fleet_forecasts,
    forecast_to_cap,
)
from engines.per_store_quota.forecast import _classify


@pytest.fixture(autouse=True)
def _isolated_costs_log(tmp_path, monkeypatch):
    live = tmp_path / "per_store_costs.jsonl"
    archive = tmp_path / "per_store_costs.archive.jsonl"
    monkeypatch.setattr(cost_recorder, "DATA_PATH", live)
    monkeypatch.setattr(
        cost_recorder, "ARCHIVE_PATH", archive,
    )
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    yield live


def _seed(live: Path, events: list[dict]) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    with open(live, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


# ── Verdict classifier ────────────────────────────────────


class TestClassify:
    def test_no_cap_when_zero(self):
        assert _classify(
            cap=0, rate=10, hours_to_cap=99,
            spend_so_far=0,
        ) == ForecastVerdict.NO_CAP

    def test_exhausted_when_spend_exceeds_cap(self):
        assert _classify(
            cap=10, rate=1, hours_to_cap=0.0,
            spend_so_far=15,
        ) == ForecastVerdict.EXHAUSTED

    def test_no_rate_when_zero_rate(self):
        assert _classify(
            cap=10, rate=0, hours_to_cap=float("inf"),
            spend_so_far=5,
        ) == ForecastVerdict.NO_RATE

    def test_critical_when_under_4_hours(self):
        assert _classify(
            cap=10, rate=1, hours_to_cap=2.0,
            spend_so_far=5,
        ) == ForecastVerdict.CRITICAL

    def test_imminent_when_under_48_hours(self):
        assert _classify(
            cap=10, rate=1, hours_to_cap=20.0,
            spend_so_far=5,
        ) == ForecastVerdict.IMMINENT

    def test_no_risk_when_far_out(self):
        assert _classify(
            cap=10, rate=1, hours_to_cap=100.0,
            spend_so_far=5,
        ) == ForecastVerdict.NO_RISK

    def test_severity_rank_exhausted_highest(self):
        ranks = {
            v: v.severity_rank for v in ForecastVerdict
        }
        assert (
            ranks[ForecastVerdict.EXHAUSTED]
            > ranks[ForecastVerdict.CRITICAL]
            > ranks[ForecastVerdict.IMMINENT]
        )


# ── forecast_to_cap ───────────────────────────────────────


class TestForecastToCap:
    def test_no_cap_returns_no_cap_verdict(
        self, _isolated_costs_log, monkeypatch,
    ):
        for v in (
            "SHOPAI_DAILY_BUDGET_USD",
            "OPENAI_DAILY_BUDGET_USD",
            "SHOPAI_STORE_STORE_A_DAILY_BUDGET_USD",
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
        ):
            monkeypatch.delenv(v, raising=False)
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 5.0, "ok": True,
        }])
        snap = forecast_to_cap(
            "store_a", adapter="openai",
        )
        assert snap.verdict == ForecastVerdict.NO_CAP

    def test_exhausted_when_over_cap(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.0, "ok": True,
        }])
        snap = forecast_to_cap(
            "store_a", adapter="openai",
        )
        assert snap.verdict == ForecastVerdict.EXHAUSTED
        assert snap.headroom_usd == 0.0
        assert snap.hours_to_cap == 0.0

    def test_critical_at_high_rate(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Recent 6h burned $4 of $5 cap; rate is
        ~$0.67/h; headroom $1 -> hours_to_cap ~1.5."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        now = time.time()
        _seed(_isolated_costs_log, [
            {
                "ts": now - 60, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 4.0, "ok": True,
            },
        ])
        snap = forecast_to_cap(
            "store_a", adapter="openai",
            sample_hours=6.0,
        )
        assert snap.verdict == ForecastVerdict.CRITICAL
        # Spend so far is $4 over a 24h cap window
        assert snap.spend_so_far_usd == 4.0
        # Headroom $1
        assert snap.headroom_usd == 1.0
        # Rate from 6h sample: $4 / 6 = $0.667
        assert snap.rate_per_hour_usd > 0
        assert snap.hours_to_cap < 4.0

    def test_no_rate_when_no_recent_activity(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Old spend (outside sample window) but no recent
        rate."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        old = time.time() - 20 * 3600.0
        _seed(_isolated_costs_log, [{
            "ts": old, "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 1.0, "ok": True,
        }])
        snap = forecast_to_cap(
            "store_a", adapter="openai",
            sample_hours=6.0,
        )
        assert snap.verdict == ForecastVerdict.NO_RATE
        # spend_so_far = 1.0 (within 24h cap window)
        # rate = 0 (within 6h sample window)
        assert snap.spend_so_far_usd == 1.0
        assert snap.rate_per_hour_usd == 0.0

    def test_imminent_when_hours_in_range(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Spent $2 of $10 cap recently; rate enough to
        hit cap in ~24h (well within imminent range)."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time() - 1800,
            "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 2.0, "ok": True,
        }])
        snap = forecast_to_cap(
            "store_a", adapter="openai",
            sample_hours=6.0,
        )
        # rate = 2/6 = 0.33/h, headroom = 8, h_to_cap = 24h
        assert snap.verdict == ForecastVerdict.IMMINENT
        assert 20 < snap.hours_to_cap < 28

    def test_no_risk_when_slow_burn(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Very slow burn -- weeks away from cap."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "1000",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time() - 1800,
            "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 1.0, "ok": True,
        }])
        snap = forecast_to_cap(
            "store_a", adapter="openai",
            sample_hours=6.0,
        )
        # rate ~$0.17/h; cap $1000; hours_to_cap >> 48
        assert snap.verdict == ForecastVerdict.NO_RISK

    def test_hours_to_cap_capped_at_9999(
        self, _isolated_costs_log, monkeypatch,
    ):
        """When rate is 0 but cap is set, hours_to_cap
        is infinity -- serialised as 9999 for JSON."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        # no events
        snap = forecast_to_cap(
            "store_a", adapter="openai",
        )
        assert snap.hours_to_cap == 9999.0
        assert snap.verdict == ForecastVerdict.NO_RATE


# ── fleet_forecasts ───────────────────────────────────────


class TestFleetForecasts:
    def test_exhausted_sorts_first(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_OPENAI_DAILY_BUDGET_USD",
            "100",
        )
        now = time.time()
        _seed(_isolated_costs_log, [
            {
                "ts": now, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 100.0, "ok": True,
            },
            {
                "ts": now, "store_id": "store_b",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 1.0, "ok": True,
            },
        ])
        forecasts = fleet_forecasts()
        # Exhausted store_a sorts first
        assert forecasts[0].store_id == "store_a"
        assert forecasts[0].verdict == (
            ForecastVerdict.EXHAUSTED
        )

    def test_fleet_pseudo_store_excluded(
        self, _isolated_costs_log,
    ):
        """Events without store_id ('(fleet)') excluded
        from per-store forecasts."""
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 1.0, "ok": True,
        }])
        forecasts = fleet_forecasts()
        assert all(
            f.store_id != "(fleet)" for f in forecasts
        )

    def test_empty_log_returns_empty(
        self, _isolated_costs_log,
    ):
        assert fleet_forecasts() == []
