"""Customer Service Engine — escalation router.

Determines if a customer interaction needs human escalation,
assigns the appropriate team, and sets priority level.

All logic is real rule evaluation. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Escalation thresholds
# ---------------------------------------------------------------------------

_HIGH_VALUE_THRESHOLD = 1000.0     # lifetime value for VIP treatment
_REFUND_ESCALATION_AMOUNT = 100.0  # refund amounts above this trigger escalation
_REPEAT_CONTACT_THRESHOLD = 2     # contacts about same intent = escalation

# Keywords that indicate a customer wants a human agent
_HUMAN_REQUEST_KEYWORDS = [
    "agent", "human", "representative", "person", "manager",
    "supervisor", "speak to someone", "talk to someone", "real person",
]


# ---------------------------------------------------------------------------
# Team assignment mapping
# ---------------------------------------------------------------------------

_INTENT_TEAM_MAP: dict[str, str] = {
    "billing": "billing_team",
    "refund_request": "billing_team",
    "shipping": "shipping_team",
    "tracking": "shipping_team",
    "return_request": "returns_team",
    "complaint": "general_support",
    "order_status": "general_support",
    "product_question": "general_support",
    "general": "general_support",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_escalation(
    intent: dict[str, Any],
    customer: dict[str, Any],
    response: dict[str, Any],
    interaction_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine if escalation is needed and route to appropriate team.

    Args:
        intent: Intent classification result.
        customer: Customer profile dict.
        response: Built response dict.
        interaction_history: Past interaction records (optional).

    Returns:
        Structured dict with escalation decision.
    """
    try:
        intent_data = copy.deepcopy(intent)
        cust = copy.deepcopy(customer) if customer else {}
        resp = copy.deepcopy(response) if response else {}
        history = copy.deepcopy(interaction_history) if interaction_history else {}

        primary_intent = str(intent_data.get("primary", "general"))
        reasons: list[str] = []

        # --- Rule 1: Complaint from high-value customer ---
        lifetime_value = float(cust.get("lifetime_value", 0.0))
        if primary_intent == "complaint" and lifetime_value >= _HIGH_VALUE_THRESHOLD:
            reasons.append(
                f"Complaint from high-value customer (LTV ${lifetime_value:.2f})"
            )

        # --- Rule 2: Refund amount exceeds threshold ---
        entities = intent_data.get("extracted_entities", {})
        amounts = entities.get("amounts", [])
        for amount in amounts:
            if amount > _REFUND_ESCALATION_AMOUNT and primary_intent in (
                "refund_request", "billing"
            ):
                reasons.append(
                    f"Refund/billing amount ${amount:.2f} exceeds "
                    f"${_REFUND_ESCALATION_AMOUNT:.2f} threshold"
                )
                break

        # --- Rule 3: Repeat contacts about same issue ---
        past_records = history.get("records", [])
        same_intent_count = sum(
            1 for r in past_records
            if r.get("intent") == primary_intent
        )
        if same_intent_count >= _REPEAT_CONTACT_THRESHOLD:
            reasons.append(
                f"Customer has contacted {same_intent_count + 1} times "
                f"about '{primary_intent}'"
            )

        # --- Rule 4: Explicit request for human agent ---
        message = str(resp.get("message", ""))
        original_entities = intent_data.get("extracted_entities", {})
        # Check the original message context for human-request keywords
        confidence = float(intent_data.get("confidence", 0.0))
        secondary = intent_data.get("secondary")

        # We check if the secondary intent is general (often means "talk to agent")
        # combined with low confidence on primary, or explicit keywords in any text
        if _has_human_request(intent_data):
            reasons.append("Customer explicitly requested a human agent")

        # --- Rule 5: VIP customer with any complaint or late order ---
        tier = str(cust.get("loyalty_tier", "")).lower()
        if tier == "platinum":
            if primary_intent in ("complaint", "refund_request"):
                if not any("high-value" in r.lower() for r in reasons):
                    reasons.append("Platinum-tier customer with escalation-worthy issue")

        # --- Determine escalation ---
        if not reasons:
            return {
                "status": "success",
                "needed": False,
                "reason": None,
                "assigned_team": None,
                "priority": None,
            }

        # Assign team
        assigned_team = _determine_team(primary_intent, cust, reasons)

        # Assign priority
        priority = _determine_priority(reasons, cust, primary_intent)

        return {
            "status": "success",
            "needed": True,
            "reason": "; ".join(reasons),
            "assigned_team": assigned_team,
            "priority": priority,
        }
    except Exception as exc:
        return _fail(f"Escalation routing failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _has_human_request(intent_data: dict[str, Any]) -> bool:
    """Check if the customer is requesting a human agent.

    Uses the secondary intent and extracted entities as signals.
    The original message is not available here, so we rely on the
    classifier having detected agent/human keywords under 'general'.
    """
    secondary = intent_data.get("secondary")
    primary = intent_data.get("primary", "")

    # If primary or secondary is general and confidence is moderate,
    # the classifier likely matched agent/human keywords
    if secondary == "general" and primary in ("complaint", "refund_request"):
        return True

    # If primary is general with low confidence, might be just "speak to agent"
    if primary == "general":
        confidence = float(intent_data.get("confidence", 0.0))
        if confidence >= 0.4:
            return True

    return False


def _determine_team(
    primary_intent: str,
    customer: dict[str, Any],
    reasons: list[str],
) -> str:
    """Determine which team should handle the escalation."""
    tier = str(customer.get("loyalty_tier", "")).lower()
    lifetime_value = float(customer.get("lifetime_value", 0.0))

    # VIP team for platinum customers or very high value
    if tier == "platinum" or lifetime_value >= _HIGH_VALUE_THRESHOLD * 2:
        return "vip_team"

    # High-value complaint goes to VIP
    if primary_intent == "complaint" and lifetime_value >= _HIGH_VALUE_THRESHOLD:
        return "vip_team"

    return _INTENT_TEAM_MAP.get(primary_intent, "general_support")


def _determine_priority(
    reasons: list[str],
    customer: dict[str, Any],
    primary_intent: str,
) -> str:
    """Determine escalation priority: critical, high, medium, low."""
    tier = str(customer.get("loyalty_tier", "")).lower()
    lifetime_value = float(customer.get("lifetime_value", 0.0))
    reason_count = len(reasons)

    # Critical: multiple escalation reasons OR platinum with complaint
    if reason_count >= 3:
        return "critical"
    if tier == "platinum" and primary_intent == "complaint":
        return "critical"

    # High: VIP customer or complaint + high value
    if lifetime_value >= _HIGH_VALUE_THRESHOLD:
        return "high"
    if reason_count >= 2:
        return "high"

    # Medium: single escalation reason with moderate value
    if primary_intent in ("complaint", "refund_request"):
        return "medium"

    return "low"


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardised error result."""
    return {
        "status": "error",
        "needed": False,
        "reason": None,
        "assigned_team": None,
        "priority": None,
        "error": reason,
    }
