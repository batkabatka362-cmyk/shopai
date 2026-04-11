"""Bundle Engine — affinity analyzer.

Analyzes order data to find frequently bought together products.
Computes co-purchase counts, affinity scores, and lift metrics.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_affinity(
    orders: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze product co-purchase affinity from order history.

    Args:
        orders: List of OrderRecord dicts with product_ids.
        products: List of BundleProduct dicts.

    Returns:
        Structured dict with product pair affinities.
    """
    try:
        orders = copy.deepcopy(orders)
        products = copy.deepcopy(products)

        total_orders = len(orders)
        if total_orders == 0:
            return {"status": "success", "affinities": []}

        # Count individual product appearances
        product_counts: dict[str, int] = {}
        # Count co-occurrence of product pairs
        pair_counts: dict[tuple[str, str], int] = {}

        for order in orders:
            pids = list(set(str(p) for p in order.get("product_ids", [])))
            for pid in pids:
                product_counts[pid] = product_counts.get(pid, 0) + 1

            # Generate all pairs
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    pair = tuple(sorted([pids[i], pids[j]]))
                    pair_counts[pair] = pair_counts.get(pair, 0) + 1

        # Build product title lookup
        title_map = {str(p.get("id", "")): str(p.get("title", "")) for p in products}

        affinities: list[dict[str, Any]] = []

        for (pid_a, pid_b), co_count in pair_counts.items():
            if co_count < 2:
                continue  # skip noise

            count_a = product_counts.get(pid_a, 1)
            count_b = product_counts.get(pid_b, 1)

            # Support: P(A and B)
            support = co_count / total_orders

            # Expected co-occurrence under independence
            expected = (count_a / total_orders) * (count_b / total_orders) * total_orders

            # Lift: actual / expected
            lift = round(co_count / expected, 3) if expected > 0 else 0.0

            # Affinity score: combination of support and lift
            affinity_score = round(support * lift * 100, 3)

            affinities.append({
                "product_a": pid_a,
                "product_b": pid_b,
                "co_purchase_count": co_count,
                "affinity_score": affinity_score,
                "lift": lift,
            })

        # Sort by affinity score descending
        affinities.sort(key=lambda x: x["affinity_score"], reverse=True)

        return {
            "status": "success",
            "affinities": affinities,
        }
    except Exception as exc:
        return {
            "status": "error",
            "affinities": [],
            "error": f"Affinity analysis failed: {exc}",
        }
