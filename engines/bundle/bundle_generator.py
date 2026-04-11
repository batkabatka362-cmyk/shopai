"""Bundle Engine — bundle generator.

Generates bundle combinations from product affinities, respecting
constraints on bundle size and count.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_bundles(
    products: list[dict[str, Any]],
    affinities: list[dict[str, Any]],
    constraints: dict[str, Any],
) -> dict[str, Any]:
    """Generate bundle candidates from product affinities.

    Args:
        products: List of BundleProduct dicts.
        affinities: List of ProductAffinity dicts from affinity_analyzer.
        constraints: BundleConstraints dict.

    Returns:
        Structured dict with generated bundles.
    """
    try:
        products = copy.deepcopy(products)
        affinities = copy.deepcopy(affinities)

        min_products = int(constraints.get("min_products", 2))
        max_products = int(constraints.get("max_products", 4))
        max_bundles = int(constraints.get("max_bundles", 10))

        # Build product lookup
        prod_map = {str(p.get("id", "")): p for p in products}

        # Start with pairs from top affinities
        bundles: list[dict[str, Any]] = []
        used_combos: set[tuple[str, ...]] = set()
        bundle_counter = 0

        for aff in affinities:
            if bundle_counter >= max_bundles:
                break

            pid_a = str(aff.get("product_a", ""))
            pid_b = str(aff.get("product_b", ""))
            score = float(aff.get("affinity_score", 0.0))

            if pid_a not in prod_map or pid_b not in prod_map:
                continue

            # Start with the pair
            bundle_pids = [pid_a, pid_b]

            # Try to expand bundle with additional high-affinity products
            if max_products > 2:
                for other_aff in affinities:
                    if len(bundle_pids) >= max_products:
                        break
                    other_a = str(other_aff.get("product_a", ""))
                    other_b = str(other_aff.get("product_b", ""))
                    # Add product if it has affinity with any in bundle
                    if other_a in bundle_pids and other_b not in bundle_pids:
                        if other_b in prod_map:
                            bundle_pids.append(other_b)
                    elif other_b in bundle_pids and other_a not in bundle_pids:
                        if other_a in prod_map:
                            bundle_pids.append(other_a)

            if len(bundle_pids) < min_products:
                continue

            combo_key = tuple(sorted(bundle_pids))
            if combo_key in used_combos:
                continue
            used_combos.add(combo_key)

            # Calculate combined price
            titles = [str(prod_map[pid].get("title", pid)) for pid in bundle_pids]
            combined_price = sum(
                float(prod_map[pid].get("price", 0.0)) for pid in bundle_pids
            )

            bundle_counter += 1
            bundles.append({
                "bundle_id": f"BDL-{bundle_counter:04d}",
                "product_ids": bundle_pids,
                "product_titles": titles,
                "combined_price": round(combined_price, 2),
                "affinity_score": score,
            })

        return {
            "status": "success",
            "bundles": bundles,
        }
    except Exception as exc:
        return {
            "status": "error",
            "bundles": [],
            "error": f"Bundle generation failed: {exc}",
        }
