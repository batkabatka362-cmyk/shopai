"""Market Research Engine — orchestrates 5 research modules.

This is the ENGINE file. It ONLY orchestrates — no logic here.
Calls modules in sequence, passes data between them, returns unified result.

Flow:
  input → market_size → market_trends → seasonality → gap_finder → saturation → output

Engine contract:
  Input:  {status, data: {category, products, search_data, ...}, meta, error}
  Output: {status, data: {market_size, trends, seasonality, gaps, saturation}, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.market_size.code import full_market_size
from .modules.market_trends.code import compute_trend_score
from .modules.seasonality.code import compute_seasonality_profile, compute_event_calendar, compute_optimal_launch_window
from .modules.gap_finder.code import find_gaps
from .modules.saturation.code import analyze_saturation


class MarketResearchEngine:
    """Market Research Engine — orchestrator only, no logic."""

    ENGINE_NAME = "market_research"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run full market research pipeline.

        6 stages: validate input → run modules → validate output → return
        """
        start = time.monotonic()

        # Stage 1: Input validation + standardization
        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        category = data.get("category", "")

        # Stage 2-5: Run modules (each follows its own contract)
        results: dict[str, Any] = {}

        # Module 1: Market Size
        results["market_size"] = full_market_size(
            category=category,
            sub_niche_pct=data.get("sub_niche_pct", 0.1),
            geographic_reach=data.get("geographic_reach", 1.0),
            price_range_fit=data.get("price_range_fit", 0.5),
            store_maturity=data.get("store_maturity", "new_store"),
        )

        # Module 2: Market Trends
        signals = data.get("trend_signals", {})
        if signals:
            results["trends"] = compute_trend_score(signals)
        else:
            results["trends"] = {"status": "no_signals", "note": "Provide trend_signals for analysis"}

        # Module 3: Seasonality
        results["seasonality"] = compute_seasonality_profile(category=category)
        results["event_calendar"] = compute_event_calendar()
        results["launch_window"] = compute_optimal_launch_window(category=category)

        # Module 4: Gap Finder (follows engine contract)
        gap_input = {
            "status": "success",
            "data": {
                "category": category,
                "products": data.get("products", []),
                "search_data": data.get("search_data", {}),
                "reviews": data.get("reviews", []),
            },
            "meta": {},
            "error": None,
        }
        results["gaps"] = find_gaps(gap_input)

        # Module 5: Saturation (follows engine contract)
        sat_input = {
            "status": "success",
            "data": {
                "category": category,
                "competitors": data.get("competitors", []),
                "search_data": data.get("search_data", {}),
                "pricing": data.get("pricing", {}),
            },
            "meta": {},
            "error": None,
        }
        results["saturation"] = analyze_saturation(sat_input)

        elapsed = time.monotonic() - start

        # Stage 6: Format output + validate
        output = format_output(
            engine_name=self.ENGINE_NAME,
            results=results,
            category=category,
            elapsed=elapsed,
        )

        validation = validate_result(output)
        if not validation["valid"]:
            return {
                "status": "fail",
                "data": None,
                "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": _now()},
                "error": {"reason": validation["reason"], "partial_results": results},
            }

        return output


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
