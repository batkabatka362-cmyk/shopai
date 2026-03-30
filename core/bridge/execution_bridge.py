"""ExecutionBridge — converts engine output into executable actions.

Engine says "set price to $29.99" → ExecutionBridge routes to Shopify API.
Engine says "send email campaign" → routes to email execution.

SAFETY: Only PLANS actions. Does not auto-execute destructive operations.
All actions go to action_queue for review before execution.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("bridge.execution")


class ActionPlan:
    """A planned action from engine output."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id, "action_type": self.action_type,
            "target": self.target, "data": self.data, "priority": self.priority,
            "auto_execute": self.auto_execute, "status": self.status,
        }


class ExecutionBridge:
    """Converts engine results into action plans."""

    def __init__(self) -> None:
        self._action_queue: list[ActionPlan] = []
        self._executed: list[dict[str, Any]] = []

    def plan_actions(self, engine_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract actionable items from engine result and create action plans."""
        actions = []

        # Product actions
        selected = result.get("selected_products", [])
        if isinstance(selected, list):
            for product in selected[:10]:
                if isinstance(product, dict) and product.get("viable", True):
                    action = ActionPlan(
                        action_type="product.create_listing",
                        target="shopify",
                        data={"product": product, "source_engine": engine_name},
                        priority="medium",
                    )
                    actions.append(action)

        # Pricing actions
        recs = result.get("pricing_recommendations", [])
        if isinstance(recs, list):
            for rec in recs:
                if isinstance(rec, dict) and rec.get("action") in ("increase_price", "can_discount"):
                    action = ActionPlan(
                        action_type="pricing.update",
                        target="shopify",
                        data={"recommendation": rec, "source_engine": engine_name},
                        priority="high" if rec.get("action") == "increase_price" else "medium",
                    )
                    actions.append(action)

        # Inventory actions
        reorders = result.get("reorder_recommendations", [])
        if isinstance(reorders, list):
            for reorder in reorders:
                if isinstance(reorder, dict) and reorder.get("urgency") == "immediate":
                    action = ActionPlan(
                        action_type="inventory.reorder",
                        target="procurement",
                        data={"reorder": reorder, "source_engine": engine_name},
                        priority="high",
                    )
                    actions.append(action)

        # Marketing actions
        campaign = result.get("campaign_plan", {})
        if isinstance(campaign, dict) and campaign:
            action = ActionPlan(
                action_type="marketing.launch_campaign",
                target="multi_channel",
                data={"campaign": campaign, "source_engine": engine_name},
                priority="medium",
            )
            actions.append(action)

        # Content actions
        content = result.get("content_elements", {})
        if isinstance(content, dict) and content:
            action = ActionPlan(
                action_type="content.publish",
                target="cms",
                data={"content": content, "source_engine": engine_name},
                priority="low",
            )
            actions.append(action)

        # Customer actions
        churn_risks = result.get("churn_risks", [])
        if isinstance(churn_risks, list):
            high_risk = [r for r in churn_risks if isinstance(r, dict) and r.get("risk_level") == "high"]
            if high_risk:
                action = ActionPlan(
                    action_type="customer.retention_campaign",
                    target="email",
                    data={"at_risk_customers": high_risk, "source_engine": engine_name},
                    priority="high",
                )
                actions.append(action)

        # Store in queue
        for action in actions:
            self._action_queue.append(action)

        return [a.to_dict() for a in actions]

    def get_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get action queue, optionally filtered by status."""
        actions = self._action_queue
        if status:
            actions = [a for a in actions if a.status == status]
        return [a.to_dict() for a in actions]

    def approve_action(self, action_id: str) -> bool:
        """Approve a planned action for execution."""
        for action in self._action_queue:
            if action.action_id == action_id:
                action.status = "approved"
                return True
        return False

    def execute_approved(self) -> list[dict[str, Any]]:
        """Execute all approved actions. Returns execution results."""
        results = []
        for action in self._action_queue:
            if action.status != "approved":
                continue
            # Route to appropriate executor
            result = self._route_and_execute(action)
            action.status = "executed" if result.get("success") else "failed"
            results.append(result)
            self._executed.append(result)
        return results

    def get_execution_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._executed[-limit:])

    def _route_and_execute(self, action: ActionPlan) -> dict[str, Any]:
        """Route action to the right executor."""
        # For now, log the action — real execution connects to Shopify/email/etc.
        logger.info("Executing action %s: %s → %s", action.action_id, action.action_type, action.target)
        return {
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "success": True,
            "message": f"Action {action.action_type} queued for {action.target}",
            "timestamp": time.time(),
        }

    def clear_queue(self) -> int:
        count = len(self._action_queue)
        self._action_queue.clear()
        return count
