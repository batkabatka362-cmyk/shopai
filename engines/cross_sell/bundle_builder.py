"""Cross-Sell Engine — bundle builder.

Builds cross-sell bundles of 2-3 products.  Calculates an appropriate
bundle discount and projects the margin impact.

Model note: Qwen — bundle composition and discount optimization.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_BUNDLE_SIZE = 3
_MIN_BUNDLE_SIZE = 2
_MAX_BUNDLES = 5
_BASE_DISCOUNT_PERCENT = 5.0
_MAX_DISCOUNT_PERCENT = 20.0
_MIN_MARGIN_FLOOR = 0.10  # never discount below 10% margin


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_bundles(
    scored_products: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Build cross-sell bundles from scored product candidates.

    Each bundle contains 2-3 products with a calculated discount that
    preserves a minimum margin floor.

    Args:
        scored_products: AffinityScore list from affinity_scorer.
        analysis: PurchaseAnalysis from purchase_analyzer.

    Returns:
        Structured dict with bundles and status.
    """
    try:
        safe_products = copy.deepcopy(scored_products)
        safe_analysis = copy.deepcopy(analysis)

        cart_product_ids = set(safe_analysis.get("cart_product_ids", []))
        total_cart_value = safe_analysis.get("total_cart_value", 0)

        if not safe_products:
            return {
                "status": "success",
                "bundles": [],
                "model_note": "Qwen: no candidates for bundle building",
            }

        # Sort by total_affinity descending
        safe_products.sort(
            key=lambda p: float(p.get("total_affinity", 0)),
            reverse=True,
        )

        bundles: list[dict[str, Any]] = []
        used_products: set[str] = set()

        # Strategy 1: Best-pair bundles (top product + next best complement)
        for i, primary in enumerate(safe_products):
            if len(bundles) >= _MAX_BUNDLES:
                break
            pid_a = primary.get("product_id", "")
            if pid_a in used_products:
                continue

            # Find best partner from remaining products
            for secondary in safe_products[i + 1:]:
                pid_b = secondary.get("product_id", "")
                if pid_b in used_products or pid_b == pid_a:
                    continue
                # Prefer different categories for diversity
                if primary.get("category", "") != secondary.get("category", ""):
                    bundle = _create_bundle(
                        [primary, secondary],
                        total_cart_value,
                        reason="Complementary products from different categories",
                    )
                    bundles.append(bundle)
                    used_products.add(pid_a)
                    used_products.add(pid_b)
                    break

        # Strategy 2: Triple bundles from remaining high-affinity products
        remaining = [
            p for p in safe_products
            if p.get("product_id", "") not in used_products
        ]
        if len(remaining) >= 3 and len(bundles) < _MAX_BUNDLES:
            # Group by complement_type to create coherent bundles
            type_groups: dict[str, list[dict[str, Any]]] = {}
            for p in remaining:
                ct = p.get("complement_type", "companion")
                type_groups.setdefault(ct, []).append(p)

            for ct, group in type_groups.items():
                if len(group) >= 3 and len(bundles) < _MAX_BUNDLES:
                    triple = group[:3]
                    bundle = _create_bundle(
                        triple,
                        total_cart_value,
                        reason=f"Bundle of {ct} products for complete setup",
                    )
                    bundles.append(bundle)
                    for p in triple:
                        used_products.add(p.get("product_id", ""))

        # Strategy 3: Value bundles — affordable add-on collections
        value_items = [
            p for p in safe_products
            if p.get("product_id", "") not in used_products
            and float(p.get("price", 0)) <= total_cart_value * 0.3
        ]
        if len(value_items) >= _MIN_BUNDLE_SIZE and len(bundles) < _MAX_BUNDLES:
            value_bundle = _create_bundle(
                value_items[:_MAX_BUNDLE_SIZE],
                total_cart_value,
                reason="Affordable add-on bundle",
            )
            bundles.append(value_bundle)

        return {
            "status": "success",
            "bundles": bundles,
            "model_note": f"Qwen: built {len(bundles)} cross-sell bundles from {len(safe_products)} candidates",
        }
    except Exception as exc:
        return {
            "status": "error",
            "bundles": [],
            "error": f"Bundle building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _create_bundle(
    products: list[dict[str, Any]],
    total_cart_value: float,
    *,
    reason: str,
) -> dict[str, Any]:
    """Create a single bundle from a list of products."""
    bundle_products = []
    total_price = 0.0
    total_margin_value = 0.0

    for p in products:
        price = float(p.get("price", 0))
        margin = float(p.get("margin", 0))
        total_price += price
        total_margin_value += price * margin
        bundle_products.append({
            "product_id": p.get("product_id", ""),
            "title": p.get("title", ""),
            "price": price,
        })

    # Calculate discount: higher discount for higher combined price
    # relative to cart value, capped by margin floor
    discount_percent = _calculate_discount(total_price, total_cart_value, total_margin_value)
    bundle_price = round(total_price * (1 - discount_percent / 100), 2)

    # Projected margin after discount
    margin_after_discount = total_margin_value - (total_price * discount_percent / 100)
    projected_margin = round(
        margin_after_discount / bundle_price if bundle_price > 0 else 0,
        4,
    )

    bundle_id = _generate_bundle_id(products)

    return {
        "bundle_id": bundle_id,
        "products": bundle_products,
        "bundle_price": bundle_price,
        "discount_percent": round(discount_percent, 1),
        "projected_margin": max(projected_margin, 0.0),
        "reason": reason,
        "model_note": f"Qwen: {len(products)}-product bundle at {discount_percent:.1f}% discount",
    }


def _calculate_discount(
    bundle_total: float,
    cart_value: float,
    margin_value: float,
) -> float:
    """Calculate appropriate discount percent for the bundle.

    Higher discounts for larger bundles relative to cart value,
    but never below the margin floor.
    """
    if bundle_total <= 0:
        return 0.0

    # Base discount scales with bundle cost relative to cart
    if cart_value > 0:
        ratio = bundle_total / cart_value
        if ratio <= 0.2:
            discount = _BASE_DISCOUNT_PERCENT
        elif ratio <= 0.5:
            discount = _BASE_DISCOUNT_PERCENT + (ratio - 0.2) * 20
        else:
            discount = _BASE_DISCOUNT_PERCENT + 6 + (ratio - 0.5) * 10
    else:
        discount = _BASE_DISCOUNT_PERCENT

    # Ensure margin floor
    max_margin_discount = (margin_value / bundle_total - _MIN_MARGIN_FLOOR) * 100
    max_margin_discount = max(max_margin_discount, 0)

    discount = min(discount, _MAX_DISCOUNT_PERCENT, max_margin_discount)
    return max(discount, 0)


def _generate_bundle_id(products: list[dict[str, Any]]) -> str:
    """Deterministic bundle ID from product IDs."""
    pids = sorted(p.get("product_id", "") for p in products)
    raw = f"bundle|{'|'.join(pids)}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]
