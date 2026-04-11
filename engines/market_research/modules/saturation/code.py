"""Market saturation analysis — detect overcrowded markets.

Saturation = too many sellers chasing too few buyers.
Signals:
  - High competitor count relative to demand
  - Price race to bottom (avg price declining)
  - Low average margins across category
  - Top sellers dominating (concentration)
  - Ad costs rising (CPCs increasing)
  - Review velocity slowing (market mature)

Saturation index: 0 (empty market) to 100 (completely saturated)

Input contract:  {status, data: {competitors, search_data, pricing, category}, meta, error}
Output contract: {status, data: {saturation_analysis}, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import copy
import math
import time
from typing import Any

from utils.helpers import safe_float, safe_int


def analyze_saturation(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Main saturation analysis — follows engine contract.

    6 stages: validate → extract → decide → execute → validate_output → return
    """
    # Stage 1: Input validation
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    # Stage 2: Feature extraction
    data = copy.deepcopy(input_payload.get("data", {}))
    features = _extract_features(data)

    # Stage 3: Decision logic — compute saturation signals
    signals = _compute_signals(features)

    # Stage 4: Execution — aggregate into saturation index
    analysis = _build_saturation_analysis(signals, features)

    # Stage 5: Output validation
    output_check = _validate_output(analysis)
    if not output_check["valid"]:
        return _error_output(output_check["reason"])

    # Stage 6: Return structured output
    return {
        "status": "success",
        "data": analysis,
        "meta": {
            "engine": "saturation_analyzer",
            "confidence": _compute_confidence(features),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


# ── Stage 1: Input Validation ──

def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Input must be dict"}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Input.data must be dict"}
    if not (data.get("competitors") or data.get("category") or data.get("pricing")):
        return {"valid": False, "reason": "Need competitors, category, or pricing data"}
    return {"valid": True, "reason": "OK"}


# ── Stage 2: Feature Extraction ──

def _extract_features(data: dict[str, Any]) -> dict[str, Any]:
    """Extract saturation-relevant features. No input mutation."""
    features: dict[str, Any] = {"category": data.get("category", "")}

    # Competitor features
    competitors = data.get("competitors", [])
    if competitors:
        features["competitor_count"] = len(competitors)
        revenues = [safe_float(c.get("estimated_revenue", 0)) for c in competitors if isinstance(c, dict)]
        ratings = [safe_float(c.get("rating", 0)) for c in competitors if isinstance(c, dict) and safe_float(c.get("rating", 0)) > 0]
        review_counts = [safe_int(c.get("review_count", 0)) for c in competitors if isinstance(c, dict)]
        ages = [safe_int(c.get("store_age_months", 0)) for c in competitors if isinstance(c, dict) and safe_int(c.get("store_age_months", 0)) > 0]

        features["avg_competitor_rating"] = sum(ratings) / len(ratings) if ratings else 0
        features["avg_review_count"] = sum(review_counts) / len(review_counts) if review_counts else 0
        features["avg_store_age_months"] = sum(ages) / len(ages) if ages else 0
        features["new_entrants_pct"] = sum(1 for a in ages if a < 12) / max(len(ages), 1) * 100 if ages else 0

        # Market concentration (top 3 share)
        if revenues:
            total_rev = sum(revenues)
            if total_rev > 0:
                sorted_rev = sorted(revenues, reverse=True)
                top3_rev = sum(sorted_rev[:3])
                features["top3_concentration"] = round(top3_rev / total_rev * 100, 1)
            else:
                features["top3_concentration"] = 0
        else:
            features["top3_concentration"] = 0

    # Pricing features
    pricing = data.get("pricing", {})
    if pricing:
        features["avg_price"] = safe_float(pricing.get("avg_price", 0))
        features["price_trend_pct"] = safe_float(pricing.get("price_trend_pct", 0))
        features["avg_margin"] = safe_float(pricing.get("avg_margin", 0))
        features["price_range_ratio"] = safe_float(pricing.get("max_price", 0)) / max(safe_float(pricing.get("min_price", 1)), 0.01)

    # Search/demand features
    search = data.get("search_data", {})
    if search:
        features["search_volume"] = safe_int(search.get("monthly_volume", 0))
        features["cpc"] = safe_float(search.get("avg_cpc", 0))
        features["cpc_trend"] = safe_float(search.get("cpc_trend_pct", 0))

    return features


# ── Stage 3: Decision Logic — Saturation Signals ──

def _compute_signals(features: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute individual saturation signals (0-100 each)."""
    signals = []

    # Signal 1: Competitor density (competitors per 1000 monthly searches)
    comp_count = features.get("competitor_count", 0)
    search_vol = features.get("search_volume", 0)
    if search_vol > 0 and comp_count > 0:
        density = comp_count / (search_vol / 1000)
        density_score = min(100, density * 10)  # 10 competitors per 1K searches = max
        signals.append({
            "signal": "competitor_density",
            "score": round(density_score),
            "weight": 0.25,
            "raw_value": round(density, 2),
            "interpretation": _interpret_density(density),
        })
    elif comp_count > 0:
        # No search data — estimate from competitor count alone
        raw_score = min(100, comp_count * 1.5)
        signals.append({
            "signal": "competitor_count",
            "score": round(raw_score),
            "weight": 0.20,
            "raw_value": comp_count,
            "interpretation": f"{comp_count} competitors — {'crowded' if comp_count > 50 else 'moderate' if comp_count > 20 else 'uncrowded'}",
        })

    # Signal 2: Price pressure (declining prices = competition intensifying)
    price_trend = features.get("price_trend_pct", 0)
    if price_trend != 0:
        # Negative price trend = more saturation
        price_score = max(0, min(100, 50 - price_trend * 3))
        signals.append({
            "signal": "price_pressure",
            "score": round(price_score),
            "weight": 0.20,
            "raw_value": price_trend,
            "interpretation": f"Prices {'declining' if price_trend < 0 else 'rising'} {abs(price_trend):.1f}% — {'oversupply' if price_trend < -5 else 'healthy' if price_trend > 0 else 'stable'}",
        })

    # Signal 3: Margin compression
    avg_margin = features.get("avg_margin", 0)
    if avg_margin > 0:
        margin_score = max(0, 100 - avg_margin * 2)  # 50% margin = 0 saturation, 0% = 100
        signals.append({
            "signal": "margin_compression",
            "score": round(margin_score),
            "weight": 0.15,
            "raw_value": avg_margin,
            "interpretation": f"Avg margin {avg_margin:.0f}% — {'thin' if avg_margin < 20 else 'healthy' if avg_margin > 40 else 'moderate'}",
        })

    # Signal 4: Market concentration (top 3 dominating = hard to enter)
    concentration = features.get("top3_concentration", 0)
    if concentration > 0:
        conc_score = min(100, concentration * 1.2)
        signals.append({
            "signal": "market_concentration",
            "score": round(conc_score),
            "weight": 0.15,
            "raw_value": concentration,
            "interpretation": f"Top 3 hold {concentration:.0f}% market share — {'monopoly risk' if concentration > 70 else 'concentrated' if concentration > 50 else 'fragmented'}",
        })

    # Signal 5: Ad cost inflation (rising CPCs = more competition for ads)
    cpc = features.get("cpc", 0)
    cpc_trend = features.get("cpc_trend", 0)
    if cpc > 0:
        cpc_score = min(100, cpc * 25 + max(0, cpc_trend * 2))  # $4 CPC = 100
        signals.append({
            "signal": "ad_cost_inflation",
            "score": round(cpc_score),
            "weight": 0.15,
            "raw_value": cpc,
            "interpretation": f"Avg CPC ${cpc:.2f} {'(rising {0:.0f}%)'.format(cpc_trend) if cpc_trend > 0 else ''} — {'expensive' if cpc > 2 else 'moderate' if cpc > 1 else 'cheap'}",
        })

    # Signal 6: Market maturity (old stores = established market)
    avg_age = features.get("avg_store_age_months", 0)
    new_pct = features.get("new_entrants_pct", 0)
    if avg_age > 0:
        maturity_score = min(100, avg_age * 1.5)
        if new_pct < 10:
            maturity_score = min(100, maturity_score + 15)  # Few new entrants = mature/locked
        signals.append({
            "signal": "market_maturity",
            "score": round(maturity_score),
            "weight": 0.10,
            "raw_value": avg_age,
            "interpretation": f"Avg store age {avg_age:.0f} months, {new_pct:.0f}% new entrants — {'mature' if avg_age > 36 else 'established' if avg_age > 18 else 'young'}",
        })

    return signals


# ── Stage 4: Execution — Build Saturation Analysis ──

def _build_saturation_analysis(
    signals: list[dict[str, Any]],
    features: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate signals into final saturation assessment."""
    if not signals:
        return {
            "saturation_index": 0,
            "level": "unknown",
            "signals": [],
            "recommendation": "Insufficient data to assess saturation",
            "can_enter": True,
        }

    # Weighted average
    total_weight = sum(s["weight"] for s in signals)
    weighted_sum = sum(s["score"] * s["weight"] for s in signals)
    saturation_index = round(weighted_sum / max(total_weight, 0.01))

    # Classification
    if saturation_index >= 80:
        level = "oversaturated"
        can_enter = False
        recommendation = "AVOID: Market is oversaturated. Extreme competition, low margins, high ad costs."
    elif saturation_index >= 60:
        level = "highly_saturated"
        can_enter = False
        recommendation = "RISKY: Strong differentiation required. Only enter with unique product + strong brand."
    elif saturation_index >= 40:
        level = "moderately_saturated"
        can_enter = True
        recommendation = "POSSIBLE: Competition exists but room for quality entrants. Differentiation needed."
    elif saturation_index >= 20:
        level = "lightly_saturated"
        can_enter = True
        recommendation = "GOOD: Market has demand with manageable competition. Good entry opportunity."
    else:
        level = "unsaturated"
        can_enter = True
        recommendation = "EXCELLENT: Low competition. Verify demand exists (low saturation could mean low demand)."

    # Specific warnings
    warnings = _generate_warnings(signals, features)

    return {
        "saturation_index": saturation_index,
        "level": level,
        "can_enter": can_enter,
        "recommendation": recommendation,
        "signals": signals,
        "warnings": warnings,
        "entry_difficulty": _entry_difficulty(saturation_index),
        "category": features.get("category", ""),
    }


# ── Stage 5: Output Validation ──

def _validate_output(analysis: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {"valid": False, "reason": "Analysis must be dict"}
    required = ("saturation_index", "level", "can_enter", "recommendation")
    for field in required:
        if field not in analysis:
            return {"valid": False, "reason": f"Missing field: {field}"}
    if not 0 <= analysis["saturation_index"] <= 100:
        return {"valid": False, "reason": "Saturation index must be 0-100"}
    return {"valid": True, "reason": "OK"}


# ── Helpers ──

def _interpret_density(density: float) -> str:
    if density > 8:
        return f"Very crowded: {density:.1f} competitors per 1K searches"
    if density > 4:
        return f"Competitive: {density:.1f} competitors per 1K searches"
    if density > 1:
        return f"Moderate: {density:.1f} competitors per 1K searches"
    return f"Low competition: {density:.1f} competitors per 1K searches"


def _entry_difficulty(saturation: int) -> dict[str, Any]:
    """What it takes to enter at this saturation level."""
    if saturation >= 80:
        return {
            "difficulty": "extreme",
            "min_budget": "$50,000+",
            "time_to_profit": "12-18 months",
            "required": ["Unique product", "Strong brand", "Deep pockets", "Expert marketing"],
        }
    if saturation >= 60:
        return {
            "difficulty": "hard",
            "min_budget": "$15,000-50,000",
            "time_to_profit": "6-12 months",
            "required": ["Differentiated product", "Good content", "Consistent marketing"],
        }
    if saturation >= 40:
        return {
            "difficulty": "moderate",
            "min_budget": "$5,000-15,000",
            "time_to_profit": "3-6 months",
            "required": ["Quality product", "SEO + ads", "Review collection strategy"],
        }
    if saturation >= 20:
        return {
            "difficulty": "easy",
            "min_budget": "$2,000-5,000",
            "time_to_profit": "1-3 months",
            "required": ["Decent product", "Basic marketing"],
        }
    return {
        "difficulty": "very_easy",
        "min_budget": "$500-2,000",
        "time_to_profit": "2-4 weeks",
        "required": ["Product availability", "Basic listing"],
    }


def _generate_warnings(signals: list[dict[str, Any]], features: dict[str, Any]) -> list[str]:
    """Generate specific warnings from signal analysis."""
    warnings = []
    for s in signals:
        if s["score"] >= 80:
            warnings.append(f"CRITICAL: {s['signal']} at {s['score']}% — {s['interpretation']}")
        elif s["score"] >= 60:
            warnings.append(f"HIGH: {s['signal']} at {s['score']}% — {s['interpretation']}")

    concentration = features.get("top3_concentration", 0)
    if concentration > 70:
        warnings.append(f"MONOPOLY RISK: Top 3 control {concentration:.0f}% — very hard to compete")

    return warnings


def _compute_confidence(features: dict[str, Any]) -> float:
    data_points = sum(1 for k in ("competitor_count", "search_volume", "avg_margin", "cpc", "top3_concentration", "avg_store_age_months")
                      if features.get(k, 0) > 0)
    return round(min(0.95, data_points * 0.18), 2)


def _error_output(reason: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "data": None,
        "meta": {"engine": "saturation_analyzer", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "error": {"reason": reason},
    }
