"""Supplier Communication Engine — negotiation helper.

Helps with price negotiations by analyzing order volume, supplier
history, and market leverage to produce actionable negotiation tips.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Volume discount thresholds
# ---------------------------------------------------------------------------

_VOLUME_TIERS: list[dict[str, Any]] = [
    {"min_total": 10000.0, "discount_target": 5.0, "label": "mid-volume"},
    {"min_total": 25000.0, "discount_target": 8.0, "label": "high-volume"},
    {"min_total": 50000.0, "discount_target": 12.0, "label": "strategic"},
    {"min_total": 100000.0, "discount_target": 15.0, "label": "enterprise"},
]


def generate_negotiation_tips(
    purchase_orders: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    communication_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate negotiation tips for each supplier with active POs.

    Args:
        purchase_orders: List of PurchaseOrder dicts.
        suppliers: List of SupplierRecord dicts.
        communication_history: Past communications for relationship context.

    Returns:
        Structured dict with negotiation tips per supplier.
    """
    try:
        po_items = copy.deepcopy(purchase_orders)
        supplier_map: dict[str, dict[str, Any]] = {}
        for s in suppliers:
            sid = str(s.get("supplier_id", ""))
            supplier_map[sid] = s

        # Aggregate PO totals per supplier
        supplier_totals: dict[str, float] = {}
        supplier_item_counts: dict[str, int] = {}
        for po in po_items:
            sid = str(po.get("supplier_id", ""))
            total = float(po.get("total", 0.0))
            items = po.get("items", [])
            supplier_totals[sid] = supplier_totals.get(sid, 0.0) + total
            supplier_item_counts[sid] = supplier_item_counts.get(sid, 0) + len(items)

        # Count historical communications per supplier
        history_counts: dict[str, int] = {}
        for comm in communication_history:
            sid = str(comm.get("supplier_id", ""))
            history_counts[sid] = history_counts.get(sid, 0) + 1

        tips: list[dict[str, Any]] = []

        for sid, total in supplier_totals.items():
            supplier = supplier_map.get(sid, {})
            supplier_name = str(supplier.get("name", sid))
            item_count = supplier_item_counts.get(sid, 0)
            history_count = history_counts.get(sid, 0)

            leverage_points: list[str] = []
            potential_savings = 0.0

            # Volume-based leverage
            discount_target = 0.0
            volume_label = "low-volume"
            for tier in _VOLUME_TIERS:
                if total >= tier["min_total"]:
                    discount_target = tier["discount_target"]
                    volume_label = tier["label"]

            if discount_target > 0:
                leverage_points.append(
                    f"Order total ${total:,.2f} qualifies for {volume_label} pricing ({discount_target:.0f}% target)"
                )
                potential_savings = round(total * discount_target / 100.0, 2)

            # Multi-product leverage
            if item_count >= 5:
                leverage_points.append(
                    f"Ordering {item_count} products — request bundle discount"
                )

            # Relationship leverage
            if history_count >= 10:
                leverage_points.append(
                    f"Long-standing relationship ({history_count} past communications) — loyal customer discount"
                )
            elif history_count == 0:
                leverage_points.append(
                    "New supplier relationship — request introductory pricing"
                )

            # Payment terms leverage
            payment_terms = str(supplier.get("payment_terms", ""))
            if payment_terms:
                leverage_points.append(
                    f"Offer early payment (current terms: {payment_terms}) for additional discount"
                )

            # Build tip
            if leverage_points:
                tip = f"Negotiate with {supplier_name}: target {discount_target:.0f}% savings on ${total:,.2f} order"
            else:
                tip = f"Standard order with {supplier_name} — limited negotiation leverage at current volume"

            tips.append({
                "supplier_id": sid,
                "supplier_name": supplier_name,
                "tip": tip,
                "leverage_points": leverage_points,
                "potential_savings": potential_savings,
            })

        return {
            "status": "success",
            "negotiation_tips": tips,
        }
    except Exception as exc:
        return {
            "status": "error",
            "negotiation_tips": [],
            "error": f"Negotiation analysis failed: {exc}",
        }
