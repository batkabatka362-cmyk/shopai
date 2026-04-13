"""Customer Support Engine — ticket classifier.

Classify support tickets by category, priority, and sentiment.
"""
from __future__ import annotations

import copy
from typing import Any

_CATEGORY_KEYWORDS = {
    "billing": ["charge", "refund", "payment", "invoice", "price", "bill"],
    "shipping": ["delivery", "shipping", "tracking", "lost", "late", "arrived"],
    "product": ["defect", "broken", "quality", "size", "color", "wrong"],
    "account": ["login", "password", "account", "access", "email"],
    "general": [],
}


def classify_tickets(
    **kwargs: Any,
) -> dict[str, Any]:
    """Classify support tickets.

    Args:
        **kwargs: Must include 'tickets' list.

    Returns:
        Structured dict with classified tickets.
    """
    try:
        tickets = copy.deepcopy(kwargs.get("tickets", []))
        classified: list[dict[str, Any]] = []

        for ticket in tickets:
            tid = str(ticket.get("id", "unknown"))
            subject = str(ticket.get("subject", "")).lower()
            body = str(ticket.get("body", "")).lower()
            text = f"{subject} {body}"

            # Classify category
            category = "general"
            max_hits = 0
            for cat, keywords in _CATEGORY_KEYWORDS.items():
                hits = sum(1 for kw in keywords if kw in text)
                if hits > max_hits:
                    max_hits = hits
                    category = cat

            # Classify priority
            urgent_words = ["urgent", "asap", "immediately", "critical", "broken"]
            is_urgent = any(w in text for w in urgent_words)
            priority = "high" if is_urgent else "medium" if max_hits > 1 else "low"

            # Simple sentiment
            negative_words = ["angry", "frustrated", "terrible", "worst", "hate", "awful"]
            positive_words = ["thank", "great", "love", "excellent", "happy"]
            neg_count = sum(1 for w in negative_words if w in text)
            pos_count = sum(1 for w in positive_words if w in text)
            sentiment = "negative" if neg_count > pos_count else "positive" if pos_count > neg_count else "neutral"

            classified.append({
                "ticket_id": tid,
                "category": category,
                "priority": priority,
                "sentiment": sentiment,
                "subject": ticket.get("subject", ""),
            })

        return {
            "status": "success",
            "result": {"classified_tickets": classified},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Ticket classification failed: {exc}"}
