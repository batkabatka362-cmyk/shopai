"""SmartChain — intelligent workflow execution with branching, parallel, dynamic routing.

Upgrades EngineChain with:
  - Conditional branching: skip/add steps based on data
  - Parallel execution: run independent engines concurrently
  - Dynamic routing: choose next engine based on prior output
  - Error recovery: retry or fallback on failure
"""
from __future__ import annotations

import copy
import time
import threading
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id
from engines.registry import get_engine
from engines.base.engine_types import EngineInput, EngineStatus, normalize_engine_output

logger = get_logger("chaining.smart_chain")

Condition = Callable[[dict[str, Any]], bool]
Router = Callable[[dict[str, Any]], str | None]


class SmartStep:
    """A step in a smart chain with conditions and routing."""

    __slots__ = ("engine_name", "condition", "router", "required", "retry_count",
                 "parallel_with", "transform", "description")

    def __init__(
        self,
        engine_name: str,
        condition: Condition | None = None,
        router: Router | None = None,
        required: bool = True,
        retry_count: int = 0,
        parallel_with: list[str] | None = None,
        transform: Callable | None = None,
        description: str = "",
    ) -> None:
        self.engine_name = engine_name
        self.condition = condition
        self.router = router
        self.required = required
        self.retry_count = retry_count
        self.parallel_with = parallel_with or []
        self.transform = transform
        self.description = description


class SmartChain:
    """Intelligent engine chain with branching, parallel, and dynamic routing."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._steps: list[SmartStep] = []

    def add(
        self,
        engine_name: str,
        condition: Condition | None = None,
        required: bool = True,
        retry_count: int = 0,
        description: str = "",
    ) -> "SmartChain":
        self._steps.append(SmartStep(engine_name, condition=condition, required=required,
                                      retry_count=retry_count, description=description))
        return self

    def add_conditional(
        self,
        condition: Condition,
        if_true: str,
        if_false: str | None = None,
        description: str = "",
    ) -> "SmartChain":
        """Add a conditional branch — runs if_true engine when condition met, if_false otherwise."""
        def router(data: dict[str, Any]) -> str | None:
            return if_true if condition(data) else if_false
        self._steps.append(SmartStep(if_true, router=router, description=description))
        return self

    def add_parallel(self, engines: list[str], description: str = "") -> "SmartChain":
        """Add parallel execution — all engines run concurrently."""
        main = engines[0]
        self._steps.append(SmartStep(main, parallel_with=engines[1:], description=description))
        return self

    def add_dynamic(self, router: Router, description: str = "") -> "SmartChain":
        """Add dynamic routing — router function decides which engine to run."""
        self._steps.append(SmartStep("_dynamic", router=router, description=description))
        return self

    def run(self, initial_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the smart chain."""
        chain_id = generate_id("smart")
        start = time.monotonic()
        context = copy.deepcopy(initial_data)
        results = []

        logger.info("SmartChain '%s' started (id=%s, steps=%d)", self.name, chain_id, len(self._steps))

        for i, step in enumerate(self._steps):
            # Dynamic routing
            engine_name = step.engine_name
            if step.router:
                engine_name = step.router(context)
                if engine_name is None:
                    results.append({"step": i, "engine": "skipped", "status": "skipped", "reason": "router returned None"})
                    continue

            # Conditional check
            if step.condition and not step.condition(context):
                results.append({"step": i, "engine": engine_name, "status": "skipped", "reason": "condition not met"})
                continue

            # Parallel execution
            if step.parallel_with:
                all_engines = [engine_name] + step.parallel_with
                par_results = self._run_parallel(all_engines, context, chain_id, i)
                results.extend(par_results)
                for pr in par_results:
                    if pr.get("output"):
                        context.update(pr["output"])
                continue

            # Sequential execution with retry
            step_result = self._run_step(engine_name, context, chain_id, i, step.retry_count)
            results.append(step_result)

            if step_result.get("status") == "completed" and step_result.get("output"):
                context.update(step_result["output"])
            elif step.required and step_result.get("status") != "completed":
                logger.error("SmartChain '%s' stopped: required step %d failed", self.name, i)
                break

        elapsed = time.monotonic() - start
        completed = sum(1 for r in results if r.get("status") == "completed")
        total = len(results)

        return {
            "chain_id": chain_id,
            "chain_name": self.name,
            "status": "completed" if completed == total else "partial" if completed > 0 else "failed",
            "completed_steps": completed,
            "total_steps": total,
            "elapsed_seconds": round(elapsed, 3),
            "steps": results,
            "final_context_keys": list(context.keys()),
        }

    def _run_step(self, engine_name: str, context: dict, chain_id: str, index: int, retries: int) -> dict:
        """Run a single engine step with retry."""
        for attempt in range(retries + 1):
            start = time.monotonic()
            try:
                engine = get_engine(engine_name)
                inp = EngineInput(
                    task_id=f"{chain_id}_s{index}_a{attempt}",
                    engine_name=engine_name,
                    data=copy.deepcopy(context),
                )
                # Try dict-based input first (new flow.py engines), fall back to EngineInput (legacy)
                dict_input = {"status": "success", "data": inp.data, "meta": {}, "error": None}
                try:
                    raw_output = engine.run(dict_input)
                except (TypeError, AttributeError):
                    raw_output = engine.run(inp)
                output = normalize_engine_output(raw_output, inp)
                elapsed = time.monotonic() - start

                return {
                    "step": index,
                    "engine": engine_name,
                    "status": output.status.value,
                    "elapsed": round(elapsed, 3),
                    "attempt": attempt + 1,
                    "output": output.result if output.status == EngineStatus.COMPLETED else {},
                    "error": output.error,
                }
            except Exception as exc:
                if attempt == retries:
                    return {"step": index, "engine": engine_name, "status": "failed", "error": str(exc), "attempt": attempt + 1}

        return {"step": index, "engine": engine_name, "status": "failed", "error": "max retries exceeded"}

    def _run_parallel(self, engines: list[str], context: dict, chain_id: str, index: int) -> list[dict]:
        """Run multiple engines in parallel using threads."""
        results: list[dict] = [None] * len(engines)
        threads = []

        def worker(idx: int, eng_name: str):
            results[idx] = self._run_step(eng_name, context, chain_id, index, 0)

        for idx, eng in enumerate(engines):
            t = threading.Thread(target=worker, args=(idx, eng))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=60)

        return [r for r in results if r is not None]
