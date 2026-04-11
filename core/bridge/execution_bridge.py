"""ExecutionBridge — converts engine output into executable actions.

Engine says "set price to $29.99" → ExecutionBridge routes to Shopify API.
Engine says "send email campaign" → routes to email execution.

Features:
  - Action planning from engine output
  - Executor registry (target+action_type → executor)
  - Retry with exponential backoff on failure
  - Fallback executor when primary fails
  - Lifecycle tracking: planned → approved → executing → executed/failed
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("bridge.execution")

MAX_RETRIES = 2
RETRY_BACKOFF = [0.1, 0.5]  # seconds between retries


class ActionPlan:
    """A planned action with full lifecycle tracking."""

    def __init__(self, action_type: str, target: str, data: dict[str, Any],
                 priority: str = "medium", auto_execute: bool = False) -> None:
        self.action_id = generate_id("act")
        self.action_type = action_type
        self.target = target
        self.data = data
        self.priority = priority
        self.auto_execute = auto_execute
        self.status = "planned"
        self.created_at = time.time()
        self.approved_at: float | None = None
        self.execution_start: float | None = None
        self.execution_end: float | None = None
        self.attempt_count = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        result = {
            "action_id": self.action_id, "action_type": self.action_type,
            "target": self.target, "data": self.data, "priority": self.priority,
            "auto_execute": self.auto_execute, "status": self.status,
            "created_at": self.created_at, "attempt_count": self.attempt_count,
        }
        if self.errors:
            result["errors"] = self.errors
        if self.execution_end and self.execution_start:
            result["duration_ms"] = round((self.execution_end - self.execution_start) * 1000, 1)
        return result


class ExecutionBridge:
    """Converts engine results into action plans, dispatches with retry + fallback."""

    def __init__(self) -> None:
        self._action_queue: list[ActionPlan] = []
        self._executed: list[dict[str, Any]] = []
        self._executors: dict[str, Any] = {}
        self._fallback_executors: dict[str, Any] = {}

    def register_executor(self, target: str, action_type: str, executor: Any) -> None:
        key = f"{target}:{action_type}"
        self._executors[key] = executor
        logger.info("Registered executor for %s", key)

    def register_fallback(self, target: str, action_type: str, fallback_executor: Any) -> None:
        key = f"{target}:{action_type}"
        self._fallback_executors[key] = fallback_executor
        logger.info("Registered fallback executor for %s", key)

    def plan_actions(self, engine_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []

        selected = result.get("selected_products", [])
        if isinstance(selected, list):
            for product in selected[:10]:
                if isinstance(product, dict) and product.get("viable", True):
                    actions.append(ActionPlan("product.create_listing", "shopify", {"product": product, "source_engine": engine_name}, "medium"))

        recs = result.get("pricing_recommendations", [])
        if isinstance(recs, list):
            for rec in recs:
                if isinstance(rec, dict) and rec.get("action") in ("increase_price", "can_discount"):
                    pri = "high" if rec.get("action") == "increase_price" else "medium"
                    actions.append(ActionPlan("pricing.update", "shopify", {"recommendation": rec, "source_engine": engine_name}, pri))

        reorders = result.get("reorder_recommendations", [])
        if isinstance(reorders, list):
            for reorder in reorders:
                if isinstance(reorder, dict) and reorder.get("urgency") == "immediate":
                    actions.append(ActionPlan("inventory.reorder", "procurement", {"reorder": reorder, "source_engine": engine_name}, "high"))

        campaign = result.get("campaign_plan", {})
        if isinstance(campaign, dict) and campaign:
            actions.append(ActionPlan("marketing.launch_campaign", "multi_channel", {"campaign": campaign, "source_engine": engine_name}, "medium"))

        content = result.get("content_elements", {})
        if isinstance(content, dict) and content:
            actions.append(ActionPlan("content.publish", "cms", {"content": content, "source_engine": engine_name}, "low"))

        churn_risks = result.get("churn_risks", [])
        if isinstance(churn_risks, list):
            high_risk = [r for r in churn_risks if isinstance(r, dict) and r.get("risk_level") == "high"]
            if high_risk:
                actions.append(ActionPlan("customer.retention_campaign", "email", {"at_risk_customers": high_risk, "source_engine": engine_name}, "high"))

        for action in actions:
            self._action_queue.append(action)

        return [a.to_dict() for a in actions]

    def get_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        actions = self._action_queue
        if status:
            actions = [a for a in actions if a.status == status]
        return [a.to_dict() for a in actions]

    def approve_action(self, action_id: str) -> bool:
        for action in self._action_queue:
            if action.action_id == action_id:
                action.status = "approved"
                action.approved_at = time.time()
                return True
        return False

    def execute_approved(self) -> list[dict[str, Any]]:
        """Execute all approved actions with retry + fallback."""
        results = []
        for action in self._action_queue:
            if action.status != "approved":
                continue
            action.status = "executing"
            action.execution_start = time.time()

            result = self._execute_with_retry(action)

            action.execution_end = time.time()
            action.status = "executed" if result.get("success") else "failed"
            result["attempt_count"] = action.attempt_count
            if action.execution_start and action.execution_end:
                result["duration_ms"] = round((action.execution_end - action.execution_start) * 1000, 1)
            results.append(result)
            self._executed.append(result)
        return results

    def _execute_with_retry(self, action: ActionPlan) -> dict[str, Any]:
        """Execute with retry on failure, then try fallback executor."""
        key = f"{action.target}:{action.action_type}"
        executor = self._executors.get(key)

        # Try primary executor with retries
        if executor is not None:
            for attempt in range(MAX_RETRIES + 1):
                action.attempt_count = attempt + 1
                result = self._try_execute(action, executor, key)
                if result.get("success"):
                    return result
                action.errors.append(result.get("error", "unknown"))
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF[attempt])

            # Primary exhausted — try fallback
            fallback = self._fallback_executors.get(key)
            if fallback is not None:
                logger.info("Primary executor failed for %s, trying fallback", key)
                action.attempt_count += 1
                result = self._try_execute(action, fallback, f"{key}:fallback")
                if result.get("success"):
                    result["used_fallback"] = True
                    return result
                action.errors.append(result.get("error", "unknown"))

            # All retries + fallback exhausted
            return {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "target": action.target,
                "success": False,
                "error": f"All {action.attempt_count} attempts failed: {action.errors[-1]}",
                "all_errors": action.errors,
                "executor": key,
                "timestamp": time.time(),
            }

        # No executor registered — queued for manual
        logger.info("No executor for %s — action %s queued", key, action.action_id)
        return {
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "success": True,
            "message": f"Action {action.action_type} queued for {action.target} (no auto-executor)",
            "timestamp": time.time(),
        }

    @staticmethod
    def _try_execute(action: ActionPlan, executor: Any, executor_key: str) -> dict[str, Any]:
        """Single execution attempt."""
        try:
            method = getattr(executor, "execute", None) or getattr(executor, "run", None)
            if method:
                exec_result = method(action.data)
                success = exec_result.get("status") != "error" if isinstance(exec_result, dict) else True
                return {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "target": action.target,
                    "success": success,
                    "result": exec_result,
                    "executor": executor_key,
                    "timestamp": time.time(),
                }
            return {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "target": action.target,
                "success": False,
                "error": "Executor has no execute() or run() method",
                "executor": executor_key,
                "timestamp": time.time(),
            }
        except Exception as exc:
            logger.error("Executor %s attempt failed: %s", executor_key, exc)
            return {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "target": action.target,
                "success": False,
                "error": str(exc),
                "executor": executor_key,
                "timestamp": time.time(),
            }

    def get_execution_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._executed[-limit:])

    def get_execution_stats(self) -> dict[str, Any]:
        """Get execution performance metrics."""
        if not self._executed:
            return {"total": 0}

        successes = sum(1 for e in self._executed if e.get("success"))
        failures = len(self._executed) - successes
        durations = [e.get("duration_ms", 0) for e in self._executed if e.get("duration_ms")]
        by_type: dict[str, dict] = {}
        for e in self._executed:
            t = e.get("action_type", "unknown")
            if t not in by_type:
                by_type[t] = {"total": 0, "success": 0, "fail": 0}
            by_type[t]["total"] += 1
            if e.get("success"):
                by_type[t]["success"] += 1
            else:
                by_type[t]["fail"] += 1

        return {
            "total": len(self._executed),
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / max(len(self._executed), 1), 2),
            "avg_duration_ms": round(sum(durations) / max(len(durations), 1), 1) if durations else 0,
            "by_action_type": by_type,
        }

    def clear_queue(self) -> int:
        count = len(self._action_queue)
        self._action_queue.clear()
        return count
