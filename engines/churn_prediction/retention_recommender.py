"""Churn Prediction Engine — retention recommender.

Recommends a retention action based on risk level and customer value.
Higher-risk and higher-value customers receive more aggressive (and
costlier) retention interventions.

Actions:
  - personal_outreach:     Direct human contact for critical/high-value customers
  - win_back_offer:        Aggressive discount or incentive to recover at-risk customers
  - loyalty_reward:        Reward program upgrade for medium-risk valued customers
  - re-engagement_email:   Automated email sequence for low-risk customers
  - exclusive_access:      Early/VIP access to new products for medium-risk high-value

Model note: Uses LLaMA for retention strategy reasoning.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Value tier thresholds
# ---------------------------------------------------------------------------

_HIGH_VALUE_LTV = 500.0       # lifetime value above this = high-value
_MEDIUM_VALUE_LTV = 150.0     # lifetime value above this = medium-value


# ---------------------------------------------------------------------------
# Action mapping: (risk_level, value_tier) -> action config
# ---------------------------------------------------------------------------

_ACTION_MAP: dict[tuple[str, str], dict[str, str]] = {
    # Critical risk
    ("critical", "high"): {
        "action": "personal_outreach",
        "rationale": "Critical risk on a high-value customer demands immediate personal contact to understand concerns and prevent loss",
        "urgency": "immediate",
        "estimated_cost_tier": "high",
    },
    ("critical", "medium"): {
        "action": "win_back_offer",
        "rationale": "Critical risk customer with moderate value warrants an aggressive win-back incentive before they fully disengage",
        "urgency": "immediate",
        "estimated_cost_tier": "medium",
    },
    ("critical", "low"): {
        "action": "win_back_offer",
        "rationale": "Critical risk requires intervention; a targeted offer may recover this customer at acceptable cost",
        "urgency": "immediate",
        "estimated_cost_tier": "low",
    },

    # High risk
    ("high", "high"): {
        "action": "personal_outreach",
        "rationale": "High-risk, high-value customer justifies personal outreach to rebuild relationship before churn becomes irreversible",
        "urgency": "immediate",
        "estimated_cost_tier": "high",
    },
    ("high", "medium"): {
        "action": "exclusive_access",
        "rationale": "High-risk customer with moderate value responds well to exclusivity signals that reinforce their importance",
        "urgency": "soon",
        "estimated_cost_tier": "medium",
    },
    ("high", "low"): {
        "action": "win_back_offer",
        "rationale": "High-risk customer with lower value can be re-engaged with a cost-effective discount offer",
        "urgency": "soon",
        "estimated_cost_tier": "low",
    },

    # Medium risk
    ("medium", "high"): {
        "action": "exclusive_access",
        "rationale": "Medium-risk high-value customer benefits from VIP treatment to reinforce loyalty before risk escalates",
        "urgency": "soon",
        "estimated_cost_tier": "medium",
    },
    ("medium", "medium"): {
        "action": "loyalty_reward",
        "rationale": "Medium-risk customer with moderate value is a good candidate for loyalty program upgrades to deepen engagement",
        "urgency": "soon",
        "estimated_cost_tier": "medium",
    },
    ("medium", "low"): {
        "action": "re-engagement_email",
        "rationale": "Medium-risk lower-value customer can be nudged back with automated re-engagement at minimal cost",
        "urgency": "routine",
        "estimated_cost_tier": "low",
    },

    # Low risk
    ("low", "high"): {
        "action": "loyalty_reward",
        "rationale": "Low-risk high-value customer benefits from proactive loyalty recognition to maintain strong engagement",
        "urgency": "routine",
        "estimated_cost_tier": "medium",
    },
    ("low", "medium"): {
        "action": "re-engagement_email",
        "rationale": "Low-risk customer with moderate value needs only a light-touch automated email to stay engaged",
        "urgency": "routine",
        "estimated_cost_tier": "low",
    },
    ("low", "low"): {
        "action": "re-engagement_email",
        "rationale": "Low-risk lower-value customer is best served by cost-efficient automated outreach",
        "urgency": "routine",
        "estimated_cost_tier": "low",
    },

    # Minimal risk
    ("minimal", "high"): {
        "action": "loyalty_reward",
        "rationale": "Minimal-risk high-value customer is healthy but benefits from proactive appreciation to reinforce retention",
        "urgency": "routine",
        "estimated_cost_tier": "low",
    },
    ("minimal", "medium"): {
        "action": "re-engagement_email",
        "rationale": "Minimal-risk customer needs only routine engagement to maintain current healthy relationship",
        "urgency": "routine",
        "estimated_cost_tier": "low",
    },
    ("minimal", "low"): {
        "action": "re-engagement_email",
        "rationale": "Minimal-risk lower-value customer requires no special intervention; routine contact suffices",
        "urgency": "routine",
        "estimated_cost_tier": "low",
    },
}

# Fallback when lookup misses
_DEFAULT_ACTION: dict[str, str] = {
    "action": "re-engagement_email",
    "rationale": "Default re-engagement email for unclassified risk/value combination",
    "urgency": "routine",
    "estimated_cost_tier": "low",
}


def recommend_retention(
    risk_level: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    """Recommend a retention action based on risk level and customer value.

    Args:
        risk_level: One of critical, high, medium, low, minimal.
        features: ExtractedFeatures (needs total_lifetime_value).

    Returns:
        Structured dict with RetentionAction data and status.
    """
    try:
        safe_features = copy.deepcopy(features)
        ltv = float(safe_features.get("total_lifetime_value", 0.0))

        # Determine value tier
        if ltv >= _HIGH_VALUE_LTV:
            value_tier = "high"
        elif ltv >= _MEDIUM_VALUE_LTV:
            value_tier = "medium"
        else:
            value_tier = "low"

        # Look up action
        key = (risk_level, value_tier)
        config = _ACTION_MAP.get(key, _DEFAULT_ACTION)

        return {
            "status": "success",
            "retention": {
                "action": config["action"],
                "rationale": config["rationale"],
                "urgency": config["urgency"],
                "estimated_cost_tier": config["estimated_cost_tier"],
                "model_note": f"LLaMA: retention strategy for {risk_level} risk, {value_tier} value customer",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "retention": {},
            "error": f"Retention recommendation failed: {exc}",
        }
