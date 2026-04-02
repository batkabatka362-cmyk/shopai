"""Customer Segmentation Engine — RFM analyzer.

Computes Recency, Frequency, Monetary scores on a 1-5 quintile scale
for each customer. Assigns RFM segment labels based on composite scores.

Real quintile-based scoring: customers are ranked against each other,
then split into five equal buckets.

Model note: Would use Mistral for RFM segment interpretation and naming.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# RFM segment labels based on composite score ranges
# ---------------------------------------------------------------------------

_RFM_SEGMENT_MAP: dict[str, tuple[int, int]] = {
    "Champions":          (445, 555),
    "Loyal":              (335, 444),
    "Potential Loyalist": (253, 334),
    "Recent Customers":   (412, 452),
    "Promising":          (312, 411),
    "Needs Attention":    (222, 311),
    "About to Sleep":     (211, 252),
    "At Risk":            (122, 221),
    "Hibernating":        (111, 211),
    "Lost":               (100, 121),
}


def analyze_rfm(
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute RFM scores for all customers using quintile ranking.

    Args:
        customers: List of normalized customer dicts.

    Returns:
        Structured dict with list of RFMScores dicts.
    """
    try:
        if not customers:
            return {"status": "success", "rfm_scores": [], "count": 0}

        custs = copy.deepcopy(customers)

        # Extract raw values
        recency_vals = [c.get("days_since_last", 0) for c in custs]
        frequency_vals = [c.get("total_orders", 0) for c in custs]
        monetary_vals = [c.get("total_spent", 0.0) for c in custs]

        # Compute quintile boundaries
        r_quintiles = _compute_quintile_boundaries(recency_vals)
        f_quintiles = _compute_quintile_boundaries(frequency_vals)
        m_quintiles = _compute_quintile_boundaries(monetary_vals)

        rfm_scores: list[dict[str, Any]] = []

        for c in custs:
            cid = c.get("id", "unknown")
            days_since = c.get("days_since_last", 0)
            orders = c.get("total_orders", 0)
            spent = c.get("total_spent", 0.0)

            # Recency: LOWER days = HIGHER score (inverted)
            r_score = _assign_quintile_inverted(days_since, r_quintiles)
            # Frequency: HIGHER orders = HIGHER score
            f_score = _assign_quintile(orders, f_quintiles)
            # Monetary: HIGHER spend = HIGHER score
            m_score = _assign_quintile(spent, m_quintiles)

            composite = r_score * 100 + f_score * 10 + m_score
            segment = _label_rfm_segment(r_score, f_score, m_score)

            rfm_scores.append({
                "customer_id": cid,
                "recency_score": r_score,
                "frequency_score": f_score,
                "monetary_score": m_score,
                "rfm_composite": composite,
                "rfm_segment": segment,
            })

        return {
            "status": "success",
            "rfm_scores": rfm_scores,
            "count": len(rfm_scores),
        }
    except Exception as exc:
        return {
            "status": "error",
            "rfm_scores": [],
            "count": 0,
            "error": f"RFM analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Quintile scoring
# ---------------------------------------------------------------------------

def _compute_quintile_boundaries(values: list[float | int]) -> list[float]:
    """Compute four boundary values that split data into five quintiles.

    Returns sorted list of 4 boundary values [Q20, Q40, Q60, Q80].
    """
    if not values:
        return [0.0, 0.0, 0.0, 0.0]

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    if n < 5:
        # With fewer than 5 customers, distribute evenly
        if n == 1:
            return [sorted_vals[0]] * 4
        step = (sorted_vals[-1] - sorted_vals[0]) / 5.0
        base = sorted_vals[0]
        return [base + step * (i + 1) for i in range(4)]

    boundaries = []
    for pct in (0.2, 0.4, 0.6, 0.8):
        idx = pct * (n - 1)
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        val = sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])
        boundaries.append(val)

    return boundaries


def _assign_quintile(value: float | int, boundaries: list[float]) -> int:
    """Assign a 1-5 quintile score where HIGHER value = HIGHER score."""
    if value <= boundaries[0]:
        return 1
    if value <= boundaries[1]:
        return 2
    if value <= boundaries[2]:
        return 3
    if value <= boundaries[3]:
        return 4
    return 5


def _assign_quintile_inverted(value: float | int, boundaries: list[float]) -> int:
    """Assign a 1-5 quintile score where LOWER value = HIGHER score (recency)."""
    if value <= boundaries[0]:
        return 5
    if value <= boundaries[1]:
        return 4
    if value <= boundaries[2]:
        return 3
    if value <= boundaries[3]:
        return 2
    return 1


def _label_rfm_segment(r: int, f: int, m: int) -> str:
    """Label an RFM segment based on the three individual scores.

    Uses score pattern matching against known segment archetypes.
    """
    composite = r * 100 + f * 10 + m

    # Check from highest-value segments downward
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 3 and m >= 3:
        return "Loyal"
    if r >= 4 and f >= 1 and f <= 2:
        return "Recent Customers"
    if r >= 3 and f >= 1 and f <= 2:
        return "Promising"
    if r >= 2 and f >= 3:
        return "Potential Loyalist"
    if r == 2 and f >= 2:
        return "Needs Attention"
    if r == 2 and f == 1:
        return "About to Sleep"
    if r == 1 and f >= 2:
        return "At Risk"
    if r == 1 and f == 1 and m >= 2:
        return "Hibernating"
    return "Lost"
