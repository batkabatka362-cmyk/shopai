"""Data Enrichment Engine — gap detector.

Detects missing data, sparse fields, and coverage gaps
across the dataset. Suggests remediation actions.
"""
from __future__ import annotations

import copy
from typing import Any


def detect_gaps(
    raw_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect data gaps across all records.

    Args:
        raw_data: List of raw data records.

    Returns:
        Structured dict with detected gaps and severity ratings.
    """
    try:
        records = copy.deepcopy(raw_data)
        if not records:
            return {
                "status": "success",
                "gaps": [],
                "total_gaps": 0,
            }

        # Collect all fields across all records
        all_fields: set[str] = set()
        for record in records:
            all_fields.update(record.keys())

        gaps: list[dict[str, Any]] = []
        total_records = len(records)

        for field in sorted(all_fields):
            missing_count = 0
            empty_count = 0

            for record in records:
                if field not in record:
                    missing_count += 1
                elif record[field] is None or record[field] == "" or record[field] == []:
                    empty_count += 1

            affected = missing_count + empty_count
            if affected == 0:
                continue

            pct = round(affected / total_records * 100, 1)

            # Determine gap type and severity
            if missing_count > 0 and empty_count > 0:
                gap_type = "mixed_missing"
            elif missing_count > 0:
                gap_type = "field_absent"
            else:
                gap_type = "empty_values"

            severity = _severity_from_pct(pct, field)
            suggestion = _suggest_fix(field, gap_type, pct)

            gaps.append({
                "field": field,
                "gap_type": gap_type,
                "affected_records": affected,
                "severity": severity,
                "suggestion": suggestion,
                "missing_pct": pct,
            })

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        gaps.sort(key=lambda g: severity_order.get(g["severity"], 4))

        return {
            "status": "success",
            "gaps": gaps,
            "total_gaps": len(gaps),
        }
    except Exception as exc:
        return {
            "status": "error",
            "gaps": [],
            "error": f"Gap detection failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CRITICAL_FIELDS = {"id", "price", "email", "customer_id", "order_id", "product_id"}


def _severity_from_pct(pct: float, field: str) -> str:
    """Determine severity based on missing percentage and field importance."""
    is_critical = field in _CRITICAL_FIELDS

    if is_critical and pct > 5:
        return "critical"
    if pct > 50:
        return "high" if is_critical else "medium"
    if pct > 20:
        return "medium" if is_critical else "low"
    return "low"


def _suggest_fix(field: str, gap_type: str, pct: float) -> str:
    """Suggest a fix for the detected gap."""
    if pct > 80:
        return f"Field '{field}' is largely empty — consider removing or making optional"
    if gap_type == "field_absent":
        return f"Add default value for '{field}' during data ingestion"
    if gap_type == "empty_values":
        return f"Validate '{field}' at source to prevent empty submissions"
    return f"Review data pipeline for '{field}' completeness"
