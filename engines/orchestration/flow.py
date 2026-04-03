"""Orchestration Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Workflow Planner → Dependency Resolver → Parallel Scheduler → Result Aggregator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {workflow, context}, meta, error}
  Output: {status, data: {execution_plan, results, timing, success_rate}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .workflow_planner import plan_workflow
from .dependency_resolver import resolve_dependencies
from .parallel_scheduler import schedule_parallel
from .result_aggregator import aggregate_results
from .memory_reader import read_past_results
from .memory_writer import write_result


class OrchestrationEngine:
    """Orchestration Engine — orchestrator only, no logic."""

    ENGINE_NAME = "orchestration"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full orchestration pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            OrchestrationOutput dict.
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

        workflow = data.get("workflow", [])
        context = data.get("context", {})

        if not workflow:
            return self._fail("Workflow definition is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Plan engine execution order ----
        workflow_planner_result = plan_workflow(
            workflow=workflow, context=context,
        )
        if workflow_planner_result.get("status") == "error":
            return self._fail(
                f"Plan engine execution order failed: {workflow_planner_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        workflow_planner_data = workflow_planner_result.get("result", {})

        # ---- Stage 3: Resolve engine dependencies ----
        dependency_resolver_result = resolve_dependencies(
            workflow=workflow, context=context, workflow_planner_data=workflow_planner_data,
        )
        if dependency_resolver_result.get("status") == "error":
            return self._fail(
                f"Resolve engine dependencies failed: {dependency_resolver_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        dependency_resolver_data = dependency_resolver_result.get("result", {})

        # ---- Stage 4: Schedule parallel execution ----
        parallel_scheduler_result = schedule_parallel(
            workflow=workflow, context=context, workflow_planner_data=workflow_planner_data, dependency_resolver_data=dependency_resolver_data,
        )
        if parallel_scheduler_result.get("status") == "error":
            return self._fail(
                f"Schedule parallel execution failed: {parallel_scheduler_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        parallel_scheduler_data = parallel_scheduler_result.get("result", {})

        # ---- Stage 5: Aggregate results from multiple engines ----
        result_aggregator_result = aggregate_results(
            workflow=workflow, context=context, workflow_planner_data=workflow_planner_data, dependency_resolver_data=dependency_resolver_data, parallel_scheduler_data=parallel_scheduler_data,
        )
        if result_aggregator_result.get("status") == "error":
            return self._fail(
                f"Aggregate results from multiple engines failed: {result_aggregator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        result_aggregator_data = result_aggregator_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "execution_plan": result_aggregator_data.get("execution_plan", []),
                "results": result_aggregator_data.get("results", {}),
                "timing": result_aggregator_data.get("timing", {}),
                "success_rate": result_aggregator_data.get("success_rate", 0.0),
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
