"""Execution Intelligence — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Task Parser → Task Validator → Tool Selector → Execution Router →
  Action Executor → (Retry Handler ↔ Error Handler) → Result Collector →
  Status Reporter → Memory Writer → Output

Engine contract:
  Input:  {status, data: {actions: [...]}, meta, error}
  Output: {status, data: {executed, failed, results, logs}, meta: {engine, ...}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .task_parser import parse_action_plan
from .task_validator import validate_tasks
from .tool_selector import select_tools
from .execution_router import route_tasks
from .action_executor import execute_task
from .result_collector import collect_results
from .status_reporter import generate_status_report
from .retry_handler import build_retry_state, should_retry, record_attempt, wait_for_retry
from .error_handler import classify_error
from .memory_reader import read_past_executions, compute_input_hash
from .memory_writer import write_execution_result


class ExecutionIntelligenceEngine:
    """Execution Intelligence Engine — orchestrator only, no logic."""

    ENGINE_NAME = "execution_intelligence"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full execution intelligence pipeline.

        Args:
            input_payload: ActionPlan dict from decision engine.

        Returns:
            ExecutionIntelligenceOutput dict.
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

        actions = data.get("actions", [])
        if not isinstance(actions, list) or not actions:
            return self._fail("No actions provided in input", 0.0)

        # ---- Stage 1: Read past executions (non-blocking) ----
        input_hash = compute_input_hash(data)
        _past = read_past_executions(limit=5)

        # ---- Stage 2: Parse action plan into tasks ----
        parse_result = parse_action_plan(actions)
        if parse_result.get("status") == "error":
            return self._fail(
                f"Task parsing failed: {parse_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        parsed_tasks = parse_result.get("tasks", [])
        all_logs: list[str] = list(parse_result.get("logs", []))

        if not parsed_tasks:
            return self._fail("No valid tasks parsed from actions", time.monotonic() - start)

        # ---- Stage 3: Validate tasks ----
        validation_result = validate_tasks(parsed_tasks)
        if validation_result.get("status") == "error":
            return self._fail(
                f"Task validation failed: {validation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        valid_tasks = validation_result.get("valid_tasks", [])
        invalid_tasks = validation_result.get("invalid_tasks", [])
        all_logs.extend(validation_result.get("logs", []))

        if not valid_tasks:
            return self._fail(
                f"No tasks passed validation ({len(invalid_tasks)} invalid)",
                time.monotonic() - start,
            )

        # ---- Stage 4: Select tools ----
        tool_result = select_tools(valid_tasks)
        if tool_result.get("status") == "error":
            return self._fail(
                f"Tool selection failed: {tool_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tool_selections = tool_result.get("selections", [])
        all_logs.extend(tool_result.get("logs", []))

        # ---- Stage 5: Route tasks into execution batches ----
        route_result = route_tasks(valid_tasks, tool_selections)
        if route_result.get("status") == "error":
            return self._fail(
                f"Routing failed: {route_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        batches = route_result.get("batches", [])
        all_logs.extend(route_result.get("logs", []))

        # ---- Stage 6: Execute tasks batch by batch with retry ----
        selection_map: dict[str, dict[str, Any]] = {}
        for sel in tool_selections:
            selection_map[sel.get("task_id", "")] = sel

        all_execution_results: list[dict[str, Any]] = []

        for batch_index, batch in enumerate(batches):
            batch_results = self._execute_batch(
                batch, selection_map, batch_index, all_logs,
            )
            all_execution_results.extend(batch_results)

        # ---- Stage 7: Collect results ----
        collected = collect_results(all_execution_results)
        all_logs.extend(collected.get("logs", []))

        # ---- Stage 8: Generate status report ----
        elapsed = time.monotonic() - start
        report_result = generate_status_report(
            collected=collected,
            execution_results=all_execution_results,
            total_elapsed_seconds=elapsed,
        )
        report = report_result.get("report", {})
        all_logs.extend(
            entry for entry in report.get("logs", [])
            if entry not in all_logs
        )

        # ---- Stage 9: Write to memory (non-fatal) ----
        _write_result = write_execution_result(
            input_hash=input_hash,
            status_report=report,
            executed=collected.get("executed", []),
            failed=collected.get("failed", []),
            results=collected.get("results", []),
            logs=all_logs,
        )

        # ---- Stage 10: Assemble output ----
        overall_status = report.get("overall_status", "fail")

        return {
            "status": overall_status,
            "data": {
                "executed": collected.get("executed", []),
                "failed": collected.get("failed", []),
                "results": collected.get("results", []),
                "logs": all_logs,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(time.monotonic() - start, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Batch execution with retry (pure orchestration, no business logic)
    # -------------------------------------------------------------------

    def _execute_batch(
        self,
        batch: list[dict[str, Any]],
        selection_map: dict[str, dict[str, Any]],
        batch_index: int,
        logs: list[str],
    ) -> list[dict[str, Any]]:
        """Execute all tasks in a batch, with retry on failure.

        Tasks within a batch can conceptually run in parallel, but are
        executed sequentially here. Retry is handled per-task.
        """
        results: list[dict[str, Any]] = []

        for task in batch:
            task_id = task.get("task_id", "unknown")
            action_type = task.get("action_type", "")
            selection = selection_map.get(task_id, {})

            # Build initial retry state
            retry_state = build_retry_state(task_id, action_type)

            # First attempt
            result = execute_task(task, selection)

            # Retry loop if failed
            while result.get("status") == "fail":
                error_msg = result.get("error", "unknown error")
                classification = classify_error(
                    task_id, error_msg, action_type,
                )
                error_cls = classification.get("classification", {})

                retry_state = record_attempt(retry_state, error_msg)

                if not should_retry(retry_state, error_cls):
                    logs.append(
                        f"Task {task_id} ({action_type}): retry exhausted or "
                        f"non-recoverable ({error_cls.get('recovery_strategy', 'skip')})"
                    )
                    break

                attempts = retry_state.get("attempts", 0)
                delay = retry_state.get("next_delay_seconds", 1.0)
                logs.append(
                    f"Task {task_id} ({action_type}): retrying "
                    f"(attempt {attempts}/{retry_state.get('max_retries', 3)}, "
                    f"delay {delay:.2f}s)"
                )

                wait_for_retry(retry_state)
                result = execute_task(task, selection)

            results.append(result)

        return results

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
