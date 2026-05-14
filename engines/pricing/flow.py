"""Pricing Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Product + Market Data → Cost Analyzer → Competitor Price Mapper →
  Value Estimator → Price Calculator → Margin Validator →
  Psychology Optimizer → Elasticity Estimator → Price Recommender →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {product, market, platform_fees_pct, payment_processing_pct, target_margin}, meta, error}
  Output: {status, data: {recommended_price, price_range, strategy, ...}, meta: {engine, ...}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .cost_analyzer import analyze_costs
from .competitor_price_mapper import map_competitor_prices
from .value_estimator import estimate_value
from .price_calculator import calculate_prices
from .margin_validator import validate_margin
from .psychology_optimizer import optimize_psychology
from .elasticity_estimator import estimate_elasticity
from .price_recommender import recommend_price
from .price_applier import (
    apply_strategic_price,
    enqueue_strategic_price_for_approval,
)
from .memory_reader import read_past_pricing
from .memory_writer import write_pricing_result
from engines._shopify_hydrator import hydrate_one


class PricingEngine:
    """Pricing Engine — orchestrator only, no logic."""

    ENGINE_NAME = "pricing"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full pricing pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            PricingOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        product = data.get("product", {})
        market = data.get("market", {})
        platform_fees_pct = float(data.get("platform_fees_pct", 0.029))
        payment_processing_pct = float(data.get("payment_processing_pct", 0.029))
        target_margin = float(data.get("target_margin", 0.30))

        # Auto-hydrate a single product from Shopify when caller
        # left the dict empty. Pre-existing failure semantics
        # preserved: empty supplied AND empty hydrated → standard
        # error.
        product = hydrate_one(
            supplied=product if isinstance(product, dict) else {},
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            query=data.get("hydrate_query"),
        )

        if not product:
            return self._fail("Product data is required", 0.0)

        # ---- Stage 1: Read past pricing (non-blocking) ----
        _past = read_past_pricing(limit=5)

        # ---- Stage 2: Cost Analyzer ----
        cost_result = analyze_costs(
            product=product,
            platform_fees_pct=platform_fees_pct,
            payment_processing_pct=payment_processing_pct,
        )
        if cost_result.get("status") == "error":
            return self._fail(
                f"Cost analysis failed: {cost_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        cost_analysis = cost_result.get("analysis", {})

        # ---- Stage 3: Competitor Price Mapper ----
        cost_floor = float(cost_analysis.get("cost_floor", 0.0))
        comp_result = map_competitor_prices(
            market=market,
            reference_price=cost_floor,
        )
        if comp_result.get("status") == "error":
            return self._fail(
                f"Competitor mapping failed: {comp_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        competitor_mapping = comp_result.get("mapping", {})

        # ---- Stage 4: Value Estimator ----
        value_result = estimate_value(
            product=product,
            market=market,
            cost_analysis=cost_analysis,
            competitor_mapping=competitor_mapping,
        )
        if value_result.get("status") == "error":
            return self._fail(
                f"Value estimation failed: {value_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        value_estimate = value_result.get("estimate", {})

        # ---- Stage 5: Price Calculator ----
        demand_level = str(market.get("demand_level", "medium"))
        calc_result = calculate_prices(
            cost_analysis=cost_analysis,
            competitor_mapping=competitor_mapping,
            value_estimate=value_estimate,
            target_margin=target_margin,
            demand_level=demand_level,
        )
        if calc_result.get("status") == "error":
            return self._fail(
                f"Price calculation failed: {calc_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_calculation = calc_result.get("calculation", {})
        weighted_price = float(price_calculation.get("weighted_price", 0.0))

        # ---- Stage 6: Margin Validator ----
        margin_result = validate_margin(
            proposed_price=weighted_price,
            cost_analysis=cost_analysis,
            competitor_mapping=competitor_mapping,
            target_margin=target_margin,
            demand_level=demand_level,
        )
        if margin_result.get("status") == "error":
            return self._fail(
                f"Margin validation failed: {margin_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        margin_validation = margin_result.get("validation", {})

        # ---- Stage 7: Psychology Optimizer ----
        ceiling_price = float(margin_validation.get("ceiling_price", 0.0))
        psych_result = optimize_psychology(
            proposed_price=weighted_price,
            cost_floor=cost_floor,
            ceiling_price=ceiling_price,
            competitor_mapping=competitor_mapping,
        )
        if psych_result.get("status") == "error":
            return self._fail(
                f"Psychology optimization failed: {psych_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        psychology_adjustment = psych_result.get("adjustment", {})

        # ---- Stage 8: Elasticity Estimator ----
        adjusted_price = float(psychology_adjustment.get("adjusted_price", weighted_price))
        elast_result = estimate_elasticity(
            proposed_price=adjusted_price,
            cost_analysis=cost_analysis,
            competitor_mapping=competitor_mapping,
            product=product,
            market=market,
        )
        if elast_result.get("status") == "error":
            return self._fail(
                f"Elasticity estimation failed: {elast_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        elasticity = elast_result.get("elasticity", {})

        # ---- Stage 9: Price Recommender ----
        rec_result = recommend_price(
            psychology_adjustment=psychology_adjustment,
            margin_validation=margin_validation,
            price_calculation=price_calculation,
            cost_analysis=cost_analysis,
            competitor_mapping=competitor_mapping,
            value_estimate=value_estimate,
            elasticity=elasticity,
            target_margin=target_margin,
        )
        if rec_result.get("status") == "error":
            return self._fail(
                f"Price recommendation failed: {rec_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        recommendation = rec_result.get("recommendation", {})

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _write_result = write_pricing_result(
            recommended_price=float(recommendation.get("optimal_price", 0.0)),
            strategy=str(recommendation.get("strategy", "")),
            projected_margin=float(recommendation.get("projected_margin", 0.0)),
            cost_breakdown=cost_analysis,
            competitive_position=str(recommendation.get("competitive_position", "")),
            confidence=float(recommendation.get("confidence", 0.0)),
        )

        # ---- Stage 10.5: Strategic-price writeback (opt-in) ----
        # Default OFF — existing callers keep the pure-
        # recommendation contract. Two opt-in modes mirror the
        # Phase 6/7 pattern:
        #
        #   data.apply_strategic_price=True + data.require_approval=False
        #     → push price via SHOPIFY_UPDATE_VARIANTS immediately
        #   data.apply_strategic_price=True + data.require_approval=True
        #     → enqueue to core.approval; merchant approves before
        #       the mutation lands
        #
        # Both paths share the same upfront guards (positive
        # recommended_price, confidence floor, product has
        # variants). Known limitation matches dynamic_pricing's:
        # hydrator-fetched products from SHOPIFY_LIST_PRODUCTS
        # don't include variants, so callers wanting writeback
        # need to pre-fetch with SHOPIFY_GET_PRODUCT.
        price_apply_result: dict[str, Any] | None = None
        price_pending_action: dict[str, Any] | None = None
        store_cfg = data.get("store", {}) if isinstance(
            data.get("store"), dict,
        ) else {}
        if data.get("apply_strategic_price") is True:
            if data.get("require_approval") is True:
                price_pending_action = enqueue_strategic_price_for_approval(
                    product=product,
                    recommendation=recommendation,
                    store=store_cfg,
                )
            else:
                price_apply_result = apply_strategic_price(
                    product=product,
                    recommendation=recommendation,
                    store=store_cfg,
                )

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        recommended_price = float(recommendation.get("optimal_price", 0.0))
        projected_margin = float(recommendation.get("projected_margin", 0.0))

        return {
            "status": "success",
            "data": {
                "recommended_price": recommended_price,
                "price_range": recommendation.get("price_range", {"floor": 0.0, "ceiling": 0.0}),
                "strategy": recommendation.get("strategy", "cost_plus"),
                "margin_at_recommended": round(projected_margin, 4),
                "competitive_position": recommendation.get("competitive_position", "unknown"),
                "psychology_applied": psychology_adjustment.get("technique_applied", "none"),
                "cost_breakdown": cost_analysis,
                "elasticity": {
                    "sensitivity": elasticity.get("sensitivity", "medium"),
                    "optimal_volume_price": elasticity.get("optimal_volume_price", 0.0),
                },
                "confidence": float(recommendation.get("confidence", 0.0)),
                "rationale": recommendation.get("rationale", ""),
                # Stage 10.5 output — mutually exclusive: one
                # or the other is populated when the opt-in
                # flags routed through a path; both ``None`` when
                # default-off or guardrails rejected.
                "price_apply_result": price_apply_result,
                "price_pending_action": price_pending_action,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

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
