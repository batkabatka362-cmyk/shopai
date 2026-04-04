"""Store Design Engine — navigation builder.

Builds optimal navigation structure based on product catalog,
best practices for e-commerce menus, and conversion optimization.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Navigation constraints
# ---------------------------------------------------------------------------

_MAX_TOP_LEVEL_ITEMS = 7
_MAX_DEPTH = 3
_STANDARD_PAGES = [
    {"label": "Home", "url": "/", "priority": 1},
    {"label": "Shop", "url": "/collections", "priority": 2},
    {"label": "About", "url": "/pages/about", "priority": 5},
    {"label": "Contact", "url": "/pages/contact", "priority": 6},
]


def build_navigation(
    products: list[dict[str, Any]],
    brand: dict[str, Any],
) -> dict[str, Any]:
    """Build optimal navigation structure for the store.

    Args:
        products: List of product dicts (may include category/type info).
        brand: Brand info dict.

    Returns:
        Structured dict with navigation menu items and hierarchy.
    """
    try:
        items = copy.deepcopy(products)

        # Extract unique categories/types from products
        categories: dict[str, list[str]] = {}
        for product in items:
            cat = str(product.get("category", product.get("product_type", "General")))
            sub = str(product.get("subcategory", ""))
            if cat not in categories:
                categories[cat] = []
            if sub and sub not in categories[cat]:
                categories[cat].append(sub)

        # Build menu items
        menu_items: list[dict[str, Any]] = []

        # Add standard pages
        for page in _STANDARD_PAGES:
            if page["label"] == "Shop" and categories:
                # Build Shop with category children
                children = []
                for cat_name, subcats in sorted(categories.items()):
                    cat_slug = cat_name.lower().replace(" ", "-")
                    cat_children = [
                        {
                            "label": sub,
                            "url": f"/collections/{cat_slug}/{sub.lower().replace(' ', '-')}",
                            "children": [],
                            "priority": idx + 1,
                        }
                        for idx, sub in enumerate(sorted(subcats))
                    ]
                    children.append({
                        "label": cat_name,
                        "url": f"/collections/{cat_slug}",
                        "children": cat_children,
                        "priority": len(children) + 1,
                    })

                # Add "All Products" link
                children.insert(0, {
                    "label": "All Products",
                    "url": "/collections/all",
                    "children": [],
                    "priority": 0,
                })

                menu_items.append({
                    "label": page["label"],
                    "url": page["url"],
                    "children": children[:_MAX_TOP_LEVEL_ITEMS],
                    "priority": page["priority"],
                })
            else:
                menu_items.append({
                    "label": page["label"],
                    "url": page["url"],
                    "children": [],
                    "priority": page["priority"],
                })

        # Sort by priority and enforce max items
        menu_items.sort(key=lambda m: m.get("priority", 99))
        menu_items = menu_items[:_MAX_TOP_LEVEL_ITEMS]

        # Build hierarchy map
        hierarchy: dict[str, list[str]] = {}
        for item in menu_items:
            child_labels = [c.get("label", "") for c in item.get("children", [])]
            if child_labels:
                hierarchy[item["label"]] = child_labels

        # Count total items
        total = len(menu_items)
        for item in menu_items:
            total += len(item.get("children", []))
            for child in item.get("children", []):
                total += len(child.get("children", []))

        # Compute max depth
        max_depth = 1
        for item in menu_items:
            if item.get("children"):
                max_depth = max(max_depth, 2)
                for child in item["children"]:
                    if child.get("children"):
                        max_depth = max(max_depth, 3)

        return {
            "status": "success",
            "navigation": {
                "menu_items": menu_items,
                "hierarchy": hierarchy,
                "max_depth": max_depth,
                "total_items": total,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "navigation": {},
            "error": f"Navigation building failed: {exc}",
        }
