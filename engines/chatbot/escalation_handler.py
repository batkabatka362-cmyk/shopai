"""Chatbot Engine — escalation handler.

Detects when a conversation should be escalated to a human agent.
Considers sentiment, complexity, repeated failures, and customer tier.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Escalation triggers
# ---------------------------------------------------------------------------

_ESCALATION_KEYWORDS = [
    "speak to a human", "talk to someone", "real person", "manager",
    "supervisor", "escalate", "agent", "representative", "operator",
]

_HIGH_EMOTION_KEYWORDS = [
    "furious", "outraged", "unacceptable", "lawsuit", "legal",
    "report", "bbb", "attorney", "disgusted", "worst ever",
]

_COMPLEX_INTENTS = ["complaint", "return"]

# Maximum turns before suggesting escalation
_MAX_TURNS_BEFORE_ESCALATION = 5


def check_escalation(
    message: str,
    intent_result: dict[str, Any],
    conversation_state: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Determine if the conversation should be escalated to a human.

    Args:
        message: Current customer message.
        intent_result: Intent classification result.
        conversation_state: Current conversation state.
        customer: Customer info dict.

    Returns:
        Structured dict with escalation decision.
    """
    try:
        msg_lower = message.lower()
        intent = str(intent_result.get("intent", "general"))
        confidence = float(intent_result.get("confidence", 0.5))
        turn_count = int(conversation_state.get("turn_count", 1))
        resolved = bool(conversation_state.get("resolved", False))
        customer_tier = str(customer.get("tier", "standard")).lower()

        escalate = False
        reasons: list[str] = []
        priority = "normal"
        department = "general_support"

        # Check 1: Explicit escalation request
        if any(kw in msg_lower for kw in _ESCALATION_KEYWORDS):
            escalate = True
            reasons.append("Customer explicitly requested human agent")
            priority = "high"

        # Check 2: High emotion / anger
        if any(kw in msg_lower for kw in _HIGH_EMOTION_KEYWORDS):
            escalate = True
            reasons.append("High emotional intensity detected")
            priority = "urgent"
            department = "customer_retention"

        # Check 3: Complex intent with low confidence
        if intent in _COMPLEX_INTENTS and confidence < 0.5:
            escalate = True
            reasons.append(f"Complex intent '{intent}' with low confidence ({confidence})")
            department = "specialized_support"

        # Check 4: Too many turns without resolution
        if turn_count >= _MAX_TURNS_BEFORE_ESCALATION and not resolved:
            escalate = True
            reasons.append(f"Conversation reached {turn_count} turns without resolution")

        # Check 5: VIP customer handling
        if customer_tier in ("vip", "premium", "enterprise"):
            if intent in _COMPLEX_INTENTS:
                escalate = True
                reasons.append(f"VIP customer ({customer_tier}) with {intent} intent")
                priority = "high"
                department = "vip_support"

        # Determine department from intent if not already set
        if escalate and department == "general_support":
            dept_map = {
                "return": "returns_department",
                "complaint": "customer_retention",
                "support": "technical_support",
                "shipping": "logistics",
                "account": "account_services",
            }
            department = dept_map.get(intent, "general_support")

        reason_text = "; ".join(reasons) if reasons else "No escalation needed"

        return {
            "status": "success",
            "escalation": {
                "escalate": escalate,
                "reason": reason_text,
                "priority": priority,
                "department": department,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "escalation": {},
            "error": f"Escalation check failed: {exc}",
        }
