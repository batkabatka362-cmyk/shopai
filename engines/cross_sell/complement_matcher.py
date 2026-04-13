"""Cross-Sell Engine — complement matcher.

Matches complementary products from the catalog to current cart items
using category-based rules.  For example: cases for phones, care kits
for leather goods, batteries for electronics, etc.

Model note: no model usage — deterministic rule matching.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Category complement rules
# ---------------------------------------------------------------------------

_COMPLEMENT_RULES: dict[str, list[dict[str, str]]] = {
    "electronics": [
        {"target": "accessories", "type": "accessory", "reason": "Accessories complement electronics purchases"},
        {"target": "cases", "type": "accessory", "reason": "Protective case for electronic device"},
        {"target": "cables", "type": "accessory", "reason": "Cable/charger for electronic device"},
        {"target": "batteries", "type": "accessory", "reason": "Power supply for electronic device"},
        {"target": "warranty", "type": "companion", "reason": "Extended warranty for electronics"},
        {"target": "software", "type": "companion", "reason": "Software enhances electronic device"},
    ],
    "clothing": [
        {"target": "accessories", "type": "accessory", "reason": "Fashion accessory to complete the outfit"},
        {"target": "shoes", "type": "companion", "reason": "Shoes to match clothing purchase"},
        {"target": "care", "type": "care_product", "reason": "Garment care product for clothing"},
        {"target": "laundry", "type": "care_product", "reason": "Laundry care for fabric maintenance"},
        {"target": "jewelry", "type": "accessory", "reason": "Jewelry accessory for outfit"},
    ],
    "shoes": [
        {"target": "socks", "type": "accessory", "reason": "Socks pair with shoe purchase"},
        {"target": "care", "type": "care_product", "reason": "Shoe care product for maintenance"},
        {"target": "insoles", "type": "accessory", "reason": "Comfort insoles for shoes"},
        {"target": "laces", "type": "accessory", "reason": "Replacement laces for shoes"},
    ],
    "furniture": [
        {"target": "decor", "type": "companion", "reason": "Decor complements furniture purchase"},
        {"target": "lighting", "type": "companion", "reason": "Lighting enhances furniture setup"},
        {"target": "care", "type": "care_product", "reason": "Furniture care and polish products"},
        {"target": "assembly", "type": "accessory", "reason": "Assembly tools for furniture"},
    ],
    "kitchen": [
        {"target": "utensils", "type": "accessory", "reason": "Kitchen utensils complement cookware"},
        {"target": "storage", "type": "companion", "reason": "Food storage pairs with kitchen items"},
        {"target": "cleaning", "type": "care_product", "reason": "Cleaning supplies for kitchen maintenance"},
    ],
    "sports": [
        {"target": "accessories", "type": "accessory", "reason": "Sports accessories for better performance"},
        {"target": "nutrition", "type": "companion", "reason": "Sports nutrition complements fitness gear"},
        {"target": "apparel", "type": "companion", "reason": "Athletic apparel for sports activities"},
        {"target": "bags", "type": "accessory", "reason": "Sports bag for gear transport"},
    ],
    "beauty": [
        {"target": "skincare", "type": "companion", "reason": "Skincare complements beauty purchase"},
        {"target": "tools", "type": "accessory", "reason": "Beauty tools for application"},
        {"target": "accessories", "type": "accessory", "reason": "Beauty accessories complement purchase"},
    ],
    "books": [
        {"target": "stationery", "type": "accessory", "reason": "Stationery complements book purchase"},
        {"target": "bookmarks", "type": "accessory", "reason": "Bookmark accessory for reading"},
        {"target": "lighting", "type": "companion", "reason": "Reading light for book enjoyment"},
    ],
}

# Symmetric affinities (if A complements B, B also complements A)
_SYMMETRIC_PAIRS: list[tuple[str, str, str, str]] = [
    ("phone", "case", "accessory", "Phone case protects device"),
    ("laptop", "bag", "accessory", "Laptop bag for transport"),
    ("camera", "memory", "accessory", "Memory card for camera storage"),
    ("printer", "ink", "accessory", "Ink cartridge for printer"),
    ("tablet", "stylus", "accessory", "Stylus for tablet input"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_complements(
    analysis: dict[str, Any],
    associations: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find complementary products for the current cart.

    Uses category-based rules to match catalog products that complement
    the items currently in the customer's cart.

    Args:
        analysis: PurchaseAnalysis from purchase_analyzer.
        associations: AssociationResult from association_finder.
        catalog: Full product catalog.

    Returns:
        Structured dict with complement matches and status.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_associations = copy.deepcopy(associations)
        safe_catalog = copy.deepcopy(catalog)

        cart_ids = set(safe_analysis.get("cart_product_ids", []))
        cart_categories = safe_analysis.get("cart_categories", [])
        top_associated = safe_associations.get("top_associated_products", [])

        # Build catalog index
        catalog_index: dict[str, dict[str, Any]] = {}
        for p in safe_catalog:
            if isinstance(p, dict) and p.get("product_id"):
                catalog_index[str(p["product_id"])] = p

        matches: list[dict[str, Any]] = []
        seen_products: set[str] = set()

        # Strategy 1: Rule-based complement matching
        for cart_cat in cart_categories:
            cart_cat_lower = cart_cat.lower()
            rules = _find_rules_for_category(cart_cat_lower)

            for rule in rules:
                target_cat = rule["target"]
                for pid, product in catalog_index.items():
                    if pid in cart_ids or pid in seen_products:
                        continue
                    prod_cat = str(product.get("category", "")).lower()
                    if target_cat in prod_cat or prod_cat in target_cat:
                        # Find which cart item this complements
                        matched_cart_item = _find_cart_item_for_category(
                            cart_cat, cart_ids, catalog_index
                        )
                        matches.append({
                            "product_id": pid,
                            "title": str(product.get("title", "")),
                            "category": str(product.get("category", "")),
                            "price": float(product.get("price", 0)),
                            "margin": float(product.get("margin", 0)),
                            "complement_type": rule["type"],
                            "matched_cart_item": matched_cart_item,
                            "rule_reason": rule["reason"],
                        })
                        seen_products.add(pid)

        # Strategy 2: Association-based complement matching
        # Products identified by the association finder that are in
        # the catalog but not in the cart
        for pid in top_associated:
            if pid in cart_ids or pid in seen_products:
                continue
            if pid not in catalog_index:
                continue
            product = catalog_index[pid]
            prod_cat = str(product.get("category", "")).lower()

            # Determine complement type from category relationship
            complement_type = "companion"
            for cart_cat in cart_categories:
                if cart_cat.lower() != prod_cat:
                    complement_type = "companion"
                    break
            else:
                complement_type = "upgrade"

            matched_cart_item = _find_cart_item_for_category(
                cart_categories[0] if cart_categories else "",
                cart_ids,
                catalog_index,
            )

            matches.append({
                "product_id": pid,
                "title": str(product.get("title", "")),
                "category": str(product.get("category", "")),
                "price": float(product.get("price", 0)),
                "margin": float(product.get("margin", 0)),
                "complement_type": complement_type,
                "matched_cart_item": matched_cart_item,
                "rule_reason": f"Co-purchase association with cart items (category: {prod_cat})",
            })
            seen_products.add(pid)

        # Strategy 3: Price-compatible catalog items from different categories
        price_range = safe_analysis.get("price_range", {})
        avg_price = price_range.get("avg", 0)
        if avg_price > 0 and len(matches) < 10:
            for pid, product in catalog_index.items():
                if pid in cart_ids or pid in seen_products:
                    continue
                prod_cat = str(product.get("category", "")).lower()
                prod_price = float(product.get("price", 0))

                # Cross-sell items should be lower priced than cart average
                if 0 < prod_price <= avg_price * 0.6:
                    is_different_category = all(
                        prod_cat != cc.lower() for cc in cart_categories
                    )
                    if is_different_category:
                        matched_cart_item = next(iter(cart_ids), "")
                        matches.append({
                            "product_id": pid,
                            "title": str(product.get("title", "")),
                            "category": str(product.get("category", "")),
                            "price": prod_price,
                            "margin": float(product.get("margin", 0)),
                            "complement_type": "companion",
                            "matched_cart_item": matched_cart_item,
                            "rule_reason": (
                                f"Price-compatible add-on from {prod_cat} category"
                            ),
                        })
                        seen_products.add(pid)
                if len(matches) >= 30:
                    break

        return {
            "status": "success",
            "complements": matches,
        }
    except Exception as exc:
        return {
            "status": "error",
            "complements": [],
            "error": f"Complement matching failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_rules_for_category(
    category_lower: str,
) -> list[dict[str, str]]:
    """Find all complement rules applicable to a category."""
    rules: list[dict[str, str]] = []
    for rule_cat, rule_list in _COMPLEMENT_RULES.items():
        if rule_cat in category_lower or category_lower in rule_cat:
            rules.extend(rule_list)
    # Also check symmetric pairs
    for kw_a, kw_b, ctype, reason in _SYMMETRIC_PAIRS:
        if kw_a in category_lower:
            rules.append({"target": kw_b, "type": ctype, "reason": reason})
        elif kw_b in category_lower:
            rules.append({"target": kw_a, "type": ctype, "reason": reason})
    return rules


def _find_cart_item_for_category(
    category: str,
    cart_ids: set[str],
    catalog_index: dict[str, dict[str, Any]],
) -> str:
    """Find the first cart item matching a given category."""
    cat_lower = category.lower()
    for cid in cart_ids:
        if cid in catalog_index:
            prod_cat = str(catalog_index[cid].get("category", "")).lower()
            if cat_lower in prod_cat or prod_cat in cat_lower:
                return cid
    # Fallback: return first cart item
    return next(iter(cart_ids), "")
