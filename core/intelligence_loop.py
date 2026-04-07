"""IntelligenceLoop — the BRAIN of ShopAI.

ONE connected loop: Data → Decision → Execution → Result → Learning → Better Decision

Stages:
  1. CLEAN   — validate, fix, score data quality
  2. ANALYZE — compute scores, detect patterns, assess opportunity
  3. DECIDE  — rank multiple options, apply learning, calculate real confidence
  4. PLAN    — create specific executable actions
  5. EXECUTE — format for target systems (Shopify, email, ads)
  6. TRACK   — record what was decided and why
  7. LEARN   — compare outcomes, adjust weights, feed back to stage 3
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id, safe_float, safe_int, safe_dict

logger = get_logger("intelligence_loop")


# Persistent learned weights — saved to disk, survives restarts
try:
    from core.memory.storage_config import learned_weights_path
    _WEIGHTS_PATH = learned_weights_path()
except Exception:
    _WEIGHTS_PATH = "/tmp/shopai_learned_weights.json"
_learned_weights: dict[str, float] = {}
_weights_loaded = False


def _load_weights() -> None:
    """Load learned weights from disk on first access."""
    global _learned_weights, _weights_loaded
    if _weights_loaded:
        return
    _weights_loaded = True
    try:
        import json
        import os
        if os.path.exists(_WEIGHTS_PATH):
            with open(_WEIGHTS_PATH) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _learned_weights.update(data)
                    logger.info("Loaded %d learned weights from disk", len(data))
    except Exception as exc:
        logger.warning("Failed to load learned weights: %s", exc)


def _save_weights() -> None:
    """Save learned weights to disk (atomic write)."""
    try:
        import json
        import os
        tmp = _WEIGHTS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_learned_weights, f)
        os.replace(tmp, _WEIGHTS_PATH)
    except Exception as exc:
        logger.warning("Failed to save learned weights: %s", exc)


def get_learned_weights() -> dict[str, float]:
    """Get current learned scoring weight adjustments."""
    _load_weights()
    return dict(_learned_weights)


class IntelligenceLoop:
    """Complete closed intelligence loop with multi-factor confidence and adaptive learning."""

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    def run(self, raw_data: dict[str, Any], goal: str = "maximize_profit") -> dict[str, Any]:
        loop_id = generate_id("loop")
        start = time.monotonic()
        context = {"loop_id": loop_id, "goal": goal, "raw_data": raw_data}

        # Stage 1: CLEAN
        clean_result = self._stage_clean(raw_data)
        context["clean"] = clean_result

        if clean_result["quality_score"] < 20:
            return self._abort(loop_id, "Data quality too low", clean_result, start)

        # Stage 2: ANALYZE
        analysis = self._stage_analyze(clean_result["data"], goal)
        context["analysis"] = analysis

        # Stage 3: DECIDE — multi-option with real confidence
        decision = self._stage_decide(analysis, clean_result, goal)
        context["decision"] = decision

        # Stage 4: PLAN
        plan = self._stage_plan(decision, clean_result["data"])
        context["plan"] = plan

        # Stage 5: EXECUTE
        execution = self._stage_execute(plan, clean_result["data"])
        context["execution"] = execution

        # Stage 6: TRACK
        self._stage_track(loop_id, context)

        # Stage 7: LEARN
        learning = self._stage_learn(loop_id, decision)
        context["learning"] = learning

        elapsed = time.monotonic() - start

        result = {
            "loop_id": loop_id,
            "goal": goal,
            "elapsed_seconds": round(elapsed, 3),
            "data_quality": clean_result["quality_score"],
            "decision": {
                "action": decision["recommended_action"],
                "confidence": decision["confidence"],
                "confidence_score": decision["confidence_score"],
                "reason": decision["reason"],
                "options_evaluated": decision.get("options_evaluated", 0),
                "opportunity_score": decision.get("opportunity_score", 0),
            },
            "plan": {
                "actions": len(plan["actions"]),
                "priority_1": [a for a in plan["actions"] if a["priority"] == 1],
            },
            "execution": {
                "ready_actions": len(execution["ready"]),
                "targets": list(set(a["target"] for a in execution["ready"])),
            },
            "learning": {
                "past_outcomes": learning["past_outcomes"],
                "adjusted": learning["adjustments_made"],
                "advice": learning["advice"],
                "weight_adjustments": learning.get("weight_adjustments", {}),
            },
            "stages_completed": 7,
            "summary": self._summarize(decision, plan, execution, learning, elapsed),
        }

        self._history.append(result)
        return result

    # ── Stage 1: CLEAN ──────────────────────────────────────

    def _stage_clean(self, raw: dict[str, Any]) -> dict[str, Any]:
        data = copy.deepcopy(raw)
        fixes = []
        issues = []

        for key in list(data.keys()):
            if key.startswith("_"):
                continue
            val = data[key]

            if isinstance(val, str) and key.lower() in ("price", "cost", "revenue", "spend", "budget"):
                converted = safe_float(val, default=None)
                if converted is not None:
                    data[key] = converted
                    fixes.append(f"{key}: string→float")
                else:
                    issues.append(f"{key}: invalid number '{val}'")

            if isinstance(val, list):
                cleaned = []
                is_product_list = key in ("products", "product_data")
                for item in val:
                    if isinstance(item, dict):
                        for k in ("price", "cost", "total", "spend"):
                            if k in item and isinstance(item[k], str):
                                converted = safe_float(item[k], default=None)
                                if converted is not None:
                                    item[k] = converted
                                    fixes.append(f"{key}[].{k}: string→float")
                        # Only require name/id for product lists, not orders/customers
                        if is_product_list:
                            if item.get("name") or item.get("id") or item.get("title"):
                                cleaned.append(item)
                            else:
                                issues.append(f"{key}: item without name/id removed")
                        else:
                            cleaned.append(item)
                    elif item is not None:
                        cleaned.append(item)
                data[key] = cleaned
                # Re-bind val so the empty-removal check below sees
                # the cleaned list. Previously `val` still pointed at
                # the *original* list, so a list whose every item got
                # filtered out would leave a zombie empty list in
                # `data` instead of being removed — which then leaked
                # into stage 2 as a non-empty `data[key]` field that
                # downstream isinstance(...) and len(...) checks
                # treated as valid input.
                val = cleaned

            if val is None or val == "" or val == []:
                # `key` may already have been deleted earlier in the
                # loop body if a previous branch popped it. Use pop
                # so we don't double-delete.
                if key in data:
                    del data[key]
                fixes.append(f"{key}: removed empty")

        # Business logic validation
        biz_issues = []
        for key in ("products", "product_data"):
            items = data.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_price = safe_float(item.get("price"))
                item_cost = safe_float(item.get("cost"))
                item_name = item.get("name", item.get("title", "?"))

                if item_price < 0:
                    biz_issues.append(f"{item_name}: negative price ({item_price})")
                    issues.append(f"Negative price: {item_price}")
                if item_cost < 0:
                    biz_issues.append(f"{item_name}: negative cost ({item_cost})")
                    issues.append(f"Negative cost: {item_cost}")
                if item_cost > 0 and item_price > 0 and item_cost > item_price:
                    biz_issues.append(f"{item_name}: cost > price")
                    issues.append(f"Cost exceeds price: {item_cost} > {item_price}")

        # Quality score
        total_fields = len([k for k in data if not k.startswith("_")])
        non_empty = sum(1 for k, v in data.items() if not k.startswith("_") and v)
        has_products = bool(data.get("products") or data.get("product_data"))
        has_numbers = any(isinstance(v, (int, float)) for v in data.values())

        quality = 0
        if total_fields > 0:
            quality += min(40, non_empty / total_fields * 40)
        if has_products:
            quality += 30
        if has_numbers:
            quality += 15
        if not issues:
            quality += 15

        if biz_issues:
            penalty = min(50, len(biz_issues) * 25)
            quality = max(0, quality - penalty)

        return {
            "data": data,
            "quality_score": round(quality),
            "quality_grade": "A" if quality >= 80 else "B" if quality >= 60 else "C" if quality >= 40 else "F",
            "fixes": fixes,
            "issues": issues,
            "fields": total_fields,
        }

    # ── Stage 2: ANALYZE ────────────────────────────────────

    def _stage_analyze(self, data: dict[str, Any], goal: str) -> dict[str, Any]:
        analysis = {"goal": goal, "findings": []}

        # Product analysis
        products = data.get("products", data.get("product_data", []))
        if isinstance(products, list) and products:
            from core.step_logic.smart_executor import SmartExecutor
            scored = SmartExecutor()._score_products(products)
            viable = [p for p in scored if p.get("viable")]
            top = sorted(scored, key=lambda p: p.get("total_score", 0), reverse=True)

            analysis["products"] = {
                "total": len(products),
                "viable": len(viable),
                "top_product": top[0] if top else {},
                "avg_score": round(sum(p.get("total_score", 0) for p in scored) / max(len(scored), 1), 2),
                "scored": scored,
            }

            if viable:
                analysis["findings"].append(f"{len(viable)}/{len(products)} products viable")
            if top and top[0].get("total_score", 0) > 8:
                analysis["findings"].append(f"Strong candidate: {top[0].get('name')} (score {top[0]['total_score']})")

        # Customer analysis
        customers = data.get("customer_data", data.get("customers", []))
        if isinstance(customers, list) and customers:
            repeat = sum(1 for c in customers if isinstance(c, dict) and safe_int(c.get("orders")) > 1)
            at_risk = sum(1 for c in customers if isinstance(c, dict) and safe_int(c.get("days_since_last_order")) > 60)
            analysis["customers"] = {
                "total": len(customers),
                "repeat_rate": round(repeat / max(len(customers), 1) * 100, 1),
                "at_risk": at_risk,
            }
            if at_risk > 0:
                analysis["findings"].append(f"{at_risk} customers at churn risk")

        # Revenue analysis
        orders = data.get("orders", data.get("order_data", []))
        if isinstance(orders, list) and orders:
            revenue = sum(safe_float(o.get("total", o.get("amount", o.get("total_price", 0)))) for o in orders if isinstance(o, dict))
            aov = revenue / max(len(orders), 1)
            analysis["revenue"] = {"total": round(revenue, 2), "orders": len(orders), "aov": round(aov, 2)}
            if aov < 30:
                analysis["findings"].append(f"Low AOV ${aov:.2f} — upsell/bundle opportunity")

        # Revenue forecast — predict future trends
        revenue_series = data.get("daily_revenue", data.get("revenue_history", []))
        if not revenue_series and isinstance(orders, list) and len(orders) >= 3:
            # Build revenue series from orders
            revenue_series = [safe_float(o.get("total", o.get("amount", 0))) for o in orders if isinstance(o, dict)]

        if isinstance(revenue_series, list) and len(revenue_series) >= 3:
            try:
                from core.intelligence.forecasting import Forecasting
                fc = Forecasting()
                forecast = fc.forecast([safe_float(v) for v in revenue_series if safe_float(v) > 0], periods=7)
                if "error" not in forecast:
                    growth = safe_float(forecast.get("summary", {}).get("growth_pct"))
                    trend = forecast.get("trend", {})
                    analysis["forecast"] = {
                        "method": forecast.get("method"),
                        "growth_pct": growth,
                        "trend_direction": trend.get("direction", "stable"),
                        "forecast_avg": forecast.get("summary", {}).get("forecast_avg", 0),
                        "confidence": forecast.get("confidence_level"),
                    }
                    if growth > 10:
                        analysis["findings"].append(f"Revenue forecast: +{growth:.1f}% growth — momentum is strong")
                    elif growth < -10:
                        analysis["findings"].append(f"Revenue forecast: {growth:.1f}% decline — action needed")
                    else:
                        analysis["findings"].append(f"Revenue forecast: {growth:+.1f}% — stable")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "IntelligenceLoop: revenue forecasting failed (%s); "
                    "analysis will proceed without forecast", exc,
                )

        # ── Consume enriched context from CoreOrchestrator ──
        financial_ctx = data.get("_financial", {})
        if financial_ctx.get("net_margin", 100) < 10:
            analysis["findings"].append("WARNING: Net margin below 10% — pricing decisions critical")
            analysis["financial_pressure"] = True
        if financial_ctx.get("margin_alerts_count", 0) > 0:
            analysis["findings"].append(f"Financial: {financial_ctx['margin_alerts_count']} margin alerts active")

        competitive_ctx = data.get("_competitive", {})
        if isinstance(competitive_ctx, dict) and competitive_ctx.get("alerts"):
            alerts = competitive_ctx["alerts"]
            if isinstance(alerts, list) and alerts:
                analysis["findings"].append(f"Competitor activity: {len(alerts)} alerts detected")
                analysis["competitor_active"] = True

        expert_ctx = data.get("_expert", {})
        if isinstance(expert_ctx, dict):
            if expert_ctx.get("reorder_urgent", 0) > 0:
                analysis["findings"].append(f"URGENT: {expert_ctx['reorder_urgent']} products need immediate reorder")
            if expert_ctx.get("creative_fatigue_count", 0) > 0:
                analysis["findings"].append(f"Marketing: {expert_ctx['creative_fatigue_count']} campaigns showing creative fatigue")
            if expert_ctx.get("compliance_violations", 0) > 0:
                analysis["findings"].append(f"Legal: {expert_ctx['compliance_violations']} compliance violations detected")
            if expert_ctx.get("dead_stock_value", 0) > 100:
                analysis["findings"].append(f"Inventory: ${expert_ctx['dead_stock_value']:,.0f} tied up in dead stock")
            lifecycle_action = expert_ctx.get("lifecycle_action")
            if lifecycle_action:
                analysis["findings"].append(f"Customer: {lifecycle_action}")

        # ── Past episodes (similar decisions) ──
        episodes = data.get("_episodes", [])
        if episodes:
            failures = [ep for ep in episodes if not ep.get("success", True)]
            if failures:
                for ep in failures[:2]:
                    lesson = ep.get("lesson", "")
                    if lesson:
                        analysis["findings"].append(f"HISTORY: {lesson}")
                analysis["past_failure_risk"] = True

        analysis["opportunity_score"] = self._calc_opportunity(analysis)
        return analysis

    # ── Stage 3: DECIDE ─────────────────────────────────────

    def _stage_decide(self, analysis: dict[str, Any], clean_result: dict[str, Any], goal: str) -> dict[str, Any]:
        """Data-driven decision: options generated FROM analysis, scored FROM data."""

        past_advice = self._get_past_learning(goal)

        products = analysis.get("products", {})
        customers = analysis.get("customers", {})
        revenue = analysis.get("revenue", {})
        forecast = analysis.get("forecast", {})
        opp_score = analysis.get("opportunity_score", 50)
        # `top` is used below in the past-advice gate. Previously this
        # variable was undefined in _stage_decide and only existed in
        # the helper _generate_options, so any cycle where the
        # outcome tracker had set `avoid_below_score` would crash with
        # NameError. Hoist the same extraction up here.
        top = safe_dict(products.get("top_product"))

        # Generate options FROM DATA — not hardcoded menu
        options = self._generate_options(products, customers, revenue, forecast, past_advice)

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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IntelligenceLoop: strategy_optimizer.get_adjusted_weights "
                "failed (%s); using unadjusted weights", exc,
            )
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
            ab_variant = self._ab_test_decision(options, goal)

        if ab_variant is not None:
            best = ab_variant["selected"]

        # Apply past learning adjustment
        if past_advice.get("avoid_below_score"):
            threshold = past_advice["avoid_below_score"]
            if safe_float(top.get("total_score"), 10) < threshold:
                best["action"] = f"CAUTION: Past data shows scores below {threshold} fail. " + best["action"]

        # Calculate REAL confidence score (0-100)
        confidence_score = self._calculate_confidence(
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

    @staticmethod
    def _generate_options(products: dict, customers: dict, revenue: dict,
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

    def _calculate_confidence(self, clean_result: dict, analysis: dict,
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

    # ── Stage 4: PLAN ───────────────────────────────────────

    def _stage_plan(self, decision: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        actions = []
        confidence = decision.get("confidence", "medium")
        decision_type = decision.get("decision_type", "")

        products = data.get("products", data.get("product_data", []))
        customers = data.get("customer_data", data.get("customers", []))

        if isinstance(products, list) and products:
            actions.append({"type": "pricing_analysis", "priority": 1, "description": "Run pricing intelligence", "target": "pricing_engine", "data_needed": "products"})
            actions.append({"type": "seo_audit", "priority": 2, "description": "Audit product pages for SEO", "target": "seo_engine", "data_needed": "products"})
            actions.append({"type": "content_check", "priority": 2, "description": "Improve product descriptions", "target": "content_engine", "data_needed": "products"})

        if isinstance(customers, list) and customers:
            actions.append({"type": "segment_customers", "priority": 1, "description": "Segment by RFM and detect churn", "target": "customer_engine", "data_needed": "customers"})

        # Decision-type-specific actions
        if decision_type == "product_launch":
            actions.append({"type": "product_launch", "priority": 1, "description": "Execute product launch workflow", "target": "workflow_engine", "data_needed": "products"})
        elif decision_type == "customer_retention":
            actions.append({"type": "win_back_email", "priority": 1, "description": "Create win-back email campaign", "target": "email_engine", "data_needed": "customers"})
        elif decision_type == "aov_increase":
            actions.append({"type": "bundle_strategy", "priority": 1, "description": "Create bundle/upsell offers", "target": "pricing_engine", "data_needed": "products"})

        # Deprioritize if low confidence
        if confidence == "low":
            for a in actions:
                a["priority"] = max(a["priority"], 2)
            actions.append({"type": "gather_more_data", "priority": 1, "description": "Low confidence — collect more data", "target": "data_engine", "data_needed": "all"})

        actions.sort(key=lambda a: a["priority"])
        return {"actions": actions, "total": len(actions)}

    # ── Stage 5: EXECUTE ────────────────────────────────────

    def _stage_execute(self, plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        ready = []
        products = data.get("products", data.get("product_data", []))
        products_valid = isinstance(products, list) and products and isinstance(products[0], dict)

        for action in plan["actions"]:
            target = action["target"]
            formatted = {
                "action_type": action["type"],
                "priority": action["priority"],
                "target": target,
                "description": action["description"],
                "status": "ready",
            }

            try:
                if target == "pricing_engine" and products_valid:
                    formatted["payload"] = {"engine": "pricing", "data": {"products": products[:10]}}

                elif target == "email_engine":
                    from core.intelligence.email_intelligence import EmailIntelligence
                    flow = EmailIntelligence().build_automation_flow("win_back")
                    formatted["payload"] = {"flow": flow["name"], "emails": len(flow["emails"])}

                elif target == "seo_engine" and products_valid:
                    from core.intelligence.seo_intelligence import SEOIntelligence
                    audit = SEOIntelligence().audit_page({"title": products[0].get("name", ""), "keyword": products[0].get("category", "product")})
                    formatted["payload"] = {"audit_score": audit["score"], "issues": audit["issue_count"]}

                elif target == "content_engine" and products_valid:
                    from core.intelligence.content_generator import ContentGenerator
                    desc = ContentGenerator().product_description(products[0])
                    formatted["payload"] = {"headline": desc["headline"][:60], "bullets": len(desc["bullet_points"])}

            except Exception as exc:
                formatted["payload_error"] = str(exc)

            ready.append(formatted)

        return {"ready": ready, "total": len(ready)}

    # ── Stage 6: TRACK ──────────────────────────────────────

    def _stage_track(self, loop_id: str, context: dict[str, Any]) -> None:
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            decision = context.get("decision", {})
            analysis = context.get("analysis", {})
            ot.record_decision(loop_id, "intelligence_loop", {
                "goal": context.get("goal"),
                "action": decision.get("recommended_action", ""),
                "confidence": decision.get("confidence", ""),
                "confidence_score": decision.get("confidence_score", 0),
                "opportunity_score": decision.get("opportunity_score", 0),
                "data_quality": context.get("clean", {}).get("quality_score", 0),
                "viable_products": analysis.get("products", {}).get("viable", 0),
                "avg_score": analysis.get("products", {}).get("avg_score", 0),
                "decision_type": decision.get("decision_type", ""),
                "options_evaluated": decision.get("options_evaluated", 0),
            })
        except Exception as exc:  # noqa: BLE001
            # Tracking is what closes the learn-feedback loop. A
            # silent swallow here means the learning flywheel
            # silently stops turning — log so the operator notices
            # the system has stopped accumulating evidence.
            logger.warning(
                "IntelligenceLoop: outcome tracking failed for loop %s "
                "(%s); learn flywheel may stall", loop_id, exc,
            )

    # ── Stage 7: LEARN — Bayesian incremental updates ──────

    # Learning hyperparameters
    LEARNING_RATE = 0.05   # How fast to adjust (small = stable, large = reactive)
    DECAY = 0.95           # How fast old learning fades (0.95 = 5% decay per cycle)
    MAX_ADJUSTMENT = 0.30  # Maximum deviation from base weight

    # All learnable scoring factors
    LEARNABLE_FACTORS = ("margin", "demand", "competition", "shipping", "rating", "review", "price", "velocity")

    def _stage_learn(self, loop_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            patterns = ot.get_winning_patterns("intelligence_loop")

            adjustments = []
            success_rate = patterns.get("success_rate", 0.5)

            if success_rate < 0.4:
                adjustments.append("Low success rate — strategy adjustment needed")
            if success_rate > 0.7:
                adjustments.append("High success rate — continue current approach")

            # Bayesian incremental weight updates for ALL factors
            entries = ot._load("intelligence_loop")
            outcomes = [e for e in entries if e.get("outcome") is not None]
            successes = [e for e in outcomes if e.get("success")]
            failures = [e for e in outcomes if not e.get("success")]

            if successes and failures:
                # Compare factor averages between successes and failures
                for factor in self.LEARNABLE_FACTORS:
                    score_key = f"{factor}_score" if factor != "price" else "price_point_score"
                    success_avg = self._avg_decision_field(successes, score_key)
                    failure_avg = self._avg_decision_field(failures, score_key)

                    if success_avg is not None and failure_avg is not None:
                        if success_avg > failure_avg + 0.5:
                            self._update_weight(factor, +1)
                            adjustments.append(f"{factor}: success avg {success_avg:.1f} > fail avg {failure_avg:.1f} → boost")
                        elif failure_avg > success_avg + 0.5:
                            self._update_weight(factor, -1)
                            adjustments.append(f"{factor}: fail avg {failure_avg:.1f} > success avg {success_avg:.1f} → reduce")
                        else:
                            # Decay toward zero when no clear signal
                            self._decay_weight(factor)
            elif outcomes:
                # Only successes or only failures — decay all toward zero
                for factor in self.LEARNABLE_FACTORS:
                    self._decay_weight(factor)

            # Pattern-based meta-learning
            for p in patterns.get("patterns", []):
                if p.get("pattern") == "high_confidence_wins":
                    _learned_weights["confidence_boost"] = min(
                        _learned_weights.get("confidence_boost", 0) + 0.02, 0.2
                    )
                    adjustments.append("High confidence → success: boosting confidence factor")

                if p.get("pattern") == "quality_matters":
                    _learned_weights["quality_gate"] = min(
                        _learned_weights.get("quality_gate", 40) + 2, 70
                    )
                    adjustments.append("Data quality matters: raising quality threshold")

            # Persist all weight changes
            if adjustments or outcomes:
                _save_weights()

            advice_result = ot.should_proceed("intelligence_loop", decision)

            return {
                "past_outcomes": patterns.get("with_outcomes", 0),
                "success_rate": patterns.get("success_rate", 0),
                "adjustments_made": len(adjustments) > 0,
                "adjustments": adjustments,
                "advice": advice_result.get("reasons", ["No past data — first run"]),
                "patterns": patterns.get("patterns", []),
                "weight_adjustments": dict(_learned_weights),
            }
        except Exception:
            return {"past_outcomes": 0, "adjustments_made": False, "advice": ["Learning system initializing"]}

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _ab_test_decision(options: list[dict], goal: str) -> dict[str, Any] | None:
        """Occasionally A/B test the second-best option against the best.

        Returns None (use best) or a dict with the selected variant.
        Uses ABFramework if available, falls back to simple random.
        """
        if len(options) < 2:
            return None
        try:
            from core.intelligence.ab_framework import ABFramework
            ab = ABFramework()

            exp_name = f"decision_{goal}"

            # Check if experiment exists, create if not
            existing = [e for e in ab._experiments.values() if e.get("name") == exp_name and e.get("status") == "running"]
            if existing:
                exp = existing[0]
            else:
                exp = ab.create_experiment(
                    name=exp_name,
                    test_type="decision_strategy",
                    variants=[
                        {"name": "best_score", "strategy": "highest_score"},
                        {"name": "second_best", "strategy": "explore_alternative"},
                    ],
                    traffic_pct=100,
                    min_samples=20,
                )

            # Assign variant based on timestamp (deterministic per cycle)
            import time
            assignment = ab.assign_variant(exp["id"], str(int(time.time())))

            if assignment.get("assigned") and assignment.get("variant_index") == 1:
                # A/B test: use second-best option
                ab.record_impression(exp["id"], 1)
                return {
                    "selected": options[1],
                    "variant_name": "explore_alternative",
                    "experiment_id": exp["id"],
                }
            else:
                ab.record_impression(exp["id"], 0)
                return None  # Use best (default)

        except Exception:
            return None

    @classmethod
    def _update_weight(cls, factor: str, direction: int) -> None:
        """Bayesian incremental weight update: small steps, bounded."""
        current = _learned_weights.get(factor, 0.0)
        current *= cls.DECAY  # Decay old learning
        current += cls.LEARNING_RATE * direction  # Add new signal
        _learned_weights[factor] = max(-cls.MAX_ADJUSTMENT, min(cls.MAX_ADJUSTMENT, round(current, 4)))

    @classmethod
    def _decay_weight(cls, factor: str) -> None:
        """Decay weight toward zero when no clear signal."""
        current = _learned_weights.get(factor, 0.0)
        if abs(current) > 0.001:
            _learned_weights[factor] = round(current * cls.DECAY, 4)

    @staticmethod
    def _avg_decision_field(entries: list[dict], field: str) -> float | None:
        """Average a numeric field from decision data in outcome entries."""
        values = []
        for e in entries:
            d = e.get("decision", {})
            if isinstance(d, dict):
                v = d.get(field)
                if isinstance(v, (int, float)):
                    values.append(float(v))
        return sum(values) / len(values) if values else None

    def _get_past_learning(self, goal: str) -> dict[str, Any]:
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            patterns = OutcomeTracker().get_winning_patterns("intelligence_loop")
            result = {"success_rate": patterns.get("success_rate", 0)}
            for p in patterns.get("patterns", []):
                if p.get("pattern") == "avoid_low_scores":
                    result["avoid_below_score"] = safe_float(p.get("threshold"))
                if p.get("pattern") == "quality_matters":
                    result["min_quality"] = 50
            return result
        except Exception:
            return {}

    @staticmethod
    def _calc_opportunity(analysis: dict) -> int:
        score = 50
        products = analysis.get("products", {})
        if products.get("viable", 0) > 0:
            score += 20
        if safe_float(products.get("avg_score")) > 7:
            score += 10
        customers = analysis.get("customers", {})
        if safe_float(customers.get("repeat_rate")) > 30:
            score += 10
        if safe_int(customers.get("at_risk")) > 0:
            score -= 5
        revenue = analysis.get("revenue", {})
        if safe_float(revenue.get("aov")) > 50:
            score += 10
        return max(0, min(100, score))

    @staticmethod
    def _summarize(decision, plan, execution, learning, elapsed) -> str:
        lines = [
            f"Decision: {decision['recommended_action'][:80]}",
            f"Confidence: {decision['confidence']} ({decision['confidence_score']}/100)",
            f"Options: {decision.get('options_evaluated', 1)} evaluated",
            f"Actions: {plan['total']} planned, {len(execution['ready'])} ready",
        ]
        if learning.get("past_outcomes", 0) > 0:
            lines.append(f"Learning: {learning['past_outcomes']} past outcomes, success {learning.get('success_rate', 0):.0%}")
        lines.append(f"Time: {elapsed:.3f}s")
        return "\n".join(lines)

    def _abort(self, loop_id, reason, clean_result, start_time):
        elapsed = time.monotonic() - start_time
        return {
            "loop_id": loop_id, "status": "aborted", "reason": reason,
            "data_quality": clean_result["quality_score"],
            "data_issues": clean_result["issues"],
            "elapsed_seconds": round(elapsed, 3),
            "stages_completed": 1,
            "summary": f"ABORTED: {reason}. Fix data quality first.",
        }

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._history[-limit:])
