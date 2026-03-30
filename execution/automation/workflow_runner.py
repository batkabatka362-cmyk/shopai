"""WorkflowRunner — executes named workflows defined as sequences of steps.

A workflow is a dict with a ``steps`` list.  Each step is a dict with at
minimum a ``type`` key.  Supported step types:

- ``"engine"``    — run a ShopAI engine (via engines.registry.get_engine).
- ``"condition"`` — branch on a context value.
- ``"loop"``      — iterate over a context list, running sub-steps per item.
- ``"task"``      — delegate to TaskExecutor.

Uses only the Python standard library (concurrent.futures for parallel steps).
"""

from __future__ import annotations

import concurrent.futures
import time
from datetime import datetime, timezone
from typing import Any

# Built-in workflow definitions (name → list of step dicts)
_BUILTIN_WORKFLOWS: dict[str, dict[str, Any]] = {
    "product_launch": {
        "steps": [
            {"type": "engine", "engine": "product_validation", "input_key": "product"},
            {"type": "engine", "engine": "content_generation", "input_key": "product"},
            {"type": "engine", "engine": "pricing", "input_key": "product"},
        ]
    },
    "campaign_setup": {
        "steps": [
            {"type": "engine", "engine": "audience_targeting", "input_key": "campaign"},
            {"type": "engine", "engine": "campaign", "input_key": "campaign"},
            {"type": "engine", "engine": "ads", "input_key": "campaign"},
        ]
    },
}


