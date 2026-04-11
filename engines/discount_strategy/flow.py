"""Discount Strategy Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Business Context → Margin Analyzer → Discount Type Selector →
  Depth Calculator → Target Selector → Duration Planner →
  Cannibalization Checker → Revenue Projector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products: [...], goal, inventory_days, customer_segments}, meta, error}
  Output: {status, data: {strategy, margin_impact, projected_revenue, cannibalization_risk, confidence}, meta, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .margin_analyzer import analyze_margins
from .discount_type_selector import select_discount_type
from .depth_calculator import calculate_depth
from .target_selector import select_target
from .duration_planner import plan_duration
from .cannibalization_checker import check_cannibalization
from .revenue_projector import project_revenue
from .memory_reader import read_past_discounts
from .memory_writer import write_discount_result


class DiscountStrategyEngine:
    """Discount Strategy Engine — orchestrator only, no logic."""

    ENGINE_NAME = "discount_strategy"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full discount strategy pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            DiscountStrategyOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        products = data.get("products", [])
        goal = str(data.get("goal", "boost_revenue"))
        inventory_days = int(data.get("inventory_days", 90))
        customer_segments = data.get("customer_segments", [])

        if not products:
            return self._fail("Products list is required", 0.0)

        # ---- Stage 1: Read past discounts (non-blocking) ----
        _past = read_past_discounts(limit=5)

        # ---- Stage 2: Margin Analyzer ----
        margin_result = analyze_margins(products=products, goal=goal)
        if margin_result.get("status") == "error":
            return self._fail(
                f"Margin analysis failed: {margin_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        margin_analyses = margin_result.get("analyses", [])
        margin_summary = margin_result.get("summary", {})

        # ---- Stage 3: Discount Type Selector ----
        type_result = select_discount_type(
            goal=goal,
            margin_summary=margin_summary,
            products=products,
        )
        if type_result.get("status") == "error":
            return self._fail(
                f"Type selection failed: {type_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        type_selection = type_result.get("selection", {})
        selected_type = str(type_selection.get("selected_type", "percentage_off"))

        # ---- Stage 4: Depth Calculator ----
        depth_result = calculate_depth(
            discount_type=selected_type,
            margin_analyses=margin_analyses,
            goal=goal,
            inventory_days=inventory_days,
        )
        if depth_result.get("status") == "error":
            return self._fail(
                f"Depth calculation failed: {depth_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        depth_calc = depth_result.get("calculation", {})
        sweet_spot_pct = float(depth_calc.get("sweet_spot_pct", 0.15))
        volume_lift = float(depth_calc.get("expected_volume_lift", 1.0))
        margin_at_sweet_spot = float(depth_calc.get("margin_at_sweet_spot", 0.0))

        # ---- Stage 5: Target Selector ----
        target_result = select_target(
            goal=goal,
            customer_segments=customer_segments,
            discount_type=selected_type,
            sweet_spot_pct=sweet_spot_pct,
        )
        if target_result.get("status") == "error":
            return self._fail(
                f"Target selection failed: {target_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        target_sel = target_result.get("selection", {})
        target_audience = str(target_sel.get("target_audience", "all"))
        target_reach = float(target_sel.get("estimated_reach_pct", 1.0))
        response_rate = float(target_sel.get("expected_response_rate", 0.03))

        # ---- Stage 6: Duration Planner ----
        dur_result = plan_duration(
            goal=goal,
            inventory_days=inventory_days,
            sweet_spot_pct=sweet_spot_pct,
            target_audience=target_audience,
        )
        if dur_result.get("status") == "error":
            return self._fail(
                f"Duration planning failed: {dur_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        dur_plan = dur_result.get("plan", {})
        duration_hours = int(dur_plan.get("duration_hours", 24))
        start_time = str(dur_plan.get("start_time", "00:00"))

        # ---- Stage 7: Cannibalization Checker ----
        cannibal_result = check_cannibalization(
            discount_type=selected_type,
            sweet_spot_pct=sweet_spot_pct,
            duration_hours=duration_hours,
            target_audience=target_audience,
            goal=goal,
            margin_summary=margin_summary,
        )
        if cannibal_result.get("status") == "error":
            return self._fail(
                f"Cannibalization check failed: {cannibal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        cannibal_check = cannibal_result.get("check", {})
        cannibalization_risk = str(cannibal_check.get("cannibalization_risk", "medium"))
        cannibalization_impact = float(cannibal_check.get("regular_sales_impact_pct", 0.0))

        # ---- Stage 8: Revenue Projector ----
        # Enrich margin_analyses with daily_sales from original products
        enriched_analyses = _enrich_with_daily_sales(margin_analyses, products)

        rev_result = project_revenue(
            margin_analyses=enriched_analyses,
            sweet_spot_pct=sweet_spot_pct,
            volume_lift=volume_lift,
            margin_at_sweet_spot=margin_at_sweet_spot,
            duration_hours=duration_hours,
            target_reach_pct=target_reach,
            response_rate=response_rate,
            cannibalization_impact_pct=cannibalization_impact,
        )
        if rev_result.get("status") == "error":
            return self._fail(
                f"Revenue projection failed: {rev_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        rev_proj = rev_result.get("projection", {})

        # ---- Stage 9: Compute final confidence ----
        confidence = float(rev_proj.get("projection_confidence", 0.50))

        # ---- Stage 10: Assemble output ----
        avg_margin = float(margin_summary.get("avg_margin", 0.0))
        avg_safe_room = float(margin_summary.get("avg_safe_discount_room", 0.0))

        strategy = {
            "type": selected_type,
            "depth_pct": round(sweet_spot_pct, 4),
            "target_audience": target_audience,
            "duration_hours": duration_hours,
            "start_time": start_time,
        }

        margin_impact = {
            "current_margin": round(avg_margin, 4),
            "discounted_margin": round(margin_at_sweet_spot, 4),
            "margin_loss_pct": round(avg_margin - margin_at_sweet_spot, 4),
            "max_safe_discount": round(avg_safe_room, 4),
        }

        projected_revenue = {
            "base_daily": float(rev_proj.get("base_revenue_daily", 0.0)),
            "projected_daily": float(rev_proj.get("projected_revenue_daily", 0.0)),
            "change_pct": float(rev_proj.get("revenue_change_pct", 0.0)),
            "break_even_volume": float(rev_proj.get("break_even_volume", 0.0)),
            "break_even_achievable": bool(rev_proj.get("break_even_achievable", False)),
            "net_profit_impact": float(rev_proj.get("net_profit_impact", 0.0)),
        }

        # ---- Stage 11: Memory Writer (non-fatal) ----
        _write_result = write_discount_result(
            strategy=strategy,
            margin_impact=margin_impact,
            projected_revenue=projected_revenue,
            cannibalization_risk=cannibalization_risk,
            confidence=confidence,
            goal=goal,
            products_count=len(products),
        )

        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "strategy": strategy,
                "margin_impact": margin_impact,
                "projected_revenue": projected_revenue,
                "cannibalization_risk": cannibalization_risk,
                "confidence": round(confidence, 4),
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


def _enrich_with_daily_sales(
    analyses: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge daily_sales from original products into margin analyses."""
    product_sales: dict[str, float] = {}
    for p in products:
        pid = str(p.get("id", ""))
        if pid:
            product_sales[pid] = float(p.get("daily_sales", 1.0))

    enriched = []
    for a in analyses:
        entry = dict(a)
        pid = str(a.get("product_id", ""))
        entry["daily_sales"] = product_sales.get(pid, 1.0)
        enriched.append(entry)

    return enriched
