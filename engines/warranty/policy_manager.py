"""Warranty Engine — policy manager.

Manages warranty policies: coverage terms, duration,
exclusions, and policy-product mappings.
"""
from __future__ import annotations

import copy
from typing import Any


def manage_policies(
    products: list[dict[str, Any]],
    policies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Manage warranty policies and map to products.

    Args:
        products: Product records.
        policies: Warranty policy definitions.

    Returns:
        Structured dict with policy management data.
    """
    try:
        prods = copy.deepcopy(products)
        pols = copy.deepcopy(policies)

        # Build policy lookup
        policy_map: dict[str, dict[str, Any]] = {}
        for pol in pols:
            pid = str(pol.get("id", pol.get("policy_id", "")))
            policy_map[pid] = pol

        # Map products to policies
        covered = 0
        uncovered = 0
        mappings: list[dict[str, Any]] = []

        for prod in prods:
            prod_id = str(prod.get("id", ""))
            warranty_id = str(prod.get("warranty_policy", prod.get("policy_id", "")))

            if warranty_id and warranty_id in policy_map:
                policy = policy_map[warranty_id]
                mappings.append({
                    "product_id": prod_id,
                    "policy_id": warranty_id,
                    "coverage_days": int(policy.get("duration_days", 0)),
                    "coverage_type": str(policy.get("type", "standard")),
                })
                covered += 1
            else:
                uncovered += 1

        coverage_rate = round(covered / len(prods) * 100, 1) if prods else 0.0

        return {
            "status": "success",
            "mappings": mappings,
            "policy_count": len(policy_map),
            "covered_products": covered,
            "uncovered_products": uncovered,
            "coverage_rate_pct": coverage_rate,
        }
    except Exception as exc:
        return {
            "status": "error",
            "mappings": [],
            "error": f"Policy management failed: {exc}",
        }
