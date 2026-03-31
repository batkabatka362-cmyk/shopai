"""SmartExecutor — intelligent step execution with real computation.

When model inference is not available, SmartExecutor uses pre-computed data
and business rules to produce REAL results instead of empty placeholders.

When model IS available, SmartExecutor enriches model output with computed data
so the final result is always better than model alone or computation alone.

This is the key to "зөв data цуглуулбал → зөв хуваарилбал → зөв ашиглавал".
"""
from __future__ import annotations

import copy
import math
from typing import Any

from utils.logger import get_logger
from .computation import Computation
from .domain import DomainRouter

logger = get_logger("step_logic.smart_executor")

_domain_router = DomainRouter()


class SmartExecutor:
    """Executes engine steps with real intelligence.

    Two-layer execution:
      1. DomainRouter: if engine has domain-specific logic (pricing, marketing, etc.),
         use that for deep, specialized computation
      2. Generic: fallback to universal scoring/ranking/validation

    Never modifies engine code. Adds intelligence at the framework level.
    """

    def __init__(self) -> None:
        self._comp = Computation()

    def execute_analyze(self, data: dict[str, Any], model_result: dict[str, Any], engine_name: str = "") -> dict[str, Any]:
        """Smart analysis: combine model output with real computed scores.

        Priority: SmartExecutor core logic → Domain logic → Generic fallback
        Domain results MERGE into (not replace) SmartExecutor results.
        """
        result = copy.deepcopy(model_result)

        # Generic analysis for ALL engines: compute stats on any input data
        result.update(self._generic_analyze(data, engine_name))

        # Use pre-computed scores if available
        pre_scored = data.get("_pre_scored_products", [])
        pre_computed = data.get("_pre_computed", {})

        if pre_scored:
            # Real scoring from PreProcessor
            viable = [p for p in pre_scored if p.get("viable", False)]
            result["score"] = pre_computed.get("avg_score", 0)
            result["decision"] = "approve" if viable else "reject"
            result["reason"] = (
                f"{len(viable)}/{len(pre_scored)} products viable. "
                f"Avg score: {pre_computed.get('avg_score', 0)}, "
                f"Top margin: {pre_computed.get('top_margin', 0)}%"
            )
            result["scored_products"] = pre_scored
            result["viable_count"] = len(viable)
            result["total_count"] = len(pre_scored)
        else:
            # Compute from raw data
            products = data.get("products", data.get("product_data", []))
            if isinstance(products, list) and products:
                scores = self._score_products(products)
                result["scored_products"] = scores
                result["score"] = self._comp.mean([s["total_score"] for s in scores])
                result["decision"] = "approve" if result["score"] >= 5.0 else "reject"
                result["reason"] = f"Computed score: {result['score']}"

        # Add enrichment stats
        stats = data.get("_product_stats", {})
        if stats:
            result["market_context"] = {
                "avg_price": stats.get("price_avg"),
                "margin_avg": stats.get("margin_avg"),
                "category_mix": stats.get("category_distribution"),
            }

        # Data quality assessment
        quality = data.get("_data_quality", {})
        if quality:
            result["data_quality"] = quality.get("quality_tier", "unknown")

        # Merge domain-specific analysis (additive, not replacing)
        domain_result = _domain_router.analyze(engine_name, data)
        if domain_result:
            for k, v in domain_result.items():
                if k not in result:  # Only add, never overwrite SmartExecutor results
                    result[k] = v

        return result

    def execute_work(self, data: dict[str, Any], model_result: dict[str, Any], engine_name: str = "") -> dict[str, Any]:
        """Smart execution: generate structured output from analysis + computation."""
        result = copy.deepcopy(model_result)

        # Generic execution for ALL engines
        result.update(self._generic_execute(data, engine_name))

        # Use analysis results to generate structured output
        analysis = data.get("_analyze_output", data.get("analysis", {}))
        scored_products = (
            analysis.get("scored_products", [])
            if isinstance(analysis, dict) else []
        )

        if scored_products:
            # Sort by total_score, select top
            ranked = sorted(scored_products, key=lambda p: p.get("total_score", 0), reverse=True)
            criteria = data.get("criteria", {})
            min_margin = float(criteria.get("min_margin", 0))

            selected = []
            rejected = []
            for i, p in enumerate(ranked):
                margin = p.get("margin_pct", 0)
                competition = float(p.get("competition", 0))
                max_comp = float(criteria.get("max_competition", 0))

                # Apply criteria filters
                skip_reason = None
                if min_margin and margin < min_margin:
                    skip_reason = f"margin {margin:.0f}% < min {min_margin:.0f}%"
                if max_comp and competition > max_comp:
                    skip_reason = f"competition {competition:.0f} > max {max_comp:.0f}"

                if skip_reason:
                    rejected.append({"name": p.get("name", ""), "reason": skip_reason})
                    continue

                selected.append({
                    "rank": len(selected) + 1,
                    "name": p.get("name", f"Product {i}"),
                    "total_score": p.get("total_score", 0),
                    "confidence": p.get("confidence", "unknown"),
                    "margin_pct": p.get("margin_pct", 0),
                    "margin_score": p.get("margin_score", 0),
                    "demand_score": p.get("demand_score", 0),
                    "competition_score": p.get("competition_score", 0),
                    "shipping_score": p.get("shipping_score", 0),
                    "rating_score": p.get("rating_score", 0),
                    "review_score": p.get("review_score", 0),
                    "price_point_score": p.get("price_point_score", 0),
                    "strong_factors": p.get("strong_factors", 0),
                    "weak_factors": p.get("weak_factors", 0),
                    "viable": p.get("viable", False),
                    "price": p.get("price", 0),
                    "cost": p.get("cost", 0),
                    "price_tier": self._price_tier(float(p.get("price", 0))),
                })

            result["selected_products"] = selected
            result["rankings"] = [{"name": s["name"], "score": s["total_score"]} for s in selected]
            result["selection_summary"] = {
                "total_evaluated": len(ranked),
                "selected": len(selected),
                "rejected": len(rejected),
                "rejected_reasons": rejected,
                "avg_score": self._comp.mean([s["total_score"] for s in selected]) if selected else 0,
                "top_product": selected[0]["name"] if selected else None,
                "criteria_applied": {k: v for k, v in criteria.items() if v},
            }
            result["generated"] = True
        else:
            # Compute from available data
            hint = data.get("_execution_hint", {})
            result["execution_approach"] = hint.get("approach", "balanced")
            result["generated"] = bool(result.get("content"))

        # Merge domain execution results (additive)
        domain_result = _domain_router.execute(engine_name, data)
        if domain_result:
            for k, v in domain_result.items():
                if k not in result:
                    result[k] = v
            if not result.get("generated") and domain_result.get("generated"):
                result["generated"] = True

        return result

    def execute_enhance(self, data: dict[str, Any], model_result: dict[str, Any], engine_name: str = "") -> dict[str, Any]:
        """Smart enhancement: add computed insights, not just creative text."""
        result = copy.deepcopy(model_result)

        # Get execution output
        execution = data.get("_execute_output", data.get("execution", {}))
        selected = execution.get("selected_products", []) if isinstance(execution, dict) else []

        # Generic enhancement for ALL engines when no selected products
        if not selected:
            result.update(self._generic_enhance(data, engine_name))
            return result

        if selected:
            enhanced_products = []
            for p in selected:
                ep = dict(p)
                price = float(p.get("price", 0))
                cost = float(p.get("cost", 0))
                margin = float(p.get("margin_pct", 0))

                # Pricing intelligence
                ep["pricing_insight"] = self._pricing_insight(price, cost, margin)

                # Competitive positioning
                comp_score = float(p.get("competition_score", 5))
                ep["competitive_position"] = (
                    "blue_ocean" if comp_score > 8
                    else "low_competition" if comp_score > 6
                    else "moderate_competition" if comp_score > 4
                    else "high_competition"
                )

                # Revenue potential
                demand = float(p.get("demand_score", 0))
                ep["revenue_potential"] = self._revenue_potential(price, margin, demand)

                enhanced_products.append(ep)

            result["enhanced_products"] = enhanced_products
            result["strategic_insights"] = self._strategic_insights(enhanced_products)
            result["enhanced"] = True

        return result

    def execute_validate(self, data: dict[str, Any], model_result: dict[str, Any], engine_name: str = "") -> dict[str, Any]:
        """Smart validation: run real checks on output data."""
        result = copy.deepcopy(model_result)
        checks = []

        # Validate execution output
        execution = data.get("_execute_output", data.get("execution", {}))
        enhanced = data.get("_enhance_output", data.get("enhanced", {}))
        source = enhanced if isinstance(enhanced, dict) and enhanced else execution
        if not isinstance(source, dict):
            source = {}

        selected = source.get("selected_products", source.get("enhanced_products", []))

        # If no selected products, use generic validation
        if not selected:
            result.update(self._generic_validate(data, engine_name))
            return result

        # Check 1: Products exist
        checks.append({
            "check": "has_products",
            "passed": len(selected) > 0,
            "detail": f"{len(selected)} products selected",
        })

        # Check 2: Scores are valid
        for p in selected:
            score = p.get("total_score", 0)
            if score < 0 or score > 10:
                checks.append({"check": "score_range", "passed": False, "detail": f"{p.get('name')}: score {score} out of range"})
                break
        else:
            checks.append({"check": "score_range", "passed": True, "detail": "All scores in valid range"})

        # Check 3: Margins are realistic
        for p in selected:
            margin = p.get("margin_pct", 0)
            if margin < 0 or margin > 99:
                checks.append({"check": "margin_realistic", "passed": False, "detail": f"{p.get('name')}: margin {margin}% unrealistic"})
                break
        else:
            checks.append({"check": "margin_realistic", "passed": True, "detail": "All margins realistic"})

        # Check 4: No duplicates
        names = [p.get("name", "") for p in selected]
        has_dupes = len(names) != len(set(names))
        checks.append({"check": "no_duplicates", "passed": not has_dupes, "detail": f"{'Duplicates found' if has_dupes else 'No duplicates'}"})

        # Check 5: Rankings ordered
        scores = [p.get("total_score", 0) for p in selected]
        is_ordered = all(scores[i] >= scores[i+1] for i in range(len(scores)-1)) if len(scores) > 1 else True
        checks.append({"check": "rankings_ordered", "passed": is_ordered, "detail": f"{'Properly ordered' if is_ordered else 'Not ordered'}"})

        passed = sum(1 for c in checks if c["passed"])
        total = len(checks)

        result["validation_checks"] = checks
        result["score"] = round(passed / total * 10, 1) if total else 0
        result["valid"] = passed == total
        result["decision"] = "approve" if result["valid"] else "reject"
        result["reason"] = f"{passed}/{total} checks passed"

        return result

    # --- Private helpers ---

    def _score_products(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Score products with 7-factor multi-dimensional analysis.

        Factors (weights total 1.0):
          - margin:      0.25  (profitability)
          - demand:       0.20  (search volume / interest)
          - competition:  0.15  (market saturation)
          - shipping:     0.10  (weight/size affects cost)
          - rating:       0.15  (customer satisfaction signal)
          - reviews:      0.10  (social proof / demand validation)
          - price_point:  0.05  (sweet spot for e-commerce: $15-60)
        """
        from utils.helpers import safe_float, safe_int
        scored = []
        for p in products:
            if not isinstance(p, dict):
                continue
            price = safe_float(p.get("price"))
            cost = safe_float(p.get("cost"))
            weight = safe_float(p.get("weight"))
            search = safe_float(p.get("search_volume"))
            comp = safe_float(p.get("competition"), 1.0)
            rating = safe_float(p.get("rating"))
            reviews = safe_int(p.get("review_count", p.get("reviews", 0)))
            inventory = safe_int(p.get("inventory_quantity", p.get("quantity", -1)))

            # Factor 1: Margin (0-10)
            margin_pct = self._comp.margin(price, cost)
            margin_score = min(margin_pct / 10, 10)

            # Factor 2: Demand (0-10) — log scale of search volume
            demand_score = min(math.log1p(search) / math.log1p(10000) * 10, 10) if search > 0 else 0

            # Factor 3: Competition (0-10) — lower = better
            comp_score = max(10 - math.log1p(comp), 0) if comp > 0 else 10

            # Factor 4: Shipping (0-10) — lighter = cheaper to ship
            ship_score = max(10 - weight * 0.5, 0) if weight > 0 else 5

            # Factor 5: Rating (0-10) — customer satisfaction
            rating_score = 0.0
            if rating > 0:
                rating_score = min(rating * 2, 10)  # 4.5 → 9.0, 5.0 → 10.0

            # Factor 6: Reviews (0-10) — social proof volume
            review_score = 0.0
            if reviews > 0:
                review_score = min(math.log1p(reviews) / math.log1p(500) * 10, 10)

            # Factor 7: Price point (0-10) — $15-60 sweet spot
            price_score = 0.0
            if 15 <= price <= 60:
                price_score = 10.0  # Perfect range
            elif 10 <= price <= 100:
                price_score = 6.0  # Acceptable
            elif price > 0:
                price_score = 3.0  # Suboptimal

            # Weighted total
            total = (
                margin_score * 0.25
                + demand_score * 0.20
                + comp_score * 0.15
                + ship_score * 0.10
                + rating_score * 0.15
                + review_score * 0.10
                + price_score * 0.05
            )

            # Decision confidence — all 7 factors included
            all_scores = [margin_score, demand_score, comp_score, ship_score, rating_score, review_score, price_score]
            strong_factors = sum(1 for s in all_scores if s >= 7)
            weak_factors = sum(1 for s in all_scores if s < 4)
            confidence = "high" if strong_factors >= 4 and weak_factors == 0 else \
                         "medium" if strong_factors >= 2 else "low"

            # Viability: needs margin + at least 2 strong factors + in stock (if inventory known)
            in_stock = inventory != 0  # -1 means unknown (OK), 0 means out of stock
            viable = total >= 5.0 and margin_pct >= 20 and strong_factors >= 2 and in_stock

            sp = dict(p)
            sp.update({
                "margin_pct": margin_pct,
                "margin_score": round(margin_score, 2),
                "demand_score": round(demand_score, 2),
                "competition_score": round(comp_score, 2),
                "shipping_score": round(ship_score, 2),
                "rating_score": round(rating_score, 2),
                "review_score": round(review_score, 2),
                "price_point_score": round(price_score, 2),
                "total_score": round(total, 2),
                "confidence": confidence,
                "strong_factors": strong_factors,
                "weak_factors": weak_factors,
                "viable": viable,
            })
            scored.append(sp)
        return scored

    @staticmethod
    def _price_tier(price: float) -> str:
        if price < 15: return "impulse"
        if price < 30: return "budget"
        if price < 60: return "mid_range"
        if price < 150: return "premium"
        return "luxury"

    @staticmethod
    def _pricing_insight(price: float, cost: float, margin: float) -> str:
        if margin > 70: return "high_margin_opportunity"
        if margin > 50: return "healthy_margin"
        if margin > 30: return "acceptable_margin"
        if margin > 15: return "thin_margin_risk"
        return "margin_too_low"

    @staticmethod
    def _revenue_potential(price: float, margin: float, demand: float) -> str:
        score = (margin / 100) * demand * (price / 50)
        if score > 5: return "high"
        if score > 2: return "medium"
        return "low"

    def _generic_enhance(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Generic enhancement for any engine — deep insights from all prior data."""
        result: dict[str, Any] = {"enhanced": True}

        analyze = data.get("_analyze_output", {})
        execute = data.get("_execute_output", {})

        # 1. Strategic insights from scores
        insights = []
        score = 0
        for s in (analyze, execute):
            if isinstance(s, dict):
                v = s.get("score", s.get("analysis_score", 0))
                if isinstance(v, (int, float)) and 0 <= v <= 10 and v > score:
                    score = v

        if score >= 8:
            insights.append(f"Strong results (score {score}/10) — high confidence, ready for implementation")
        elif score >= 5:
            insights.append(f"Moderate results (score {score}/10) — review before implementing")
        elif score > 0:
            insights.append(f"Weak results (score {score}/10) — improve input data quality")

        # 2. Data-driven insights from execute output
        if isinstance(execute, dict):
            for key, value in execute.items():
                if key.startswith("_") or key in ("generated", "engine_name"):
                    continue
                if isinstance(value, list) and len(value) > 0:
                    if isinstance(value[0], dict):
                        # Find patterns in list items
                        numeric_fields = [k for k, v in value[0].items() if isinstance(v, (int, float))]
                        for nf in numeric_fields[:2]:
                            vals = [float(item.get(nf, 0)) for item in value if isinstance(item.get(nf), (int, float))]
                            if vals:
                                avg = sum(vals) / len(vals)
                                high = sum(1 for v in vals if v > avg * 1.2)
                                if high > 0:
                                    insights.append(f"{key}: {high}/{len(vals)} items above average {nf} ({avg:.1f})")
                    insights.append(f"{key}: {len(value)} items processed")

        # 3. Risk indicators
        risks = []
        quality = data.get("_data_quality", {})
        if quality.get("quality_tier") == "low":
            risks.append("Input data quality is low — results may be unreliable")
        completeness = data.get("data_completeness", 1)
        if isinstance(completeness, (int, float)) and completeness < 0.5:
            risks.append(f"Data only {completeness:.0%} complete — missing fields may affect accuracy")

        # 4. Opportunity detection
        opportunities = []
        if isinstance(execute, dict):
            for key, value in execute.items():
                if isinstance(value, list) and len(value) > 3:
                    opportunities.append(f"Multiple {key} options available — compare and prioritize")
                if isinstance(value, dict) and len(value) > 5:
                    opportunities.append(f"Rich {key} data — explore detailed breakdown")

        result["insights"] = insights[:5] if insights else ["Processing complete"]
        result["risks"] = risks
        result["opportunities"] = opportunities[:3]
        result["quality_assessment"] = "high" if score >= 7 else "medium" if score >= 4 else "low"
        result["engine_name"] = engine_name
        return result

    def _generic_validate(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Generic validation for any engine."""
        checks = []

        # Check data completeness
        analyze = data.get("_analyze_output", {})
        execute = data.get("_execute_output", {})
        enhance = data.get("_enhance_output", {})

        has_analysis = isinstance(analyze, dict) and len(analyze) > 3
        has_execution = isinstance(execute, dict) and (execute.get("generated") or len(execute) > 3)
        has_enhancement = isinstance(enhance, dict) and enhance.get("enhanced")

        checks.append({"check": "analysis_complete", "passed": has_analysis, "detail": f"{len(analyze)} fields" if has_analysis else "No analysis"})
        checks.append({"check": "execution_complete", "passed": has_execution, "detail": f"{len(execute)} fields" if has_execution else "No execution"})
        checks.append({"check": "enhancement_done", "passed": has_enhancement, "detail": "Enhanced" if has_enhancement else "Not enhanced"})

        # Check score validity
        score = analyze.get("score", 0)
        checks.append({"check": "score_valid", "passed": isinstance(score, (int, float)) and 0 <= score <= 10, "detail": f"Score: {score}"})

        # Check no errors in prior steps
        has_errors = any(
            isinstance(d, dict) and d.get("error")
            for d in [analyze, execute, enhance]
        )
        checks.append({"check": "no_errors", "passed": not has_errors, "detail": "Clean" if not has_errors else "Errors found"})

        # Check data quality
        quality = data.get("_data_quality", {})
        quality_ok = quality.get("quality_tier") in ("high", "medium", None)
        checks.append({"check": "data_quality", "passed": quality_ok, "detail": f"Quality: {quality.get('quality_tier', 'not_assessed')}"})

        # Check output has actionable data (not just metadata)
        all_output = {}
        for d in [analyze, execute, enhance]:
            if isinstance(d, dict):
                all_output.update(d)
        actionable_keys = [k for k in all_output if not k.startswith("_") and k not in
                           ("score", "decision", "reason", "generated", "enhanced", "engine_name",
                            "request_id", "model", "role", "context_keys", "input_summary",
                            "input_field_count", "data_completeness", "data_quality")]
        has_actionable = len(actionable_keys) >= 2
        checks.append({"check": "actionable_output", "passed": has_actionable, "detail": f"{len(actionable_keys)} actionable fields"})

        # Check consistency — score should match decision
        a_score = analyze.get("score", 5)
        a_decision = analyze.get("decision", "approve")
        consistent = True
        if isinstance(a_score, (int, float)):
            if a_score >= 7 and a_decision == "reject":
                consistent = False
            if a_score < 3 and a_decision == "approve":
                consistent = False
        checks.append({"check": "consistency", "passed": consistent, "detail": f"Score {a_score} / Decision {a_decision}"})

        passed = sum(1 for c in checks if c["passed"])
        total = len(checks)
        return {
            "validation_checks": checks,
            "score": round(passed / total * 10, 1) if total else 0,
            "valid": passed >= total - 2,  # Allow up to 2 non-critical failures
            "decision": "approve" if passed >= total - 2 else "reject",
            "reason": f"{passed}/{total} checks passed",
            "issues": [c["detail"] for c in checks if not c["passed"]],
        }

    def _generic_analyze(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Generic analysis for any engine — computes stats on available data."""
        result: dict[str, Any] = {}

        # Count and summarize all input data
        input_stats = {}
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, list):
                input_stats[key] = {"type": "list", "count": len(value)}
                if value and isinstance(value[0], dict):
                    input_stats[key]["fields"] = list(value[0].keys())[:10]
            elif isinstance(value, dict):
                input_stats[key] = {"type": "dict", "fields": len(value)}
            elif isinstance(value, (int, float)):
                input_stats[key] = {"type": "number", "value": value}
            elif isinstance(value, str):
                input_stats[key] = {"type": "string", "length": len(value)}

        result["input_summary"] = input_stats
        result["input_field_count"] = len(input_stats)

        # Compute data completeness
        non_empty = sum(1 for v in data.values() if v is not None and v != "" and v != [] and v != {})
        total = sum(1 for k in data if not k.startswith("_"))
        result["data_completeness"] = round(non_empty / max(total, 1), 2)

        # Use enrichment stats if available
        for stat_key in ("_product_stats", "_customer_stats", "_order_stats"):
            if stat_key in data:
                result[stat_key[1:]] = data[stat_key]

        # Quality assessment
        quality = data.get("_data_quality", {})
        result["data_quality"] = quality.get("quality_tier", "unknown")

        # Auto-score based on data quality
        completeness = result["data_completeness"]
        result["score"] = round(completeness * 10, 1)
        result["decision"] = "approve" if completeness >= 0.5 else "reject"
        result["reason"] = f"Data completeness: {completeness:.0%}, {non_empty}/{total} fields populated"

        return result

    def _generic_execute(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Generic execution for any engine — produces structured output."""
        result: dict[str, Any] = {}

        # Extract analysis from prior step
        analysis = data.get("_analyze_output", {})
        if isinstance(analysis, dict):
            result["analysis_score"] = analysis.get("score", 0)
            result["analysis_decision"] = analysis.get("decision", "pending")

        # Process lists of items (products, customers, orders, etc.)
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, list) and value and isinstance(value[0], dict):
                processed = self._process_item_list(key, value)
                result[f"processed_{key}"] = processed
                result["generated"] = True

        # If no lists found, generate summary from dict fields
        if not result.get("generated"):
            summary = {}
            for key, value in data.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, dict) and value:
                    summary[key] = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
                elif isinstance(value, (int, float, str, bool)):
                    summary[key] = value
            result["summary"] = summary
            result["generated"] = True

        result["engine_name"] = engine_name
        return result

    def _process_item_list(self, key: str, items: list[dict]) -> dict[str, Any]:
        """Process a list of items — compute stats and rank."""
        stats: dict[str, Any] = {"total": len(items)}

        # Find numeric fields and compute stats
        if items and isinstance(items[0], dict):
            numeric_fields = {}
            for field, value in items[0].items():
                if isinstance(value, (int, float)):
                    numeric_fields[field] = []

            for item in items:
                for field in numeric_fields:
                    val = item.get(field)
                    if isinstance(val, (int, float)):
                        numeric_fields[field].append(val)

            for field, values in numeric_fields.items():
                if values:
                    stats[f"{field}_min"] = round(min(values), 2)
                    stats[f"{field}_max"] = round(max(values), 2)
                    stats[f"{field}_avg"] = round(sum(values) / len(values), 2)

        # Count unique values in string fields
        if items and isinstance(items[0], dict):
            for field, value in items[0].items():
                if isinstance(value, str):
                    unique = len(set(item.get(field, "") for item in items))
                    if unique < len(items):
                        stats[f"{field}_unique"] = unique

        return stats

    @staticmethod
    def _strategic_insights(products: list[dict[str, Any]]) -> list[str]:
        insights = []
        if not products:
            return ["No products to analyze"]

        avg_margin = sum(p.get("margin_pct", 0) for p in products) / len(products)
        if avg_margin > 60:
            insights.append(f"Strong margins ({avg_margin:.0f}% avg) — room for promotional pricing")
        elif avg_margin < 30:
            insights.append(f"Thin margins ({avg_margin:.0f}% avg) — focus on volume or cost reduction")

        positions = [p.get("competitive_position", "") for p in products]
        if "blue_ocean" in positions:
            insights.append("Blue ocean opportunity detected — low competition, high potential")
        if all(p == "high_competition" for p in positions):
            insights.append("All products in high competition — differentiation strategy needed")

        potentials = [p.get("revenue_potential", "") for p in products]
        high_rev = sum(1 for p in potentials if p == "high")
        if high_rev:
            insights.append(f"{high_rev} high revenue potential products identified")

        return insights if insights else ["Standard product mix — balanced opportunity"]
