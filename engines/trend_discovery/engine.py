"""Trend Discovery Engine — orchestrates 5 trend detection modules.

Flow: input → search_trends → social_trends → marketplace_trends → emerging_niches → trend_scorer → output
Engine contract: {status, data, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.search_trends.code import analyze_search_trends
from .modules.social_trends.code import analyze_social_trends
from .modules.marketplace_trends.code import analyze_marketplace_trends
from .modules.emerging_niches.code import discover_emerging_niches
from .modules.trend_scorer.code import score_trend


class TrendDiscoveryEngine:
    """Trend Discovery Engine — orchestrator only."""

    ENGINE_NAME = "trend_discovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        results: dict[str, Any] = {}

        # Module 1: Search Trends
        results["search"] = analyze_search_trends({"status": "success", "data": {"keywords": data.get("keywords", []), "category": data.get("category", "")}, "meta": {}, "error": None})

        # Module 2: Social Trends
        results["social"] = analyze_social_trends({"status": "success", "data": {"trends": data.get("social_trends", []), "category": data.get("category", "")}, "meta": {}, "error": None})

        # Module 3: Marketplace Trends
        results["marketplace"] = analyze_marketplace_trends({"status": "success", "data": {"products": data.get("marketplace_products", []), "category": data.get("category", "")}, "meta": {}, "error": None})

        # Module 4: Emerging Niches
        results["emerging"] = discover_emerging_niches({"status": "success", "data": {"category": data.get("category", ""), "scan_known": True}, "meta": {}, "error": None})

        # Module 5: Trend Scorer (aggregates all signals)
        scorer_signals = {}
        for key in ("search", "social", "marketplace", "emerging"):
            module_result = results.get(key, {})
            if module_result.get("status") == "success":
                scorer_signals[key] = module_result.get("data", {})

        results["composite"] = score_trend({"status": "success", "data": {"signals": scorer_signals, "category": data.get("category", ""), "trend_name": data.get("category", "")}, "meta": {}, "error": None})

        elapsed = time.monotonic() - start
        output = format_output(self.ENGINE_NAME, results, data.get("category", ""), elapsed)

        validation = validate_result(output)
        if not validation["valid"]:
            return {"status": "fail", "data": None, "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": _now()}, "error": {"reason": validation["reason"]}}

        return output


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
