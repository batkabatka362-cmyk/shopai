"""Product Validation Engine — quality assessor.

Assesses product quality based on defect rates, grades, and review data.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_GRADE_SCORES: dict[str, float] = {
    "A": 9.0, "B": 7.0, "C": 5.0, "D": 3.0, "F": 1.0,
}


def assess_quality(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess quality for each product.

    Args:
        products: List of product dicts.

    Returns:
        Structured dict with quality assessments and summary.
    """
    try:
        items = copy.deepcopy(products)
        assessments: list[dict[str, Any]] = []
        total_score = 0.0

        for item in items:
            product_id = str(item.get("id", "unknown"))
            defect_rate = float(item.get("defect_rate_pct", 2.0))
            grade = str(item.get("quality_grade", "B")).upper()
            review_rating = float(item.get("review_rating", 4.0))

            concerns: list[str] = []

            # Score from grade
            grade_score = _GRADE_SCORES.get(grade, 5.0)

            # Penalty for defect rate
            defect_penalty = min(defect_rate * 0.5, 4.0)

            # Review bonus/penalty
            review_adj = (review_rating - 3.0) * 0.5

            quality_score = round(max(0.0, min(10.0, grade_score - defect_penalty + review_adj)), 2)

            if defect_rate > 5.0:
                concerns.append(f"High defect rate: {defect_rate:.1f}%")
            if review_rating < 3.0:
                concerns.append(f"Low review rating: {review_rating:.1f}")
            if grade in ("D", "F"):
                concerns.append(f"Low quality grade: {grade}")

            total_score += quality_score

            assessments.append({
                "id": product_id,
                "quality_score": quality_score,
                "grade": grade,
                "concerns": concerns,
            })

        n = len(assessments)
        summary = {
            "total_assessed": n,
            "avg_quality_score": round(total_score / n, 2) if n else 0.0,
            "high_quality_count": sum(1 for a in assessments if a["quality_score"] >= 7.0),
            "low_quality_count": sum(1 for a in assessments if a["quality_score"] < 4.0),
        }

        return {"status": "success", "assessments": assessments, "summary": summary}
    except Exception as exc:
        return {"status": "error", "assessments": [], "error": f"Quality assessment failed: {exc}"}
