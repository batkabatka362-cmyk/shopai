"""Main score aggregation engine.

Combines scores from all upstream engines (market research, trend discovery,
profitability, competition, demand, risk, product filter) into a unified
product score using weighted normalization.
Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import (
    DEFAULT_WEIGHTS,
    NORMALIZATION_RANGES,
    MINIMUM_CONFIDENCE,
)
from .logic import (
    customize_weights,
    detect_score_conflicts,
    compute_weighted_score,
)
from .rules import validate_aggregation_inputs


def aggregate_scores(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Aggregate scores from all previous engines into a unified product score.

    Args:
        input_payload: dict with keys:
            - products (list[dict]): each product dict contains engine scores:
                - product_id (str): unique identifier
                - product_name (str): display name (optional)
                - market_research (dict): {market_verdict (str), market_size_score (float)}
                - trend_discovery (dict): {trend_score (float)}
                - profitability (dict): {margin (float), roi (float), margin_score (float)}
                - competition (dict): {competitive_landscape (str), competition_score (float)}
                - demand (dict): {volume_projection (float), demand_score (float)}
                - risk (dict): {composite_risk (float), risk_level (str)}
                - filter (dict): {passed (bool), fail_reasons (list)}
            - goal (str): profit|growth|balanced (default "balanced")

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        products = input_payload.get("products")
        if not products or not isinstance(products, list):
            return _error("products list is required and must be non-empty")

        goal = input_payload.get("goal", "balanced")
        weights = customize_weights(goal)

        results: list[dict[str, Any]] = []
        total_conflicts = 0
        products_with_low_confidence = 0

        for product in products:
            product_id = product.get("product_id", "unknown")
            product_name = product.get("product_name", product_id)

            # --- Extract and normalize scores from each engine ---
            raw_scores = _extract_raw_scores(product)
            available_engines = [k for k, v in raw_scores.items() if v is not None]
            missing_engines = [k for k, v in raw_scores.items() if v is None]

            # --- Validate minimum engine coverage ---
            validation = validate_aggregation_inputs(raw_scores, product)
            penalties = validation.get("penalties", [])

            # --- Normalize scores to 0-100 ---
            normalized = _normalize_scores(raw_scores)

            # --- Redistribute weights if engines are missing ---
            effective_weights = _redistribute_weights(weights, available_engines)

            # --- Apply risk as a multiplier ---
            risk_multiplier = _calculate_risk_multiplier(raw_scores.get("risk"))

            # --- Compute the weighted score ---
            base_score = compute_weighted_score(normalized, effective_weights)

            # --- Apply risk multiplier ---
            unified_score = round(base_score * risk_multiplier, 1)
            unified_score = max(0.0, min(100.0, unified_score))

            # --- Apply penalties from filter failures ---
            penalty_total = sum(p.get("amount", 0) for p in penalties)
            unified_score = max(0.0, round(unified_score - penalty_total, 1))

            # --- Detect conflicts between engine scores ---
            conflicts = detect_score_conflicts(normalized)
            total_conflicts += len(conflicts)

            # --- Confidence assessment ---
            confidence = _assess_confidence(available_engines, missing_engines)
            if confidence["level"] == "low":
                products_with_low_confidence += 1

            results.append({
                "product_id": product_id,
                "product_name": product_name,
                "unified_score": unified_score,
                "base_score": round(base_score, 1),
                "risk_multiplier": risk_multiplier,
                "normalized_scores": normalized,
                "effective_weights": effective_weights,
                "available_engines": available_engines,
                "missing_engines": missing_engines,
                "conflicts": conflicts,
                "penalties": penalties,
                "confidence": confidence,
            })

        # Sort by unified score descending for convenience
        results.sort(key=lambda r: r["unified_score"], reverse=True)

        return {
            "status": "success",
            "data": {
                "products": results,
                "aggregation_summary": {
                    "total_products": len(results),
                    "goal": goal,
                    "weights_used": weights,
                    "total_conflicts_detected": total_conflicts,
                    "products_with_low_confidence": products_with_low_confidence,
                    "score_range": {
                        "min": min(r["unified_score"] for r in results) if results else 0,
                        "max": max(r["unified_score"] for r in results) if results else 0,
                        "spread": round(
                            (max(r["unified_score"] for r in results)
                             - min(r["unified_score"] for r in results)), 1
                        ) if len(results) > 1 else 0,
                    },
                },
            },
            "meta": {
                "goal": goal,
                "engines_expected": list(DEFAULT_WEIGHTS.keys()),
                "products_evaluated": len(results),
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Score aggregation failed: {exc}")


def _extract_raw_scores(product: dict[str, Any]) -> dict[str, float | None]:
    """Pull raw scores from each engine's output in the product dict."""
    market = product.get("market_research")
    trend = product.get("trend_discovery")
    profit = product.get("profitability")
    comp = product.get("competition")
    demand = product.get("demand")
    risk = product.get("risk")
    filt = product.get("filter")

    return {
        "profitability": _safe_score(profit, "margin_score"),
        "demand": _safe_score(demand, "demand_score"),
        "competition": _safe_score(comp, "competition_score"),
        "risk": _safe_score(risk, "composite_risk"),
        "trend": _safe_score(trend, "trend_score"),
        "market_size": _safe_market_score(market),
        "filter": _filter_to_score(filt),
    }


