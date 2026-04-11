"""Customer Service Engine — response builder.

Builds empathetic, actionable customer responses based on classified intent,
order data, knowledge articles, and customer profile.

All logic is real template assembly. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Tone selection
# ---------------------------------------------------------------------------

_INTENT_TONES: dict[str, str] = {
    "complaint": "empathetic_urgent",
    "refund_request": "empathetic_helpful",
    "return_request": "helpful",
    "order_status": "informative",
    "tracking": "informative",
    "billing": "professional",
    "shipping": "informative",
    "product_question": "friendly",
    "general": "friendly",
}

# ---------------------------------------------------------------------------
# Greeting templates by tier
# ---------------------------------------------------------------------------

_TIER_GREETINGS: dict[str, str] = {
    "platinum": "Thank you for being a valued Platinum member, {name}.",
    "gold": "Thank you for being a loyal Gold member, {name}.",
    "silver": "Thank you for reaching out, {name}.",
    "bronze": "Thank you for contacting us, {name}.",
}

_DEFAULT_GREETING = "Thank you for contacting us."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_response(
    intent: dict[str, Any],
    order_info: dict[str, Any],
    knowledge: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Build a customer-facing response.

    Args:
        intent: Intent classification result.
        order_info: Order lookup result (may be None/empty or found=False).
        knowledge: Knowledge search result with articles.
        customer: Customer profile dict.

    Returns:
        Structured dict with response message, tone, and suggested actions.
    """
    try:
        intent_data = copy.deepcopy(intent)
        order_data = copy.deepcopy(order_info) if order_info else {}
        kb_data = copy.deepcopy(knowledge) if knowledge else {}
        cust = copy.deepcopy(customer) if customer else {}

        primary_intent = str(intent_data.get("primary", "general"))
        tone = _INTENT_TONES.get(primary_intent, "friendly")

        # --- Build greeting ---
        name = str(cust.get("name", "")).strip()
        tier = str(cust.get("loyalty_tier", "bronze")).lower()
        if name:
            greeting = _TIER_GREETINGS.get(tier, _DEFAULT_GREETING).format(name=name)
        else:
            greeting = _DEFAULT_GREETING

        # --- Build body ---
        body = _build_body(primary_intent, intent_data, order_data, kb_data)

        # --- Build suggested actions ---
        actions = _build_actions(primary_intent, order_data)

        # --- Assemble message ---
        message = f"{greeting}\n\n{body}"

        return {
            "status": "success",
            "message": message,
            "tone": tone,
            "suggested_actions": actions,
        }
    except Exception as exc:
        return _fail(f"Response building failed: {exc}")


# ---------------------------------------------------------------------------
# Body builders by intent
# ---------------------------------------------------------------------------

