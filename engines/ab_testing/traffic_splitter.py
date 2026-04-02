"""A/B Testing -- traffic splitter.

Splits traffic across variants: 50/50 default for two variants,
even split for multi-arm tests.  Validates minimum traffic requirements.

Model note: Would use Qwen for structured allocation output.
"""
from __future__ import annotations

import math
from typing import Any


def split_traffic(
    variants: list[dict[str, Any]],
    daily_traffic: int,
    sample_size_per_variant: int,
) -> dict[str, Any]:
    """Allocate traffic evenly across variants.

    Args:
        variants: List of variant objects (must include variant_id).
        daily_traffic: Total daily visitors available.
        sample_size_per_variant: Minimum visitors needed per variant.

    Returns:
        Structured dict with traffic allocation details.
    """
    try:
        num_variants = len(variants)
        if num_variants == 0:
            return {
                "status": "error",
                "split": {},
                "error": "No variants provided",
            }

        # Even split across all variants
        fraction = round(1.0 / num_variants, 4)
        splits: dict[str, float] = {}
        for v in variants:
            splits[v["variant_id"]] = fraction

        daily_per_variant = max(1, daily_traffic // num_variants)

        # Check minimum traffic requirement
        minimum_traffic_met = daily_per_variant > 0 and sample_size_per_variant > 0
        if minimum_traffic_met:
            # Need at least 7 days of traffic to reach sample size
            days_needed = math.ceil(sample_size_per_variant / daily_per_variant)
            # If it would take > 180 days, traffic may be insufficient
            minimum_traffic_met = days_needed <= 180

        allocation_method = "equal"

        split = {
            "num_variants": num_variants,
            "splits": splits,
            "daily_visitors_per_variant": daily_per_variant,
            "minimum_traffic_met": minimum_traffic_met,
            "allocation_method": allocation_method,
        }

        return {
            "status": "success",
            "split": split,
        }
    except Exception as exc:
        return {
            "status": "error",
            "split": {},
            "error": str(exc),
        }
