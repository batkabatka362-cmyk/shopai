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

logger = get_logger("step_logic.smart_executor")


class SmartExecutor:
    """Executes engine steps with real intelligence.

    For each step type:
      - analyze: runs scoring algorithms, produces real scores
      - execute: generates real structured output from computed data
      - enhance: adds computed insights (not just creative fluff)
      - validate: runs real validation checks with pass/fail

    Never modifies engine code. Adds intelligence at the framework level.
    """

    def __init__(self) -> None:
        self._comp = Computation()

    def execute_analyze(self, data: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any]:
        """Smart analysis: combine model output with real computed scores."""
        result = copy.deepcopy(model_result)

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

        return result

    def execute_work(self, data: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any]:
        """Smart execution: generate structured output from analysis + computation."""
        result = copy.deepcopy(model_result)

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
            for i, p in enumerate(ranked):
                margin = p.get("margin_pct", 0)
                if min_margin and margin < min_margin:
                    continue
                selected.append({
                    "rank": i + 1,
                    "name": p.get("name", f"Product {i}"),
                    "total_score": p.get("total_score", 0),
                    "margin_pct": p.get("margin_pct", 0),
                    "margin_score": p.get("margin_score", 0),
                    "demand_score": p.get("demand_score", 0),
                    "competition_score": p.get("competition_score", 0),
                    "shipping_score": p.get("shipping_score", 0),
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
                "rejected": len(ranked) - len(selected),
                "avg_score": self._comp.mean([s["total_score"] for s in selected]) if selected else 0,
                "top_product": selected[0]["name"] if selected else None,
            }
            result["generated"] = True
        else:
            # Compute from available data
            hint = data.get("_execution_hint", {})
            result["execution_approach"] = hint.get("approach", "balanced")
            result["generated"] = bool(result.get("content"))

        return result

    def execute_enhance(self, data: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any]:
        """Smart enhancement: add computed insights, not just creative text."""
        result = copy.deepcopy(model_result)

        # Get execution output
        execution = data.get("_execute_output", data.get("execution", {}))
        selected = execution.get("selected_products", []) if isinstance(execution, dict) else []

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

    def execute_validate(self, data: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any]:
        """Smart validation: run real checks on output data."""
        result = copy.deepcopy(model_result)
        checks = []

        # Validate execution output
        execution = data.get("_execute_output", data.get("execution", {}))
        enhanced = data.get("_enhance_output", data.get("enhanced", {}))
        source = enhanced if enhanced else execution
        if not isinstance(source, dict):
            source = {}

        selected = source.get("selected_products", source.get("enhanced_products", []))

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
        """Score a list of products."""
        scored = []
        for p in products:
            if not isinstance(p, dict):
                continue
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            weight = float(p.get("weight", 0))
            search = float(p.get("search_volume", 0))
            comp = float(p.get("competition", 1))

            margin_pct = self._comp.margin(price, cost)
            margin_score = min(margin_pct / 10, 10)
            demand_score = min(math.log1p(search) / math.log1p(10000) * 10, 10) if search > 0 else 0
            comp_score = max(10 - math.log1p(comp), 0) if comp > 0 else 10
            ship_score = max(10 - weight * 0.5, 0) if weight > 0 else 5

            total = margin_score * 0.35 + demand_score * 0.30 + comp_score * 0.20 + ship_score * 0.15

            sp = dict(p)
            sp.update({
                "margin_pct": margin_pct,
                "margin_score": round(margin_score, 2),
                "demand_score": round(demand_score, 2),
                "competition_score": round(comp_score, 2),
                "shipping_score": round(ship_score, 2),
                "total_score": round(total, 2),
                "viable": total >= 5.0 and margin_pct >= 20,
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
