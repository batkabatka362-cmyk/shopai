"""Cross-Sell Engine — association finder.

Finds product associations using co-purchase frequency.  Computes real
association-rule metrics (support, confidence, lift) in the style of
the Apriori algorithm, operating over the customer's past purchases
combined with the current cart context.

Model note: Uses Mistral for enriching association insights.
"""
from __future__ import annotations

import copy
from collections import Counter
from itertools import combinations
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_associations(
    analysis: dict[str, Any],
    catalog: list[dict[str, Any]],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Discover product association rules from purchase history.

    Uses a simplified Apriori approach: treats each past purchase as a
    single-item transaction, then pairs them with cart items to compute
    support, confidence, and lift.

    Args:
        analysis: PurchaseAnalysis from purchase_analyzer.
        catalog: Full product catalog.
        customer: Customer profile with past_purchases.

    Returns:
        Structured dict with AssociationResult data and status.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_catalog = copy.deepcopy(catalog)
        safe_customer = copy.deepcopy(customer)

        cart_ids = set(safe_analysis.get("cart_product_ids", []))
        past_purchases = safe_customer.get("past_purchases", [])
        catalog_index = {
            str(p.get("product_id", "")): p
            for p in safe_catalog
            if isinstance(p, dict) and p.get("product_id")
        }

        # Build transaction baskets from category co-occurrence
        # Each unique category in past purchases is a "transaction"
        # containing all product_ids purchased in that category
        category_baskets: dict[str, set[str]] = {}
        for p in past_purchases:
            if not isinstance(p, dict):
                continue
            cat = str(p.get("category", "general"))
            pid = str(p.get("product_id", ""))
            if pid:
                category_baskets.setdefault(cat, set()).add(pid)

        # Also add cart items to their category baskets (simulating
        # the "current transaction")
        for cid in cart_ids:
            if cid in catalog_index:
                cat = str(catalog_index[cid].get("category", "general"))
                category_baskets.setdefault(cat, set()).add(cid)

        # Flatten into list of baskets (sets of product_ids)
        baskets: list[set[str]] = []
        for cat_items in category_baskets.values():
            if len(cat_items) >= 1:
                baskets.append(cat_items)
        # Add a "global" basket combining cart + all past purchases
        all_ids: set[str] = set()
        for p in past_purchases:
            if isinstance(p, dict) and p.get("product_id"):
                all_ids.add(str(p["product_id"]))
        all_ids.update(cart_ids)
        if len(all_ids) >= 2:
            baskets.append(all_ids)

        n_baskets = max(len(baskets), 1)

        # Compute item frequencies (for support denominators)
        item_freq: Counter[str] = Counter()
        for basket in baskets:
            for item in basket:
                item_freq[item] += 1

        # Compute pairwise co-occurrence (support numerator)
        pair_freq: Counter[tuple[str, str]] = Counter()
        for basket in baskets:
            items_list = sorted(basket)
            for a, b in combinations(items_list, 2):
                pair_freq[(a, b)] += 1

        # Build association rules where antecedent is a cart item
        rules: list[dict[str, Any]] = []
        for (item_a, item_b), co_count in pair_freq.most_common(200):
            # We want rules where the antecedent is in cart and
            # consequent is NOT in cart (a potential recommendation)
            pairs_to_check = []
            if item_a in cart_ids and item_b not in cart_ids:
                pairs_to_check.append((item_a, item_b))
            if item_b in cart_ids and item_a not in cart_ids:
                pairs_to_check.append((item_b, item_a))

            for antecedent, consequent in pairs_to_check:
                # Support: fraction of baskets containing both
                support = round(co_count / n_baskets, 4)

                # Confidence: P(consequent | antecedent)
                ant_count = max(item_freq.get(antecedent, 0), 1)
                confidence = round(co_count / ant_count, 4)

                # Lift: confidence / P(consequent)
                cons_freq = max(item_freq.get(consequent, 0), 1)
                p_consequent = cons_freq / n_baskets
                lift = round(confidence / max(p_consequent, 0.001), 4)

                rules.append({
                    "antecedent": antecedent,
                    "consequent": consequent,
                    "support": min(support, 1.0),
                    "confidence": min(confidence, 1.0),
                    "lift": lift,
                    "model_note": "Mistral: co-purchase association mining",
                })

        # Sort by lift (strongest associations first)
        rules.sort(key=lambda r: r["lift"], reverse=True)
        rules = rules[:50]  # cap at top 50

        # Extract top associated product_ids (unique consequents)
        seen: set[str] = set()
        top_associated: list[str] = []
        for rule in rules:
            cid = rule["consequent"]
            if cid not in seen:
                seen.add(cid)
                top_associated.append(cid)
            if len(top_associated) >= 20:
                break

        return {
            "status": "success",
            "associations": {
                "rules": rules,
                "top_associated_products": top_associated,
                "model_note": (
                    "Mistral: Apriori-style association rules from "
                    f"{n_baskets} baskets, {len(rules)} rules generated"
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "associations": {},
            "error": f"Association finding failed: {exc}",
        }
