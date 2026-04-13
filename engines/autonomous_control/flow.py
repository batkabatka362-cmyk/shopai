"""Autonomous Control Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Safety Checker → Resource Monitor → Governor →
  Rollback Manager → Memory Writer → Output

Engine contract:
  Input:  {status, data: {actions, safety_limits, resource_budget}, meta, error}
  Output: {status, data: {approved, blocked, resource_usage, rollback_points}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .safety_checker import check_safety
from .resource_monitor import monitor_resources
from .rollback_manager import create_rollback_points
from .governor import govern_execution
from .memory_reader import read_past_controls
from .memory_writer import write_control_result


class AutonomousControlEngine:
    """Autonomous Control Engine — orchestrator only, no logic."""

    ENGINE_NAME = "autonomous_control"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full autonomous control pipeline."""
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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

        actions = data.get("actions", [])
        safety_limits = data.get("safety_limits", {})
        resource_budget = data.get("resource_budget", {})

        if not actions:
            return self._fail("Actions list is required", 0.0)

        # ---- Stage 1: Read past controls (non-blocking) ----
        _past = read_past_controls(limit=5)

        # ---- Stage 2: Safety Checker ----
        safety_result = check_safety(
            actions=actions,
            safety_limits=safety_limits,
        )
        if safety_result.get("status") == "error":
            return self._fail(
                f"Safety check failed: {safety_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        safety_checks = safety_result.get("checks", [])

        # ---- Stage 3: Resource Monitor ----
        resource_result = monitor_resources(
            actions=actions,
            resource_budget=resource_budget,
        )
        if resource_result.get("status") == "error":
            return self._fail(
                f"Resource monitoring failed: {resource_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        resource_usage = resource_result.get("usage", {})

        # ---- Stage 4: Governor ----
        governor_result = govern_execution(
            actions=actions,
            safety_limits=safety_limits,
            resource_usage=resource_usage,
        )
        if governor_result.get("status") == "error":
            return self._fail(
                f"Governor failed: {governor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        governor_decisions = governor_result.get("decisions", [])

        # ---- Stage 5: Build approved/blocked lists ----
        safety_map = {c["action_id"]: c for c in safety_checks}
        governor_map = {d["action_id"]: d for d in governor_decisions}

        approved: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []

        for action in actions:
            action_id = str(action.get("id", "unknown"))
            sc = safety_map.get(action_id, {})
            gd = governor_map.get(action_id, {})

            if sc.get("safe", False) and gd.get("allowed", False):
                approved.append({"action": action, "safe": True})
            else:
                reason = sc.get("reason", "") if not sc.get("safe", False) else gd.get("reason", "Governor blocked")
                blocked.append({"action": action, "reason": reason})

        # ---- Stage 6: Rollback Manager ----
        approved_actions = [a["action"] for a in approved]
        rollback_result = create_rollback_points(approved_actions=approved_actions)
        if rollback_result.get("status") == "error":
            return self._fail(
                f"Rollback creation failed: {rollback_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        rollback_points = rollback_result.get("rollback_points", [])

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_control_result(
            approved=approved,
            blocked=blocked,
            resource_usage=resource_usage,
            rollback_points=rollback_points,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "approved": approved,
                "blocked": blocked,
                "resource_usage": resource_usage,
                "rollback_points": rollback_points,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

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
