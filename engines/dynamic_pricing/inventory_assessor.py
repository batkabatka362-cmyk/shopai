"""Dynamic Pricing Engine — inventory assessor.

Assesses inventory health: days of stock, stockout risk, overstock risk,
urgency level, and an inventory-based price multiplier.

1 file = 1 job: inventory assessment only.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Inventory thresholds (in days of stock)
# ---------------------------------------------------------------------------

_CRITICAL_LOW = 3.0       # below = imminent stockout
_LOW_STOCK = 7.0          # below = low stock warning
_NORMAL_LOW = 14.0        # below = slightly tight
_NORMAL_HIGH = 45.0       # above = comfortable
_OVERSTOCK = 60.0         # above = overstock territory
_SEVERE_OVERSTOCK = 90.0  # above = severe overstock


def assess_inventory(
    signals: dict[str, Any],
) -> dict[str, Any]:
    """Assess inventory health and produce an inventory multiplier.

    Args:
        signals: CollectedSignals dict from signal_collector.

    Returns:
        Structured dict with InventoryAssessment data.
    """
    try:
        sig = copy.deepcopy(signals)

        days_of_stock = float(sig.get("inventory_days", 30.0))
        days_of_stock = max(days_of_stock, 0.0)

        # --- Stockout risk ---
        # Probability-like score [0, 1] of running out of stock
        if days_of_stock <= 0:
            stockout_risk = 1.0
        elif days_of_stock <= _CRITICAL_LOW:
            stockout_risk = 0.90
        elif days_of_stock <= _LOW_STOCK:
            stockout_risk = 0.60 + ((_LOW_STOCK - days_of_stock) / (_LOW_STOCK - _CRITICAL_LOW)) * 0.30
        elif days_of_stock <= _NORMAL_LOW:
            stockout_risk = 0.20 + ((_NORMAL_LOW - days_of_stock) / (_NORMAL_LOW - _LOW_STOCK)) * 0.40
        else:
            stockout_risk = max(0.0, 0.20 - (days_of_stock - _NORMAL_LOW) / 100.0)

        # --- Overstock risk ---
        # Score [0, 1] for excess inventory
        if days_of_stock >= _SEVERE_OVERSTOCK:
            overstock_risk = 0.95
        elif days_of_stock >= _OVERSTOCK:
            overstock_risk = 0.50 + ((days_of_stock - _OVERSTOCK) / (_SEVERE_OVERSTOCK - _OVERSTOCK)) * 0.45
        elif days_of_stock >= _NORMAL_HIGH:
            overstock_risk = 0.10 + ((days_of_stock - _NORMAL_HIGH) / (_OVERSTOCK - _NORMAL_HIGH)) * 0.40
        else:
            overstock_risk = 0.0

        # --- Urgency level ---
        if days_of_stock <= _CRITICAL_LOW:
            urgency_level = "critical_low"
        elif days_of_stock <= _LOW_STOCK:
            urgency_level = "low"
        elif days_of_stock >= _SEVERE_OVERSTOCK:
            urgency_level = "severe_overstock"
        elif days_of_stock >= _OVERSTOCK:
            urgency_level = "overstock"
        else:
            urgency_level = "normal"

        # --- Inventory multiplier ---
        # Low stock -> price up (scarcity premium)
        # Overstock -> price down (clear inventory)
        # Normal -> neutral
        if days_of_stock <= _CRITICAL_LOW:
            # Scarcity premium: up to +10%
            inventory_multiplier = 1.10
        elif days_of_stock <= _LOW_STOCK:
            # Moderate scarcity: +3% to +10%
            t = (_LOW_STOCK - days_of_stock) / (_LOW_STOCK - _CRITICAL_LOW)
            inventory_multiplier = 1.03 + t * 0.07
        elif days_of_stock <= _NORMAL_HIGH:
            # Normal range: no adjustment
            inventory_multiplier = 1.0
        elif days_of_stock <= _OVERSTOCK:
            # Mild overstock: -2% to -5%
            t = (days_of_stock - _NORMAL_HIGH) / (_OVERSTOCK - _NORMAL_HIGH)
            inventory_multiplier = 1.0 - t * 0.05
        elif days_of_stock <= _SEVERE_OVERSTOCK:
            # Overstock: -5% to -12%
            t = (days_of_stock - _OVERSTOCK) / (_SEVERE_OVERSTOCK - _OVERSTOCK)
            inventory_multiplier = 0.95 - t * 0.07
        else:
            # Severe overstock: -12%
            inventory_multiplier = 0.88

        return {
            "status": "success",
            "assessment": {
                "days_of_stock": round(days_of_stock, 1),
                "stockout_risk": round(stockout_risk, 3),
                "overstock_risk": round(overstock_risk, 3),
                "urgency_level": urgency_level,
                "inventory_multiplier": round(inventory_multiplier, 4),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "assessment": {},
            "error": f"Inventory assessment failed: {exc}",
        }
