"""International Expansion Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Market Evaluator → Currency Manager → Localization Checker →
  Shipping Planner → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, target_markets, current_currency}, meta, error}
  Output: {status, data: {market_scores, currency_pricing, localization_gaps, shipping_plans, recommended_markets}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .market_evaluator import evaluate_markets
from .currency_manager import manage_currency_pricing
from .localization_checker import check_localization
from .shipping_planner import plan_shipping
from .memory_reader import read_past_expansions
from .memory_writer import write_expansion_result


class InternationalExpansionEngine:
    """International Expansion Engine — orchestrator only, no logic."""

    ENGINE_NAME = "international_expansion"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full international expansion pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ExpansionOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        products = data.get("products", [])
        target_markets = data.get("target_markets", [])
        current_currency = str(data.get("current_currency", "USD"))

        if not products:
            return self._fail("Product list is required", 0.0)
        if not target_markets:
            return self._fail("Target markets list is required", 0.0)

        # ---- Stage 1: Read past expansions (non-blocking) ----
        _past = read_past_expansions(limit=5)

        # ---- Stage 2: Market Evaluator ----
        market_result = evaluate_markets(
            target_markets=target_markets,
            products=products,
        )
        if market_result.get("status") == "error":
            return self._fail(
                f"Market evaluation failed: {market_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        market_scores = market_result.get("market_scores", [])

        # ---- Stage 3: Currency Manager ----
        currency_result = manage_currency_pricing(
            products=products,
            target_markets=target_markets,
            current_currency=current_currency,
        )
        if currency_result.get("status") == "error":
            return self._fail(
                f"Currency management failed: {currency_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        currency_pricing = currency_result.get("currency_pricing", [])

        # ---- Stage 4: Localization Checker ----
        local_result = check_localization(
            products=products,
            target_markets=target_markets,
        )
        if local_result.get("status") == "error":
            return self._fail(
                f"Localization check failed: {local_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        localization_gaps = local_result.get("localization_gaps", [])

        # ---- Stage 5: Shipping Planner ----
        shipping_result = plan_shipping(
            target_markets=target_markets,
            products=products,
        )
        if shipping_result.get("status") == "error":
            return self._fail(
                f"Shipping planning failed: {shipping_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        shipping_plans = shipping_result.get("shipping_plans", [])

        # ---- Stage 6: Determine recommended markets ----
        recommended_markets = [
            s["market"] for s in market_scores
            if s.get("recommendation") in ("strongly_recommended", "recommended")
        ]

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_expansion_result(
            market_scores=market_scores,
            currency_pricing=currency_pricing,
            localization_gaps=localization_gaps,
            shipping_plans=shipping_plans,
            recommended_markets=recommended_markets,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "market_scores": market_scores,
                "currency_pricing": currency_pricing,
                "localization_gaps": localization_gaps,
                "shipping_plans": shipping_plans,
                "recommended_markets": recommended_markets,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
