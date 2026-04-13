"""Stage 3: DECIDE — rank multiple options, apply learning, calculate real confidence."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_dict
from core.intelligence.loop.helpers import _get_past_learning, _ab_test_decision


def generate_options(products: dict, customers: dict, revenue: dict,
                     forecast: dict, past_advice: dict) -> list[dict[str, Any]]:
    """Generate decision options FROM DATA — every score comes from analysis."""
    options = []
    top = safe_dict(products.get("top_product"))
    total_products = products.get("total", 0)
    viable_count = products.get("viable", 0)
    avg_score = safe_float(products.get("avg_score"))
    total_customers = customers.get("total", 0)
    at_risk = customers.get("at_risk", 0)
    repeat_rate = safe_float(customers.get("repeat_rate"))
    aov = safe_float(revenue.get("aov"))
    growth_pct = safe_float(forecast.get("growth_pct"))
    past_success = safe_float(past_advice.get("success_rate"))

    # Option: Launch top product (only if viable products exist)
    if viable_count > 0 and top:
        top_score = safe_float(top.get("total_score"))
        conf_num = safe_float(top.get("confidence_numeric", 5))
        options.append({
            "action": f"Launch {top.get('name', 'top product')} — score {top_score:.1f}",
            "type": "product_launch",
            "scores": {
                "profit_potential": min(top_score, 10),            # FROM product score
                "risk": max(10 - conf_num, 1),                     # FROM confidence
                "data_support": min(total_products * 1.5, 10),     # FROM volume
                "speed": 7,
            },
        })

    # Option: Pricing optimization (if margin room exists)
    if total_products > 0:
        margin = safe_float(top.get("margin_pct"))
        options.append({
            "action": f"Optimize pricing ({margin:.0f}% avg margin, {total_products} products)",
            "type": "pricing_optimization",
            "scores": {
                "profit_potential": min(margin / 10, 10),          # FROM actual margin
                "risk": 2,
                "data_support": min(total_products * 2, 10),       # FROM product count
                "speed": 9,
            },
        })

    # Option: Customer retention (if churn risk detected)
    if at_risk > 0:
        risk_ratio = at_risk / max(total_customers, 1)
        options.append({
            "action": f"Retain {at_risk} at-risk customers ({risk_ratio:.0%} of base)",
            "type": "customer_retention",
            "scores": {
                "profit_potential": min(risk_ratio * 20, 10),       # FROM risk severity
                "risk": 2,
                "data_support": min(total_customers, 10),           # FROM customer volume
                "speed": 8,
            },
        })

    # Option: AOV increase (if AOV is below potential)
    if aov > 0 and aov < 80:
        options.append({
            "action": f"Increase AOV ${aov:.0f} → target ${aov * 1.3:.0f} with bundles/upsells",
            "type": "aov_increase",
            "scores": {
                "profit_potential": min((80 - aov) / 8, 10),        # FROM aov gap
                "risk": 3,
                "data_support": min(revenue.get("orders", 0) * 2, 10),
                "speed": 6,
            },
        })

    # NEW: Emergency pricing (if revenue declining)
    if growth_pct < -10:
        options.append({
            "action": f"Emergency: revenue declining {growth_pct:.1f}% — run promotions + ad boost",
            "type": "emergency_pricing",
            "scores": {
                "profit_potential": min(abs(growth_pct) / 5, 10),   # FROM decline severity
                "risk": 6,
                "data_support": 7,
                "speed": 10,
            },
        })

    # NEW: Product improvement (if avg score is low)
    if total_products > 0 and avg_score < 5:
        options.append({
            "action": f"Improve product catalog (avg score {avg_score:.1f}/10 — below threshold)",
            "type": "product_improvement",
            "scores": {
                "profit_potential": min((5 - avg_score) * 2.5, 10),  # FROM score gap
                "risk": 3,
                "data_support": min(total_products * 2, 10),
                "speed": 5,
            },
        })

    # NEW: Loyalty program (if repeat rate is low)
    if total_customers > 3 and repeat_rate < 25:
        options.append({
            "action": f"Launch loyalty program (repeat rate {repeat_rate:.0f}% — below 25% target)",
            "type": "loyalty_program",
            "scores": {
                "profit_potential": min((25 - repeat_rate) / 3, 10),  # FROM retention gap
                "risk": 3,
                "data_support": min(total_customers, 10),
                "speed": 6,
            },
        })

    # NEW: Inventory restock (if products are selling fast)
    if viable_count > 0 and top:
        velocity = safe_float(top.get("velocity"))
        inv = safe_float(top.get("inventory_quantity", top.get("quantity", 100)))
        if velocity > 0 and inv > 0:
            days_until_oos = inv / max(velocity, 0.01)
            if days_until_oos < 14:
                options.append({
                    "action": f"Restock {top.get('name')} — {days_until_oos:.0f} days until out-of-stock",
                    "type": "inventory_restock",
                    "scores": {
                        "profit_potential": min(velocity * 3, 10),
                        "risk": 1,
                        "data_support": 8,
                        "speed": 7,
                    },
                })

    # Boost options that historically succeed
    if past_success > 0:
        for opt in options:
            opt["scores"]["past_success_boost"] = round(past_success * 3, 1)

    return options


def calculate_confidence(clean_result: dict, analysis: dict,
                         best_option: dict, past_advice: dict,
                         all_options: list) -> int:
    """Calculate real confidence score 0-100 based on multiple factors."""
    score = 0

    # Factor 1: Data quality (0-25 pts)
    data_quality = clean_result.get("quality_score", 0)
    score += min(data_quality * 0.25, 25)

    # Factor 2: Best option strength (0-25 pts)
    best_score = best_option.get("total_score", 0)
    score += min(best_score * 2.5, 25)

    # Factor 3: Score gap between best and second-best (0-15 pts)
    # Larger gap = higher confidence in choice
    if len(all_options) >= 2:
        gap = all_options[0].get("total_score", 0) - all_options[1].get("total_score", 0)
        score += min(gap * 5, 15)
    else:
        score += 5  # Only one option = moderate confidence

    # Factor 4: Historical success rate (0-20 pts)
    success_rate = past_advice.get("success_rate", 0)
    score += success_rate * 20

    # Factor 5: Evidence volume (0-10 pts)
    findings_count = len(analysis.get("findings", []))
    products_count = analysis.get("products", {}).get("total", 0)
    evidence = min(findings_count * 2 + products_count * 2, 10)
    score += evidence

    # Factor 6: Forecast alignment (0-5 pts)
    forecast = analysis.get("forecast", {})
    growth = safe_float(forecast.get("growth_pct"))
    if growth > 10:
        score += 5  # Strong positive forecast
    elif growth > 0:
        score += 3  # Mild positive
    elif growth < -10:
        score -= 5  # Negative forecast reduces confidence

    return max(0, min(100, round(score)))


def stage_decide(analysis: dict[str, Any], clean_result: dict[str, Any], goal: str) -> dict[str, Any]:
    """Data-driven decision: options generated FROM analysis, scored FROM data."""

    past_advice = _get_past_learning(goal)

    products = analysis.get("products", {})
    customers = analysis.get("customers", {})
    revenue = analysis.get("revenue", {})
    forecast = analysis.get("forecast", {})
    opp_score = analysis.get("opportunity_score", 50)

    # Generate options FROM DATA — not hardcoded menu
    options = generate_options(products, customers, revenue, forecast, past_advice)

    if not options:
        options.append({
            "action": f"Collect more data for: {goal}",
            "type": "data_collection",
            "scores": {"profit_potential": 2, "risk": 1, "data_support": 2, "speed": 5},
        })

    # Score options with goal-weighted factors
    goal_weights = {
        "maximize_profit": {"profit_potential": 0.40, "risk": 0.20, "data_support": 0.25, "speed": 0.15},
        "grow_customers": {"profit_potential": 0.20, "risk": 0.15, "data_support": 0.30, "speed": 0.35},
        "increase_aov": {"profit_potential": 0.35, "risk": 0.15, "data_support": 0.25, "speed": 0.25},
    }
    weights = goal_weights.get(goal, {"profit_potential": 0.30, "risk": 0.20, "data_support": 0.25, "speed": 0.25})

    # Get strategy adjustments from past outcomes
    try:
        from core.intelligence.strategy_optimizer import StrategyOptimizer
        strategy_weights = StrategyOptimizer().get_adjusted_weights(goal)
    except Exception:
        strategy_weights = {}

    for opt in options:
        s = opt["scores"]
        risk_score = 10 - s.get("risk", 5)
        base_score = (
            s.get("profit_potential", 5) * weights["profit_potential"]
            + risk_score * weights["risk"]
            + s.get("data_support", 5) * weights["data_support"]
            + s.get("speed", 5) * weights["speed"]
        )
        # Apply strategy weight multiplier (learned from outcomes)
        opt_type = opt.get("type", "")
        strategy_mult = strategy_weights.get(opt_type, 1.0)
        opt["total_score"] = round(base_score * strategy_mult, 2)
        opt["strategy_multiplier"] = strategy_mult

    # Rank options
    options.sort(key=lambda o: o["total_score"], reverse=True)
    best = options[0]

    # A/B testing: occasionally test alternative strategy
    ab_variant = None
    if len(options) >= 2:
        ab_variant = _ab_test_decision(options, goal)

    if ab_variant is not None:
        best = ab_variant["selected"]

    # Apply past learning adjustment
    if past_advice.get("avoid_below_score"):
        threshold = past_advice["avoid_below_score"]
        if safe_float(top.get("total_score"), 10) < threshold:
            best["action"] = f"CAUTION: Past data shows scores below {threshold} fail. " + best["action"]

    # Calculate REAL confidence score (0-100)
    confidence_score = calculate_confidence(
        clean_result, analysis, best, past_advice, options
    )

    confidence = "high" if confidence_score >= 70 else "medium" if confidence_score >= 40 else "low"

    reason_parts = analysis.get("findings", [])[:3]
    if past_advice.get("success_rate"):
        reason_parts.append(f"Past success rate: {past_advice['success_rate']:.0%}")
    if len(options) > 1:
        reason_parts.append(f"Best of {len(options)} options (score: {best['total_score']})")
    if ab_variant:
        reason_parts.append(f"A/B test: variant {ab_variant['variant_name']}")

    return {
        "recommended_action": best["action"],
        "confidence": confidence,
        "confidence_score": confidence_score,
        "reason": " | ".join(reason_parts) if reason_parts else "Standard analysis",
        "opportunity_score": opp_score,
        "goal": goal,
        "decision_type": best.get("type", "unknown"),
        "options_evaluated": len(options),
        "all_options": [{"action": o["action"][:60], "score": o["total_score"]} for o in options],
        "past_learning_applied": bool(past_advice.get("success_rate")),
    }
