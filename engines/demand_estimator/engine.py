"""Demand Estimator Engine — estimate product demand from multiple signals."""
from __future__ import annotations
import time
from typing import Any
from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.search_volume.code import analyze_search_volume
from .modules.conversion_estimator.code import estimate_conversion
from .modules.price_sensitivity.code import analyze_price_sensitivity
from .modules.volume_projector.code import project_volume
from .modules.demand_trend.code import analyze_demand_trend

class DemandEstimatorEngine:
    ENGINE_NAME = "demand_estimator"
    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed
        data = processed["data"]
        results: dict[str, Any] = {}
        contract = lambda d: {"status": "success", "data": d, "meta": {}, "error": None}
        results["search_volume"] = analyze_search_volume(contract(data))
        results["conversion"] = estimate_conversion(contract(data))
        results["price_sensitivity"] = analyze_price_sensitivity(contract(data))
        results["volume_projection"] = project_volume(contract(data))
        results["demand_trend"] = analyze_demand_trend(contract(data))
        elapsed = time.monotonic() - start
        output = format_output(self.ENGINE_NAME, results, data, elapsed)
        v = validate_result(output)
        if not v["valid"]:
            return {"status": "fail", "data": None, "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": v["reason"]}}
        return output