class WorkflowRunner:
    """Execute multi-step workflows with support for engine, condition, and loop steps."""

    def __init__(self) -> None:
        # Allow callers to register custom workflow definitions at runtime
        self._workflows: dict[str, dict[str, Any]] = dict(_BUILTIN_WORKFLOWS)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def register_workflow(self, name: str, definition: dict[str, Any]) -> None:
        """Register (or overwrite) a workflow definition by name."""
        self._workflows[name] = definition

    def run_workflow(
        self, workflow_name: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute all steps of a named workflow sequentially.

        Args:
            workflow_name: Registered workflow name (e.g. ``"product_launch"``).
            context:       Mutable dict passed through every step; each step
                           may read from and write to it.

        Returns:
            ``{"workflow": str, "status": "completed"|"error",
               "steps_run": int, "duration_s": float,
               "context": dict, "step_results": [...]}``
        """
        definition = self._workflows.get(workflow_name)
        if definition is None:
            return {
                "workflow": workflow_name,
                "status": "error",
                "error": f"Workflow '{workflow_name}' is not registered.",
                "steps_run": 0,
            }

        steps: list[dict[str, Any]] = definition.get("steps", [])
        ctx = dict(context)
        step_results: list[dict[str, Any]] = []
        start = time.monotonic()

        for idx, step in enumerate(steps):
            result = self.run_step(step, ctx)
            result["step_index"] = idx
            step_results.append(result)

            # Merge step output back into context
            if isinstance(result.get("output"), dict):
                ctx.update(result["output"])

            if result.get("status") == "error" and step.get("halt_on_error", True):
                return {
                    "workflow": workflow_name,
                    "status": "error",
                    "error": result.get("error", "Step failed"),
                    "steps_run": idx + 1,
                    "duration_s": round(time.monotonic() - start, 3),
                    "context": ctx,
                    "step_results": step_results,
                }

        return {
            "workflow": workflow_name,
            "status": "completed",
            "steps_run": len(steps),
            "duration_s": round(time.monotonic() - start, 3),
            "context": ctx,
            "step_results": step_results,
        }

    def run_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a single step dict against *context*.

        Returns:
            ``{"type": str, "status": "ok"|"error",
               "output": dict|None, "duration_s": float}``
        """
        step_type = step.get("type", "unknown")
        handler = self._resolve_step_type(step_type)
        start = time.monotonic()
        try:
            output = handler(step, context)
            return {
                "type": step_type,
                "status": "ok",
                "output": output,
                "duration_s": round(time.monotonic() - start, 3),
            }
        except Exception as exc:
            return {
                "type": step_type,
                "status": "error",
                "error": str(exc),
                "output": None,
                "duration_s": round(time.monotonic() - start, 3),
            }

    def run_parallel_steps(
        self, steps: list[dict[str, Any]], context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Execute *steps* concurrently using a thread pool.

        Each step receives a shallow copy of *context* so they don't
        interfere with each other.  Results are returned in submission order.

        Returns:
            List of step result dicts (same shape as :meth:`run_step`).
        """
        results: list[dict[str, Any]] = [{}] * len(steps)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(steps), 10)
        ) as pool:
            future_to_index = {
                pool.submit(self.run_step, step, dict(context)): idx
                for idx, step in enumerate(steps)
            }
            for future in concurrent.futures.as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    results[idx] = {
                        "type": steps[idx].get("type", "unknown"),
                        "status": "error",
                        "error": str(exc),
                        "output": None,
                        "duration_s": 0.0,
                    }
        return results

    # ------------------------------------------------------------------ #
    # Step type resolution                                                 #
    # ------------------------------------------------------------------ #

    def _resolve_step_type(self, step_type: str):
        """Map a step type string to a handler callable."""
        mapping = {
            "engine": self._handle_engine_step,
            "condition": self._handle_condition_step,
            "loop": self._handle_loop_step,
            "task": self._handle_task_step,
            "parallel": self._handle_parallel_step,
            "noop": lambda step, ctx: {},
        }
        return mapping.get(step_type, self._handle_unknown_step)

    def _handle_engine_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Run a ShopAI engine by name.

        Step keys:
            ``engine``    — engine name (required).
            ``input_key`` — key in context to pass as the engine's input.
            ``output_key``— key under which to store the engine's output.
        """
        from engines.registry import get_engine

        engine_name = step.get("engine", "")
        if not engine_name:
            raise ValueError("Engine step missing 'engine' key.")

        engine = get_engine(engine_name)
        input_key = step.get("input_key", "input")
        payload = context.get(input_key, context)

        # Engines expose a `run` method by convention
        if hasattr(engine, "run"):
            result = engine.run(payload)
        elif callable(engine):
            result = engine(payload)
        else:
            raise TypeError(f"Engine '{engine_name}' has no callable interface.")

        output_key = step.get("output_key", f"{engine_name}_result")
        return {output_key: result}

    def _handle_condition_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate a condition and run the matching branch.

        Step keys:
            ``condition_key`` — context key to evaluate (truthy/falsy).
            ``if_true``       — list of steps to run when truthy.
            ``if_false``      — list of steps to run when falsy.
        """
        key = step.get("condition_key", "")
        value = context.get(key)
        branch_steps = step.get("if_true", []) if value else step.get("if_false", [])

        branch_results = []
        for branch_step in branch_steps:
            result = self.run_step(branch_step, context)
            branch_results.append(result)
            if isinstance(result.get("output"), dict):
                context.update(result["output"])

        return {
            "branch_taken": "if_true" if value else "if_false",
            "branch_results": branch_results,
        }

    def _handle_loop_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Iterate over a context list, running sub-steps for each item.

        Step keys:
            ``iterate_key``  — context key holding the list to iterate.
            ``item_key``     — key under which to inject the current item.
            ``steps``        — list of steps to run per item.
        """
        iterate_key = step.get("iterate_key", "items")
        item_key = step.get("item_key", "item")
        sub_steps = step.get("steps", [])
        items = context.get(iterate_key, [])

        iteration_results = []
        for item in items:
            item_ctx = {**context, item_key: item}
            iter_step_results = []
            for sub_step in sub_steps:
                result = self.run_step(sub_step, item_ctx)
                iter_step_results.append(result)
                if isinstance(result.get("output"), dict):
                    item_ctx.update(result["output"])
            iteration_results.append(
                {"item": item, "step_results": iter_step_results}
            )

        return {"iterations": len(items), "results": iteration_results}

    def _handle_task_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Delegate to TaskExecutor."""
        from execution.automation.task_executor import TaskExecutor

        executor = TaskExecutor()
        task = {
            "type": step.get("task_type", "generic"),
            "config": step.get("config", {}),
            "retry_count": step.get("retry_count", 0),
            "timeout": step.get("timeout", 60),
            "context": context,
        }
        return executor.execute(task)

    def _handle_parallel_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Run a list of sub-steps in parallel."""
        sub_steps = step.get("steps", [])
        results = self.run_parallel_steps(sub_steps, context)
        return {"parallel_results": results}

    def _handle_unknown_step(
        self, step: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        raise ValueError(f"Unknown step type: {step.get('type')!r}")
