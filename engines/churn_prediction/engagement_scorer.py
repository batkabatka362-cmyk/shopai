"""Churn Prediction Engine — engagement scorer.

Scores customer engagement across multiple channels: email opens, site
visits, cart activity, and social interaction.  Produces a weighted
composite score used downstream by the churn probability calculator.

Weights:
  - email_opens:         0.30
  - site_visits:         0.30
  - cart_activity:        0.25
  - social_interaction:   0.15

Model note: Uses Mistral for engagement pattern analysis.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Scoring thresholds
# ---------------------------------------------------------------------------

# Expected monthly site visits for a healthy customer
_HEALTHY_SITE_VISITS_30D = 8.0

# Support tickets are a negative signal — more tickets lower engagement
_HIGH_TICKET_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, float] = {
    "email_opens": 0.30,
    "site_visits": 0.30,
    "cart_activity": 0.25,
    "social_interaction": 0.15,
}


def score_engagement(
    features: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Score customer engagement from extracted features and raw record.

    Args:
        features: ExtractedFeatures from feature_extractor.
        customer: Original customer record (for additional signals).

    Returns:
        Structured dict with EngagementScore data and status.
    """
    try:
        safe_features = copy.deepcopy(features)
        safe_customer = copy.deepcopy(customer)

        # --- Email opens score ---
        email_engagement = float(safe_features.get("email_engagement", 0.0))
        email_opens_score = _clamp(email_engagement)

        # --- Site visits score ---
        site_visits_30d = int(safe_customer.get("site_visits_30d", 0))
        site_visits_score = _clamp(site_visits_30d / _HEALTHY_SITE_VISITS_30D)

        # --- Cart activity score ---
        # Proxy: order frequency indicates cart conversion; site visits
        # without orders suggest browsing-only behaviour.
        order_frequency = float(safe_features.get("order_frequency", 0.0))
        if site_visits_30d > 0:
            conversion_proxy = min(order_frequency / 0.5, 1.0)  # 0.5 orders/30d = fully active
            browse_ratio = min(site_visits_30d / _HEALTHY_SITE_VISITS_30D, 1.0)
            cart_activity_score = _clamp(conversion_proxy * 0.6 + browse_ratio * 0.4)
        else:
            cart_activity_score = 0.0

        # --- Social interaction score ---
        # Proxy: low support tickets + high email engagement = healthy social
        support_tickets = int(safe_features.get("support_tickets", 0))
        ticket_penalty = min(support_tickets / _HIGH_TICKET_THRESHOLD, 1.0)
        social_interaction_score = _clamp(
            email_opens_score * 0.5 + (1.0 - ticket_penalty) * 0.5
        )

        # --- Weighted composite ---
        composite_score = round(
            _WEIGHTS["email_opens"] * email_opens_score
            + _WEIGHTS["site_visits"] * site_visits_score
            + _WEIGHTS["cart_activity"] * cart_activity_score
            + _WEIGHTS["social_interaction"] * social_interaction_score,
            4,
        )

        return {
            "status": "success",
            "engagement": {
                "email_opens_score": round(email_opens_score, 4),
                "site_visits_score": round(site_visits_score, 4),
                "cart_activity_score": round(cart_activity_score, 4),
                "social_interaction_score": round(social_interaction_score, 4),
                "composite_score": composite_score,
                "model_note": "Mistral: weighted engagement pattern analysis",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "engagement": {},
            "error": f"Engagement scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a value to [low, high]."""
    return max(low, min(high, value))
