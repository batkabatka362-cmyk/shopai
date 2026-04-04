"""Browse Recovery Engine — intent scorer.

Scores purchase intent from browsing behavior. Higher scores indicate
stronger buying signals: cart additions, product detail views, repeat
visits, time spent, and engagement depth.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_WEIGHT_CART = 35.0        # Cart items are strongest signal
_WEIGHT_PRODUCTS = 25.0    # Product views show interest
_WEIGHT_DURATION = 20.0    # Time on site indicates engagement
_WEIGHT_PAGES = 20.0       # Page depth shows exploration

# Likelihood thresholds
_HIGH_INTENT = 70.0
_MEDIUM_INTENT = 40.0


def score_intent(
    analyzed_sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score purchase intent for each browse-abandon session.

    Args:
        analyzed_sessions: List of AnalyzedSession dicts from session_analyzer.

    Returns:
        Structured dict with per-user intent scores.
    """
    try:
        items = copy.deepcopy(analyzed_sessions)
        scores: list[dict[str, Any]] = []

        for session in items:
            if not session.get("is_browse_abandon", False):
                continue

            user_id = str(session.get("user_id", "unknown"))
            products_count = int(session.get("products_viewed_count", 0))
            pages_count = int(session.get("pages_viewed_count", 0))
            duration = float(session.get("duration", 0.0))
            cart_count = int(session.get("cart_items_count", 0))

            # Compute intent score (0-100)
            cart_score = min(cart_count / 3.0, 1.0) * _WEIGHT_CART
            product_score = min(products_count / 5.0, 1.0) * _WEIGHT_PRODUCTS
            duration_score = min(duration / 300.0, 1.0) * _WEIGHT_DURATION
            page_score = min(pages_count / 8.0, 1.0) * _WEIGHT_PAGES

            intent_score = round(cart_score + product_score + duration_score + page_score, 1)

            # Identify signals
            signals: list[str] = []
            if cart_count > 0:
                signals.append(f"added_{cart_count}_to_cart")
            if products_count >= 3:
                signals.append("viewed_multiple_products")
            if duration >= 180.0:
                signals.append("extended_browsing")
            if pages_count >= 5:
                signals.append("deep_exploration")

            # Purchase likelihood
            if intent_score >= _HIGH_INTENT:
                likelihood = "high"
            elif intent_score >= _MEDIUM_INTENT:
                likelihood = "medium"
            else:
                likelihood = "low"

            scores.append({
                "user_id": user_id,
                "intent_score": intent_score,
                "signals": signals,
                "purchase_likelihood": likelihood,
            })

        return {
            "status": "success",
            "scores": scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scores": [],
            "error": f"Intent scoring failed: {exc}",
        }
