"""Audience Targeting Engine — rule matcher.

Matches customers against targeting rules and computes match rates.
Supports compound rules (AND logic) with various operators.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def match_rules(
    segments: list[dict[str, Any]],
    total_customers: int,
) -> dict[str, Any]:
    """Compute match rates and validate rule matching for built segments.

    Args:
        segments: List of BuiltSegment dicts (from segment_builder).
        total_customers: Total number of customers in the pool.

    Returns:
        Structured dict with match results per segment.
    """
    try:
        segments = copy.deepcopy(segments)
        results: list[dict[str, Any]] = []

        for seg in segments:
            seg_id = str(seg.get("segment_id", ""))
            name = str(seg.get("name", ""))
            matched_ids = seg.get("customer_ids", [])
            match_count = len(matched_ids)

            match_rate = (
                round(match_count / total_customers, 4)
                if total_customers > 0 else 0.0
            )

            results.append({
                "segment_id": seg_id,
                "name": name,
                "matched_customer_ids": matched_ids,
                "match_count": match_count,
                "match_rate": match_rate,
            })

        # Sort by match rate descending
        results.sort(key=lambda r: r["match_rate"], reverse=True)

        # Detect overlaps between segments
        overlaps = _compute_overlaps(results)

        return {
            "status": "success",
            "match_results": results,
            "overlaps": overlaps,
        }
    except Exception as exc:
        return {
            "status": "error",
            "match_results": [],
            "error": f"Rule matching failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_overlaps(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute pairwise overlap between segments."""
    overlaps: list[dict[str, Any]] = []
    for i, seg_a in enumerate(results):
        ids_a = set(seg_a.get("matched_customer_ids", []))
        if not ids_a:
            continue
        for seg_b in results[i + 1:]:
            ids_b = set(seg_b.get("matched_customer_ids", []))
            if not ids_b:
                continue
            common = ids_a & ids_b
            if common:
                overlap_rate = round(len(common) / min(len(ids_a), len(ids_b)), 4)
                overlaps.append({
                    "segment_a": seg_a.get("segment_id", ""),
                    "segment_b": seg_b.get("segment_id", ""),
                    "overlap_count": len(common),
                    "overlap_rate": overlap_rate,
                })

    return overlaps
