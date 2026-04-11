"""Supplier search — find potential suppliers for a product.

Supplier sources:
  1. Alibaba / AliExpress (China manufacturing)
  2. Domestic wholesalers (US/EU)
  3. Print-on-demand (Printful, Printify)
  4. Dropship suppliers (CJ, Spocket)
  5. Private label manufacturers

Each source has different: lead time, MOQ, cost, quality, reliability.

Input contract: {status, data: {product_type, category, target_price, target_quantity}, meta, error}
Output contract: {status, data: {suppliers}, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.helpers import safe_float, safe_int


# Supplier source profiles
SUPPLIER_SOURCES = {
    "alibaba": {
        "name": "Alibaba / China Manufacturing",
        "type": "manufacturer",
        "avg_cost_multiplier": 0.20,  # Typically 20% of retail price
        "min_moq": 100,
        "typical_moq": 500,
        "lead_time_days": {"min": 21, "typical": 35, "max": 60},
        "shipping_method": "sea_freight",
        "quality_variance": "high",  # Ranges from excellent to terrible
        "communication": "moderate",
        "payment_terms": ["Trade Assurance", "Letter of Credit", "T/T"],
        "best_for": ["custom products", "private label", "bulk orders", "low cost"],
        "risks": ["quality inconsistency", "long lead times", "communication barriers", "IP theft"],
    },
    "domestic_wholesale": {
        "name": "Domestic Wholesalers (US/EU)",
        "type": "wholesaler",
        "avg_cost_multiplier": 0.45,
        "min_moq": 10,
        "typical_moq": 50,
        "lead_time_days": {"min": 3, "typical": 7, "max": 14},
        "shipping_method": "ground",
        "quality_variance": "low",
        "communication": "excellent",
        "payment_terms": ["Net 30", "Credit Card", "COD"],
        "best_for": ["fast start", "low MOQ", "quality assurance", "easy returns"],
        "risks": ["higher cost", "limited customization", "less margin"],
    },
    "print_on_demand": {
        "name": "Print-on-Demand (Printful, Printify)",
        "type": "pod",
        "avg_cost_multiplier": 0.55,
        "min_moq": 1,
        "typical_moq": 1,
        "lead_time_days": {"min": 3, "typical": 5, "max": 10},
        "shipping_method": "direct_to_customer",
        "quality_variance": "low",
        "communication": "automated",
        "payment_terms": ["Per order", "Monthly billing"],
        "best_for": ["zero inventory risk", "custom designs", "testing ideas", "apparel"],
        "risks": ["low margins", "limited product types", "no bulk discounts"],
    },
    "dropship": {
        "name": "Dropship (CJ, Spocket, DSers)",
        "type": "dropship",
        "avg_cost_multiplier": 0.35,
        "min_moq": 1,
        "typical_moq": 1,
        "lead_time_days": {"min": 7, "typical": 14, "max": 30},
        "shipping_method": "epacket_or_express",
        "quality_variance": "medium",
        "communication": "moderate",
        "payment_terms": ["Per order", "Prepaid balance"],
        "best_for": ["zero inventory", "wide product range", "testing markets"],
        "risks": ["slow shipping", "quality control", "returns difficult", "thin margins"],
    },
    "private_label": {
        "name": "Private Label Manufacturer",
        "type": "private_label",
        "avg_cost_multiplier": 0.25,
        "min_moq": 500,
        "typical_moq": 1000,
        "lead_time_days": {"min": 30, "typical": 45, "max": 90},
        "shipping_method": "sea_freight",
        "quality_variance": "medium",
        "communication": "moderate",
        "payment_terms": ["30% deposit + 70% before shipping", "Trade Assurance"],
        "best_for": ["brand building", "unique products", "best margins", "competitive moat"],
        "risks": ["high upfront cost", "long lead times", "MOQ commitment", "design iterations"],
    },
}


def search_suppliers(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Search for suppliers — engine contract."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    features = _extract_features(data)
    matches = _find_matching_sources(features)
    ranked = _rank_sources(matches, features)

    return {
        "status": "success",
        "data": {
            "recommended_sources": ranked,
            "total_sources_evaluated": len(SUPPLIER_SOURCES),
            "top_recommendation": ranked[0] if ranked else None,
            "product_type": features.get("product_type", ""),
            "strategy_note": _strategy_note(features, ranked),
        },
        "meta": {
            "engine": "supplier_search",
            "confidence": min(0.85, len(ranked) * 0.2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return {"valid": False, "reason": "Invalid input structure"}
    data = payload["data"]
    if not (data.get("product_type") or data.get("category")):
        return {"valid": False, "reason": "Need product_type or category"}
    return {"valid": True, "reason": "OK"}


def _extract_features(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_type": data.get("product_type", data.get("category", "")),
        "target_price": safe_float(data.get("target_price", 0)),
        "target_quantity": safe_int(data.get("target_quantity", 0)),
        "budget": safe_float(data.get("budget", 0)),
        "time_constraint_days": safe_int(data.get("time_constraint_days", 60)),
        "quality_priority": data.get("quality_priority", "medium"),  # low/medium/high
        "customization_needed": data.get("customization_needed", False),
        "brand_own": data.get("brand_own", False),
        "zero_inventory_preferred": data.get("zero_inventory_preferred", False),
    }


def _find_matching_sources(features: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter supplier sources that match requirements."""
    matches = []
    target_qty = features.get("target_quantity", 0)
    time_limit = features.get("time_constraint_days", 60)

    for key, source in SUPPLIER_SOURCES.items():
        # MOQ check
        if target_qty > 0 and target_qty < source["min_moq"]:
            moq_ok = False
        else:
            moq_ok = True

        # Lead time check
        if time_limit > 0 and source["lead_time_days"]["typical"] > time_limit:
            time_ok = False
        else:
            time_ok = True

        # Zero inventory preference
        if features.get("zero_inventory_preferred") and source["type"] not in ("pod", "dropship"):
            inventory_ok = False
        else:
            inventory_ok = True

        # Customization need
        if features.get("customization_needed") and source["type"] in ("dropship",):
            custom_ok = False
        else:
            custom_ok = True

        # Brand building
        if features.get("brand_own") and source["type"] in ("dropship",):
            brand_ok = False
        else:
            brand_ok = True

        fit_score = sum([moq_ok, time_ok, inventory_ok, custom_ok, brand_ok])

        matches.append({
            "source_key": key,
            **source,
            "fit_score": fit_score,
            "max_fit": 5,
            "issues": {
                "moq": "MOQ too high for your quantity" if not moq_ok else None,
                "lead_time": "Lead time exceeds your deadline" if not time_ok else None,
                "inventory": "Requires holding inventory" if not inventory_ok else None,
                "customization": "Limited customization" if not custom_ok else None,
                "branding": "Cannot build own brand" if not brand_ok else None,
            },
        })

    return matches


