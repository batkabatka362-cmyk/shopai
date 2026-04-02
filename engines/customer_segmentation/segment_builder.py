"""Customer Segmentation Engine — segment builder.

Builds final customer segments by combining RFM scores, behavioral
clusters, lifecycle stages, and value scores. Produces named segments
with member lists and aggregate metrics.

Model note: Would use Qwen for intelligent segment naming and boundary
detection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Segment definitions — priority ordered
# ---------------------------------------------------------------------------

_SEGMENT_RULES: list[dict[str, Any]] = [
    {
        "name": "VIP Champions",
        "match": lambda r, b, l, v: (
            l.get("stage") == "VIP"
            and v.get("value_tier") in ("platinum", "gold")
        ),
    },
    {
        "name": "Loyal High-Value",
        "match": lambda r, b, l, v: (
            l.get("stage") in ("loyal", "VIP")
            and v.get("value_tier") in ("gold", "silver")
            and r.get("rfm_segment") in ("Champions", "Loyal")
        ),
    },
    {
        "name": "Rising Stars",
        "match": lambda r, b, l, v: (
            l.get("stage") in ("new", "active")
            and r.get("frequency_score", 0) >= 3
            and v.get("value_tier") in ("silver", "gold")
        ),
    },
    {
        "name": "Active Regulars",
        "match": lambda r, b, l, v: (
            l.get("stage") == "active"
            and r.get("rfm_segment") in ("Loyal", "Potential Loyalist", "Promising")
        ),
    },
    {
        "name": "New Customers",
        "match": lambda r, b, l, v: l.get("stage") == "new",
    },
    {
        "name": "Bargain Seekers",
        "match": lambda r, b, l, v: (
            b.get("cluster") in ("bargain_hunter", "window_shopper")
            and l.get("stage") in ("active", "at_risk")
        ),
    },
    {
        "name": "At-Risk Valuable",
        "match": lambda r, b, l, v: (
            l.get("stage") == "at_risk"
            and v.get("value_tier") in ("platinum", "gold", "silver")
        ),
    },
    {
        "name": "At-Risk Standard",
        "match": lambda r, b, l, v: l.get("stage") == "at_risk",
    },
    {
        "name": "Dormant Recoverable",
        "match": lambda r, b, l, v: (
            l.get("stage") == "dormant"
            and v.get("total_clv", 0) > 200
        ),
    },
    {
        "name": "Dormant Low-Value",
        "match": lambda r, b, l, v: l.get("stage") == "dormant",
    },
    {
        "name": "Churned",
        "match": lambda r, b, l, v: l.get("stage") == "churned",
    },
]

_FALLBACK_SEGMENT = "Uncategorized"


def build_segments(
    rfm_scores: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    value_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build final segments by combining all analysis dimensions.

    Args:
        rfm_scores: List of RFMScores dicts.
        clusters: List of BehavioralCluster dicts.
        stages: List of LifecycleStage dicts.
        value_scores: List of ValueScore dicts.

    Returns:
        Structured dict with segment list and distribution.
    """
    try:
        # Index all data by customer_id
        rfm_map = {r["customer_id"]: r for r in rfm_scores}
        cluster_map = {c["customer_id"]: c for c in clusters}
        stage_map = {s["customer_id"]: s for s in stages}
        value_map = {v["customer_id"]: v for v in value_scores}

        all_ids = set(rfm_map) | set(cluster_map) | set(stage_map) | set(value_map)

        # Assign each customer to a segment
        assignments: dict[str, list[str]] = {}
        segment_clvs: dict[str, list[float]] = {}

        for cid in all_ids:
            r = rfm_map.get(cid, {})
            b = cluster_map.get(cid, {})
            l = stage_map.get(cid, {})
            v = value_map.get(cid, {})

            segment_name = _FALLBACK_SEGMENT
            for rule in _SEGMENT_RULES:
                try:
                    if rule["match"](r, b, l, v):
                        segment_name = rule["name"]
                        break
                except Exception:
                    continue

            assignments.setdefault(segment_name, []).append(cid)
            clv = float(v.get("total_clv", 0.0))
            segment_clvs.setdefault(segment_name, []).append(clv)

        # Build segment output
        segments: list[dict[str, Any]] = []
        distribution: dict[str, int] = {}
        high_value_count = 0
        at_risk_count = 0

        for seg_name, customer_ids in sorted(assignments.items(), key=lambda x: -len(x[1])):
            clvs = segment_clvs.get(seg_name, [0.0])
            avg_clv = sum(clvs) / len(clvs) if clvs else 0.0
            size = len(customer_ids)

            segments.append({
                "name": seg_name,
                "size": size,
                "customers": sorted(customer_ids),
                "avg_clv": round(avg_clv, 2),
                "strategy": "",  # filled by strategy_mapper
            })
            distribution[seg_name] = size

            # Track high value and at risk
            if seg_name in ("VIP Champions", "Loyal High-Value"):
                high_value_count += size
            if "At-Risk" in seg_name or "Dormant" in seg_name:
                at_risk_count += size

        return {
            "status": "success",
            "segments": segments,
            "segment_distribution": distribution,
            "high_value_count": high_value_count,
            "at_risk_count": at_risk_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "segments": [],
            "segment_distribution": {},
            "high_value_count": 0,
            "at_risk_count": 0,
            "error": f"Segment building failed: {exc}",
        }
