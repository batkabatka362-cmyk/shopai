"""PreProcessor — runs real computation BEFORE model is called.

This is where real business logic lives. Model gets pre-computed data
so it can make better decisions. Never sends raw, unprocessed data to model.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from utils.logger import get_logger

logger = get_logger("step_logic.pre")


class PreProcessor:
    """Runs business computations before model call."""

    def process(self, data: dict[str, Any], engine_name: str, step_name: str) -> dict[str, Any]:
        """Pre-process data for a specific engine step. Returns new dict."""
        result = copy.deepcopy(data)

        # Always compute data quality score
        result["_data_quality"] = self._score_data_quality(data)

        # Step-specific pre-processing
        if step_name == "analyze":
            result = self._pre_analyze(result, engine_name)
        elif step_name == "execute":
            result = self._pre_execute(result, engine_name)
        elif step_name == "validate":
            result = self._pre_validate(result, engine_name)

        return result

    def _pre_analyze(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Pre-compute scores and metrics for analyzer."""
        products = data.get("products", data.get("product_data", []))

        if isinstance(products, list):
            scored = []
            for p in products:
                if isinstance(p, dict):
                    scored.append(self._score_product(p))
            if scored:
                data["_pre_scored_products"] = scored
                data["_pre_computed"] = {
                    "avg_score": round(sum(s.get("total_score", 0) for s in scored) / len(scored), 2),
                    "viable_count": sum(1 for s in scored if s.get("viable", False)),
                    "top_margin": max((s.get("margin_pct", 0) for s in scored), default=0),
                }

        # Pre-compute pricing intelligence
        if "pricing_data" in data or "price" in str(data.keys()):
            data["_pricing_analysis"] = self._analyze_pricing(data)

        return data

    def _pre_execute(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Pre-compute structured context for worker."""
        # Add execution hints based on pre-analysis
        analysis = data.get("_analyze_output", data.get("analysis", {}))
        if isinstance(analysis, dict):
            score = analysis.get("score", 0)
            data["_execution_hint"] = {
                "confidence": "high" if score > 7 else "medium" if score > 4 else "low",
                "approach": "aggressive" if score > 8 else "balanced" if score > 5 else "conservative",
            }
        return data

    def _pre_validate(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Pre-compute validation checks."""
        checks = []

        # Check output completeness
        execute_output = data.get("_execute_output", data.get("execution", {}))
        if isinstance(execute_output, dict):
            if not execute_output:
                checks.append({"check": "output_empty", "passed": False})
            else:
                checks.append({"check": "output_present", "passed": True})
                checks.append({"check": "output_fields", "passed": True, "count": len(execute_output)})

        data["_pre_validation_checks"] = checks
        return data

    def _score_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Score a product on multiple dimensions."""
        scored = dict(product)

        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))
        weight = float(product.get("weight", 0))
        search_volume = float(product.get("search_volume", 0))
        competition = float(product.get("competition", 1))

        # Margin score (0-10)
        margin_pct = (price - cost) / price * 100 if price > 0 and cost > 0 else 0
        margin_score = min(margin_pct / 10, 10)

        # Demand score (0-10)
        demand_score = min(math.log1p(search_volume) / math.log1p(10000) * 10, 10) if search_volume > 0 else 0

        # Competition score (0-10, lower competition = higher score)
        comp_score = max(10 - math.log1p(competition), 0) if competition > 0 else 10

        # Shipping score (0-10, lighter = better)
        ship_score = max(10 - weight * 0.5, 0) if weight > 0 else 5

        # Total weighted score
        total = (
            margin_score * 0.35
            + demand_score * 0.30
            + comp_score * 0.20
            + ship_score * 0.15
        )

        scored["margin_pct"] = round(margin_pct, 2)
        scored["margin_score"] = round(margin_score, 2)
        scored["demand_score"] = round(demand_score, 2)
        scored["competition_score"] = round(comp_score, 2)
        scored["shipping_score"] = round(ship_score, 2)
        scored["total_score"] = round(total, 2)
        scored["viable"] = total >= 5.0 and margin_pct >= 20

        return scored

    @staticmethod
    def _analyze_pricing(data: dict[str, Any]) -> dict[str, Any]:
        """Pre-compute pricing analysis."""
        prices = []
        for key in ("products", "product_data"):
            items = data.get(key, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "price" in item:
                        prices.append(float(item["price"]))
            elif isinstance(items, dict) and "price" in items:
                prices.append(float(items["price"]))

        if not prices:
            return {"has_pricing": False}

        return {
            "has_pricing": True,
            "price_count": len(prices),
            "price_range": [round(min(prices), 2), round(max(prices), 2)],
            "price_avg": round(sum(prices) / len(prices), 2),
            "price_std": round((sum((p - sum(prices)/len(prices))**2 for p in prices) / len(prices)) ** 0.5, 2),
        }

    @staticmethod
    def _score_data_quality(data: dict[str, Any]) -> dict[str, Any]:
        """Score the quality/completeness of input data."""
        total_fields = len(data)
        non_empty = sum(1 for v in data.values() if v is not None and v != "" and v != [] and v != {})
        completeness = round(non_empty / total_fields, 2) if total_fields > 0 else 0

        return {
            "total_fields": total_fields,
            "non_empty_fields": non_empty,
            "completeness": completeness,
            "quality_tier": "high" if completeness > 0.8 else "medium" if completeness > 0.5 else "low",
        }
