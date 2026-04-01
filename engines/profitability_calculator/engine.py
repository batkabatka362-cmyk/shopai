"""Profitability Calculator Engine — complete product profitability analysis.

Flow: input → cost_breakdown → margin_calculator → break_even → roi_projector → scenario_modeler → output
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.cost_breakdown.code import calculate_cost_breakdown
from .modules.margin_calculator.code import calculate_margins
from .modules.break_even.code import calculate_break_even
from .modules.roi_projector.code import project_roi
from .modules.scenario_modeler.code import model_scenarios


class ProfitabilityCalculatorEngine:
    """Profitability Calculator — orchestrator only."""

    ENGINE_NAME = "profitability_calculator"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        results: dict[str, Any] = {}

        contract = lambda d: {"status": "success", "data": d, "meta": {}, "error": None}

        # Module 1: Cost breakdown
        results["cost_breakdown"] = calculate_cost_breakdown(contract(data))

        # Module 2: Margins (uses cost breakdown)
        cost_data = results["cost_breakdown"].get("data") or {}
        margin_input = {**data}
        if isinstance(cost_data, dict) and cost_data.get("total_cost_per_unit"):
            margin_input["total_variable_cost"] = cost_data["total_cost_per_unit"]
        results["margins"] = calculate_margins(contract(margin_input))

        # Module 3: Break-even
        margin_data = results["margins"].get("data") or {}
        be_input = {
            **data,
            "contribution_margin_per_unit": margin_data.get("contribution_margin_per_unit", data.get("price", 30) * 0.4),
            "initial_investment": data.get("initial_investment", data.get("budget", 3000)),
        }
        # break_even module takes raw dict, not contract wrapper
        be_input["variable_cost_per_unit"] = data.get("cost", 0) * 1.3  # COGS + ~30% variable costs
        try:
            results["break_even"] = {"status": "success", "data": calculate_break_even(be_input), "meta": {}, "error": None}
        except Exception as exc:
            results["break_even"] = {"status": "fail", "data": {}, "meta": {}, "error": {"reason": str(exc)}}

        # Module 4: ROI projection
        roi_input = {
            **data,
            "monthly_profit": margin_data.get("monthly_net_profit", 0),
            "initial_investment": be_input.get("initial_investment", 3000),
        }
        try:
            results["roi"] = project_roi(contract(roi_input))
        except Exception as exc:
            results["roi"] = {"status": "fail", "data": {}, "meta": {}, "error": {"reason": str(exc)}}

        # Module 5: Scenario modeling
        results["scenarios"] = model_scenarios(contract(data))

        elapsed = time.monotonic() - start

        output = format_output(self.ENGINE_NAME, results, data, elapsed)
        validation = validate_result(output)
        if not validation["valid"]:
            return {"status": "fail", "data": None, "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": _now()}, "error": {"reason": validation["reason"]}}
        return output

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
