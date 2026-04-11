"""Reference data for product ranking.

Tier boundary definitions, score gap significance thresholds,
ranking stability metrics, and minimum viable score requirements.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Minimum score to be included in ranking
# ---------------------------------------------------------------------------
MINIMUM_VIABLE_SCORE: float = 40.0

# ---------------------------------------------------------------------------
# Tier boundary definitions (percentage of top score)
# ---------------------------------------------------------------------------
TIER_BOUNDARIES: dict[str, float] = {
    "top_tier_pct": 90.0,       # Within 10% of #1 score
    "middle_tier_pct": 70.0,    # Within 30% of #1 score
    # Below 70% of top = bottom tier
}

TIER_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "top": {
        "label": "Top Tier",
        "description": "Strong candidates within 10% of the top score — any could be selected",
        "action": "Compare qualitatively or gather additional data to differentiate",
    },
    "middle": {
        "label": "Middle Tier",
        "description": "Decent products but clearly behind the leaders — consider as backups",
        "action": "Only pursue if top-tier products fall through",
    },
    "bottom": {
        "label": "Bottom Tier",
        "description": "Weak candidates far from the top — likely not worth pursuing",
        "action": "Discard unless new data significantly changes the analysis",
    },
}

# ---------------------------------------------------------------------------
# Score gap significance thresholds
# ---------------------------------------------------------------------------
SCORE_GAP_THRESHOLDS: dict[str, float] = {
    "too_close_to_call": 5.0,     # Gap < 5 points = statistically tied
    "clear_winner": 15.0,          # Gap > 15 points = clear winner
    "moderate_gap": 8.0,           # 5-15 points = leading but not dominant
    "tier_separation": 10.0,       # Minimum gap to consider a tier break
}

SCORE_GAP_INTERPRETATIONS: dict[str, dict[str, str]] = {
    "tied": {
        "gap_range": "0-5 points",
        "interpretation": "Products are statistically equivalent — score difference is noise",
        "action": "Use qualitative factors (brand potential, supplier reliability, personal interest)",
    },
    "slight_lead": {
        "gap_range": "5-10 points",
        "interpretation": "Top product has a slight edge but could flip with new data",
        "action": "Lean toward the leader but validate the key differentiating scores",
    },
    "moderate_lead": {
        "gap_range": "10-15 points",
        "interpretation": "Top product is clearly better but runner-up is still viable",
        "action": "Select the leader unless qualitative review reveals red flags",
    },
    "dominant": {
        "gap_range": "15+ points",
        "interpretation": "Top product is decisively better — ranking is reliable",
        "action": "Proceed with the winner — the gap is too large to be coincidental",
    },
}

# ---------------------------------------------------------------------------
# Ranking stability metrics
# ---------------------------------------------------------------------------
RANKING_STABILITY_METRICS: dict[str, Any] = {
    "score_margin_of_error": 5.0,
    "description": (
        "Given the uncertainty in each input engine, unified scores have "
        "an approximate margin of error of +/-5 points. Rankings where "
        "adjacent products are separated by less than this margin are "
        "considered unstable — small data changes could flip the order."
    ),
    "stability_levels": {
        "high": "All adjacent products separated by >5 points",
        "moderate": "1 adjacent pair within 5 points",
        "low": "Multiple adjacent pairs within 5 points — ranking is unreliable",
    },
}

# ---------------------------------------------------------------------------
# Shortlist sizing guidelines
# ---------------------------------------------------------------------------
SHORTLIST_GUIDELINES: dict[str, dict[str, Any]] = {
    "ideal_size": {
        "min": 2,
        "max": 5,
        "description": "Review 2-5 products — fewer lacks comparison, more causes paralysis",
    },
    "single_product_warning": {
        "description": (
            "Ranking a single product is not selection — it is validation. "
            "You need at least 2 candidates to make a comparative decision."
        ),
    },
    "too_many_warning": {
        "threshold": 8,
        "description": (
            "Shortlisting more than 8 products means your upstream filtering "
            "was too loose. Tighten filter criteria or raise the minimum score."
        ),
    },
}

# ---------------------------------------------------------------------------
# Ranking confidence benchmarks
# ---------------------------------------------------------------------------
RANKING_CONFIDENCE: dict[str, dict[str, Any]] = {
    "high": {
        "conditions": [
            "Clear winner with 15+ point gap",
            "All products have high confidence scores",
            "No critical conflicts in top 3",
        ],
        "trust_level": "Proceed with automated selection",
    },
    "moderate": {
        "conditions": [
            "Leading product with 8-15 point gap",
            "Most products have moderate+ confidence",
            "Minor conflicts may exist",
        ],
        "trust_level": "Review top 2-3 before finalizing",
    },
    "low": {
        "conditions": [
            "Top products within 5 points",
            "Multiple low-confidence products",
            "Critical conflicts in top candidates",
        ],
        "trust_level": "Do not auto-select — human review required",
    },
}
