"""Chatbot Engine — response generator.

Generates contextual responses based on intent classification,
customer data, and conversation context.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Response templates by intent
# ---------------------------------------------------------------------------

_RESPONSE_TEMPLATES: dict[str, dict[str, Any]] = {
    "purchase": {
        "response": (
            "I'd be happy to help you with your purchase! "
            "{product_context}"
            "Is there anything specific you'd like to know about pricing or availability?"
        ),
        "actions": ["View product details", "Check availability", "Add to cart"],
    },
    "support": {
        "response": (
            "I'm sorry to hear you're experiencing an issue. "
            "Let me help you resolve this. "
            "{issue_context}"
            "Could you provide more details about what happened?"
        ),
        "actions": ["Submit support ticket", "View troubleshooting guide", "Contact specialist"],
    },
    "shipping": {
        "response": (
            "Let me look into your shipping status. "
            "{order_context}"
            "Is there a specific order you'd like me to track?"
        ),
        "actions": ["Track order", "View shipping policy", "Update shipping address"],
    },
    "return": {
        "response": (
            "I understand you'd like to process a return. "
            "Our return policy allows returns within 30 days of purchase. "
            "{order_context}"
            "Would you like to start a return request?"
        ),
        "actions": ["Start return", "View return policy", "Contact support"],
    },
    "information": {
        "response": (
            "Great question! "
            "{product_context}"
            "What specific details are you looking for?"
        ),
        "actions": ["View product specs", "Compare products", "Read reviews"],
    },
    "account": {
        "response": (
            "I can help you with your account. "
            "For security, some changes may require email verification. "
            "What would you like to update?"
        ),
        "actions": ["Update profile", "Reset password", "View order history"],
    },
    "complaint": {
        "response": (
            "I sincerely apologize for your experience. "
            "Your satisfaction is very important to us. "
            "Let me connect you with someone who can make this right."
        ),
        "actions": ["Speak to manager", "Submit formal complaint", "Request compensation"],
    },
    "general": {
        "response": (
            "Thanks for reaching out! I'm here to help. "
            "Could you tell me a bit more about what you're looking for?"
        ),
        "actions": ["Browse products", "View FAQ", "Contact support"],
    },
}


def generate_response(
    intent_result: dict[str, Any],
    message: str,
    customer: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Generate a contextual response for the customer.

    Args:
        intent_result: Intent classification result.
        message: Original customer message.
        customer: Customer info dict.
        context: Additional context dict.

    Returns:
        Structured dict with response, actions, and references.
    """
    try:
        intent = str(intent_result.get("intent", "general"))
        entities = dict(intent_result.get("entities", {}))
        customer_name = str(customer.get("name", ""))

        template_data = _RESPONSE_TEMPLATES.get(intent, _RESPONSE_TEMPLATES["general"])
        response_template = str(template_data["response"])
        actions = list(template_data["actions"])

        # Build context substitutions
        product_context = ""
        order_context = ""
        issue_context = ""

        order_ids = entities.get("order_ids", [])
        if order_ids:
            order_context = f"I can see you're asking about order {order_ids[0]}. "

        # Add product context from context dict
        product_name = str(context.get("product_name", ""))
        if product_name:
            product_context = f"Regarding {product_name}: "

        # Personalize with customer name
        greeting = ""
        if customer_name:
            greeting = f"Hi {customer_name}! "

        # Substitute placeholders
        response = response_template.replace("{product_context}", product_context)
        response = response.replace("{order_context}", order_context)
        response = response.replace("{issue_context}", issue_context)
        response = greeting + response

        # Clean up double spaces
        response = " ".join(response.split())

        # Build references
        references: list[str] = []
        if intent == "shipping":
            references.append("shipping_policy")
        elif intent == "return":
            references.append("return_policy")
        elif intent == "support":
            references.append("troubleshooting_guide")

        return {
            "status": "success",
            "generated": {
                "response": response,
                "suggested_actions": actions,
                "references": references,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "generated": {},
            "error": f"Response generation failed: {exc}",
        }
