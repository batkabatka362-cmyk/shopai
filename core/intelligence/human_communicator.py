"""HumanCommunicator — tone-aware messaging for customers, suppliers, owners.

System structured dict буцаадаг. Customer-д email бичихгүй, supplier-тэй
negotiate хийхгүй. HumanCommunicator зөв tone сонгоно.

Tone rules:
  - Angry customer → empathetic, apologetic, solution-focused
  - VIP customer → premium, exclusive, grateful
  - Supplier → professional, firm on terms, relationship-building
  - Store owner → clear, data-driven, actionable
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.communicator")

# Tone profiles
TONE_PROFILES = {
    "empathetic": {
        "description": "For upset/frustrated customers",
        "openings": [
            "I completely understand your frustration.",
            "I'm really sorry to hear about this experience.",
            "Thank you for bringing this to our attention.",
        ],
        "closings": [
            "We value your business and want to make this right.",
            "Please don't hesitate to reach out if you need anything else.",
            "We appreciate your patience as we resolve this.",
        ],
        "avoid": ["unfortunately", "policy states", "we can't", "that's not possible"],
        "prefer": ["I understand", "let me help", "here's what I can do", "absolutely"],
    },
    "premium": {
        "description": "For VIP/high-value customers",
        "openings": [
            "As a valued member of our community,",
            "We've prepared something special just for you.",
            "Thank you for being one of our most treasured customers.",
        ],
        "closings": [
            "With gratitude for your continued loyalty.",
            "Exclusively yours,",
            "We look forward to serving you again.",
        ],
        "avoid": ["deal", "cheap", "discount", "sale"],
        "prefer": ["exclusive", "curated", "complimentary", "first access", "personally selected"],
    },
    "professional": {
        "description": "For supplier/vendor communication",
        "openings": [
            "I hope this message finds you well.",
            "Thank you for your partnership.",
            "Following up on our recent discussion,",
        ],
        "closings": [
            "Looking forward to your response.",
            "Best regards,",
            "Thank you for your continued partnership.",
        ],
        "key_phrases": ["mutual benefit", "volume commitment", "payment terms", "quality standards"],
    },
    "data_driven": {
        "description": "For store owner reports and updates",
        "format": "metric → context → action",
        "openings": [
            "Here's your store performance update:",
            "Key metrics from this week:",
            "Action items based on latest data:",
        ],
        "closings": [
            "Reply to any item to get more details.",
            "These are prioritized by impact.",
            "Next update scheduled for [date].",
        ],
    },
    "urgent": {
        "description": "For time-sensitive issues",
        "openings": [
            "Action needed:",
            "Important update about your store:",
            "Immediate attention required:",
        ],
        "format": "issue → impact → action → deadline",
    },
}

# Email templates by scenario
EMAIL_TEMPLATES = {
    "order_thank_you": {
        "tone": "premium",
        "subject": "Thank you for your order, {customer_name}!",
        "body": "Your order #{order_id} is confirmed.\n\nItems: {items}\nTotal: ${total}\n\nWe're preparing your order with care and will notify you when it ships.",
    },
    "shipping_confirmation": {
        "tone": "professional",
        "subject": "Your order is on its way! 📦",
        "body": "Great news, {customer_name}! Your order #{order_id} has shipped.\n\nTracking: {tracking_url}\nEstimated delivery: {delivery_date}\n\nTrack your package anytime using the link above.",
    },
    "review_request": {
        "tone": "premium",
        "subject": "How do you like your {product_name}?",
        "body": "Hi {customer_name},\n\nYou've had your {product_name} for about a week now. We'd love to hear what you think!\n\nShare a photo review and get 10% off your next order.\n\n[Leave a Review]",
    },
    "cart_recovery_1h": {
        "tone": "empathetic",
        "subject": "Did you forget something?",
        "body": "Hi {customer_name},\n\nYou left some items in your cart:\n{cart_items}\n\nYour cart is saved and waiting for you.\n\n[Complete Your Order]",
    },
    "cart_recovery_24h": {
        "tone": "empathetic",
        "subject": "Your cart is about to expire",
        "body": "Hi {customer_name},\n\nThe items in your cart are selling fast:\n{cart_items}\n\nComplete your order now and we'll include free shipping.\n\n[Complete Your Order]",
    },
    "winback_30d": {
        "tone": "empathetic",
        "subject": "We miss you, {customer_name}!",
        "body": "Hi {customer_name},\n\nIt's been a while since your last visit. We've added some new items we think you'll love.\n\n[See What's New]",
    },
    "winback_60d": {
        "tone": "premium",
        "subject": "A special gift just for you",
        "body": "Hi {customer_name},\n\nAs one of our valued customers, we've prepared a special offer: 15% off your next order.\n\nUse code: WELCOME15\n\n[Shop Now]",
    },
    "complaint_response": {
        "tone": "empathetic",
        "subject": "Re: {original_subject}",
        "body": "Hi {customer_name},\n\nI completely understand your frustration with {issue}. This isn't the experience we want for you.\n\nHere's what I'm doing to fix this:\n{resolution}\n\nI've also {compensation} as an apology for the inconvenience.\n\nPlease reach out directly if you need anything else.",
    },
    "supplier_reorder": {
        "tone": "professional",
        "subject": "Purchase Order — {product_name} Restock",
        "body": "Hi {supplier_name},\n\nWe'd like to place a reorder:\n\nProduct: {product_name}\nQuantity: {quantity}\nRequested delivery: {delivery_date}\n\nPlease confirm availability and current pricing.\n\nBased on our volume ({total_units_ytd} units YTD), we'd like to discuss improved terms.\n\nBest regards,",
    },
    "owner_daily_report": {
        "tone": "data_driven",
        "subject": "Daily Report: {date} — Revenue ${revenue}",
        "body": "Revenue: ${revenue} ({revenue_change})\nOrders: {orders} ({order_change})\nConversion: {conversion}% ({cvr_change})\nTop Product: {top_product}\n\nActions Taken:\n{actions}\n\nUpcoming:\n{upcoming}",
    },
}

# Supplier negotiation strategies
NEGOTIATION_STRATEGIES = {
    "volume_discount": {
        "approach": "Leverage total purchase volume for better unit price",
        "opener": "Given our {volume} unit commitment this year...",
        "fallback": "Even a {pct}% improvement would help us increase order frequency",
    },
    "payment_terms": {
        "approach": "Extend payment terms from Net 30 to Net 45/60",
        "opener": "To better align with our cash conversion cycle...",
        "fallback": "We could offer early payment discount in exchange",
    },
    "exclusive_deal": {
        "approach": "Offer exclusivity in exchange for better terms",
        "opener": "We'd like to make you our exclusive supplier for...",
        "condition": "Requires 15%+ cost reduction or significant improvement",
    },
}


class HumanCommunicator:
    """Generates tone-appropriate messages for different audiences.

    Usage:
        comm = HumanCommunicator()
        email = comm.compose_email("review_request", {"customer_name": "John", "product_name": "Widget"})
        response = comm.handle_complaint(complaint_data)
        report = comm.owner_report(store_metrics)
    """

    def compose_email(self, template_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Compose an email from a template with variables."""
        template = EMAIL_TEMPLATES.get(template_name)
        if not template:
            return {"status": "error", "error": f"Unknown template: {template_name}", "available": list(EMAIL_TEMPLATES.keys())}

        tone = TONE_PROFILES.get(template["tone"], {})

        subject = template["subject"]
        body = template["body"]
        for key, val in variables.items():
            subject = subject.replace(f"{{{key}}}", str(val))
            body = body.replace(f"{{{key}}}", str(val))

        return {
            "template": template_name,
            "tone": template["tone"],
            "subject": subject,
            "body": body,
            "tone_guidelines": {
                "avoid": tone.get("avoid", []),
                "prefer": tone.get("prefer", tone.get("key_phrases", [])),
            },
        }

    def select_tone(self, context: dict[str, Any]) -> dict[str, Any]:
        """Select the appropriate tone based on context."""
        customer_sentiment = context.get("sentiment", "neutral")
        customer_value = context.get("ltv", 0)
        is_complaint = context.get("is_complaint", False)
        audience = context.get("audience", "customer")

        if audience == "supplier":
            return {"tone": "professional", **TONE_PROFILES["professional"]}
        if audience == "owner":
            return {"tone": "data_driven", **TONE_PROFILES["data_driven"]}
        if is_complaint or customer_sentiment in ("angry", "frustrated", "disappointed"):
            return {"tone": "empathetic", **TONE_PROFILES["empathetic"]}
        if customer_value > 500:
            return {"tone": "premium", **TONE_PROFILES["premium"]}
        if context.get("urgency") == "high":
            return {"tone": "urgent", **TONE_PROFILES["urgent"]}

        return {"tone": "professional", **TONE_PROFILES["professional"]}

    def handle_complaint(self, complaint: dict[str, Any]) -> dict[str, Any]:
        """Generate a response to a customer complaint."""
        issue = complaint.get("issue", "your recent experience")
        order_id = complaint.get("order_id", "")
        customer_name = complaint.get("customer_name", "there")
        severity = complaint.get("severity", "medium")

        # Determine compensation
        if severity == "high":
            compensation = "applied a full refund to your account"
            resolution = "1. Issued full refund\n2. Sent replacement at no cost\n3. Added priority shipping"
        elif severity == "medium":
            compensation = "added a 20% discount code for your next order"
            resolution = f"1. Investigating order #{order_id}\n2. Will ship replacement within 48 hours"
        else:
            compensation = "added free shipping to your next order"
            resolution = f"1. Looking into the issue with order #{order_id}"

        email = self.compose_email("complaint_response", {
            "customer_name": customer_name,
            "original_subject": complaint.get("subject", "Your order"),
            "issue": issue,
            "resolution": resolution,
            "compensation": compensation,
        })

        return {
            **email,
            "severity": severity,
            "compensation_type": compensation,
            "follow_up_needed": severity in ("high", "medium"),
        }

    def supplier_negotiation(
        self,
        strategy: str,
        supplier: dict[str, Any],
        leverage_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate supplier negotiation message."""
        strat = NEGOTIATION_STRATEGIES.get(strategy)
        if not strat:
            return {"status": "error", "available": list(NEGOTIATION_STRATEGIES.keys())}

        return {
            "strategy": strategy,
            "approach": strat["approach"],
            "opener": strat["opener"].format(**leverage_data) if leverage_data else strat["opener"],
            "fallback": strat.get("fallback", ""),
            "supplier": supplier.get("name", "Supplier"),
            "tone": "professional",
        }

    def owner_report(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Generate a daily/weekly report for the store owner."""
        return self.compose_email("owner_daily_report", {
            "date": metrics.get("date", "today"),
            "revenue": f"{metrics.get('revenue', 0):,.2f}",
            "revenue_change": metrics.get("revenue_change", "N/A"),
            "orders": metrics.get("orders", 0),
            "order_change": metrics.get("order_change", "N/A"),
            "conversion": metrics.get("conversion", 0),
            "cvr_change": metrics.get("cvr_change", "N/A"),
            "top_product": metrics.get("top_product", "N/A"),
            "actions": metrics.get("actions_taken", "No automated actions"),
            "upcoming": metrics.get("upcoming", "No scheduled events"),
        })

    def get_available_templates(self) -> list[str]:
        """List all available email templates."""
        return list(EMAIL_TEMPLATES.keys())

    def get_available_tones(self) -> list[str]:
        """List all available tone profiles."""
        return list(TONE_PROFILES.keys())
