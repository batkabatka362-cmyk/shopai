"""Data Enrichment Engine — quality scorer.

Scores data quality per record: completeness, accuracy,
consistency, and overall quality grade.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Required fields per entity type
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "product": ["id", "title", "price"],
    "customer": ["id", "email"],
    "order": ["id", "total", "customer_id"],
    "default": ["id"],
}


def score_quality(
    raw_data: list[dict[str, Any]],
    enriched_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score data quality for all records.

    Args:
        raw_data: Original raw data records.
        enriched_data: Enriched data records.

    Returns:
        Structured dict with quality scores per record and overall.
    """
    try:
        originals = copy.deepcopy(raw_data)
        enriched = copy.deepcopy(enriched_data)

        reports: list[dict[str, Any]] = []
        total_score = 0.0

        enriched_map = {
            str(r.get("id", i)): r
            for i, r in enumerate(enriched)
        }

        for i, record in enumerate(originals):
            record_id = str(record.get("id", i))
            enriched_rec = enriched_map.get(record_id, record)

            completeness = _score_completeness(enriched_rec)
            accuracy = _score_accuracy(enriched_rec)
            consistency = _score_consistency(record, enriched_rec)
            overall = round(
                completeness * 0.4 + accuracy * 0.3 + consistency * 0.3,
                3,
            )

            reports.append({
                "record_id": record_id,
                "completeness": completeness,
                "accuracy": accuracy,
                "consistency": consistency,
                "overall_score": overall,
            })
            total_score += overall

        avg_score = round(total_score / len(reports), 3) if reports else 0.0

        return {
            "status": "success",
            "reports": reports,
            "overall_quality_score": avg_score,
            "total_scored": len(reports),
        }
    except Exception as exc:
        return {
            "status": "error",
            "reports": [],
            "overall_quality_score": 0.0,
            "error": f"Quality scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_completeness(record: dict[str, Any]) -> float:
    """Score how complete a record is (0.0 to 1.0)."""
    if not record:
        return 0.0

    total = len(record)
    populated = sum(
        1 for v in record.values()
        if v is not None and v != "" and v != []
    )
    return round(populated / total, 3) if total > 0 else 0.0


def _score_accuracy(record: dict[str, Any]) -> float:
    """Score data accuracy based on value validity (0.0 to 1.0)."""
    if not record:
        return 0.0

    checks = 0
    passed = 0

    # Price should be positive
    price = record.get("price")
    if price is not None:
        checks += 1
        if isinstance(price, (int, float)) and price >= 0:
            passed += 1

    # Email should contain @
    email = record.get("email")
    if email is not None:
        checks += 1
        if isinstance(email, str) and "@" in email:
            passed += 1

    # Quantities should be non-negative
    for field in ("quantity", "quantity_sold", "stock", "current_stock"):
        val = record.get(field)
        if val is not None:
            checks += 1
            if isinstance(val, (int, float)) and val >= 0:
                passed += 1

    if checks == 0:
        return 0.8  # No checkable fields — assume reasonable quality

    return round(passed / checks, 3)


def _score_consistency(
    original: dict[str, Any],
    enriched: dict[str, Any],
) -> float:
    """Score consistency between original and enriched record."""
    if not original or not enriched:
        return 0.5

    # Check that original fields are preserved in enriched
    preserved = 0
    total_orig = 0
    for key, val in original.items():
        if val is not None:
            total_orig += 1
            enriched_val = enriched.get(key)
            if enriched_val == val:
                preserved += 1

    if total_orig == 0:
        return 1.0

    return round(preserved / total_orig, 3)
