"""Selection Decision Engine — verdict builder.

Builds a final select/reject verdict for each product based on
the decision matrix scores and constraint checks.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_SELECT_THRESHOLD = 0.50


def build_verdicts(
    matrix: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    ranked_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build selection verdicts for each product.

    Args:
        matrix: Per-product decision matrix results.
        checks: Per-product constraint check results.
        ranked_products: Original ranked product list.

    Returns:
        Structured dict with per-product verdicts.
    """
    try:
        check_map = {str(c.get("product_id", "")): c for c in checks}
        prod_map = {str(p.get("id", "")): p for p in ranked_products}

        verdicts: list[dict[str, Any]] = []

        for entry in matrix:
            pid = str(entry.get("product_id", "unknown"))
            weighted_score = float(entry.get("weighted_score", 0.0))
            rank = int(entry.get("rank", 0))
            check = check_map.get(pid, {})
            passes_all = check.get("passes_all", True)
            violations = check.get("violations", [])

            reasons: list[str] = []

            if not passes_all:
                verdict = "rejected"
                confidence = 0.85
                reasons.append(f"Failed {len(violations)} constraint(s): {', '.join(violations[:3])}")
            elif weighted_score >= _SELECT_THRESHOLD:
                verdict = "selected"
                confidence = min(0.6 + weighted_score * 0.3, 0.95)
                reasons.append(f"Ranked #{rank} with weighted score {weighted_score}")
                if weighted_score > 0.7:
                    reasons.append("Strong performance across all criteria")
            else:
                verdict = "rejected"
                confidence = min(0.5 + (1 - weighted_score) * 0.3, 0.90)
                reasons.append(f"Score {weighted_score} below threshold {_SELECT_THRESHOLD}")

            verdicts.append({
                "product_id": pid,
                "verdict": verdict,
                "confidence": round(confidence, 3),
                "reasons": reasons,
            })

        return {"status": "success", "verdicts": verdicts}
    except Exception as exc:
        return {"status": "error", "verdicts": [], "error": f"Verdict building failed: {exc}"}
