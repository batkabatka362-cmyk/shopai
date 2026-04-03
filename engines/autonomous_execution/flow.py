"""AutonomousExecution Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Action Dispatcher → Progress Tracker → Error Handler → Result Validator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {actions, execution_config}, meta, error}
  Output: {status, data: {executed, failed, progress}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .action_dispatcher import dispatch_actions
from .progress_tracker import track_progress
from .error_handler import handle_errors
from .result_validator import validate_results
from .memory_reader import read_past_results
from .memory_writer import write_result


class AutonomousExecutionEngine:
    """AutonomousExecution Engine — orchestrator only, no logic."""

    ENGINE_NAME = "autonomous_execution"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full autonomous execution pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            AutonomousExecutionOutput dict.
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
        execution_config = data.get("execution_config", {})

        if not actions:
            return self._fail("Actions list is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Dispatch actions to appropriate tools ----
        action_dispatcher_result = dispatch_actions(
            actions=actions, execution_config=execution_config,
        )
        if action_dispatcher_result.get("status") == "error":
            return self._fail(
                f"Dispatch actions to appropriate tools failed: {action_dispatcher_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        action_dispatcher_data = action_dispatcher_result.get("result", {})

        # ---- Stage 3: Track execution progress ----
        progress_tracker_result = track_progress(
            actions=actions, execution_config=execution_config, action_dispatcher_data=action_dispatcher_data,
        )
        if progress_tracker_result.get("status") == "error":
            return self._fail(
                f"Track execution progress failed: {progress_tracker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        progress_tracker_data = progress_tracker_result.get("result", {})

        # ---- Stage 4: Handle execution errors with retry ----
        error_handler_result = handle_errors(
            actions=actions, execution_config=execution_config, action_dispatcher_data=action_dispatcher_data, progress_tracker_data=progress_tracker_data,
        )
        if error_handler_result.get("status") == "error":
            return self._fail(
                f"Handle execution errors with retry failed: {error_handler_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        error_handler_data = error_handler_result.get("result", {})

        # ---- Stage 5: Validate execution results ----
        result_validator_result = validate_results(
            actions=actions, execution_config=execution_config, action_dispatcher_data=action_dispatcher_data, progress_tracker_data=progress_tracker_data, error_handler_data=error_handler_data,
        )
        if result_validator_result.get("status") == "error":
            return self._fail(
                f"Validate execution results failed: {result_validator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        result_validator_data = result_validator_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "executed": result_validator_data.get("executed", []),
                "failed": result_validator_data.get("failed", []),
                "progress": result_validator_data.get("progress", {}),
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
