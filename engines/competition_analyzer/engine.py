"""Competition Analyzer Engine — comprehensive competitive analysis.

Flow: input → competitor_finder → price_comparison → review_analyzer → differentiation → market_position → output
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.competitor_finder.code import find_competitors
from .modules.price_comparison.code import compare_prices
from .modules.review_analyzer.code import analyze_reviews
from .modules.differentiation.code import find_differentiation
from .modules.market_position.code import analyze_market_position


class CompetitionAnalyzerEngine:
    """Competition Analyzer — orchestrator only."""

    ENGINE_NAME = "competition_analyzer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        contract = lambda d: {"status": "success", "data": d, "meta": {}, "error": None}
        results: dict[str, Any] = {}

        results["competitors"] = find_competitors(contract(data))
        results["pricing"] = compare_prices(contract(data))
        results["reviews"] = analyze_reviews(contract(data))
        results["differentiation"] = find_differentiation(contract(data))
        results["positioning"] = analyze_market_position(contract(data))

        elapsed = time.monotonic() - start
        output = format_output(self.ENGINE_NAME, results, data, elapsed)
        validation = validate_result(output)
        if not validation["valid"]:
            return {"status": "fail", "data": None, "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": _now()}, "error": {"reason": validation["reason"]}}
        return output

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
