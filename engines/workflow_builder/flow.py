"""Workflow Builder Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Step Designer → Dependency Resolver →
  Validator → Executor Planner → Memory Writer → Output

Engine contract:
  Input:  {status, data: {steps, context}, meta, error}
  Output: {status, data: {workflow, validation, execution_plan, estimated_duration}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
import uuid
from typing import Any

from .step_designer import design_steps
from .dependency_resolver import resolve_dependencies
from .validator import validate_workflow
from .executor_planner import plan_execution
from .memory_reader import read_past_workflows
from .memory_writer import write_workflow_result


class WorkflowBuilderEngine:
    """Workflow Builder Engine — orchestrator only, no logic."""

    ENGINE_NAME = "workflow_builder"

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

        steps = data.get("steps", [])
        context = data.get("context", {})

        if not steps:
            return self._fail("Workflow steps are required", 0.0)

        # ---- Stage 1: Memory Reader ----
        _past = read_past_workflows(limit=5)

        # ---- Stage 2: Step Designer ----
        design_result = design_steps(steps=steps, context=context)
        if design_result.get("status") == "error":
            return self._fail(f"Step design failed: {design_result.get('error', 'unknown')}", time.monotonic() - start)
        designed_steps = design_result.get("designed_steps", [])

        # ---- Stage 3: Dependency Resolver ----
        dep_result = resolve_dependencies(designed_steps=designed_steps)
        if dep_result.get("status") == "error":
            return self._fail(f"Dependency resolution failed: {dep_result.get('error', 'unknown')}", time.monotonic() - start)
        dependency_graph = dep_result.get("dependency_graph", {})

        # ---- Stage 4: Validator ----
        val_result = validate_workflow(designed_steps=designed_steps, dependency_graph=dependency_graph)
        if val_result.get("status") == "error":
            return self._fail(f"Validation failed: {val_result.get('error', 'unknown')}", time.monotonic() - start)
        validation = val_result.get("validation", {})

        # ---- Stage 5: Executor Planner ----
        exec_result = plan_execution(designed_steps=designed_steps, dependency_graph=dependency_graph)
        if exec_result.get("status") == "error":
            return self._fail(f"Execution planning failed: {exec_result.get('error', 'unknown')}", time.monotonic() - start)
        execution_plan = exec_result.get("execution_plan", {})

        # ---- Stage 6: Build workflow output ----
        workflow_id = uuid.uuid4().hex[:12]
        workflow = {
            "id": workflow_id,
            "steps_ordered": dependency_graph.get("steps_ordered", []),
            "dependencies": dependency_graph.get("dependencies", {}),
            "parallel_groups": dependency_graph.get("parallel_groups", []),
        }

        estimated_duration = float(execution_plan.get("estimated_duration_seconds", 0))

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write = write_workflow_result(workflow=workflow, validation=validation, execution_plan=execution_plan)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "workflow": workflow,
                "validation": validation,
                "execution_plan": execution_plan,
                "estimated_duration": estimated_duration,
            },
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
