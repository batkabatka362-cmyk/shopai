"""Customer Service Engine — intent classifier.

Classifies customer messages into intents using keyword/regex matching,
and extracts entities (order IDs, product names, dates, amounts).

All logic is real pattern matching. No faking, no random numbers.
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
        re.compile(r"\b(where\s+is\s+my\s+order|order\s+status|check\s+order|order\s+update)\b", re.I),
        re.compile(r"\b(what\s+happened\s+to\s+my\s+order|when\s+will\s+my\s+order)\b", re.I),
        re.compile(r"\b(has\s+my\s+order\s+(shipped|arrived|been\s+sent))\b", re.I),
        re.compile(r"\border\b.*\b(status|update|progress)\b", re.I),
    ],
    "tracking": [
        re.compile(r"\b(track(ing)?(\s+number|\s+info)?|where\s+is\s+my\s+package)\b", re.I),
        re.compile(r"\b(shipment\s+(status|update|track))\b", re.I),
        re.compile(r"\b(delivery\s+(status|update|estimate))\b", re.I),
        re.compile(r"\b(package\s+(location|status|track))\b", re.I),
    ],
    "return_request": [
        re.compile(r"\b(return|send\s+back|exchange|swap)\b", re.I),
        re.compile(r"\b(return\s+(policy|process|label|window))\b", re.I),
        re.compile(r"\b(want\s+to\s+return|how\s+do\s+i\s+return|can\s+i\s+return)\b", re.I),
        re.compile(r"\b(doesn.t\s+fit|wrong\s+(size|color|item))\b", re.I),
    ],
    "refund_request": [
        re.compile(r"\b(refund|money\s+back|reimburse|credit\s+back)\b", re.I),
        re.compile(r"\b(want\s+my\s+money\s+back|get\s+a\s+refund|request\s+refund)\b", re.I),
        re.compile(r"\b(charged\s+(twice|incorrectly|wrong\s+amount))\b", re.I),
    ],
    "product_question": [
        re.compile(r"\b(product\s+(info|detail|question|spec|feature))\b", re.I),
        re.compile(r"\b(does\s+(this|it)\s+(come|have|work|fit|support))\b", re.I),
        re.compile(r"\b(compatible|dimensions|material|warranty|size\s+guide|sizing)\b", re.I),
        re.compile(r"\b(tell\s+me\s+about|info\s+on|details\s+about)\b", re.I),
        re.compile(r"\b(what\s+(size|color|material|weight))\b", re.I),
        re.compile(r"\b(in\s+stock|availability|available)\b", re.I),
    ],
    "complaint": [
        re.compile(r"\b(complaint|complain|unhappy|dissatisfied|terrible|awful|worst)\b", re.I),
        re.compile(r"\b(unacceptable|outrageous|disgusted|furious|angry|upset)\b", re.I),
        re.compile(r"\b(broken|damaged|defective|faulty|doesn.t\s+work)\b", re.I),
        re.compile(r"\b(never\s+(again|buying|ordering|shopping))\b", re.I),
        re.compile(r"\b(horrible\s+(experience|service|quality))\b", re.I),
        re.compile(r"\b(rip.?off|scam|fraud)\b", re.I),
    ],
    "billing": [
        re.compile(r"\b(bill(ing)?|invoice|charge|payment|receipt)\b", re.I),
        re.compile(r"\b(credit\s+card|debit\s+card|payment\s+method)\b", re.I),
        re.compile(r"\b(double\s+charge|overcharge|incorrect\s+charge)\b", re.I),
        re.compile(r"\b(update\s+(payment|billing)|change\s+card)\b", re.I),
        re.compile(r"\b(promo\s*code|coupon|discount)\s*(not|didn.t|isn.t)?\s*(work|apply|applied)\b", re.I),
    ],
    "shipping": [
        re.compile(r"\b(shipping\s+(cost|rate|time|option|method|fee|policy))\b", re.I),
        re.compile(r"\b(free\s+shipping|express|overnight|rush|expedit)\b", re.I),
        re.compile(r"\b(change\s+(address|delivery)|update\s+address)\b", re.I),
        re.compile(r"\b(international\s+shipping|ship\s+to)\b", re.I),
        re.compile(r"\b(how\s+long\s+(does|will)\s+(shipping|delivery)\s+take)\b", re.I),
    ],
    "general": [
        re.compile(r"\b(help|support|question|hello|hi|hey)\b", re.I),
        re.compile(r"\b(speak|talk)\s+(to|with)\s+(a\s+)?(agent|human|representative|person|manager)\b", re.I),
        re.compile(r"\b(hours|open|close|store\s+location)\b", re.I),
        re.compile(r"\b(account|profile|password|login|sign\s+in)\b", re.I),
    ],
}

# Intent priority (higher = more specific, preferred in tie-breaks)
_INTENT_PRIORITY: dict[str, int] = {
    "refund_request": 9,
    "return_request": 8,
    "complaint": 7,
    "billing": 6,
    "order_status": 5,
    "tracking": 4,
    "shipping": 3,
    "product_question": 2,
    "general": 1,
}

# ---------------------------------------------------------------------------
# Entity extraction patterns
# ---------------------------------------------------------------------------

_ORDER_ID_PATTERNS = [
    re.compile(r"#(\d{4,})", re.I),
    re.compile(r"\bord[_-](\w{4,})\b", re.I),
    re.compile(r"\border\s+(?:number|#|id)?\s*[:#]?\s*(\d{4,})\b", re.I),
]

_DATE_PATTERN = re.compile(
    r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"
)

_AMOUNT_PATTERN = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")

_PRODUCT_HINT_PATTERN = re.compile(
    r'\b(?:product|item|order(?:ed)?|bought|purchased)\s+(?:called|named)?\s*"?([A-Z][\w\s-]{2,30})"?',
    re.I,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(
    message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a customer message into an intent and extract entities.

    Args:
        message: The customer's message text.
        context: Optional conversation context (prior intents, etc.).

    Returns:
        Structured dict with intent classification and entities.
    """
    try:
        if not message or not isinstance(message, str):
            return _fail("Message must be a non-empty string")

        text = message.strip()
        ctx = copy.deepcopy(context) if context else {}

        # --- Score each intent ---
        intent_scores: dict[str, float] = {}
        for intent, patterns in _INTENT_PATTERNS.items():
            score = 0.0
            for pat in patterns:
                matches = pat.findall(text)
                score += len(matches) * 1.0
            intent_scores[intent] = score

        # --- Context boosting ---
        prior_intent = ctx.get("prior_intent")
        if prior_intent and prior_intent in intent_scores:
            intent_scores[prior_intent] += 0.5

        # --- Pick primary + secondary ---
        ranked = sorted(
            intent_scores.items(),
            key=lambda kv: (kv[1], _INTENT_PRIORITY.get(kv[0], 0)),
            reverse=True,
        )

        primary = "general"
        secondary: str | None = None
        confidence = 0.0

        if ranked and ranked[0][1] > 0:
            primary = ranked[0][0]
            raw_score = ranked[0][1]
            # Confidence: sigmoid-like mapping — 1 match ~ 0.4, 2 ~ 0.57, 3+ ~ 0.67+
            confidence = round(min(raw_score / (raw_score + 1.5), 0.99), 2)
            if len(ranked) > 1 and ranked[1][1] > 0:
                secondary = ranked[1][0]
        else:
            confidence = 0.3  # default low confidence for general fallback

        # --- Extract entities ---
        entities = _extract_entities(text)

        # --- If order IDs found, boost order-related intents ---
        if entities.get("order_ids") and primary == "general":
            primary = "order_status"
            confidence = max(confidence, 0.55)

        return {
            "status": "success",
            "primary": primary,
            "secondary": secondary,
            "confidence": confidence,
            "extracted_entities": entities,
        }
    except Exception as exc:
        return _fail(f"Intent classification failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_entities(text: str) -> dict[str, Any]:
    """Extract order IDs, dates, amounts, and product name hints."""
    order_ids: list[str] = []
    for pat in _ORDER_ID_PATTERNS:
        for match in pat.finditer(text):
            oid = match.group(1)
            # Normalise to ord_XXXX format
            normalised = f"ord_{oid}" if not oid.startswith("ord_") else oid
            if normalised not in order_ids:
                order_ids.append(normalised)

    dates = _DATE_PATTERN.findall(text)

    amounts: list[float] = []
    for m in _AMOUNT_PATTERN.finditer(text):
        try:
            amounts.append(float(m.group(1)))
        except ValueError:
            # regex pre-filters to digit-like matches; tolerate
            # the rare edge case (e.g. "1.2.3") that float()
            # rejects -- intentional fall-through.
            pass

    product_names: list[str] = []
    for m in _PRODUCT_HINT_PATTERN.finditer(text):
        name = m.group(1).strip()
        if name and name not in product_names:
            product_names.append(name)

    return {
        "order_ids": order_ids,
        "product_names": product_names,
        "dates": dates,
        "amounts": amounts,
    }


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardised error result."""
    return {
        "status": "error",
        "primary": None,
        "secondary": None,
        "confidence": 0.0,
        "extracted_entities": {},
        "error": reason,
    }
