"""Supplier Discovery Engine — qualification checker.

Check supplier qualifications against product requirements.
"""
from __future__ import annotations

import copy
from typing import Any


def check_qualifications(
    **kwargs: Any,
) -> dict[str, Any]:
    """Check supplier qualifications.

    Args:
        **kwargs: Must include search results and product_requirements.

    Returns:
        Structured dict with qualification check results.
    """
    try:
        requirements = copy.deepcopy(kwargs.get("product_requirements", {}))
        search_data = kwargs.get("search_engine_data", {})
        candidates = search_data.get("candidates", [])
        criteria = search_data.get("search_criteria", {})

        qualified: list[dict[str, Any]] = []

        for candidate in candidates:
            checks = {
                "meets_quality": float(candidate.get("quality_rating", 0)) >= criteria.get("min_quality", 0),
                "meets_lead_time": int(candidate.get("lead_time_days", 999)) <= criteria.get("max_lead_time_days", 90),
                "meets_moq": int(candidate.get("moq", 0)) >= criteria.get("min_moq", 1),
                "in_region": candidate.get("region", "") in criteria.get("regions", ["global"]) or "global" in criteria.get("regions", []),
            }
            passed = all(checks.values())
            score = round(sum(checks.values()) / max(len(checks), 1), 2)

            qualified.append({
                **candidate,
                "qualification_checks": checks,
                "qualified": passed,
                "qualification_score": score,
            })

        return {
            "status": "success",
            "result": {
                "qualified": [q for q in qualified if q["qualified"]],
                "disqualified": [q for q in qualified if not q["qualified"]],
                "total_checked": len(qualified),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Qualification check failed: {exc}"}
