"""Marketplace trends rules — constraints on bestseller-based product decisions.

Core guardrails:
  - Don't copy exact bestsellers (IP risk, review moat, brand protection)
  - Verify cross-platform demand before committing inventory
  - Distinguish seasonal spikes from sustained demand
  - Respect marketplace fee structures in margin calculations
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_int


SEASONAL_KEYWORDS = [
    "christmas", "halloween", "valentine", "easter", "mothers day", "fathers day",
    "back to school", "summer", "winter", "spring", "fall", "holiday", "new year",
    "thanksgiving", "black friday", "cyber monday", "prime day", "graduation",
]

RULES = [
    {
        "id": "no_exact_copy",
        "name": "No exact bestseller copies",
        "description": "Don't replicate a trademarked/patented bestseller directly",
        "severity": "blocker",
        "action": "Find adjacent opportunity — accessory, bundle, or improved variation",
        "check": lambda p: not _is_exact_copy_risk(p),
    },
    {
        "id": "cross_platform_verify",
        "name": "Cross-platform verification",
        "description": "Demand should appear on at least 2 marketplaces or channels",
        "severity": "warning",
        "action": "Single-platform demand is fragile — wait for cross-platform confirmation",
        "check": lambda p: _has_cross_platform(p),
    },
    {
        "id": "seasonal_check",
        "name": "Seasonal vs sustained demand",
        "description": "Flag products whose BSR spike aligns with seasonal events",
        "severity": "warning",
        "action": "Seasonal product — plan inventory carefully, don't over-order",
        "check": lambda p: not _is_seasonal_only(p),
    },
    {
        "id": "review_moat_check",
        "name": "Review moat too high",
        "description": "Avoid direct competition with 3000+ review listings",
        "severity": "warning",
        "action": "Review moat is insurmountable — differentiate or find adjacent niche",
        "check": lambda p: safe_int(p.get("review_count", 0)) < 3000,
    },
    {
        "id": "margin_viability",
        "name": "Minimum margin after fees",
        "description": "Product must have at least 30% gross margin after marketplace fees",
        "severity": "blocker",
        "action": "Margins too thin after fees — cannot sustain ads + operations",
        "check": lambda p: _margin_viable(p),
    },
    {
        "id": "bsr_stability",
        "name": "BSR not single-day spike",
        "description": "BSR improvement must be sustained over at least 3 data points",
        "severity": "warning",
        "action": "Single-day BSR spike — likely a promotion or viral moment, wait for confirmation",
        "check": lambda p: _bsr_is_stable(p),
    },
    {
        "id": "price_floor",
        "name": "Minimum price for viability",
        "description": "Product price must be above $12 for sustainable FBA/marketplace margins",
        "severity": "warning",
        "action": "Price too low for marketplace economics — shipping and fees eat all margin",
        "check": lambda p: safe_float(p.get("price", 0)) == 0 or safe_float(p.get("price", 0)) >= 12.0,
    },
]


def evaluate_rules(product_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all marketplace trend rules against a product opportunity."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](product_data)
        except Exception:
            passed = True  # fail-open: don't block on evaluation errors

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(RULES),
    }


def _is_exact_copy_risk(product: dict[str, Any]) -> bool:
    """Detect signals that a product is a direct copy of a branded bestseller."""
    name = str(product.get("name", "")).lower()
    has_trademark = product.get("has_trademark", False)
    has_patent = product.get("has_patent", False)
    is_brand_exclusive = product.get("is_brand_exclusive", False)

    if has_trademark or has_patent or is_brand_exclusive:
        return True

    # Known brand indicators in product name
    brand_signals = ["(tm)", "(r)", "official", "authentic", "licensed", "patented"]
    return any(signal in name for signal in brand_signals)


def _has_cross_platform(product: dict[str, Any]) -> bool:
    """Check if demand exists on multiple platforms."""
    marketplaces = product.get("marketplaces", {})
    active = 0
    for _mkt, data in marketplaces.items():
        if isinstance(data, dict) and safe_int(data.get("rank", data.get("bsr", 0))) > 0:
            active += 1
    # Also count the primary marketplace if BSR exists
    if product.get("current_bsr", 0) > 0:
        active = max(active, 1)
    return active >= 2


def _is_seasonal_only(product: dict[str, Any]) -> bool:
    """Check if the product name or category strongly suggests seasonal-only demand."""
    name = str(product.get("name", "")).lower()
    category = str(product.get("category", "")).lower()
    combined = f"{name} {category}"
    seasonal_matches = sum(1 for kw in SEASONAL_KEYWORDS if kw in combined)
    return seasonal_matches >= 1 and not product.get("evergreen_confirmed", False)


def _margin_viable(product: dict[str, Any]) -> bool:
    """Check if margin is viable after marketplace fees."""
    price = safe_float(product.get("price", 0))
    cost = safe_float(product.get("estimated_cost", 0))
    if price <= 0 or cost <= 0:
        return True  # can't evaluate without data, don't block

    marketplace = str(product.get("marketplace", "amazon")).lower()
    fee_pct = {"amazon": 0.35, "shopify": 0.08, "etsy": 0.12}.get(marketplace, 0.30)

    gross_margin = (price - cost - price * fee_pct) / price
    return gross_margin >= 0.30


def _bsr_is_stable(product: dict[str, Any]) -> bool:
    """Check that BSR improvement spans multiple data points, not a single spike."""
    history = product.get("bsr_history", [])
    if len(history) < 3:
        return len(history) == 0  # no history = can't judge, don't block

    improving = 0
    for i in range(1, len(history)):
        curr = safe_int(history[i])
        prev = safe_int(history[i - 1])
        if curr > 0 and prev > 0 and curr < prev:
            improving += 1

    return improving >= 2
