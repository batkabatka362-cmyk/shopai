"""Meta-Intelligence Governance — activity monitor.

Monitors incoming system activity, classifies by type
(decision / execution / learning), and extracts key attributes.

Model note: Pure rule-based classification — no model needed.
"""
from __future__ import annotations

import copy
import time
import uuid
from typing import Any


# Actions that indicate a decision is being made (not yet executed)
_DECISION_ACTIONS = frozenset({
    "launch_ad", "change_price", "create_campaign", "set_budget",
    "select_audience", "choose_supplier", "plan_promotion",
    "allocate_budget", "set_discount", "schedule_email",
})

# Actions that indicate something is being executed right now
_EXECUTION_ACTIONS = frozenset({
    "execute_order", "send_notification", "publish_content",
    "process_payment", "ship_order", "update_inventory",
    "deploy_campaign", "activate_rule",
})

# Actions that indicate learning / data gathering
_LEARNING_ACTIONS = frozenset({
    "collect_data", "train_model", "update_segment",
    "refresh_forecast", "analyze_feedback", "recalculate_scores",
})

# Severity classification by action type
_HIGH_SEVERITY_ACTIONS = frozenset({
    "launch_ad", "change_price", "execute_order", "process_payment",
    "set_budget", "allocate_budget", "deploy_campaign",
})

_CRITICAL_SEVERITY_ACTIONS = frozenset({
    "delete_product", "refund_order", "disable_store",
    "override_safety", "bulk_price_change",
})


def monitor_activity(
    source_engine: str,
    action: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Monitor and classify a system activity.

    Args:
        source_engine: Name of the engine producing this activity.
        action: The proposed action dict (must have 'type').
        context: Current system context.

    Returns:
        Structured dict with MonitorResult shape.
    """
    try:
        action = copy.deepcopy(action)
        context = copy.deepcopy(context)

        action_type = str(action.get("type", "unknown"))
        activity_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        classification = _classify_activity(action_type)
        severity = _classify_severity(action_type, action, context)
        requires_deep = severity in ("high", "critical") or classification == "execution"

        activity: dict[str, Any] = {
            "activity_id": activity_id,
            "source_engine": source_engine,
            "activity_type": classification,
            "action_type": action_type,
            "action_details": action,
            "context": context,
            "timestamp": timestamp,
        }

        return {
            "status": "success",
            "activity": activity,
            "classification": classification,
            "severity": severity,
            "requires_deep_check": requires_deep,
        }
    except Exception as exc:
        return {
            "status": "error",
            "activity": None,
            "classification": "unknown",
            "severity": "high",
            "requires_deep_check": True,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_activity(action_type: str) -> str:
    """Classify action into decision / execution / learning."""
    if action_type in _DECISION_ACTIONS:
        return "decision"
    if action_type in _EXECUTION_ACTIONS:
        return "execution"
    if action_type in _LEARNING_ACTIONS:
        return "learning"
    # Default: treat unknown actions as decisions (needs governance)
    return "decision"


def _classify_severity(
    action_type: str,
    action: dict[str, Any],
    context: dict[str, Any],
) -> str:
    """Determine severity level of the activity."""
    if action_type in _CRITICAL_SEVERITY_ACTIONS:
        return "critical"

    if action_type in _HIGH_SEVERITY_ACTIONS:
        # Escalate to critical if budget is large
        budget = float(action.get("budget", 0))
        if budget > 1000:
            return "critical"
        return "high"

    # Medium for execution actions not already classified
    if action_type in _EXECUTION_ACTIONS:
        return "medium"

    # Learning actions are low severity
    if action_type in _LEARNING_ACTIONS:
        return "low"

    # Unknown action types default to medium
    return "medium"
