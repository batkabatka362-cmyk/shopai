"""Product Selection Engine — initial scorer.

Computes an initial composite score for each candidate to produce
a ranked shortlist and rejected list.
"""
from __future__ import annotations

import copy
from typing import Any


def score_initial(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score candidates for shortlisting.

    Args:
        candidates: List of candidate product dicts with criteria and supplier info.

    Returns:
        Structured dict with scored, shortlist, and rejected lists.
    """
    try:
        items = copy.deepcopy(candidates)
        scored: list[dict[str, Any]] = []

        for item in items:
            demand = float(item.get("demand_score", 0.0))
            margin = float(item.get("margin", 0.0))
            reliability = float(item.get("supplier", {}).get("reliability", 0.5))
            criteria_pass = item.get("criteria_pass", False)

            score = round(
                demand * 0.35 + margin * 10 * 0.30 + reliability * 0.20
                + (0.15 if criteria_pass else 0.0),
                3,
            )

            item["initial_score"] = score
            scored.append(item)

        scored.sort(key=lambda x: x["initial_score"], reverse=True)

        shortlist = [s for s in scored if s.get("criteria_pass") and s.get("supplier_available")]
        rejected = [s for s in scored if not s.get("criteria_pass") or not s.get("supplier_available")]

        return {
            "status": "success",
            "scored": scored,
            "shortlist": shortlist,
            "rejected": rejected,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scored": [],
            "error": f"Initial scoring failed: {exc}",
        }
