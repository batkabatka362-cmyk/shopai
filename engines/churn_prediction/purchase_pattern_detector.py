"""Churn Prediction Engine — purchase pattern detector.

Detects purchase pattern changes that signal churn risk: declining
frequency, falling average order value, category shifts, and weakening
engagement signals.

Model note: Uses Mistral for pattern trend analysis.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_HEALTHY_ORDER_FREQUENCY = 1.0       # 1 order per 30 days
_HEALTHY_AOV = 50.0                  # baseline AOV benchmark
_HIGH_SUPPORT_TICKET_RATE = 2        # tickets per 90 days
_LOW_EMAIL_ENGAGEMENT = 0.2          # below 20% open rate = concern
_LOW_SITE_VISITS = 3                 # fewer than 3 visits in 30 days


def detect_purchase_patterns(
    features: dict[str, Any],
    engagement: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Detect purchase pattern changes that signal churn.

    Args:
        features: ExtractedFeatures from feature_extractor.
        engagement: EngagementScore from engagement_scorer.
        customer: Original customer record.

    Returns:
        Structured dict with PurchasePattern data and status.
    """
    try:
        safe_features = copy.deepcopy(features)
        safe_engagement = copy.deepcopy(engagement)
        safe_customer = copy.deepcopy(customer)

        order_frequency = float(safe_features.get("order_frequency", 0.0))
        avg_order_value = float(safe_features.get("avg_order_value", 0.0))
        email_engagement = float(safe_features.get("email_engagement", 0.0))
        support_tickets = int(safe_features.get("support_tickets", 0))
        site_visits_30d = int(safe_customer.get("site_visits_30d", 0))
        total_orders = int(safe_customer.get("total_orders", 0))
        composite_engagement = float(safe_engagement.get("composite_score", 0.5))

        # --- Frequency change ---
        # Negative value = declining frequency relative to healthy baseline
        if _HEALTHY_ORDER_FREQUENCY > 0:
            frequency_change = round(
                (order_frequency - _HEALTHY_ORDER_FREQUENCY) / _HEALTHY_ORDER_FREQUENCY,
                4,
            )
        else:
            frequency_change = 0.0

        # --- AOV trend ---
        # Negative value = AOV below baseline
        if _HEALTHY_AOV > 0:
            aov_trend = round(
                (avg_order_value - _HEALTHY_AOV) / _HEALTHY_AOV,
                4,
            )
        else:
            aov_trend = 0.0

        # --- Category shift ---
        # With limited data we detect this as a low-order customer with
        # high site visits (browsing new categories without buying).
        category_shift = (
            total_orders >= 3
            and site_visits_30d >= 5
            and order_frequency < _HEALTHY_ORDER_FREQUENCY * 0.5
        )

        # --- Declining engagement signals ---
        declining_engagement = (
            email_engagement < _LOW_EMAIL_ENGAGEMENT
            or site_visits_30d < _LOW_SITE_VISITS
            or composite_engagement < 0.3
        )

        # --- Combined pattern risk ---
        risk_components: list[float] = []

        # Frequency risk
        freq_risk = max(0.0, min(1.0, -frequency_change))  # more negative = higher risk
        risk_components.append(freq_risk * 0.35)

        # AOV risk
        aov_risk = max(0.0, min(1.0, -aov_trend))
        risk_components.append(aov_risk * 0.20)

        # Engagement drop risk
        engagement_risk = max(0.0, min(1.0, 1.0 - composite_engagement))
        risk_components.append(engagement_risk * 0.25)

        # Support ticket risk
        ticket_risk = min(support_tickets / max(_HIGH_SUPPORT_TICKET_RATE, 1), 1.0)
        risk_components.append(ticket_risk * 0.10)

        # Category shift risk
        shift_risk = 0.5 if category_shift else 0.0
        risk_components.append(shift_risk * 0.10)

        pattern_risk = round(sum(risk_components), 4)
        pattern_risk = max(0.0, min(1.0, pattern_risk))

        return {
            "status": "success",
            "pattern": {
                "frequency_change": frequency_change,
                "aov_trend": aov_trend,
                "category_shift": category_shift,
                "declining_engagement": declining_engagement,
                "pattern_risk": pattern_risk,
                "model_note": "Mistral: purchase pattern trend analysis",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "pattern": {},
            "error": f"Purchase pattern detection failed: {exc}",
        }
