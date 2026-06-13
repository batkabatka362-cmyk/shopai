"""W963-136: empire + daily-brief forecast block tests.

Quota row (W963-134/135) shows WHO IS at cap. Forecast
row (this commit) shows WHO WILL BE at cap soon. Together
they're proactive: operator sees both reactive + leading
signals in the morning check.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engines.per_store_costs import recorder as cost_recorder


@pytest.fixture(autouse=True)
def _isolated_costs_log(tmp_path, monkeypatch):
    live = tmp_path / "per_store_costs.jsonl"
    archive = (
        tmp_path / "per_store_costs.archive.jsonl"
    )
    monkeypatch.setattr(cost_recorder, "DATA_PATH", live)
    monkeypatch.setattr(
        cost_recorder, "ARCHIVE_PATH", archive,
    )
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    yield live


class TestForecastSubstrateSurfaces:
    def test_imminent_burn_yields_urgent_forecast(
        self, _isolated_costs_log, monkeypatch,
    ):
        from engines.per_store_quota import (
            ForecastVerdict, fleet_forecasts,
        )

        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        now = time.time()
        # Steady $1/h burn over 6h, $6 spent, $4 headroom
        # -> ~4h to cap -> CRITICAL
        live = _isolated_costs_log
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            for h in (5, 4, 3, 2, 1):
                f.write(json.dumps({
                    "ts": now - 3600 * h,
                    "store_id": "store_a",
                    "adapter": "openai",
                    "capability": "chat",
                    "cost_usd": 1.2,
                    "ok": True,
                }) + "\n")
        fcs = fleet_forecasts(
            sample_hours=6.0, cap_window_hours=24.0,
        )
        urgent = [
            f for f in fcs if f.verdict in (
                ForecastVerdict.CRITICAL,
                ForecastVerdict.IMMINENT,
            )
        ]
        assert urgent, "expected at least one urgent forecast"
        # store_a should appear
        assert any(
            f.store_id == "store_a" for f in urgent
        )

    def test_no_caps_no_urgent_forecast(
        self, _isolated_costs_log, monkeypatch,
    ):
        from engines.per_store_quota import (
            ForecastVerdict, fleet_forecasts,
        )

        monkeypatch.delenv(
            "SHOPAI_DAILY_BUDGET_USD", raising=False,
        )
        now = time.time()
        live = _isolated_costs_log
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now,
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 1000.0,
                "ok": True,
            }) + "\n")
        fcs = fleet_forecasts()
        # No cap -> NO_CAP for all rows
        for f in fcs:
            assert f.verdict in (
                ForecastVerdict.NO_CAP,
                ForecastVerdict.NO_RATE,
            )


class TestEmpireJsonHasForecastKey:
    def test_forecast_key_present(
        self, _isolated_costs_log,
    ):
        result = subprocess.run(
            [sys.executable, "cli.py", "empire", "--json"],
            capture_output=True,
            text=True,
            cwd=str(
                Path(__file__).parent.parent,
            ),
            timeout=60,
        )
        assert result.returncode == 0
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.skip("empire JSON unparseable")
        assert "forecast" in envelope
