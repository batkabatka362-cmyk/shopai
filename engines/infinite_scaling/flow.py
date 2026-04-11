"""InfiniteScaling Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Growth Analyzer → Bottleneck Finder → Capacity Planner → Scaling Advisor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {metrics, resources, growth_targets}, meta, error}
  Output: {status, data: {growth_trajectory, bottlenecks, capacity_plan, scaling_recommendations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .growth_analyzer import analyze_growth
from .bottleneck_finder import find_bottlenecks
from .capacity_planner import plan_capacity
from .scaling_advisor import advise_scaling
from .memory_reader import read_past_results
from .memory_writer import write_result


class InfiniteScalingEngine:
    """InfiniteScaling Engine — orchestrator only, no logic."""

    ENGINE_NAME = "infinite_scaling"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full infinite scaling pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            InfiniteScalingOutput dict.
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

        metrics = data.get("metrics", {})
        resources = data.get("resources", {})
        growth_targets = data.get("growth_targets", {})

        if not metrics:
            return self._fail("Metrics data is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Analyze current growth trajectory ----
        growth_analyzer_result = analyze_growth(
            metrics=metrics, resources=resources, growth_targets=growth_targets,
        )
        if growth_analyzer_result.get("status") == "error":
            return self._fail(
                f"Analyze current growth trajectory failed: {growth_analyzer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        growth_analyzer_data = growth_analyzer_result.get("result", {})

        # ---- Stage 3: Find scaling bottlenecks ----
        bottleneck_finder_result = find_bottlenecks(
            metrics=metrics, resources=resources, growth_targets=growth_targets, growth_analyzer_data=growth_analyzer_data,
        )
        if bottleneck_finder_result.get("status") == "error":
            return self._fail(
                f"Find scaling bottlenecks failed: {bottleneck_finder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        bottleneck_finder_data = bottleneck_finder_result.get("result", {})

        # ---- Stage 4: Plan capacity for growth ----
        capacity_planner_result = plan_capacity(
            metrics=metrics, resources=resources, growth_targets=growth_targets, growth_analyzer_data=growth_analyzer_data, bottleneck_finder_data=bottleneck_finder_data,
        )
        if capacity_planner_result.get("status") == "error":
            return self._fail(
                f"Plan capacity for growth failed: {capacity_planner_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        capacity_planner_data = capacity_planner_result.get("result", {})

        # ---- Stage 5: Advise on scaling strategy ----
        scaling_advisor_result = advise_scaling(
            metrics=metrics, resources=resources, growth_targets=growth_targets, growth_analyzer_data=growth_analyzer_data, bottleneck_finder_data=bottleneck_finder_data, capacity_planner_data=capacity_planner_data,
        )
        if scaling_advisor_result.get("status") == "error":
            return self._fail(
                f"Advise on scaling strategy failed: {scaling_advisor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scaling_advisor_data = scaling_advisor_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "growth_trajectory": scaling_advisor_data.get("growth_trajectory", {}),
                "bottlenecks": scaling_advisor_data.get("bottlenecks", []),
                "capacity_plan": scaling_advisor_data.get("capacity_plan", {}),
                "scaling_recommendations": scaling_advisor_data.get("scaling_recommendations", []),
        }
        _write_result = write_result(output_data=output_data)

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": output_data,
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
