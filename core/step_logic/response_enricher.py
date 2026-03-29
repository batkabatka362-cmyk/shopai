"""ResponseEnricher — enriches every engine output with actionable intelligence.

Adds to EVERY engine output:
  - next_steps: what to do with these results
  - confidence: how confident is the result
  - action_items: specific actionable items
  - metadata: timing, data quality, engine info
  - related_engines: what engines to run next
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("step_logic.enricher")

# Engine relationship map — what to run after each engine
ENGINE_NEXT_STEPS = {
    "product_selection": ["pricing", "content_generation", "seo", "inventory"],
    "pricing": ["discount_strategy", "ab_testing", "competitor_pricing", "dynamic_pricing"],
    "customer_segmentation": ["personalization", "email_marketing", "retention", "churn_prediction"],
    "seo": ["content_optimization", "keyword_research", "link_building", "blog_generation"],
    "inventory": ["stock_prediction", "demand_forecasting", "supplier", "procurement"],
    "content_generation": ["seo", "social_media", "email_marketing", "blog_generation"],
    "analytics": ["forecasting", "kpi_tracking", "reporting", "dashboard_creation"],
    "email_marketing": ["ab_testing", "audience_targeting", "conversion_tracking"],
    "churn_prediction": ["retention", "customer_segmentation", "win_back", "loyalty_program"],
    "demand_forecasting": ["inventory", "stock_prediction", "procurement", "supply_chain"],
    "competitor_analysis": ["pricing", "market_research", "content_gap", "seo"],
    "shipping_optimization": ["delivery_optimization", "packaging_optimization", "carrier_options"],
    "loyalty_program": ["points_system", "referral_program", "vip_management"],
}

# Confidence thresholds
CONFIDENCE_THRESHOLDS = {"high": 8.0, "medium": 5.0, "low": 0.0}


class ResponseEnricher:
    """Enriches every engine response with actionable intelligence."""

    def enrich(self, result: dict[str, Any], engine_name: str, elapsed_seconds: float = 0) -> dict[str, Any]:
        """Enrich an engine result with intelligence. Never mutates input."""
        enriched = copy.deepcopy(result)

        score = self._extract_score(result)
        confidence = self._calculate_confidence(result, score)

        enriched["_intelligence"] = {
            "confidence": confidence,
            "confidence_score": score,
            "next_steps": self._suggest_next_steps(engine_name, result),
            "action_items": self._extract_action_items(result, engine_name),
            "related_engines": ENGINE_NEXT_STEPS.get(engine_name, []),
            "result_quality": self._assess_quality(result),
            "metadata": {
                "engine": engine_name,
                "elapsed_seconds": elapsed_seconds,
                "output_fields": len([k for k in result if not k.startswith("_")]),
                "has_validation": "validation_checks" in result,
                "has_insights": "insights" in result or "strategic_insights" in result,
                "timestamp": time.time(),
            },
        }

        return enriched

    def _suggest_next_steps(self, engine_name: str, result: dict) -> list[str]:
        """Suggest actionable next steps based on results."""
        steps = []
        score = self._extract_score(result)
        decision = result.get("decision", "")

        if decision == "approve" and score >= 7:
            related = ENGINE_NEXT_STEPS.get(engine_name, [])
            if related:
                steps.append(f"Run {related[0]} engine with these results")
            steps.append("Review and implement recommendations")
        elif decision == "reject" or score < 5:
            steps.append("Review input data quality — may need improvement")
            steps.append("Check data completeness and accuracy")
        else:
            steps.append("Review results carefully before implementing")

        # Domain-specific next steps
        if "selected_products" in result:
            steps.append("Set up product listings for selected products")
            steps.append("Generate content for top-ranked products")
        if "pricing_recommendations" in result:
            steps.append("Review and apply price changes")
            steps.append("Set up A/B price testing")
        if "churn_risks" in result:
            steps.append("Launch retention campaigns for at-risk customers")
        if "keyword_strategy" in result:
            steps.append("Create content for primary keywords")
        if "reorder_recommendations" in result:
            steps.append("Submit purchase orders for low-stock items")

        return steps[:5]

    def _extract_action_items(self, result: dict, engine_name: str) -> list[dict[str, Any]]:
        """Extract specific actionable items from results."""
        actions = []

        # From recommendations
        for key in ("pricing_recommendations", "recommendations", "optimization_actions",
                     "reorder_recommendations", "retention_strategies", "action_items"):
            items = result.get(key, [])
            if isinstance(items, list):
                for item in items[:3]:
                    if isinstance(item, dict):
                        actions.append({
                            "action": item.get("action", item.get("name", str(item)[:60])),
                            "priority": item.get("priority", "medium"),
                            "source": key,
                        })
                    elif isinstance(item, str):
                        actions.append({"action": item[:80], "priority": "medium", "source": key})

        # From insights
        for key in ("insights", "strategic_insights"):
            insights = result.get(key, [])
            if isinstance(insights, list):
                for insight in insights[:2]:
                    if isinstance(insight, str):
                        actions.append({"action": f"Investigate: {insight[:60]}", "priority": "low", "source": "insight"})

        # From validation issues
        checks = result.get("validation_checks", [])
        for check in checks:
            if isinstance(check, dict) and not check.get("passed", True):
                actions.append({"action": f"Fix: {check.get('detail', check.get('check', 'unknown'))}", "priority": "high", "source": "validation"})

        return actions[:8]

    def _calculate_confidence(self, result: dict, score: float) -> str:
        """Calculate confidence level from multiple signals."""
        signals = 0
        total = 0

        # Score signal
        total += 1
        if score >= 7: signals += 1

        # Validation signal
        total += 1
        if result.get("valid", False): signals += 1

        # Data quality signal
        total += 1
        quality = result.get("data_quality", "")
        if quality == "high": signals += 1

        # Generated signal
        total += 1
        if result.get("generated", False): signals += 1

        # Insights signal
        total += 1
        if result.get("insights") or result.get("strategic_insights"): signals += 1

        ratio = signals / total if total > 0 else 0
        if ratio >= 0.8: return "high"
        if ratio >= 0.5: return "medium"
        return "low"

    def _assess_quality(self, result: dict) -> dict[str, Any]:
        """Assess overall result quality."""
        real_fields = [k for k in result if not k.startswith("_") and k not in
                       ("analysis", "execution", "enhanced", "validation", "request_id", "model", "role", "context_keys")]
        has_lists = sum(1 for k in real_fields if isinstance(result.get(k), list) and result[k])
        has_dicts = sum(1 for k in real_fields if isinstance(result.get(k), dict) and result[k])
        has_computed = any(k in result for k in ("score", "scored_products", "price_analysis", "customer_analysis",
                                                   "keyword_analysis", "inventory_analysis", "campaign_analysis"))

        depth_score = min(10, len(real_fields) * 0.5 + has_lists * 1.5 + has_dicts + (3 if has_computed else 0))
        return {
            "depth_score": round(depth_score, 1),
            "field_count": len(real_fields),
            "has_computed_data": has_computed,
            "has_structured_output": has_lists > 0 or has_dicts > 0,
            "tier": "deep" if depth_score >= 8 else "standard" if depth_score >= 5 else "shallow",
        }

    @staticmethod
    def _extract_score(result: dict) -> float:
        for key in ("score", "analysis_score", "confidence_score"):
            val = result.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        return 5.0