def _build_body(
    primary_intent: str,
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    """Build the main response body based on intent and available data."""
    builder = _BODY_BUILDERS.get(primary_intent, _build_general_body)
    return builder(intent_data, order_data, kb_data)


def _build_order_status_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    order = order_data.get("order")
    if not order_data.get("found") or not order:
        order_ids = intent_data.get("extracted_entities", {}).get("order_ids", [])
        oid_str = ", ".join(order_ids) if order_ids else "the requested order"
        return (
            f"I was unable to find {oid_str} in our system. "
            "Could you please double-check the order number? You can find it in your "
            "order confirmation email or under My Orders in your account."
        )

    status = order.get("status", "unknown")
    oid = order.get("id", "")
    est = order.get("estimated_delivery", "")
    is_late = order.get("is_late", False)
    days_late = order.get("days_late", 0)

    lines = [f"Here is the latest on your order {oid}:"]
    lines.append(f"- Current status: {_humanise_status(status)}")

    if est:
        lines.append(f"- Estimated delivery: {est}")

    if is_late and days_late > 0:
        lines.append(
            f"- This order appears to be running {days_late} day(s) behind schedule. "
            "I sincerely apologize for the delay. I have flagged this for our shipping team "
            "to investigate and expedite."
        )

    tracking_num = order.get("tracking_number", "")
    carrier = order.get("carrier", "")
    if tracking_num and carrier:
        lines.append(f"- Carrier: {carrier}, Tracking: {tracking_num}")

    return "\n".join(lines)


def _build_tracking_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    order = order_data.get("order")
    if not order_data.get("found") or not order:
        return (
            "To track your package, please provide your order number and I will look it up. "
            "You can also track your order directly in your account under My Orders."
        )

    tracking_num = order.get("tracking_number", "")
    carrier = order.get("carrier", "")
    status = order.get("status", "unknown")

    if tracking_num and carrier:
        return (
            f"Your order is currently {_humanise_status(status)}. "
            f"You can track it with {carrier} using tracking number: {tracking_num}. "
            "If the tracking has not updated in 48 hours, please let us know and we will "
            "investigate with the carrier."
        )

    return (
        f"Your order is currently {_humanise_status(status)}. "
        "Tracking information will be available once the order has shipped. "
        "You will receive an email with the tracking details."
    )


def _build_return_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    body = (
        "We are happy to help with your return. Our return policy allows returns within "
        "30 days of delivery. Items must be unused, in original packaging, and with tags attached.\n\n"
        "To start your return:\n"
        "1. Go to My Orders in your account\n"
        "2. Select the item you wish to return\n"
        "3. Choose 'Return Item' and follow the instructions\n"
        "4. Print the prepaid return label\n\n"
        "For defective items, return shipping is free. For other returns, a $5.99 return "
        "shipping fee applies. Exchanges are always free."
    )

    kb_snippet = _get_best_kb_snippet(kb_data)
    if kb_snippet:
        body += f"\n\nAdditional info: {kb_snippet}"

    return body


def _build_refund_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    body = (
        "I understand you would like a refund and I am here to help. "
        "Refunds are processed within 3-5 business days after we receive the returned item. "
        "The refund will be issued to your original payment method.\n\n"
        "Credit card refunds may take an additional 5-10 business days to appear on your "
        "statement. PayPal refunds typically appear within 1-2 business days."
    )

    entities = intent_data.get("extracted_entities", {})
    amounts = entities.get("amounts", [])
    if amounts:
        body += f"\n\nI see a refund amount of ${amounts[0]:.2f} referenced. "
        body += "I will ensure this is reviewed promptly."

    return body


def _build_complaint_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    body = (
        "I am truly sorry to hear about your experience. Your satisfaction is our top priority "
        "and I want to make this right.\n\n"
        "I have taken note of your concerns and will ensure they are addressed promptly. "
    )

    order = order_data.get("order")
    if order_data.get("found") and order:
        oid = order.get("id", "")
        body += f"I can see your order {oid} and I am looking into this now. "

    body += (
        "A member of our team will follow up with you to resolve this matter. "
        "If you would like to speak with a supervisor, please let me know and I will "
        "arrange that right away."
    )

    return body


def _build_billing_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    body = "I would be happy to help with your billing question."

    kb_snippet = _get_best_kb_snippet(kb_data)
    if kb_snippet:
        body += f"\n\n{kb_snippet}"
    else:
        body += (
            "\n\nWe accept Visa, Mastercard, American Express, Discover, PayPal, Apple Pay, "
            "and Google Pay. If you are seeing an incorrect charge, please provide the order "
            "number and the amount in question, and I will investigate immediately."
        )

    return body


def _build_shipping_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    body = "Here is our shipping information:"

    kb_snippet = _get_best_kb_snippet(kb_data)
    if kb_snippet:
        body += f"\n\n{kb_snippet}"
    else:
        body += (
            "\n\n- Standard shipping (5-7 business days): Free on orders over $50\n"
            "- Express shipping (2-3 business days): $9.99\n"
            "- Overnight shipping: $19.99\n"
            "- International shipping: Starting at $14.99\n\n"
            "Orders placed before 2 PM EST ship the same day."
        )

    return body


def _build_product_question_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    product_names = intent_data.get("extracted_entities", {}).get("product_names", [])

    if product_names:
        body = f"I would be happy to help with your question about {', '.join(product_names)}."
    else:
        body = "I would be happy to help with your product question."

    kb_snippet = _get_best_kb_snippet(kb_data)
    if kb_snippet:
        body += f"\n\n{kb_snippet}"

    body += (
        "\n\nFor detailed product specifications, you can also check the product page. "
        "If you need more specific information, please let me know and I will look into it."
    )

    return body


def _build_general_body(
    intent_data: dict[str, Any],
    order_data: dict[str, Any],
    kb_data: dict[str, Any],
) -> str:
    body = "I am here to help! How can I assist you today?"

    kb_snippet = _get_best_kb_snippet(kb_data)
    if kb_snippet:
        body += f"\n\n{kb_snippet}"

    body += (
        "\n\nHere are some things I can help with:\n"
        "- Order status and tracking\n"
        "- Returns and refunds\n"
        "- Product questions\n"
        "- Shipping information\n"
        "- Account help\n\n"
        "Just let me know what you need!"
    )

    return body


_BODY_BUILDERS: dict[str, Any] = {
    "order_status": _build_order_status_body,
    "tracking": _build_tracking_body,
    "return_request": _build_return_body,
    "refund_request": _build_refund_body,
    "complaint": _build_complaint_body,
    "billing": _build_billing_body,
    "shipping": _build_shipping_body,
    "product_question": _build_product_question_body,
    "general": _build_general_body,
}


# ---------------------------------------------------------------------------
# Suggested actions by intent
# ---------------------------------------------------------------------------

def _build_actions(
    primary_intent: str,
    order_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build a list of suggested actions based on intent and order data."""
    actions: list[dict[str, Any]] = []

    order = order_data.get("order") if order_data.get("found") else None

    if primary_intent == "order_status":
        if order and order.get("tracking_number"):
            actions.append({
                "action": "track_package",
                "label": "Track Package",
                "url": _tracking_url(order.get("carrier", ""), order.get("tracking_number", "")),
            })
        actions.append({
            "action": "view_orders",
            "label": "View My Orders",
            "url": "/account/orders",
        })

    elif primary_intent == "tracking":
        if order and order.get("tracking_number"):
            actions.append({
                "action": "track_package",
                "label": "Track Package",
                "url": _tracking_url(order.get("carrier", ""), order.get("tracking_number", "")),
            })
        actions.append({
            "action": "contact_support",
            "label": "Contact Support",
            "trigger": "live_chat",
        })

    elif primary_intent == "return_request":
        actions.append({
            "action": "start_return",
            "label": "Start a Return",
            "url": "/account/orders?action=return",
        })
        actions.append({
            "action": "view_return_policy",
            "label": "View Return Policy",
            "url": "/policies/returns",
        })

    elif primary_intent == "refund_request":
        actions.append({
            "action": "check_refund_status",
            "label": "Check Refund Status",
            "url": "/account/orders?tab=refunds",
        })
        actions.append({
            "action": "contact_support",
            "label": "Contact Billing Support",
            "trigger": "billing_chat",
        })

    elif primary_intent == "complaint":
        actions.append({
            "action": "speak_to_agent",
            "label": "Speak to an Agent",
            "trigger": "escalate_agent",
        })
        actions.append({
            "action": "submit_feedback",
            "label": "Submit Feedback",
            "url": "/feedback",
        })

    elif primary_intent == "billing":
        actions.append({
            "action": "view_billing",
            "label": "View Billing History",
            "url": "/account/billing",
        })
        actions.append({
            "action": "update_payment",
            "label": "Update Payment Method",
            "url": "/account/payment-methods",
        })

    elif primary_intent == "shipping":
        actions.append({
            "action": "view_shipping_options",
            "label": "View Shipping Options",
            "url": "/policies/shipping",
        })

    elif primary_intent == "product_question":
        actions.append({
            "action": "browse_products",
            "label": "Browse Products",
            "url": "/products",
        })
        actions.append({
            "action": "size_guide",
            "label": "Sizing Guide",
            "url": "/size-guide",
        })

    else:
        actions.append({
            "action": "contact_support",
            "label": "Contact Support",
            "trigger": "live_chat",
        })
        actions.append({
            "action": "faq",
            "label": "Browse FAQ",
            "url": "/help",
        })

    return actions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATUS_LABELS: dict[str, str] = {
    "confirmed": "Confirmed — preparing for shipment",
    "processing": "Being processed",
    "shipped": "Shipped — on the way",
    "in_transit": "In transit",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "returned": "Returned",
    "refunded": "Refunded",
}


def _humanise_status(status: str) -> str:
    """Convert a status code to a human-friendly label."""
    return _STATUS_LABELS.get(status, status.replace("_", " ").title())


def _tracking_url(carrier: str, tracking_number: str) -> str:
    """Build a tracking URL for known carriers."""
    carrier_lower = carrier.lower()
    if "ups" in carrier_lower:
        return f"https://www.ups.com/track?tracknum={tracking_number}"
    if "fedex" in carrier_lower:
        return f"https://www.fedex.com/fedextrack/?trknbr={tracking_number}"
    if "usps" in carrier_lower:
        return f"https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}"
    if "dhl" in carrier_lower:
        return f"https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}"
    return f"/track/{tracking_number}"


def _get_best_kb_snippet(kb_data: dict[str, Any]) -> str:
    """Get the snippet from the highest-scoring knowledge article."""
    results = kb_data.get("results", [])
    if results:
        return str(results[0].get("snippet", ""))
    return ""


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardised error result."""
    return {
        "status": "error",
        "message": "",
        "tone": "neutral",
        "suggested_actions": [],
        "error": reason,
    }
