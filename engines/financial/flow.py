"""Financial Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Revenue Calculator → Cost Analyzer →
  Margin Calculator → Health Grader → Memory Writer → Output

Engine contract:
  Input:  {status, data: {orders, products, costs, period}, meta, error}
  Output: {status, data: {revenue, costs, margins, health_grade, pnl_summary}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .revenue_calculator import calculate_revenue
from .cost_analyzer import analyze_costs
from .margin_calculator import calculate_margins
from .health_grader import grade_health
from .memory_reader import read_past_financials
from .memory_writer import write_financial_result


class FinancialEngine:
    """Financial Engine — orchestrator only, no logic."""

    ENGINE_NAME = "financial"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        orders = data.get("orders", [])
        products = data.get("products", [])
        costs_input = data.get("costs", {})
        period = str(data.get("period", "month"))

        if not orders:
            return self._fail("Orders list is required", 0.0)

        _past = read_past_financials(limit=5)

        # ---- Revenue Calculator ----
        rev_result = calculate_revenue(orders=orders, products=products)
        if rev_result.get("status") == "error":
            return self._fail(f"Revenue calculation failed: {rev_result.get('error', 'unknown')}", time.monotonic() - start)
        revenue = rev_result.get("revenue", {})

        # ---- Cost Analyzer ----
        cost_result = analyze_costs(orders=orders, products=products, costs=costs_input)
        if cost_result.get("status") == "error":
            return self._fail(f"Cost analysis failed: {cost_result.get('error', 'unknown')}", time.monotonic() - start)
        costs = cost_result.get("costs", {})

        # ---- Margin Calculator ----
        margin_result = calculate_margins(revenue=revenue, costs=costs, products=products)
        if margin_result.get("status") == "error":
            return self._fail(f"Margin calculation failed: {margin_result.get('error', 'unknown')}", time.monotonic() - start)
        margins = margin_result.get("margins", {})

        # ---- Health Grader ----
        health_result = grade_health(revenue=revenue, costs=costs, margins=margins)
        if health_result.get("status") == "error":
            return self._fail(f"Health grading failed: {health_result.get('error', 'unknown')}", time.monotonic() - start)
        health = health_result.get("health", {})

        # ---- P&L Summary ----
        total_revenue = float(revenue.get("total_revenue", 0))
        total_cogs = float(costs.get("total_cogs", 0))
        total_operating = float(costs.get("total_operating", 0))

        pnl_summary: dict[str, Any] = {
            "period": period,
            "revenue": total_revenue,
            "cogs": total_cogs,
            "gross_profit": round(total_revenue - total_cogs, 2),
            "operating_expenses": total_operating,
            "net_income": round(total_revenue - float(costs.get("total_costs", 0)), 2),
        }

        _write_result = write_financial_result(
            revenue=revenue, costs=costs, margins=margins, health_grade=health,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "revenue": revenue,
                "costs": costs,
                "margins": margins,
                "health_grade": health,
                "pnl_summary": pnl_summary,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
