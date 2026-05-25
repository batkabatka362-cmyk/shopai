"""Tests for engines._attribution_snapshot.

Per-cycle attribution snapshot persistence. Pattern J guard
means writes are normally test-suppressed; tests here lift
the guard to verify the write path works.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines._attribution_snapshot import (
    AttributionSnapshot,
    attribution_trend,
    clear_snapshots,
    last_snapshot,
    recent_snapshots,
    record_snapshot,
)


@pytest.fixture
def isolated_snapshots(monkeypatch, tmp_path):
    """Per-test data dir + lift Pattern J guard."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    with patch(
        "engines._attribution_snapshot._is_test_environment",
        return_value=False,
    ):
        yield tmp_path


def _fake_report(
    *, attributed=0.0, total_orders=0, total_revenue=0.0,
    per_cluster=None, per_engine=None,
):
    """Build a minimal AttributionReport for mocking."""
    from engines._revenue_attribution import (
        AttributionReport, ClusterAttribution, EngineAttribution,
    )
    rpt = AttributionReport(window_hours=168.0)
    rpt.total_orders_in_window = total_orders
    rpt.total_revenue_in_window = total_revenue
    for c_dict in (per_cluster or []):
        rpt.per_cluster.append(
            ClusterAttribution(
                cluster=c_dict["cluster"],
                window_hours=168.0,
                attributed_revenue=c_dict.get("revenue", 0.0),
                attributed_orders=c_dict.get("orders", 0),
            )
        )
    for e_dict in (per_engine or []):
        rpt.per_engine.append(
            EngineAttribution(
                engine=e_dict["engine"],
                cluster=e_dict.get("cluster"),
                window_hours=168.0,
                attributed_revenue=e_dict.get("revenue", 0.0),
                attributed_orders=e_dict.get("orders", 0),
            )
        )
    return rpt


class TestRecord:

    def test_record_persists_a_snapshot(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(
                attributed=0.0, total_orders=0,
            ),
        ):
            snap = record_snapshot(window_hours=24.0)
        assert snap is not None
        assert snap.window_hours == 24.0
        # And it's readable
        assert len(recent_snapshots()) == 1

    def test_record_with_per_cluster(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(
                attributed=100.0,
                total_orders=1,
                total_revenue=100.0,
                per_cluster=[
                    {"cluster": "retention", "revenue": 100.0,
                     "orders": 1},
                ],
            ),
        ):
            snap = record_snapshot(window_hours=168.0)
        assert snap is not None
        assert snap.attributed_revenue == 100.0
        assert len(snap.per_cluster) == 1
        assert snap.per_cluster[0]["cluster"] == "retention"

    def test_record_links_cycle_run_id(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(),
        ):
            snap = record_snapshot(
                window_hours=24.0,
                cycle_run_id="cycle_test_123",
            )
        assert snap.cycle_run_id == "cycle_test_123"

    def test_record_suppressed_under_pytest(
        self, monkeypatch, tmp_path,
    ):
        """When Pattern J guard is ON (no fixture lift), record
        returns None even on a happy path."""
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        # Don't patch _is_test_environment -> guard active
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(attributed=100.0),
        ):
            snap = record_snapshot(window_hours=24.0)
        assert snap is None

    def test_record_handles_attribution_raise(
        self, isolated_snapshots,
    ):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=RuntimeError("net blip"),
        ):
            snap = record_snapshot(window_hours=24.0)
        assert snap is None


class TestRetrieval:

    def test_recent_snapshots_newest_first(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(),
        ):
            s1 = record_snapshot(window_hours=24.0)
            s2 = record_snapshot(window_hours=48.0)
            s3 = record_snapshot(window_hours=72.0)
        snaps = recent_snapshots(limit=10)
        assert snaps[0].snapshot_id == s3.snapshot_id
        assert snaps[-1].snapshot_id == s1.snapshot_id

    def test_last_snapshot(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(),
        ):
            record_snapshot(window_hours=24.0)
            s2 = record_snapshot(window_hours=48.0)
        last = last_snapshot()
        assert last is not None
        assert last.snapshot_id == s2.snapshot_id

    def test_last_snapshot_returns_none_when_empty(
        self, isolated_snapshots,
    ):
        assert last_snapshot() is None

    def test_store_filter(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(),
        ):
            record_snapshot(window_hours=24.0, store_id="A")
            record_snapshot(window_hours=24.0, store_id="B")
        snaps_a = recent_snapshots(store_id="A")
        assert len(snaps_a) == 1
        assert snaps_a[0].store_id == "A"


class TestTrend:

    def test_trend_oldest_first(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(
                attributed=100.0, total_orders=1,
                per_cluster=[
                    {"cluster": "retention", "revenue": 100.0},
                ],
                per_engine=[
                    {"engine": "loyalty",
                     "cluster": "retention", "revenue": 100.0},
                ],
            ),
        ):
            record_snapshot(window_hours=24.0)
            record_snapshot(window_hours=24.0)
            record_snapshot(window_hours=24.0)
        trend = attribution_trend(limit=10)
        # 3 rows
        assert len(trend) == 3
        # Each carries the rollup fields
        assert trend[0]["attributed_revenue"] == 100.0
        assert trend[0]["top_cluster"] == "retention"
        assert trend[0]["top_engine"] == "loyalty"

    def test_trend_empty_when_no_snapshots(self, isolated_snapshots):
        assert attribution_trend() == []


class TestPerStoreSnapshots:
    """Wave 14: per-store snapshots co-exist with fleet-wide."""

    def test_fleet_and_store_snapshots_coexist(
        self, isolated_snapshots,
    ):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(),
        ):
            # Fleet-wide
            record_snapshot(window_hours=168.0)
            # Per-store
            record_snapshot(window_hours=168.0, store_id="A")
            record_snapshot(window_hours=168.0, store_id="B")
        all_snaps = recent_snapshots(limit=10)
        assert len(all_snaps) == 3
        # Store filter only returns matching
        a_snaps = recent_snapshots(store_id="A")
        assert len(a_snaps) == 1
        assert a_snaps[0].store_id == "A"

    def test_per_store_delta_only_diffs_same_store(
        self, isolated_snapshots,
    ):
        """Two snapshots for store A + one for store B should
        diff A's pair, not cross-pollinate."""
        from engines._attribution_delta import latest_delta
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(
                attributed=100.0,
                per_cluster=[
                    {"cluster": "retention",
                     "revenue": 100.0, "orders": 5},
                ],
            ),
        ):
            record_snapshot(window_hours=168.0, store_id="A")
            record_snapshot(window_hours=168.0, store_id="B")
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(
                attributed=50.0,
                per_cluster=[
                    {"cluster": "retention",
                     "revenue": 50.0, "orders": 3},
                ],
            ),
        ):
            record_snapshot(window_hours=168.0, store_id="A")
        # Store A has 2 snapshots, delta possible.
        # Store B has 1, no delta.
        delta_a = latest_delta(store_id="A")
        delta_b = latest_delta(store_id="B")
        assert delta_a is not None
        assert delta_b is None


class TestClear:

    def test_clear_snapshots_removes_file(self, isolated_snapshots):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report(),
        ):
            record_snapshot(window_hours=24.0)
        assert len(recent_snapshots()) == 1
        clear_snapshots()
        assert recent_snapshots() == []
