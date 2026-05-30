"""Tests for substrate_fire_trend (W855)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.substrate_fire_kpi import (
    DomainFireKPI, FireKPIReport,
)
from core.automation.substrate_fire_trend import (
    DomainFireTrend,
    FireTrendReport,
    _SIGNIFICANT_DELTA,
    _verdict,
    compute_fire_trend,
)


class TestVerdict:

    def test_both_none(self):
        assert _verdict(None, None) == "flat"

    def test_new_when_no_prev(self):
        cur = DomainFireKPI(domain="x", fired=5, errors=1)
        assert _verdict(cur, None) == "new"

    def test_dormant_when_no_cur(self):
        prev = DomainFireKPI(domain="x", fired=5, errors=1)
        assert _verdict(None, prev) == "dormant"

    def test_rising_when_delta_positive(self):
        cur = DomainFireKPI(domain="x", fired=9, errors=1)
        # 90% success
        prev = DomainFireKPI(domain="x", fired=5, errors=5)
        # 50% success -> +40pts -> rising
        assert _verdict(cur, prev) == "rising"

    def test_falling_when_delta_negative(self):
        cur = DomainFireKPI(domain="x", fired=2, errors=8)
        prev = DomainFireKPI(domain="x", fired=9, errors=1)
        assert _verdict(cur, prev) == "falling"

    def test_flat_within_threshold(self):
        # 50% vs 60% = -10pts boundary exactly: just-flat per
        # the strict > threshold check (<= -threshold gates)
        cur = DomainFireKPI(domain="x", fired=5, errors=5)
        prev = DomainFireKPI(domain="x", fired=6, errors=4)
        assert _verdict(cur, prev) == "flat"

    def test_flat_strictly_inside(self):
        cur = DomainFireKPI(domain="x", fired=5, errors=5)
        # 50%
        prev = DomainFireKPI(domain="x", fired=11, errors=9)
        # 55% -> -5pts -> flat (< 10pts)
        assert _verdict(cur, prev) == "flat"

    def test_significant_threshold(self):
        # Belt-and-braces: confirm the threshold constant is
        # the documented value.
        assert _SIGNIFICANT_DELTA == 0.10


class TestComputeFireTrend:

    def test_empty_report_no_domains(self):
        with patch(
            "core.automation.substrate_fire_trend."
            "compute_fire_kpis",
            return_value=FireKPIReport(),
        ):
            r = compute_fire_trend()
        assert r.per_domain == []

    def test_window_forwarded(self):
        calls = []

        def fake(*, window_hours, store_id=None):
            calls.append(window_hours)
            return FireKPIReport()

        with patch(
            "core.automation.substrate_fire_trend."
            "compute_fire_kpis",
            side_effect=fake,
        ):
            compute_fire_trend(window_hours=24.0)
        # First call is 2W (48h), second is W (24h)
        assert calls[0] == 48.0
        assert calls[1] == 24.0

    def test_domain_present_in_both_windows(self):
        full = FireKPIReport()
        full.per_domain = [
            DomainFireKPI(
                domain="shipping_alert",
                fired=10, errors=4,
            ),
        ]
        cur = FireKPIReport()
        cur.per_domain = [
            DomainFireKPI(
                domain="shipping_alert",
                fired=7, errors=1,
            ),
        ]
        with patch(
            "core.automation.substrate_fire_trend."
            "compute_fire_kpis",
            side_effect=[full, cur],
        ):
            r = compute_fire_trend()
        assert len(r.per_domain) == 1
        sa = r.per_domain[0]
        assert sa.current_fired == 7
        assert sa.previous_fired == 3
        assert sa.current_errors == 1
        assert sa.previous_errors == 3

    def test_new_domain_only_in_cur(self):
        full = FireKPIReport()
        full.per_domain = [
            DomainFireKPI(
                domain="shipping_alert",
                fired=5, errors=0,
            ),
        ]
        cur = FireKPIReport()
        cur.per_domain = [
            DomainFireKPI(
                domain="shipping_alert",
                fired=5, errors=0,
            ),
        ]
        # Same fired counts in full + cur means prev = 0
        # which the verdict logic treats as "new"
        with patch(
            "core.automation.substrate_fire_trend."
            "compute_fire_kpis",
            side_effect=[full, cur],
        ):
            r = compute_fire_trend()
        sa = r.per_domain[0]
        assert sa.verdict == "new"

    def test_report_aggregation(self):
        full = FireKPIReport()
        full.per_domain = [
            DomainFireKPI(domain="a", fired=10, errors=10),
            DomainFireKPI(domain="b", fired=10, errors=10),
        ]
        cur = FireKPIReport()
        cur.per_domain = [
            DomainFireKPI(
                domain="a", fired=10, errors=0,
            ),  # rising
            DomainFireKPI(
                domain="b", fired=0, errors=10,
            ),  # falling
        ]
        with patch(
            "core.automation.substrate_fire_trend."
            "compute_fire_kpis",
            side_effect=[full, cur],
        ):
            r = compute_fire_trend()
        assert r.rising_count == 1
        assert r.falling_count == 1


class TestReportDataclass:

    def test_empty(self):
        r = FireTrendReport()
        assert r.rising_count == 0
        assert r.falling_count == 0
        assert r.flat_count == 0