def _rank_sources(matches: list[dict[str, Any]], features: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank sources by fit + calculate estimated costs."""
    target_price = features.get("target_price", 50)
    target_qty = features.get("target_quantity", 100)

    for match in matches:
        # Estimate unit cost
        unit_cost = round(target_price * match["avg_cost_multiplier"], 2)
        total_cost = round(unit_cost * max(target_qty, match["typical_moq"]), 2)
        estimated_margin = round((target_price - unit_cost) / max(target_price, 0.01) * 100, 1)

        match["estimated_unit_cost"] = unit_cost
        match["estimated_total_cost"] = total_cost
        match["estimated_margin_pct"] = estimated_margin
        match["estimated_profit_per_unit"] = round(target_price - unit_cost, 2)

        # Composite score: fit (40%) + margin (30%) + speed (20%) + quality (10%)
        fit_pct = match["fit_score"] / 5 * 40
        margin_pct = min(30, estimated_margin / 100 * 30 * 2)
        speed_pct = max(0, 20 - match["lead_time_days"]["typical"] / 90 * 20)
        quality_pct = {"low": 3, "medium": 7, "high": 10}.get(
            "low" if match["quality_variance"] == "high" else "high" if match["quality_variance"] == "low" else "medium", 5
        )
        match["composite_score"] = round(fit_pct + margin_pct + speed_pct + quality_pct)

    matches.sort(key=lambda m: m["composite_score"], reverse=True)

    # Clean up issues (remove None)
    for m in matches:
        m["issues"] = {k: v for k, v in m["issues"].items() if v}

    return matches


def _strategy_note(features: dict[str, Any], ranked: list[dict[str, Any]]) -> str:
    """Generate strategy recommendation."""
    if features.get("zero_inventory_preferred"):
        return "Zero inventory preferred — start with POD/dropship. Transition to private label after validating demand."
    if features.get("brand_own"):
        return "Brand building goal — invest in private label. Higher upfront cost but strongest long-term moat."
    if features.get("target_quantity", 0) < 50:
        return "Small quantity — start with domestic wholesale or POD to test. Scale to Alibaba when volume justifies MOQ."
    if ranked and ranked[0]["source_key"] == "alibaba":
        return "Best margins from Alibaba but verify quality with samples first. Use Trade Assurance for protection."
    return "Consider starting with domestic/POD to validate, then transition to manufacturing for better margins."


def _error_output(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "supplier_search", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
