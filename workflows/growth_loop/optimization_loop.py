"""Optimization Loop

Chains: analytics → experimentation → growth_loop → meta_learning

The continuous improvement cycle:
  Measure → Experiment → Learn → Improve → Repeat
"""

from __future__ import annotations

from typing import Any

from engines.registry import get_engine
from engines.base import EngineInput
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("workflow.optimization_loop")


class OptimizationLoop:
    """Continuous optimization feedback loop."""

    def __init__(self) -> None:
        self._analytics = get_engine("analytics")
        self._experimentation = get_engine("experimentation")
        self._growth_loop = get_engine("growth_loop")
        self._meta_learning = get_engine("meta_learning")

    def run(self, metrics: dict[str, Any], hypothesis: dict[str, Any]) -> dict[str, Any]:
        flow_id = generate_id("flow")
        logger.info("[%s] Starting optimization loop", flow_id)
        results: dict[str, Any] = {}

        # Step 1: Measure current state
        analytics_out = self._analytics.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="analytics",
            data={"metrics_data": metrics, "time_range": "7d"},
        ))
        results["measure"] = analytics_out.to_dict()

        # Step 2: Run experiment
        experiment_out = self._experimentation.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="experimentation",
            data={"experiment_config": analytics_out.result, "hypothesis": hypothesis},
        ))
        results["experiment"] = experiment_out.to_dict()

        # Step 3: Feedback loop
        loop_out = self._growth_loop.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="growth_loop",
            data={"loop_data": experiment_out.result, "metrics": metrics},
        ))
        results["feedback"] = loop_out.to_dict()

        # Step 4: Learn
        learn_out = self._meta_learning.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="meta_learning",
            data={"learning_data": loop_out.result, "performance_history": metrics},
        ))
        results["learning"] = learn_out.to_dict()

        return {
            "flow_id": flow_id,
            "flow": "optimization_loop",
            "status": "completed",
            "result": results,
        }
