"""Tests for engines._roas_report."""
from __future__ import annotations

from unittest.mock import patch

from engines._roas_report import (
    EngineROAS,
    ROASReport,
    compute_roas_report,
)


class TestEngineROASProperties:

    def test_roas_none_when_no_spend(self):
        e = EngineROAS(engine="x", cluster=None)
        assert e.roas is None
        assert e.verdict == "no_data"

    def test_roas_positive(self):
        e = EngineROAS(
            engine="x", cluster=None,
            total_spend=100.0,
            attributed_revenue=300.0,
        )
        assert e.roas == 3.0
        assert e.verdict == "strong"

    def test_roas_break_even(self):
        e = EngineROAS(
            engine="x", cluster=None,
            total_spend=100.0,
            attributed_revenue=150.0,
        )
        assert e.roas == 1.5
        assert e.verdict == "break_even"

    def test_roas_negative(self):
        e = EngineROAS(
            engine="x", cluster=None,
            total_spend=100.0,
            attributed_revenue=50.0,
        )
        assert e.roas == 0.5
        assert e.verdict == "negative"


class TestROASReport:

    def test_fleet_roas_none_when_no_spend(self):
        r = ROASReport(window_hours=168.0)
        assert r.fleet_roas is None

    def test_fleet_roas_computed(self):
        r = ROASReport(
            window_hours=168.0,
            total_spend=500.0,
            total_attributed_revenue=1500.0,
        )
        assert r.fleet_roas == 3.0


class TestComputeReport:
    """End-to-end with mocked queue + attribution."""

    def test_empty_when_no_spend_actions(self):
        """No executed actions with spend metrics -> empty report."""
        from unittest.mock import MagicMock
        fake_queue = MagicMock()
        fake_queue.list_by_status.return_value = []
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            report = compute_roas_report()
        assert report.per_engine == []
        assert report.total_spend == 0.0

    def test_spend_only_no_revenue(self):
        """Engine has spend but no attribution yet."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import time as _t
        recent = _t.time() - 100
        fake_action = SimpleNamespace(
            id="a1",
            engine="email_marketing",
            store_id=None,
        )
        fake_queue = MagicMock()
        fake_queue.list_by_status.return_value = [fake_action]
        fake_queue.get_outcomes.return_value = [
            {
                "captured_at": recent,
                "metrics": {"ad_spend": 200.0},
            }
        ]
        from engines._revenue_attribution import AttributionReport
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ), patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=AttributionReport(window_hours=168.0),
        ):
            report = compute_roas_report()
        assert len(report.per_engine) == 1
        e = report.per_engine[0]
        assert e.engine == "email_marketing"
        assert e.total_spend == 200.0
        assert e.attributed_revenue == 0.0
        assert e.roas is None
        assert e.verdict == "no_data"

    def test_spend_and_revenue_join(self):
        """Engine has both spend AND attribution -> ROAS computed."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import time as _t
        recent = _t.time() - 100
        fake_action = SimpleNamespace(
            id="a1",
            engine="loyalty",
            store_id=None,
        )
        fake_queue = MagicMock()
        fake_queue.list_by_status.return_value = [fake_action]
        fake_queue.get_outcomes.return_value = [
            {
                "captured_at": recent,
                "metrics": {"discount_value": 50.0},
            }
        ]
        from engines._revenue_attribution import (
            AttributionReport, EngineAttribution,
        )
        attr = AttributionReport(window_hours=168.0)
        attr.per_engine.append(
            EngineAttribution(
                engine="loyalty",
                cluster="retention",
                window_hours=168.0,
                attributed_revenue=200.0,
                attributed_orders=4,
            )
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ), patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=attr,
        ):
            report = compute_roas_report()
        assert len(report.per_engine) == 1
        e = report.per_engine[0]
        assert e.total_spend == 50.0
        assert e.attributed_revenue == 200.0
        assert e.roas == 4.0
        assert e.verdict == "strong"
        assert report.fleet_roas == 4.0

    def test_outcomes_outside_window_excluded(self):
        """Old outcomes (beyond window_hours) don't count."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import time as _t
        old = _t.time() - 1_000_000  # >7 days ago
        fake_action = SimpleNamespace(
            id="a1", engine="x", store_id=None,
        )
        fake_queue = MagicMock()
        fake_queue.list_by_status.return_value = [fake_action]
        fake_queue.get_outcomes.return_value = [
            {"captured_at": old, "metrics": {"ad_spend": 100.0}},
        ]
        from engines._revenue_attribution import AttributionReport
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ), patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=AttributionReport(window_hours=168.0),
        ):
            report = compute_roas_report(window_hours=168.0)
        assert report.per_engine == []

    def test_per_store_filter(self):
        """store_id filter excludes other stores' spend."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import time as _t
        recent = _t.time() - 100
        actions = [
            SimpleNamespace(
                id="a1", engine="e1", store_id="A",
            ),
            SimpleNamespace(
                id="a2", engine="e2", store_id="B",
            ),
        ]
        fake_queue = MagicMock()
        fake_queue.list_by_status.return_value = actions
        fake_queue.get_outcomes.return_value = [
            {"captured_at": recent, "metrics": {"cost": 100.0}},
        ]
        from engines._revenue_attribution import AttributionReport
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ), patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=AttributionReport(window_hours=168.0),
        ):
            report = compute_roas_report(store_id="A")
        # Only A's engine appears
        assert len(report.per_engine) == 1
        assert report.per_engine[0].engine == "e1"