def _safe_score(engine_data: dict | None, key: str) -> float | None:
    """Safely extract a numeric score from engine output."""
    if engine_data is None:
        return None
    val = engine_data.get(key)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return None


def _safe_market_score(market: dict | None) -> float | None:
    """Convert market research verdict into a numeric score."""
    if market is None:
        return None
    score = market.get("market_size_score")
    if score is not None:
        try:
            return float(score)
        except (TypeError, ValueError):
            pass
    verdict_map = {
        "excellent": 90.0,
        "good": 70.0,
        "moderate": 50.0,
        "limited": 30.0,
        "poor": 15.0,
    }
    verdict = market.get("market_verdict", "").lower()
    return verdict_map.get(verdict)


def _filter_to_score(filt: dict | None) -> float | None:
    """Convert filter pass/fail into a score (100 = passed, 0 = failed)."""
    if filt is None:
        return None
    passed = filt.get("passed")
    if passed is None:
        return None
    return 100.0 if passed else 0.0


def _normalize_scores(
    raw: dict[str, float | None],
) -> dict[str, float | None]:
    """Normalize all raw scores to 0-100 scale using known ranges."""
    normalized: dict[str, float | None] = {}
    for engine, value in raw.items():
        if value is None:
            normalized[engine] = None
            continue
        lo, hi = NORMALIZATION_RANGES.get(engine, (0, 100))
        if hi == lo:
            normalized[engine] = 50.0
        else:
            clamped = max(lo, min(hi, value))
            normalized[engine] = round(((clamped - lo) / (hi - lo)) * 100, 1)
    return normalized


def _redistribute_weights(
    weights: dict[str, float], available: list[str],
) -> dict[str, float]:
    """Redistribute weight from missing engines to available ones."""
    if not available:
        return weights
    total_available = sum(weights.get(e, 0) for e in available)
    if total_available <= 0:
        equal = round(1.0 / len(available), 4)
        return {e: equal for e in available}
    effective: dict[str, float] = {}
    for engine in available:
        effective[engine] = round(weights.get(engine, 0) / total_available, 4)
    return effective


def _calculate_risk_multiplier(risk_score: float | None) -> float:
    """Convert risk score into a multiplier (high risk = lower multiplier).

    Risk score 0 = no risk = multiplier 1.0
    Risk score 100 = max risk = multiplier 0.5
    """
    if risk_score is None:
        return 0.85  # Unknown risk = conservative penalty
    # Invert: lower risk score means higher multiplier
    clamped = max(0.0, min(100.0, risk_score))
    return round(1.0 - (clamped / 200.0), 3)


def _assess_confidence(
    available: list[str], missing: list[str],
) -> dict[str, Any]:
    """Assess confidence in the unified score based on data completeness."""
    total = len(available) + len(missing)
    coverage = len(available) / total if total > 0 else 0
    min_required = MINIMUM_CONFIDENCE["min_engines"]

    if len(available) < min_required:
        level = "low"
    elif coverage >= MINIMUM_CONFIDENCE["high_confidence_coverage"]:
        level = "high"
    elif coverage >= MINIMUM_CONFIDENCE["moderate_confidence_coverage"]:
        level = "moderate"
    else:
        level = "low"

    return {
        "level": level,
        "engines_available": len(available),
        "engines_missing": len(missing),
        "coverage": round(coverage, 2),
        "note": (
            "Sufficient data for reliable decision"
            if level in ("high", "moderate")
            else "Missing engine data increases uncertainty — gather more data"
        ),
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
