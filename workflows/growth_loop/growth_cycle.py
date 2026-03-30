"""Growth Cycle

Chains: analytics → decision → strategy → growth → scaling

Input:  Business metrics and growth targets
Output: Growth strategy with scaling plan
"""

from __future__ import annotations

from typing import Any

from engines.registry import get_engine
from engines.base import EngineInput
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("workflow.growth_cycle")


class GrowthCycle:
    """Full growth cycle: analyze → decide → plan → grow → scale."""

    def __init__(self) -> None:
        self._analytics = get_engine("analytics")
        self._decision = get_engine("decision")
        self._strategy = get_engine("strategy")
        self._growth = get_engine("growth")
        self._scaling = get_engine("scaling")

    def run(self, metrics: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
        flow_id = generate_id("flow")
        logger.info("[%s] Starting growth cycle", flow_id)
        results: dict[str, Any] = {}

        # Step 1: Analyze current performance
        analytics_out = self._analytics.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="analytics",
            data={"metrics_data": metrics, "time_range": targets.get("time_range", "30d")},
        ))
        results["analytics"] = analytics_out.to_dict()

        # Step 2: Make decision
        decision_out = self._decision.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="decision",
            data={"options": analytics_out.result, "evaluation_criteria": targets},
        ))
        results["decision"] = decision_out.to_dict()

        # Step 3: Develop strategy
        strategy_out = self._strategy.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="strategy",
            data={"market_data": analytics_out.result, "business_goals": targets},
        ))
        results["strategy"] = strategy_out.to_dict()

        # Step 4: Execute growth
        growth_out = self._growth.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="growth",
            data={"growth_data": strategy_out.result, "growth_targets": targets},
        ))
        results["growth"] = growth_out.to_dict()

        # Step 5: Plan scaling
        scaling_out = self._scaling.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="scaling",
            data={"scaling_data": growth_out.result, "capacity_limits": targets.get("capacity", {})},
        ))
        results["scaling"] = scaling_out.to_dict()

        return {
            "flow_id": flow_id,
            "flow": "growth_cycle",
            "status": "completed",
            "result": results,
        }
