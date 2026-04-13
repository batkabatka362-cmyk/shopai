"""Supplier scorer — score and rank individual suppliers on multiple dimensions.

Scoring dimensions (each 0-100):
  1. Price competitiveness — how the unit price compares to market benchmarks
  2. Quality rating — product quality based on reviews, certifications, samples
  3. Reliability — on-time delivery percentage and order accuracy
  4. Communication responsiveness — response speed and clarity
  5. MOQ flexibility — willingness to accommodate lower minimum orders
  6. Payment terms favorability — escrow, Trade Assurance, net terms available

Each dimension is weighted and combined into a composite score.
Suppliers are classified into tiers: gold / silver / bronze / unverified.
Red flags are detected for scam signals and unreliable patterns.

Input contract: {status, data: {supplier, source_type, market_price}, meta, error}
Output contract: {status, data: {scored_supplier}, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.helpers import safe_float, safe_int

from .data import (
    DIMENSION_WEIGHTS,
    RED_FLAG_INDICATORS,
    SOURCE_BENCHMARKS,
    get_benchmark,
    get_country_risk,
    get_tier,
)
from .rules import evaluate_rules


def score_supplier(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Score a single supplier — engine contract entry point."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    supplier = data.get("supplier", {})
    source_type = data.get("source_type", "alibaba")
    market_price = safe_float(data.get("market_price", 0))

    # Score each dimension
    dimension_scores = _score_all_dimensions(supplier, source_type, market_price)

    # Weighted composite
    composite = _calculate_composite(dimension_scores)

    # Tier classification
    tier_info = get_tier(composite)

    # Red flag detection
    red_flags = _detect_red_flags(supplier, market_price)

    # Downgrade tier if red flags present
    if len(red_flags) >= 2:
        tier_info = get_tier(max(0, composite - 20))
    elif any(f["severity"] >= 0.7 for f in red_flags):
        tier_info = get_tier(max(0, composite - 15))

    # Country risk adjustment
    country = supplier.get("country", "")
    country_risk = get_country_risk(country)
    country_adjustment = (country_risk["score"] - 50) / 100 * 5  # +/- up to 2.5 points
    adjusted_composite = round(min(100, max(0, composite + country_adjustment)), 1)

    # Rule evaluation context
    rule_context = {
        "reliability_score": dimension_scores.get("reliability", 0),
        "quality_score": dimension_scores.get("quality_rating", 0),
        "red_flags": [f["flag_id"] for f in red_flags],
        "account_age_years": safe_float(supplier.get("account_age_years", 0)),
        "has_payment_protection": supplier.get("has_trade_assurance", False),
        "contact_verified": supplier.get("contact_verified", False),
        "is_repeat_supplier": supplier.get("is_repeat", False),
        "sample_approved": supplier.get("sample_approved", False),
        "is_bulk_order": data.get("is_bulk_order", False),
        "backup_supplier_identified": data.get("backup_supplier_identified", False),
    }
    rules_result = evaluate_rules(rule_context)

    # Confidence based on data completeness
    confidence = _calculate_confidence(supplier)

    scored_supplier = {
        "supplier_name": supplier.get("name", "Unknown"),
        "supplier_id": supplier.get("id", ""),
        "country": country,
        "source_type": source_type,
        "dimension_scores": dimension_scores,
        "composite_score": adjusted_composite,
        "raw_composite": round(composite, 1),
        "tier": tier_info["tier"],
        "tier_label": tier_info["label"],
        "tier_description": tier_info["description"],
        "red_flags": red_flags,
        "red_flag_count": len(red_flags),
        "has_blockers": not rules_result["passed"],
        "rules_result": rules_result,
        "country_risk": country_risk,
        "confidence": confidence,
    }

    return {
        "status": "success",
        "data": {"scored_supplier": scored_supplier},
        "meta": {
            "engine": "supplier_scorer",
            "confidence": confidence,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the input payload structure."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return {"valid": False, "reason": "Invalid input structure"}
    data = payload["data"]
    if not isinstance(data.get("supplier"), dict):
        return {"valid": False, "reason": "Missing supplier data object"}
    return {"valid": True, "reason": "OK"}


def _score_all_dimensions(supplier: dict[str, Any], source_type: str,
                          market_price: float) -> dict[str, float]:
    """Score each of the 6 dimensions on a 0-100 scale."""
    benchmark = get_benchmark(source_type)
    scores: dict[str, float] = {}

    # 1. Price competitiveness
    unit_price = safe_float(supplier.get("unit_price", 0))
    if market_price > 0 and unit_price > 0:
        price_ratio = unit_price / market_price
        expected_low, expected_high = benchmark["expected_price_pct_of_retail"]
        if price_ratio <= expected_low:
            scores["price_competitiveness"] = 95  # Excellent price (but check for scam)
        elif price_ratio <= expected_high:
            scores["price_competitiveness"] = 70 + (expected_high - price_ratio) / (expected_high - expected_low) * 25
        elif price_ratio <= expected_high * 1.3:
            scores["price_competitiveness"] = 40 + (expected_high * 1.3 - price_ratio) / (expected_high * 0.3) * 30
        else:
            scores["price_competitiveness"] = max(5, 40 - (price_ratio - expected_high * 1.3) * 100)
    else:
        scores["price_competitiveness"] = 50  # No data — neutral

    # 2. Quality rating
    rating = safe_float(supplier.get("quality_rating", 0))
    review_count = safe_int(supplier.get("review_count", 0))
    quality_base = min(100, rating / 5.0 * 80) if rating > 0 else 30
    review_bonus = min(20, review_count / 50 * 20)  # Up to 20 points for volume of reviews
    scores["quality_rating"] = round(min(100, quality_base + review_bonus), 1)

    # 3. Reliability (on-time delivery)
    on_time_pct = safe_float(supplier.get("on_time_delivery_pct", 0))
    if on_time_pct > 0:
        scores["reliability"] = round(min(100, on_time_pct * 1.05), 1)  # Slight bonus for perfection
    else:
        scores["reliability"] = 40  # Unknown reliability is risky

    # 4. Communication responsiveness
    response_hours = safe_float(supplier.get("avg_response_hours", 0))
    expected_hours = benchmark["expected_response_hours"]
    if response_hours > 0:
        if response_hours <= expected_hours * 0.5:
            scores["communication"] = 95
        elif response_hours <= expected_hours:
            scores["communication"] = 75 + (expected_hours - response_hours) / expected_hours * 20
        elif response_hours <= expected_hours * 2:
            scores["communication"] = 50 + (expected_hours * 2 - response_hours) / expected_hours * 25
        else:
            scores["communication"] = max(10, 50 - (response_hours - expected_hours * 2) / expected_hours * 20)
    else:
        scores["communication"] = 45

    # 5. MOQ flexibility
    moq = safe_int(supplier.get("moq", 0))
    typical_moq = benchmark["typical_moq"]
    if moq > 0 and typical_moq > 0:
        moq_ratio = moq / typical_moq
        if moq_ratio <= 0.5:
            scores["moq_flexibility"] = 95
        elif moq_ratio <= 1.0:
            scores["moq_flexibility"] = 70 + (1.0 - moq_ratio) * 50
        elif moq_ratio <= 2.0:
            scores["moq_flexibility"] = 40 + (2.0 - moq_ratio) * 30
        else:
            scores["moq_flexibility"] = max(10, 40 - (moq_ratio - 2.0) * 15)
    else:
        scores["moq_flexibility"] = 50

    # 6. Payment terms favorability
    has_trade_assurance = supplier.get("has_trade_assurance", False)
    accepts_small_deposit = safe_float(supplier.get("deposit_pct", 100)) <= 30
    has_net_terms = supplier.get("has_net_terms", False)
    payment_score = 30  # Baseline
    if has_trade_assurance:
        payment_score += 35
    if accepts_small_deposit:
        payment_score += 20
    if has_net_terms:
        payment_score += 15
    scores["payment_terms"] = min(100, payment_score)

    return {k: round(v, 1) for k, v in scores.items()}


def _calculate_composite(dimension_scores: dict[str, float]) -> float:
    """Calculate weighted composite score from dimension scores."""
    total = 0.0
    for dim, weight in DIMENSION_WEIGHTS.items():
        total += dimension_scores.get(dim, 0) * weight
    return round(total, 1)


def _detect_red_flags(supplier: dict[str, Any], market_price: float) -> list[dict[str, Any]]:
    """Check supplier data against known red flag indicators."""
    flags: list[dict[str, Any]] = []

    # Price too low check
    unit_price = safe_float(supplier.get("unit_price", 0))
    if market_price > 0 and unit_price > 0 and (unit_price / market_price) < 0.10:
        flags.append({"flag_id": "price_too_low", "severity": 0.9,
                       "detail": f"Price ${unit_price:.2f} is below 10% of market (${market_price:.2f})"})

    # No factory photos
    if not supplier.get("has_factory_photos", True):
        flags.append({"flag_id": "no_factory_photos", "severity": 0.6,
                       "detail": "No factory or production line photos available"})

    # New account
    account_age = safe_float(supplier.get("account_age_years", 99))
    if account_age < 1.0:
        flags.append({"flag_id": "new_account", "severity": 0.5,
                       "detail": f"Account is only {account_age:.1f} years old"})

    # No trade assurance
    if not supplier.get("has_trade_assurance", True):
        flags.append({"flag_id": "no_trade_assurance", "severity": 0.7,
                       "detail": "No Trade Assurance or payment protection offered"})

    # Fake review signals
    authenticity = safe_float(supplier.get("review_authenticity_score", 1.0))
    if authenticity < 0.4:
        flags.append({"flag_id": "fake_reviews", "severity": 0.8,
                       "detail": f"Review authenticity score {authenticity:.0%} — likely fake reviews"})

    # Pressure tactics
    if supplier.get("uses_pressure_tactics", False):
        flags.append({"flag_id": "pressure_tactics", "severity": 0.7,
                       "detail": "Supplier uses urgency pressure tactics"})

    return flags


def _calculate_confidence(supplier: dict[str, Any]) -> float:
    """Calculate scoring confidence based on how much data we have."""
    data_fields = [
        "unit_price", "quality_rating", "review_count", "on_time_delivery_pct",
        "avg_response_hours", "moq", "has_trade_assurance", "account_age_years",
        "has_factory_photos", "contact_verified",
    ]
    present = sum(1 for f in data_fields if supplier.get(f) is not None)
    return round(min(0.95, present / len(data_fields)), 2)


def _error_output(reason: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": "supplier_scorer",
            "confidence": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": {"reason": reason},
    }
