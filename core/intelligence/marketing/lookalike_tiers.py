"""Lookalike audience tier recommendations."""
from __future__ import annotations

from typing import Any

LOOKALIKE_TIERS = {
    1: {"quality": "highest", "volume": "lowest", "cpa_multiplier": 0.7, "use_case": "Scale proven winning ads"},
    2: {"quality": "high", "volume": "low", "cpa_multiplier": 0.85, "use_case": "Expand successful campaigns"},
    3: {"quality": "medium-high", "volume": "medium", "cpa_multiplier": 1.0, "use_case": "Balanced reach"},
    5: {"quality": "medium", "volume": "high", "cpa_multiplier": 1.3, "use_case": "Broad prospecting"},
    10: {"quality": "low", "volume": "highest", "cpa_multiplier": 1.8, "use_case": "Brand awareness only"},
}


def recommend_lookalike_tiers(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    """Recommend lookalike audience sizes based on campaign goals."""
    return {
        "tiers": {
            f"{pct}%": {
                "quality": info["quality"],
                "cpa_multiplier": f"{info['cpa_multiplier']}x",
                "use_case": info["use_case"],
            }
            for pct, info in LOOKALIKE_TIERS.items()
        },
        "recommendation": "Start with 1% lookalike from top 100 customers by LTV. "
                        "Scale to 2-3% only after 1% is profitable.",
    }
