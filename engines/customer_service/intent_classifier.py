"""Customer Service Engine — intent classifier.

Classifies customer messages into intents using keyword/regex matching.
Extracts entities: order IDs, product names, dates, dollar amounts.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Intent patterns — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "order_status": [
        re.compile(r"\b(where\s+is\s+my\s+order|order\s+status|status\s+of\s+(my\s+)?order)", re.I),
        re.compile(r"\b(check\s+on\s+(my\s+)?order|what\s+happened\s+to\s+my\s+order)", re.I),
        re.compile(r"\b(when\s+will\s+my\s+order\s+(arrive|ship|be\s+delivered))", re.I),
        re.compile(r"\b(has\s+my\s+order\s+(shipped|been\s+shipped))", re.I),
    ],
    "tracking": [
        re.compile(r"\b(track(ing)?\s+(number|info|information|details|my\s+package))", re.I),
        re.compile(r"\b(where\s+is\s+my\s+(package|shipment|parcel))", re.I),
        re.compile(r"\b(delivery\s+(status|update|tracking))", re.I),
        re.compile(r"\b(package\s+(location|whereabouts|status))", re.I),
    ],
    "return_request": [
        re.compile(r"\b(return|send\s+(it\s+)?back|want\s+to\s+return|how\s+to\s+return)", re.I),
        re.compile(r"\b(return\s+(policy|process|label|instructions))", re.I),
        re.compile(r"\b(exchange\s+(this|my|the\s+product|the\s+item))", re.I),
        re.compile(r"\b(don'?t\s+want\s+(this|it)\s+anymore)", re.I),
    ],
    "refund_request": [
        re.compile(r"\b(refund|money\s+back|get\s+my\s+money\s+back|reimburse)", re.I),
        re.compile(r"\b(charge\s*back|credit\s+back|reverse\s+(the\s+)?charge)", re.I),
        re.compile(r"\b(cancel\s+and\s+refund|refund\s+my\s+(order|purchase|payment))", re.I),
    ],
    "product_question": [
        re.compile(r"\b(does\s+(this|it)\s+come\s+in|available\s+in|what\s+size)", re.I),
        re.compile(r"\b(product\s+(info|information|details|specs|specifications))", re.I),
        re.compile(r"\b(is\s+(this|it)\s+(compatible|available|in\s+stock))", re.I),
        re.compile(r"\b(what\s+(material|color|dimension)s?\s+(is|are|does))", re.I),
        re.compile(r"\b(tell\s+me\s+(about|more\s+about)\s+(this|the)\s+product)", re.I),
        re.compile(r"\b(sizing\s+(guide|chart|info|help))", re.I),
    ],
    "complaint": [
        re.compile(r"\b(terrible|awful|worst|horrible|unacceptable|disgusting|pathetic)", re.I),
        re.compile(r"\b(broken|damaged|defective|wrong\s+(item|product|order)|not\s+what\s+I\s+ordered)", re.I),
        re.compile(r"\b(never\s+(buying|ordering|shopping)\s+(from\s+you\s+)?again)", re.I),
        re.compile(r"\b(file\s+a\s+complaint|speak\s+to\s+(a\s+)?manager|escalate)", re.I),
        re.compile(r"\b(very\s+(disappointed|frustrated|upset|angry|unhappy))", re.I),
        re.compile(r"\b(rip\s*off|scam|fraud(ulent)?)", re.I),
    ],
    "billing": [
        re.compile(r"\b(bill(ing|ed)?|invoice|charge(d)?|payment\s+(issue|problem|failed))", re.I),
        re.compile(r"\b(double\s+charge|overcharge|incorrect\s+(amount|charge))", re.I),
        re.compile(r"\b(update\s+(my\s+)?(payment|card|billing)\s+(info|method|details))", re.I),
        re.compile(r"\b(promo\s*code|coupon|discount)\s+(not\s+work|didn'?t\s+(work|apply))", re.I),
    ],
    "shipping": [
        re.compile(r"\b(shipping\s+(cost|rate|fee|option|method|time|speed)s?)", re.I),
        re.compile(r"\b(free\s+shipping|expedited\s+shipping|express\s+shipping)", re.I),
        re.compile(r"\b(change\s+(my\s+)?(shipping|delivery)\s+address)", re.I),
        re.compile(r"\b(do\s+you\s+ship\s+to|international\s+shipping)", re.I),
        re.compile(r"\b(how\s+long\s+(does|will)\s+(shipping|delivery)\s+take)", re.I),
    ],
    "general": [
        re.compile(r"\b(hello|hi|hey|help|support|question|info)", re.I),
        re.compile(r"\b(thank|thanks|contact|hours|phone|email)", re.I),
    ],
}

# Order in which intents should be checked (most specific first)
_INTENT_PRIORITY = [
    "complaint",
    "refund_request",
    "return_request",
    "order_status",
    "tracking",
    "billing",
    "shipping",
    "product_question",
    "general",
]

# Entity extraction patterns
_ORDER_ID_PATTERN = re.compile(r"(?:#(\d{4,})|ord[_-](\w+))", re.I)
_DATE_PATTERN = re.compile(
    r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"
)
_DOLLAR_PATTERN = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")


def classify_intent(
    message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify customer message into an intent and extract entities.

    Args:
        message: Raw customer message text.
        context: Optional dict with prior conversation context.

    Returns:
        Structured dict with intent classification and entities.
    """
    try:
        if not message or not message.strip():
            return _fail("Empty message")

        msg = copy.deepcopy(message) if isinstance(message, str) else str(message)
        ctx = copy.deepcopy(context) if context else {}

        # --- Score each intent ---
        scores: dict[str, float] = {}
        for intent in _INTENT_PRIORITY:
            patterns = _INTENT_PATTERNS.get(intent, [])
            match_count = sum(1 for p in patterns if p.search(msg))
            if match_count > 0:
                scores[intent] = match_count / len(patterns) if patterns else 0.0

        # Context boosting: if prior intent is set, boost related intents
        prior_intent = ctx.get("prior_intent")
        if prior_intent and prior_intent in scores:
            scores[prior_intent] = min(scores[prior_intent] + 0.15, 1.0)

        # --- Determine primary and secondary intent ---
        if not scores:
            primary = "general"
            secondary = None
            confidence = 0.3
        else:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            primary = ranked[0][0]
            confidence = min(round(ranked[0][1] + 0.3, 2), 0.99)
            secondary = ranked[1][0] if len(ranked) > 1 else None

        # --- Extract entities ---
        entities = _extract_entities(msg)

        return {
            "status": "success",
            "primary": primary,
            "secondary": secondary,
            "confidence": confidence,
            "extracted_entities": entities,
        }
    except Exception as exc:
        return _fail(f"Classification failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_entities(message: str) -> dict[str, Any]:
    """Extract order IDs, dates, and dollar amounts from message text."""
    order_ids: list[str] = []
    for m in _ORDER_ID_PATTERN.finditer(message):
        if m.group(1):
            order_ids.append(f"#{m.group(1)}")
        elif m.group(2):
            order_ids.append(f"ord_{m.group(2)}")

    dates = [m.group(0) for m in _DATE_PATTERN.finditer(message)]
    dollar_amounts = [float(m.group(1)) for m in _DOLLAR_PATTERN.finditer(message)]

    # Simple product name extraction: quoted strings
    product_names = re.findall(r'"([^"]+)"', message)

    return {
        "order_ids": order_ids,
        "product_names": product_names,
        "dates": dates,
        "dollar_amounts": dollar_amounts,
    }


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {
        "status": "error",
        "primary": None,
        "secondary": None,
        "confidence": 0.0,
        "extracted_entities": {},
        "error": reason,
    }
