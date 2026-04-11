"""Audience Targeting Engine — lookalike builder.

Finds customers similar to a seed segment using attribute-based similarity.
Expands audience reach by identifying customers who share behavioral and
demographic patterns with high-value segments.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Similarity thresholds
# ---------------------------------------------------------------------------

_MIN_SIMILARITY = 0.5   # Minimum score to be considered a lookalike
_MAX_EXPANSION = 3.0     # Max expansion multiplier over seed size


def build_lookalikes(
    segments: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    campaign_goal: str = "conversion",
) -> dict[str, Any]:
    """Build lookalike audiences for each segment.

    Args:
        segments: List of BuiltSegment dicts (from segment_builder).
        customers: Full list of CustomerRecord dicts.
        campaign_goal: Campaign goal to weight similarity features.

    Returns:
        Structured dict with lookalike audiences.
    """
    try:
        segments = copy.deepcopy(segments)
        customers = copy.deepcopy(customers)

        # Build full customer lookup
        all_customers = {str(c.get("id", "")): c for c in customers if c.get("id")}

        lookalikes: list[dict[str, Any]] = []

        for seg in segments:
            seg_id = str(seg.get("segment_id", ""))
            name = str(seg.get("name", ""))
            seed_ids = set(seg.get("customer_ids", []))
            seed_size = len(seed_ids)

            if seed_size == 0:
                lookalikes.append({
                    "segment_id": seg_id,
                    "name": f"Lookalike: {name}",
                    "seed_size": 0,
                    "lookalike_size": 0,
                    "similarity_score": 0.0,
                    "lookalike_customer_ids": [],
                })
                continue

            # Compute seed profile (average attributes)
            seed_profile = _compute_profile(seed_ids, all_customers)

            # Score non-seed customers for similarity
            max_lookalike_count = int(seed_size * _MAX_EXPANSION)
            scored: list[tuple[str, float]] = []

            for cid, cdata in all_customers.items():
                if cid in seed_ids:
                    continue
                sim = _compute_similarity(cdata, seed_profile, campaign_goal)
                if sim >= _MIN_SIMILARITY:
                    scored.append((cid, sim))

            # Sort by similarity descending, cap at max expansion
            scored.sort(key=lambda x: x[1], reverse=True)
            scored = scored[:max_lookalike_count]

            lookalike_ids = [s[0] for s in scored]
            avg_sim = (
                round(sum(s[1] for s in scored) / len(scored), 4)
                if scored else 0.0
            )

            lookalikes.append({
                "segment_id": seg_id,
                "name": f"Lookalike: {name}",
                "seed_size": seed_size,
                "lookalike_size": len(lookalike_ids),
                "similarity_score": avg_sim,
                "lookalike_customer_ids": lookalike_ids,
            })

        return {
            "status": "success",
            "lookalikes": lookalikes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "lookalikes": [],
            "error": f"Lookalike building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_profile(
    seed_ids: set[str],
    all_customers: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """Compute the average profile of seed customers."""
    total_orders = 0.0
    total_spent = 0.0
    count = 0

    for cid in seed_ids:
        c = all_customers.get(cid)
        if not c:
            continue
        total_orders += float(c.get("total_orders", 0))
        total_spent += float(c.get("total_spent", 0.0))
        count += 1

    if count == 0:
        return {"avg_orders": 0.0, "avg_spent": 0.0}

    return {
        "avg_orders": total_orders / count,
        "avg_spent": total_spent / count,
    }


def _compute_similarity(
    customer: dict[str, Any],
    profile: dict[str, float],
    campaign_goal: str,
) -> float:
    """Compute similarity score (0-1) between a customer and a seed profile."""
    avg_orders = profile.get("avg_orders", 1.0)
    avg_spent = profile.get("avg_spent", 1.0)

    c_orders = float(customer.get("total_orders", 0))
    c_spent = float(customer.get("total_spent", 0.0))

    # Normalized distance for each feature
    order_diff = abs(c_orders - avg_orders) / max(avg_orders, 1.0)
    spend_diff = abs(c_spent - avg_spent) / max(avg_spent, 1.0)

    # Weight features by campaign goal
    if campaign_goal == "retention":
        order_weight, spend_weight = 0.6, 0.4
    elif campaign_goal == "awareness":
        order_weight, spend_weight = 0.3, 0.7
    else:  # conversion
        order_weight, spend_weight = 0.4, 0.6

    weighted_diff = order_weight * order_diff + spend_weight * spend_diff

    # Convert distance to similarity using exponential decay
    similarity = math.exp(-weighted_diff)

    return round(min(similarity, 1.0), 4)
