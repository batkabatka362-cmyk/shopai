"""Profitability Calculator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Cost Breakdown → Margin Calculator → Break-Even Analyzer →
  ROI Projector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, costs, pricing}, meta, error}
  Output: {status, data: {profitability: [{product_id, revenue, total_cost, net_margin, break_even_units, roi}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .cost_breakdown import break_down_costs
from .margin_calculator import calculate_margins
from .break_even_analyzer import analyze_break_even
from .roi_projector import project_roi
from .memory_reader import read_past_profitability
from .memory_writer import write_profitability_result
from engines._shopify_hydrator import hydrate


class ProfitabilityCalculatorEngine:
    """Profitability Calculator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "profitability_calculator"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full profitability pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ProfitabilityOutput dict.
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
        costs = data.get("costs", [])
        pricing = data.get("pricing", [])

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past profitability (non-blocking) ----
        _past = read_past_profitability(limit=5)

        # ---- Stage 2: Cost Breakdown ----
        cost_result = break_down_costs(
            products=products,
            costs=costs,
        )
        if cost_result.get("status") == "error":
            return self._fail(
                f"Cost breakdown failed: {cost_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        breakdowns = cost_result.get("breakdowns", [])

        # ---- Stage 3: Margin Calculator ----
        margin_result = calculate_margins(
            products=products,
            breakdowns=breakdowns,
            pricing=pricing,
        )
        if margin_result.get("status") == "error":
            return self._fail(
                f"Margin calculation failed: {margin_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        margins = margin_result.get("margins", [])

        # ---- Stage 4: Break-Even Analyzer ----
        be_result = analyze_break_even(
            products=products,
            margins=margins,
            breakdowns=breakdowns,
        )
        if be_result.get("status") == "error":
            return self._fail(
                f"Break-even analysis failed: {be_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        break_evens = be_result.get("break_evens", [])

        # ---- Stage 5: ROI Projector ----
        roi_result = project_roi(
            products=products,
            margins=margins,
            breakdowns=breakdowns,
        )
        if roi_result.get("status") == "error":
            return self._fail(
                f"ROI projection failed: {roi_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        projections = roi_result.get("projections", [])

        # ---- Stage 6: Assemble profitability output ----
        margin_map = {str(m.get("product_id", "")): m for m in margins}
        be_map = {str(b.get("product_id", "")): b for b in break_evens}
        roi_map = {str(r.get("product_id", "")): r for r in projections}

        profitability: list[dict[str, Any]] = []
        for product in products:
            pid = str(product.get("id", "unknown"))
            m = margin_map.get(pid, {})
            be = be_map.get(pid, {})
            roi = roi_map.get(pid, {})

            units_sold = int(product.get("units_sold", 0))
            revenue_per_unit = float(m.get("revenue_per_unit", 0.0))

            profitability.append({
                "product_id": pid,
                "revenue": round(revenue_per_unit * units_sold, 2),
                "total_cost": round(float(m.get("cost_per_unit", 0.0)) * units_sold, 2),
                "net_margin": m.get("net_margin", 0.0),
                "break_even_units": be.get("break_even_units", 0),
                "roi": roi.get("roi_pct", 0.0),
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_profitability_result(profitability=profitability)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "profitability": profitability,
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
