"""Alternative Presenter — reference data: comparison templates and rejection categories.

Templates for formatting alternative comparisons, and a taxonomy of
rejection reasons explaining why alternatives were not selected.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Comparison formatting templates
# ---------------------------------------------------------------------------
COMPARISON_TEMPLATES: dict[str, str] = {
    "score_comparison": (
        "{alt_name} scored {alt_score:.1f} vs {sel_name}'s {sel_score:.1f} "
        "(gap: {gap:.1f} points)"
    ),
    "dimension_win": (
        "{alt_name} outperforms on {dimension}: {alt_val:.0f} vs {sel_val:.0f}"
    ),
    "dimension_loss": (
        "{alt_name} underperforms on {dimension}: {alt_val:.0f} vs {sel_val:.0f}"
    ),
    "close_second": (
        "{alt_name} is a close second (only {gap:.1f} points behind) — keep as "
        "backup if {sel_name} underperforms"
    ),
    "clear_gap": (
        "{alt_name} scored significantly lower ({gap:.1f} points behind) and is "
        "not recommended as an alternative"
    ),
    "alternative_advantage": (
        "Note: {alt_name} has better {dimension} ({alt_val:.0f} vs {sel_val:.0f}), "
        "which may matter if priorities shift"
    ),
}

# ---------------------------------------------------------------------------
# Rejection reason categories
# ---------------------------------------------------------------------------
REJECTION_CATEGORIES: dict[str, dict[str, Any]] = {
    "lower_overall_score": {
        "description": "Lower unified score across weighted dimensions",
        "severity": "definitive",
        "revisit_condition": "Revisit if selected product underperforms within 30 days",
    },
    "lower_profitability": {
        "description": "Lower profit margins make this product less financially viable",
        "severity": "definitive",
        "revisit_condition": "Revisit if margin assumptions for the selection prove optimistic",
    },
    "lower_demand": {
        "description": "Lower demand signals suggest slower sales velocity",
        "severity": "definitive",
        "revisit_condition": "Revisit if demand trends shift or seasonal patterns emerge",
    },
    "worse_competition": {
        "description": "More competitive market increases difficulty of entry",
        "severity": "significant",
        "revisit_condition": "Revisit if major competitors exit the selected product's market",
    },
    "higher_risk": {
        "description": "Higher risk profile without proportionally higher reward",
        "severity": "significant",
        "revisit_condition": "Revisit if risk factors for this product are resolved",
    },
    "goal_misalignment": {
        "description": "Product does not align with the stated optimization goal",
        "severity": "contextual",
        "revisit_condition": "Revisit if the seller's strategic goal changes",
    },
    "data_quality": {
        "description": "Insufficient or low-confidence data for this product",
        "severity": "temporary",
        "revisit_condition": "Revisit after gathering more data on this product",
    },
}

# ---------------------------------------------------------------------------
# Score gap interpretation
# ---------------------------------------------------------------------------
SCORE_GAP_LABELS: dict[str, dict[str, Any]] = {
    "negligible": {
        "max_gap": 3.0,
        "label": "statistically tied",
        "recommendation": "Either product is a reasonable choice",
    },
    "close": {
        "max_gap": 5.0,
        "label": "close second",
        "recommendation": "Keep as backup — gap is within margin of error",
    },
    "moderate": {
        "max_gap": 15.0,
        "label": "clear but not overwhelming gap",
        "recommendation": "Selection is justified but alternative has merit",
    },
    "large": {
        "max_gap": 30.0,
        "label": "significant gap",
        "recommendation": "Selection is strongly preferred",
    },
    "decisive": {
        "max_gap": 100.0,
        "label": "decisive gap",
        "recommendation": "Alternative is not competitive",
    },
}
