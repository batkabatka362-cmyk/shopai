"""Returns Management Engine — reason analyzer.

Categorizes return reasons and computes breakdown statistics.
Identifies top products per reason category.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Reason category mappings
# ---------------------------------------------------------------------------

_REASON_CATEGORIES: dict[str, list[str]] = {
    "defective": ["defective", "broken", "damaged", "malfunction", "faulty"],
    "wrong_item": ["wrong", "incorrect", "mismatch"],
    "not_as_described": ["not as described", "different", "misleading", "inaccurate"],
    "changed_mind": ["changed mind", "no longer", "dont want", "don't want"],
    "size_fit": ["size", "fit", "too small", "too large", "too big"],
    "quality": ["quality", "cheap", "poor", "low quality"],
    "late_delivery": ["late", "delay", "slow", "shipping"],
}


def analyze_reasons(
    returns: list[dict[str, Any]],
    processed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze and categorize return reasons.

    Args:
        returns: List of original ReturnRequest dicts.
        processed: List of ProcessedReturn dicts from return_processor.

    Returns:
        Structured dict with reason breakdown.
    """
    try:
        returns = copy.deepcopy(returns)

        total = len(returns)
        if total == 0:
            return {"status": "success", "reason_breakdown": []}

        # Categorize each return
        category_counts: dict[str, int] = {}
        category_products: dict[str, list[str]] = {}

        for ret in returns:
            reason = str(ret.get("reason", "")).lower().strip()
            items = ret.get("items", [])
            product_ids = [str(i.get("product_id", "")) for i in items if i.get("product_id")]

            matched_category = "other"
            for cat, keywords in _REASON_CATEGORIES.items():
                if any(kw in reason for kw in keywords):
                    matched_category = cat
                    break

            category_counts[matched_category] = category_counts.get(matched_category, 0) + 1
            category_products.setdefault(matched_category, []).extend(product_ids)

        # Build breakdown
        reason_breakdown: list[dict[str, Any]] = []
        for category, count in sorted(
            category_counts.items(), key=lambda x: x[1], reverse=True
        ):
            # Top products by frequency within category
            prod_freq: dict[str, int] = {}
            for pid in category_products.get(category, []):
                prod_freq[pid] = prod_freq.get(pid, 0) + 1
            top_products = sorted(
                prod_freq.keys(), key=lambda p: prod_freq[p], reverse=True
            )[:5]

            reason_breakdown.append({
                "category": category,
                "count": count,
                "percentage": round(count / total * 100.0, 1),
                "top_products": top_products,
            })

        return {
            "status": "success",
            "reason_breakdown": reason_breakdown,
        }
    except Exception as exc:
        return {
            "status": "error",
            "reason_breakdown": [],
            "error": f"Reason analysis failed: {exc}",
        }
