"""W963-121: per-store P&L tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engines.per_store_costs import recorder as cost_recorder
from engines.per_store_pnl import (
    PerStorePnLEngine,
    PnLState,
    StorePnLSnapshot,
    compute_fleet_snapshot,
    compute_snapshot,
)
from engines.per_store_pnl.snapshot import _classify


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


def _stub_attribution(
    *, total_revenue: float = 0.0,
    attributed: float = 0.0,
):
    """Make attribute_revenue return a fake report."""
    fake_report = MagicMock()
    fake_report.total_revenue_in_window = total_revenue
    fake_report.attributed_revenue = attributed
    return patch(
        "engines._revenue_attribution.attribute_revenue",
        return_value=fake_report,
    )


# ── State classifier ──────────────────────────────────────


class TestClassify:
    def test_cold_when_both_zero(self):
        assert _classify(0.0, 0.0) == PnLState.COLD

    def test_losing_when_revenue_below_spend(self):
        assert _classify(5.0, 10.0) == PnLState.LOSING

    def test_thriving_when_revenue_no_spend(self):
        assert _classify(100.0, 0.0) == PnLState.THRIVING

    def test_thriving_at_66pct_margin(self):
        # 100 revenue, 33 spend -> 67% margin
        assert _classify(100.0, 33.0) == PnLState.THRIVING

    def test_healthy_band(self):
        # 100 revenue, 50 spend -> 50% margin
        assert _classify(100.0, 50.0) == PnLState.HEALTHY

    def test_breakeven_band(self):
        # 100 revenue, 90 spend -> 10% margin
        assert _classify(100.0, 90.0) == PnLState.BREAKEVEN

    def test_severity_rank_losing_highest(self):
        ranks = {
            s: s.severity_rank for s in PnLState
        }
        # Losing must be the WORST
        assert (
            ranks[PnLState.LOSING]
            > ranks[PnLState.BREAKEVEN]
            > ranks[PnLState.COLD]
            > ranks[PnLState.HEALTHY]
            > ranks[PnLState.THRIVING]
        )


# ── compute_snapshot ──────────────────────────────────────


class TestComputeSnapshot:
    def test_cold_store(self, _isolated_costs_log):
        """No cost data + no revenue -> COLD."""
        with _stub_attribution(
            total_revenue=0.0, attributed=0.0,
        ):
            snap = compute_snapshot(
                "store_a", window_hours=24.0,
            )
        assert snap.state == PnLState.COLD
        assert snap.spend_usd == 0.0
        assert snap.revenue_usd == 0.0

    def test_losing_store(
        self, _isolated_costs_log,
    ):
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 10.0, "ok": True,
        }])
        with _stub_attribution(
            total_revenue=5.0, attributed=5.0,
        ):
            snap = compute_snapshot(
                "store_a", window_hours=24.0,
            )
        assert snap.state == PnLState.LOSING
        assert snap.spend_usd == 10.0
        assert snap.revenue_usd == 5.0
        assert snap.profit_usd == -5.0

    def test_thriving_store(
        self, _isolated_costs_log,
    ):
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 1.0, "ok": True,
        }])
        with _stub_attribution(
            total_revenue=100.0, attributed=80.0,
        ):
            snap = compute_snapshot(
                "store_a", window_hours=24.0,
            )
        assert snap.state == PnLState.THRIVING
        assert snap.roas_ratio == 100.0
        assert snap.attributed_revenue_usd == 80.0

    def test_roas_capped_at_9999_when_no_spend(
        self, _isolated_costs_log,
    ):
        """Revenue with zero spend -> roas should be
        capped at 9999 (not infinity) so JSON serialises
        cleanly."""
        with _stub_attribution(
            total_revenue=100.0, attributed=80.0,
        ):
            snap = compute_snapshot(
                "store_a", window_hours=24.0,
            )
        assert snap.roas_ratio == 9999.0
        assert snap.state == PnLState.THRIVING

    def test_attribution_unavailable_fallback(
        self, _isolated_costs_log,
    ):
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 1.0, "ok": True,
        }])
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=RuntimeError(
                "test: attribution down",
            ),
        ):
            snap = compute_snapshot(
                "store_a", window_hours=24.0,
            )
        # Spend recorded; revenue 0 due to attribution
        # error; flagged in notes + has_revenue_data
        assert snap.has_revenue_data is False
        assert snap.revenue_usd == 0.0
        assert any(
            "attribution unavailable" in n
            for n in snap.notes
        )

    def test_thriving_with_zero_spend_note(
        self, _isolated_costs_log,
    ):
        with _stub_attribution(
            total_revenue=100.0, attributed=0.0,
        ):
            snap = compute_snapshot(
                "store_a", window_hours=24.0,
            )
        assert snap.state == PnLState.THRIVING
        assert any(
            "zero measured spend" in n
            for n in snap.notes
        )


# ── compute_fleet_snapshot ────────────────────────────────


class TestComputeFleetSnapshot:
    def test_no_stores_returns_empty(
        self, _isolated_costs_log,
    ):
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            snaps = compute_fleet_snapshot()
        assert snaps == []

    def test_losing_sorts_first(
        self, _isolated_costs_log,
    ):
        _seed(_isolated_costs_log, [
            {
                "ts": time.time(), "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 10.0, "ok": True,
            },
            {
                "ts": time.time(), "store_id": "store_b",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 1.0, "ok": True,
            },
        ])
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = [
                {"store_id": "store_a"},
                {"store_id": "store_b"},
            ]

            # store_a = losing, store_b = thriving
            def fake_attr(
                *args, window_hours=168.0, store_id=None,
                **kwargs,
            ):
                fake = MagicMock()
                if store_id == "store_a":
                    fake.total_revenue_in_window = 1.0
                    fake.attributed_revenue = 1.0
                else:
                    fake.total_revenue_in_window = 100.0
                    fake.attributed_revenue = 80.0
                return fake

            with patch(
                "engines._revenue_attribution."
                "attribute_revenue",
                side_effect=fake_attr,
            ):
                snaps = compute_fleet_snapshot()

        # Losing store_a sorts first
        assert snaps[0].store_id == "store_a"
        assert snaps[0].state == PnLState.LOSING
        # Thriving store_b sorts last
        assert snaps[-1].state == PnLState.THRIVING

    def test_store_manager_failure_returns_empty(
        self, _isolated_costs_log,
    ):
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            side_effect=RuntimeError("test: db unavailable"),
        ):
            snaps = compute_fleet_snapshot()
        assert snaps == []


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self, _isolated_costs_log):
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            r = PerStorePnLEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert r["meta"]["engine"] == "per_store_pnl"

    def test_none_success(self, _isolated_costs_log):
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            r = PerStorePnLEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self, _isolated_costs_log):
        r = PerStorePnLEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self, _isolated_costs_log):
        r = PerStorePnLEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_single_view(self, _isolated_costs_log):
        with _stub_attribution(
            total_revenue=10.0, attributed=8.0,
        ):
            r = PerStorePnLEngine().run({
                "data": {
                    "store_id": "store_a",
                    "window_hours": 24.0,
                },
            })
        assert r["status"] == "success"
        assert r["data"]["view"] == "single"
        snap = r["data"]["snapshot"]
        assert snap["store_id"] == "store_a"
        assert snap["revenue_usd"] == 10.0

    def test_fleet_view_with_totals(
        self, _isolated_costs_log,
    ):
        _seed(_isolated_costs_log, [{
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 2.0, "ok": True,
        }])
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = [
                {"store_id": "store_a"},
            ]
            with _stub_attribution(
                total_revenue=10.0, attributed=8.0,
            ):
                r = PerStorePnLEngine().run({})
        assert r["data"]["view"] == "fleet"
        totals = r["data"]["fleet_totals"]
        assert totals["total_spend_usd"] == 2.0
        assert totals["total_revenue_usd"] == 10.0
        assert totals["total_profit_usd"] == 8.0
