"""A/B Testing -- metric collector.

Collects (or simulates) metrics per variant: conversion rate, revenue per
visitor, bounce rate, time on page.

In production this would pull real data from an analytics backend.  Here we
simulate realistic metrics based on the baseline rate and MDE so the
downstream statistical pipeline has concrete numbers to work with.

Model note: Would use Qwen for structured metric output.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any


def collect_metrics(
    variants: list[dict[str, Any]],
    primary_metric: str,
    current_rate: float,
    mde: float,
    sample_size_per_variant: int,
) -> dict[str, Any]:
    """Collect metrics for each variant.

    For the control variant, metrics are generated at the baseline rate.
    For treatment variants, the primary metric is shifted by the MDE
    (simulating a successful test) so the statistical analyzer has a
    realistic signal to evaluate.

    Args:
        variants: List of variant objects.
        primary_metric: The metric being tested.
        current_rate: Baseline rate for the primary metric.
        mde: Minimum detectable effect (absolute).
        sample_size_per_variant: Number of visitors per variant.

    Returns:
        Structured dict with per-variant metrics.
    """
    try:
        if not variants:
            return {
                "status": "error",
                "metrics": [],
                "error": "No variants provided",
            }

        collected: list[dict[str, Any]] = []

        for variant in variants:
            is_control = variant.get("is_control", False)
            vid = variant.get("variant_id", "unknown")
            vname = variant.get("variant_name", "unknown")

            visitors = sample_size_per_variant
            if visitors <= 0:
                visitors = 1000  # fallback

            # Determine the rate for this variant
            if is_control:
                rate = current_rate
            else:
                # Treatment gets the MDE uplift
                rate = current_rate + mde

            # Generate deterministic but realistic metrics
            seed = _deterministic_seed(vid)

            metrics = _generate_metrics(
                variant_id=vid,
                variant_name=vname,
                visitors=visitors,
                rate=rate,
                primary_metric=primary_metric,
                seed=seed,
            )
            collected.append(metrics)

        return {
            "status": "success",
            "metrics": collected,
        }
    except Exception as exc:
        return {
            "status": "error",
            "metrics": [],
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_metrics(
    variant_id: str,
    variant_name: str,
    visitors: int,
    rate: float,
    primary_metric: str,
    seed: int,
) -> dict[str, Any]:
    """Generate a full metrics object for one variant."""
    # Conversion rate
    if primary_metric == "conversion_rate":
        conv_rate = rate
    else:
        conv_rate = max(0.01, min(0.99, 0.03 + (seed % 100) * 0.0001))

    conversions = max(0, round(visitors * conv_rate))
    actual_conv_rate = round(conversions / visitors, 6) if visitors > 0 else 0.0

    # Revenue per visitor
    if primary_metric == "revenue_per_visitor":
        rpv = rate
    else:
        rpv = round(2.50 + (seed % 50) * 0.05, 2)

    revenue = round(visitors * rpv, 2)

    # Bounce rate (lower is better)
    bounce_rate = round(max(0.10, min(0.80, 0.35 - (seed % 20) * 0.005)), 4)

    # Time on page (seconds)
    time_on_page = round(max(10.0, 120.0 + (seed % 60) * 1.5), 1)

    return {
        "variant_id": variant_id,
        "variant_name": variant_name,
        "visitors": visitors,
        "conversions": conversions,
        "conversion_rate": actual_conv_rate,
        "revenue": revenue,
        "revenue_per_visitor": rpv,
        "bounce_rate": bounce_rate,
        "time_on_page": time_on_page,
    }


def _deterministic_seed(variant_id: str) -> int:
    """Produce a deterministic integer seed from a variant ID."""
    h = hashlib.md5(variant_id.encode(), usedforsecurity=False).hexdigest()
    return int(h[:8], 16)
