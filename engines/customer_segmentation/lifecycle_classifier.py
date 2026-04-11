"""Customer Segmentation Engine — lifecycle classifier.

Classifies each customer into a lifecycle stage based on tenure,
recency, frequency, and engagement signals.

Stages: new, active, at_risk, dormant, churned, loyal, VIP.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Stage thresholds (days / counts)
# ---------------------------------------------------------------------------

_NEW_TENURE_MAX = 60          # days
_ACTIVE_RECENCY_MAX = 30      # days since last purchase
_AT_RISK_RECENCY_MIN = 31     # days
_AT_RISK_RECENCY_MAX = 90     # days
_DORMANT_RECENCY_MIN = 91     # days
_DORMANT_RECENCY_MAX = 180    # days
_CHURNED_RECENCY_MIN = 181    # days
_LOYAL_MIN_ORDERS = 5
_VIP_MIN_ORDERS = 10
_VIP_MIN_SPENT = 1000.0


def classify_lifecycle(
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify each customer into a lifecycle stage.

    Args:
        customers: List of normalized customer dicts.

    Returns:
        Structured dict with list of LifecycleStage dicts.
    """
    try:
        if not customers:
            return {"status": "success", "stages": [], "count": 0}

        custs = copy.deepcopy(customers)
        stages: list[dict[str, Any]] = []

        for c in custs:
            stage = _classify_one(c)
            stages.append(stage)

        return {
            "status": "success",
            "stages": stages,
            "count": len(stages),
        }
    except Exception as exc:
        return {
            "status": "error",
            "stages": [],
            "count": 0,
            "error": f"Lifecycle classification failed: {exc}",
        }


def _classify_one(c: dict[str, Any]) -> dict[str, Any]:
    """Classify a single customer into a lifecycle stage."""
    cid = c.get("id", "unknown")
    tenure = c.get("tenure_days", 0)
    days_since = c.get("days_since_last", 0)
    orders = c.get("total_orders", 0)
    spent = c.get("total_spent", 0.0)
    email_opens = c.get("email_opens", 0)

    signals: list[str] = []
    confidence = 0.0

    # VIP check first — highest value customers
    if (orders >= _VIP_MIN_ORDERS
            and spent >= _VIP_MIN_SPENT
            and days_since <= _ACTIVE_RECENCY_MAX):
        stage = "VIP"
        signals = [
            f"high_orders({orders})",
            f"high_spend({spent:.0f})",
            f"recent({days_since}d)",
        ]
        confidence = min(0.95, 0.7 + (orders / 50) + (spent / 10000))

    # Loyal — repeat buyers, still active
    elif (orders >= _LOYAL_MIN_ORDERS
            and days_since <= _AT_RISK_RECENCY_MAX):
        stage = "loyal"
        signals = [
            f"repeat_buyer({orders})",
            f"recently_active({days_since}d)",
        ]
        confidence = min(0.90, 0.65 + (orders / 30))

    # New customers
    elif tenure <= _NEW_TENURE_MAX:
        stage = "new"
        signals = [f"new_tenure({tenure}d)"]
        if orders <= 1:
            signals.append("single_purchase")
            confidence = 0.85
        else:
            signals.append(f"early_repeat({orders})")
            confidence = 0.80

    # Churned — long absence
    elif days_since >= _CHURNED_RECENCY_MIN:
        stage = "churned"
        signals = [f"long_absence({days_since}d)"]
        if email_opens == 0:
            signals.append("no_email_engagement")
            confidence = 0.90
        else:
            signals.append(f"some_email({email_opens})")
            confidence = 0.75

    # Dormant — extended absence but not yet churned
    elif days_since >= _DORMANT_RECENCY_MIN:
        stage = "dormant"
        signals = [f"extended_absence({days_since}d)"]
        confidence = 0.80
        if email_opens > 0:
            signals.append(f"email_engaged({email_opens})")
            confidence = 0.70  # might not be truly dormant

    # At risk — showing early signs of disengagement
    elif days_since >= _AT_RISK_RECENCY_MIN:
        stage = "at_risk"
        signals = [f"declining_recency({days_since}d)"]
        if orders >= 3:
            signals.append(f"was_regular({orders})")
            confidence = 0.75
        else:
            confidence = 0.65

    # Active — recent engagement
    elif days_since <= _ACTIVE_RECENCY_MAX:
        stage = "active"
        signals = [f"recent_purchase({days_since}d)"]
        if orders > 1:
            signals.append(f"repeat({orders})")
        confidence = 0.85

    # Fallback
    else:
        stage = "active"
        signals = ["default_classification"]
        confidence = 0.50

    return {
        "customer_id": cid,
        "stage": stage,
        "confidence": round(confidence, 2),
        "signals": signals,
    }
