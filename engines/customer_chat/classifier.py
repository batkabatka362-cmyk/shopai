"""Deterministic intent classifier.

Keyword-based classification with confidence scoring. Multiple
intents can match; the highest-confidence wins. Conservative
fallback to ``greeting_other`` when no signal is strong enough.

Why rule-based instead of LLM:
  - Offline-capable, reproducible, fast
  - LLM-based version goes in response_generator.py as an
    optional refinement step, not the classifier
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class IntentResult:
    intent: str
    confidence: float  # 0.0 - 1.0
    matched_keywords: list[str]


# Intent -> (keyword patterns, base confidence weight)
_RULES: dict[str, list[tuple[str, float]]] = {
    "order_status": [
        (r"\bwhere(\s+is)?\s+(my\s+)?order\b", 1.0),
        (r"\border\s+(status|update|tracking)\b", 1.0),
        (r"\btracking\s+number\b", 0.9),
        (r"\btracking\s+code\b", 0.9),
        (r"\bnot\s+(arrived|received|here)\b", 0.7),
        (r"\bwhen\s+will\s+(i\s+|my\s+)?(get|receive|arrive)\b", 0.7),
        (r"\border\s+#?\d+", 0.8),
    ],
    "shipping": [
        (r"\bshipping\s+(cost|rate|fee|time)\b", 1.0),
        (r"\bdelivery\s+(time|date|cost)\b", 1.0),
        (r"\bhow\s+(long|much).*\b(ship|deliver|arrive)\b", 0.9),
        (r"\b(international|express|standard)\s+shipping\b", 0.9),
        (r"\bfree\s+shipping\b", 0.7),
    ],
    "returns": [
        (r"\breturn\s+(this|my|the|policy)\b", 1.0),
        (r"\b(want|how)\s+to\s+return\b", 1.0),
        (r"\brefund\s+(please|me)\b", 1.0),
        (r"\bcancel\s+(my\s+)?order\b", 0.9),
        (r"\bdoesn'?t\s+fit\b", 0.8),
        (r"\bexchange\b", 0.8),
        (r"\bmoney\s+back\b", 0.8),
    ],
    "product_question": [
        (r"\bdoes\s+(it|this)\s+(have|come|work)\b", 0.9),
        (r"\bwhat\s+(size|color|material|ingredients)\b", 0.9),
        (r"\bsize\s+(guide|chart)\b", 1.0),
        (r"\bmaterials?\s+used\b", 0.8),
        (r"\bcompatible\s+with\b", 0.9),
        (r"\bingredient(s)?\b", 0.7),
        (r"\bhow\s+to\s+use\b", 0.7),
    ],
    "complaint": [
        (r"\b(disappointed|unhappy|upset)\b", 1.0),
        (r"\b(broken|damaged|defective)\b", 1.0),
        (r"\bwrong\s+(item|product|color|size)\b", 1.0),
        (r"\bworst\b", 0.9),
        (r"\bawful\b", 0.8),
        (r"\bnever\s+(buy|shop|again)\b", 0.9),
        (r"\bterrible\s+(quality|service)\b", 0.9),
    ],
}


def classify(message: str) -> IntentResult:
    """Score every intent against the message; pick the strongest.

    Returns ``greeting_other`` with confidence 0 when no rule
    matches.
    """
    if not message:
        return IntentResult(
            intent="greeting_other",
            confidence=0.0,
            matched_keywords=[],
        )

    text = message.lower()

    scores: dict[str, tuple[float, list[str]]] = {}
    for intent, rules in _RULES.items():
        total = 0.0
        matched: list[str] = []
        for pattern, weight in rules:
            if re.search(pattern, text):
                total += weight
                matched.append(pattern)
        if total > 0:
            # Normalise to 0.0-1.0 against the max possible
            # score for this intent (sum of all rule weights).
            max_score = sum(w for _, w in rules)
            normalized = min(1.0, total / max_score * 1.5)
            scores[intent] = (normalized, matched)

    if not scores:
        return IntentResult(
            intent="greeting_other",
            confidence=0.0,
            matched_keywords=[],
        )

    best_intent = max(
        scores.items(), key=lambda kv: kv[1][0],
    )
    name, (conf, matched) = best_intent
    return IntentResult(
        intent=name,
        confidence=round(conf, 2),
        matched_keywords=matched,
    )
