"""Selection Decision Engine — orchestrates the complete selection pipeline.

Flow: score_aggregator -> ranking -> confidence_calculator -> comparison -> final_selector

Each module receives the cumulative context and adds its output.
The engine returns a single contract with the selected product,
backup product, confidence assessment, and action plan.
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.score_aggregator.code import aggregate_scores
from .modules.confidence_calculator.code import calculate_confidence
from .modules.comparison.code import compare_products
from .modules.final_selector.code import select_final


class SelectionDecisionEngine:
    """Selection Decision — orchestrator for the full selection pipeline."""

    ENGINE_NAME = "selection_decision"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the selection decision pipeline.

        Args:
            input_payload: {
                data: {
                    products: list[dict] — products with engine scores
                    goal: str            — profit|growth|balanced
                    category: str        — product category
                }
            }

        Returns:
            Engine contract: {status, data, meta, error}
        """
        start = time.monotonic()

        # --- Input validation ---
        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        results: dict[str, Any] = {}
        goal = data.get("goal", "balanced")
        category = data.get("category", "general")

        # --- Module 1: Score Aggregation ---
        try:
            results["score_aggregator"] = aggregate_scores({
                "products": data.get("products", []),
                "goal": goal,
            })
        except Exception as exc:
            results["score_aggregator"] = _module_error("score_aggregator", exc)

        aggregated = results["score_aggregator"].get("data", {})
        ranked_products = aggregated.get("products", [])

        # --- Module 2: Ranking ---
        # Score aggregator already returns sorted products.
        # Apply final rank indices for downstream modules.
        try:
            ranked_products = _apply_ranks(ranked_products)
            results["ranking"] = {
                "status": "success",
                "data": {"ranked_products": ranked_products, "total": len(ranked_products)},
                "meta": {"module": "ranking"},
                "error": None,
            }
        except Exception as exc:
            results["ranking"] = _module_error("ranking", exc)

        # --- Module 3: Confidence Calculator ---
        try:
            results["confidence"] = calculate_confidence({
                "ranked_products": ranked_products,
                "engine_results": _extract_engine_results(data.get("products", [])),
                "category": category,
                "goal": goal,
            })
        except Exception as exc:
            results["confidence"] = _module_error("confidence_calculator", exc)

        confidence_data = results["confidence"].get("data", {})

        # --- Module 4: Comparison ---
        try:
            results["comparison"] = compare_products({
                "ranked_products": ranked_products,
                "goal": goal,
            })
        except Exception as exc:
            results["comparison"] = _module_error("comparison", exc)

        comparison_data = results["comparison"].get("data", {})

        # --- Module 5: Final Selector ---
        try:
            results["final_selector"] = select_final({
                "ranked_products": ranked_products,
                "confidence": confidence_data,
                "comparison": comparison_data,
                "goal": goal,
            })
        except Exception as exc:
            results["final_selector"] = _module_error("final_selector", exc)

        elapsed = time.monotonic() - start

        # --- Format and validate output ---
        output = format_output(self.ENGINE_NAME, results, data, elapsed)
        validation = validate_result(output)
        if not validation["valid"]:
            return {
                "status": "fail",
                "data": None,
                "meta": {
                    "engine": self.ENGINE_NAME,
                    "confidence": 0,
                    "timestamp": _now(),
                },
                "error": {"reason": validation["reason"]},
            }

        return output


def _apply_ranks(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add explicit rank numbers to pre-sorted products."""
    for i, product in enumerate(products):
        product["rank"] = i + 1
    return products


def _extract_engine_results(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract engine-level results from the first product for data completeness."""
    if not products:
        return {}

    # Build a summary of which engines provided data across all products
    engine_names = [
        "profitability", "demand", "competition", "risk",
        "trend_discovery", "market_research", "filter",
    ]
    engine_results: dict[str, Any] = {}
    for engine in engine_names:
        has_data = any(
            p.get(engine) is not None and isinstance(p.get(engine), dict)
            for p in products
        )
        if has_data:
            engine_results[engine] = {"status": "success", "data": True}
        else:
            engine_results[engine] = None

    return engine_results


def _module_error(module_name: str, exc: Exception) -> dict[str, Any]:
    """Return a standardized module error response."""
    return {
        "status": "error",
        "data": {},
        "meta": {"module": module_name},
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def _now() -> str:
    """Return the current UTC timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
