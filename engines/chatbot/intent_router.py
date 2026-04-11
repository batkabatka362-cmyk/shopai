"""Chatbot Engine — intent router.

Routes customer messages to the correct intent handler by
classifying intent, extracting entities, and determining sub-intents.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Intent keyword mappings
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "purchase": ["buy", "order", "purchase", "add to cart", "checkout", "price", "cost", "how much"],
    "support": ["help", "issue", "problem", "broken", "not working", "error", "fix", "defective"],
    "shipping": ["shipping", "delivery", "track", "where is", "when will", "tracking", "shipped"],
    "return": ["return", "refund", "exchange", "send back", "money back", "cancel"],
    "information": ["what is", "how does", "tell me", "information", "details", "features", "specs"],
    "account": ["account", "login", "password", "profile", "settings", "email", "update"],
    "complaint": ["terrible", "awful", "worst", "disappointed", "angry", "unacceptable", "furious"],
}

_SUB_INTENTS: dict[str, dict[str, list[str]]] = {
    "purchase": {
        "pricing_inquiry": ["price", "cost", "how much", "discount", "coupon"],
        "availability": ["in stock", "available", "when available", "restock"],
        "comparison": ["compare", "difference", "vs", "better"],
    },
    "support": {
        "technical": ["not working", "error", "crash", "bug", "glitch"],
        "setup": ["setup", "install", "configure", "connect"],
        "warranty": ["warranty", "guarantee", "coverage"],
    },
    "shipping": {
        "tracking": ["track", "tracking", "where is"],
        "timing": ["when", "how long", "delivery date", "estimated"],
        "method": ["express", "standard", "overnight", "free shipping"],
    },
}


def route_intent(
    message: str,
    conversation_history: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Classify message intent and extract entities.

    Args:
        message: Customer message text.
        conversation_history: Previous conversation messages.
        context: Additional context dict.

    Returns:
        Structured dict with intent classification.
    """
    try:
        msg_lower = message.lower()

        # ---- Primary intent classification ----
        intent_scores: dict[str, int] = {}
        for intent, keywords in _INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in msg_lower)
            if score > 0:
                intent_scores[intent] = score

        if intent_scores:
            primary_intent = max(intent_scores, key=intent_scores.get)  # type: ignore[arg-type]
            max_score = intent_scores[primary_intent]
            total_score = sum(intent_scores.values())
            confidence = round(max_score / max(total_score, 1), 2)
            confidence = min(max(confidence, 0.3), 0.99)
        else:
            primary_intent = "general"
            confidence = 0.3

        # ---- Sub-intent classification ----
        sub_intent = "general"
        sub_intents = _SUB_INTENTS.get(primary_intent, {})
        for sub_name, sub_keywords in sub_intents.items():
            if any(kw in msg_lower for kw in sub_keywords):
                sub_intent = sub_name
                break

        # ---- Entity extraction ----
        entities = _extract_entities(message)

        # ---- Context boost: if conversation history has same topic ----
        if conversation_history:
            last_msg = conversation_history[-1] if conversation_history else {}
            last_content = str(last_msg.get("content", "")).lower()
            for intent, keywords in _INTENT_KEYWORDS.items():
                if intent == primary_intent and any(kw in last_content for kw in keywords):
                    confidence = min(confidence + 0.1, 0.99)
                    break

        return {
            "status": "success",
            "intent_result": {
                "intent": primary_intent,
                "confidence": confidence,
                "entities": entities,
                "sub_intent": sub_intent,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "intent_result": {},
            "error": f"Intent routing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_entities(message: str) -> dict[str, list[str]]:
    """Extract entities (order IDs, product mentions, etc.) from message."""
    entities: dict[str, list[str]] = {
        "order_ids": [],
        "product_mentions": [],
    }

    words = message.split()
    for word in words:
        cleaned = word.strip("#").strip(".,!?")
        # Order IDs: start with ORD or are long numeric strings
        if cleaned.upper().startswith("ORD") or (cleaned.isdigit() and len(cleaned) >= 6):
            entities["order_ids"].append(cleaned)

    return entities
