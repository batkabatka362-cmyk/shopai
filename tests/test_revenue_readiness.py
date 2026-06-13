"""Tests for engines.revenue_readiness — W963-1."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines.revenue_readiness import RevenueReadinessEngine
from engines.revenue_readiness.analyzer import (
    Gate,
    ReadinessReport,
    _pick_next_action,
    _verdict,
    analyze,
)


# ── Engine: Pattern Q envelope ──────────────────────────────


class TestEngineEnvelope:
    """Pattern Q audit will run this engine on empty input;
    confirm the envelope shape is correct."""

    def test_empty_input_returns_success_envelope(self):
        result = RevenueReadinessEngine().run({})
        assert set(result.keys()) == {
            "status", "data", "meta", "error",
        }
        assert result["status"] == "success"
        assert result["error"] is None
        assert isinstance(result["data"], dict)
        assert result["meta"]["engine"] == "revenue_readiness"

    def test_none_input_returns_success(self):
        result = RevenueReadinessEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_returns_error(self):
        result = RevenueReadinessEngine().run("not a dict")
        assert result["status"] == "error"
        assert result["data"] is None

    def test_fail_upstream_short_circuits(self):
        result = RevenueReadinessEngine().run({
            "status": "fail",
            "error": "upstream blew up",
        })
        assert result["status"] == "error"
        assert "upstream" in (result["error"] or "")


# ── Analyzer: per-gate logic ────────────────────────────────


class TestProductGate:
    def test_zero_products_missing(self):
        report = analyze(stats={"products": 0})
        gate = next(g for g in report.gates if g.name == "has_products")
        assert gate.status == "missing"
        assert "0 product" in gate.detail

    def test_one_product_partial(self):
        report = analyze(stats={"products": 1})
        gate = next(g for g in report.gates if g.name == "has_products")
        assert gate.status == "partial"

    def test_many_products_ready(self):
        report = analyze(stats={"products": 50})
        gate = next(g for g in report.gates if g.name == "has_products")
        assert gate.status == "ready"


class TestOrdersGate:
    def test_zero_orders_missing(self):
        report = analyze(stats={"orders": 0})
        gate = next(g for g in report.gates if g.name == "has_orders_recent")
        assert gate.status == "missing"

    def test_few_orders_partial(self):
        report = analyze(stats={"orders": 3})
        gate = next(g for g in report.gates if g.name == "has_orders_recent")
        assert gate.status == "partial"

    def test_many_orders_ready(self):
        report = analyze(stats={"orders": 50})
        gate = next(g for g in report.gates if g.name == "has_orders_recent")
        assert gate.status == "ready"


class TestCustomersGate:
    def test_zero_customers_missing(self):
        report = analyze(stats={"customers": 0})
        gate = next(g for g in report.gates if g.name == "has_active_customers")
        assert gate.status == "missing"

    def test_many_customers_ready(self):
        report = analyze(stats={"customers": 20})
        gate = next(g for g in report.gates if g.name == "has_active_customers")
        assert gate.status == "ready"


class TestRepeatPurchaseGate:
    def test_no_customers_yields_missing(self):
        report = analyze(stats={"customers": 0, "orders": 0})
        gate = next(g for g in report.gates if g.name == "has_repeat_purchase")
        assert gate.status == "missing"
        assert "blocked" in gate.next_action

    def test_one_to_one_ratio_missing(self):
        report = analyze(stats={"customers": 10, "orders": 10})
        gate = next(g for g in report.gates if g.name == "has_repeat_purchase")
        assert gate.status == "missing"

    def test_some_repeats_partial(self):
        report = analyze(stats={"customers": 10, "orders": 12})
        gate = next(g for g in report.gates if g.name == "has_repeat_purchase")
        assert gate.status == "partial"

    def test_strong_repeat_ready(self):
        report = analyze(stats={"customers": 10, "orders": 25})
        gate = next(g for g in report.gates if g.name == "has_repeat_purchase")
        assert gate.status == "ready"


class TestAttributionGate:
    def test_no_snapshot_missing(self):
        with patch(
            "engines._attribution_snapshot.last_snapshot",
            return_value=None,
        ):
            report = analyze(stats={"products": 5})
        gate = next(
            g for g in report.gates if g.name == "has_attributed_revenue"
        )
        assert gate.status == "missing"

    def test_snapshot_with_revenue_ready(self):
        class FakeSnap:
            attributed_revenue = 42.5
            total_orders_in_window = 3
        with patch(
            "engines._attribution_snapshot.last_snapshot",
            return_value=FakeSnap(),
        ):
            report = analyze(stats={"products": 5})
        gate = next(
            g for g in report.gates if g.name == "has_attributed_revenue"
        )
        assert gate.status == "ready"
        assert "$42.50" in gate.detail


class TestAdSpendGate:
    def test_no_adapter_missing(self):
        # Default branch with adapter probe failing or empty.
        with patch(
            "core.adapters.router.get_registry",
            side_effect=Exception("no registry"),
        ):
            report = analyze(stats={"products": 5})
        gate = next(g for g in report.gates if g.name == "has_ad_spend_path")
        assert gate.status == "missing"


# ── Verdict + next-action logic ─────────────────────────────


class TestVerdict:
    def test_all_passed_earning_active(self):
        assert _verdict(6, 6) == "earning_active"

    def test_four_of_six_growing(self):
        assert _verdict(4, 6) == "growing"

    def test_two_of_six_building(self):
        assert _verdict(2, 6) == "building_traction"

    def test_zero_cold_start(self):
        assert _verdict(0, 6) == "cold_start"

    def test_zero_total_unknown(self):
        assert _verdict(0, 0) == "unknown"


class TestPickNextAction:
    def _gates(self, **kwargs):
        defaults = {
            "has_products": "ready",
            "has_orders_recent": "ready",
            "has_active_customers": "ready",
            "has_ad_spend_path": "ready",
            "has_attributed_revenue": "ready",
            "has_repeat_purchase": "ready",
        }
        defaults.update(kwargs)
        return [
            Gate(
                name=name,
                status=status,
                next_action=f"action_for_{name}",
            )
            for name, status in defaults.items()
        ]

    def test_all_ready_no_action(self):
        assert _pick_next_action(self._gates()) == ""

    def test_missing_products_takes_priority(self):
        gates = self._gates(
            has_products="missing",
            has_ad_spend_path="missing",
        )
        assert _pick_next_action(gates) == "action_for_has_products"

    def test_partial_fall_through_when_no_missing(self):
        gates = self._gates(has_ad_spend_path="partial")
        assert _pick_next_action(gates) == "action_for_has_ad_spend_path"


# ── End-to-end: realistic store states ──────────────────────


class TestRealisticStates:
    def test_brand_new_store_cold_start(self):
        result = RevenueReadinessEngine().run({
            "data": {"stats": {
                "products": 0, "orders": 0, "customers": 0,
            }},
        })
        assert result["data"]["verdict"] == "cold_start"
        # Should point at the live product-candidates command
        # (W963-2 wired the engine; W963-1's hint now leads here).
        assert "product-candidates" in result["data"]["next_action"]

    def test_well_running_store_growing(self):
        with patch(
            "engines._attribution_snapshot.last_snapshot",
            return_value=None,
        ):
            result = RevenueReadinessEngine().run({
                "data": {"stats": {
                    "products": 50, "orders": 25, "customers": 12,
                }},
            })
        # 4/6: products + orders + customers + repeat
        # missing: ads + attribution
        assert result["data"]["verdict"] in ("growing", "earning_active")
        assert result["data"]["passed"] >= 4
