"""Alternative Presenter — shows what other options were considered.

Lists the top 2-3 alternatives with their scores, explains why each
ranked lower than the selected product, and flags any close seconds
that should be kept as backup options.

Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import COMPARISON_TEMPLATES, REJECTION_CATEGORIES
from .logic import compare_to_selection, explain_rejection_reason
from .rules import validate_alternatives


def present_alternatives(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Present alternatives that were considered but not selected.

    Args:
        input_payload: dict with keys:
            - selected_product (dict): the chosen product
            - all_products (list[dict]): all evaluated candidates
            - goal (str): profit|growth|balanced

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        selected = input_payload.get("selected_product")
        if not selected or not isinstance(selected, dict):
            return _error("selected_product is required")

        all_products = input_payload.get("all_products", [])
        goal = input_payload.get("goal", "balanced")
        selected_id = selected.get("product_id", "")

        # --- Filter out the selected product ---
        candidates = [
            p for p in all_products
            if p.get("product_id") != selected_id
        ]

        # --- Sort by unified score descending ---
        candidates.sort(
            key=lambda p: p.get("unified_score", 0), reverse=True,
        )

        # --- Take top 3 alternatives ---
        top_alternatives = candidates[:3]

        # --- Build comparison for each alternative ---
        alternative_reports: list[dict[str, Any]] = []
        selected_score = selected.get("unified_score", 0)

        for alt in top_alternatives:
            comparison = compare_to_selection(alt, selected)
            rejection = explain_rejection_reason(alt, selected, goal)
            alt_score = alt.get("unified_score", 0)
            score_gap = selected_score - alt_score
            is_close_second = score_gap <= 5.0

            report = {
                "product_id": alt.get("product_id", "unknown"),
                "product_name": alt.get("product_name", alt.get("product_id", "unknown")),
                "unified_score": alt_score,
                "score_gap": round(score_gap, 1),
                "is_close_second": is_close_second,
                "comparison": comparison,
                "rejection_reason": rejection,
                "summary": _build_alternative_summary(
                    alt, selected, comparison, rejection, is_close_second,
                ),
            }
            alternative_reports.append(report)

        # --- Identify close seconds ---
        close_seconds = [a for a in alternative_reports if a["is_close_second"]]

        # --- Validate ---
        validation = validate_alternatives(alternative_reports, selected)

        return {
            "status": "success",
            "data": {
                "alternatives": alternative_reports,
                "close_seconds": close_seconds,
                "total_alternatives": len(alternative_reports),
                "total_candidates_evaluated": len(all_products),
                "selected_score": selected_score,
                "validation": validation,
            },
            "meta": {
                "module": "alternative_presenter",
                "alternatives_shown": len(alternative_reports),
                "close_seconds_count": len(close_seconds),
                "goal": goal,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Alternative presentation failed: {exc}")


def _build_alternative_summary(
    alternative: dict[str, Any],
    selected: dict[str, Any],
    comparison: dict[str, Any],
    rejection: dict[str, Any],
    is_close_second: bool,
) -> str:
    """Build a human-readable summary for one alternative."""
    alt_name = alternative.get("product_name", alternative.get("product_id", "Unknown"))
    alt_score = alternative.get("unified_score", 0)
    sel_name = selected.get("product_name", selected.get("product_id", "Unknown"))
    sel_score = selected.get("unified_score", 0)

    reason = rejection.get("primary_reason", "lower overall score")
    advantages = comparison.get("alternative_advantages", [])
    disadvantages = comparison.get("alternative_disadvantages", [])

    parts = []
    parts.append(
        f"{alt_name} scored {alt_score:.1f} vs {sel_name}'s {sel_score:.1f}"
    )

    if reason:
        parts.append(f"Not selected because: {reason}")

    if advantages:
        parts.append(f"Advantages over selection: {', '.join(advantages[:2])}")

    if disadvantages:
        parts.append(f"Weaknesses: {', '.join(disadvantages[:2])}")

    if is_close_second:
        parts.append("This is a close second — revisit if the primary selection underperforms")

    return ". ".join(parts) + "."


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "alternative_presenter"},
        "error": message,
    }
