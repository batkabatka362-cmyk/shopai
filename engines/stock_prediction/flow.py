"""Stock Prediction Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Demand Modeler → Seasonality Detector →
  Lead Time Estimator → Restock Recommender → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, orders_history, suppliers, current_stock}, meta, error}
  Output: {status, data: {predictions, seasonal_factors, confidence}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .demand_modeler import model_demand
from .seasonality_detector import detect_seasonality
from .lead_time_estimator import estimate_lead_times
from .restock_recommender import recommend_restocks
from .memory_reader import read_past_predictions
from .memory_writer import write_prediction_result
from engines._shopify_hydrator import hydrate


class StockPredictionEngine:
    """Stock Prediction Engine — orchestrator only, no logic."""

    ENGINE_NAME = "stock_prediction"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full stock prediction pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            StockPredictionOutput dict.
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

        products = data.get("products", [])
        orders_history = data.get("orders_history", [])
        suppliers = data.get("suppliers", [])
        current_stock = data.get("current_stock", {})

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past predictions (non-blocking) ----
        _past = read_past_predictions(limit=5)

        # ---- Stage 2: Demand Modeler ----
        demand_result = model_demand(
            products=products,
            orders_history=orders_history,
        )
        if demand_result.get("status") == "error":
            return self._fail(
                f"Demand modeling failed: {demand_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        demand_models = demand_result.get("models", [])

        # ---- Stage 3: Seasonality Detector ----
        seasonality_result = detect_seasonality(
            orders_history=orders_history,
            demand_models=demand_models,
        )
        if seasonality_result.get("status") == "error":
            return self._fail(
                f"Seasonality detection failed: {seasonality_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        seasonal_factors = seasonality_result.get("seasonal_factors", [])

        # ---- Stage 4: Lead Time Estimator ----
        lead_time_result = estimate_lead_times(
            products=products,
            suppliers=suppliers,
        )
        if lead_time_result.get("status") == "error":
            return self._fail(
                f"Lead time estimation failed: {lead_time_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        lead_times = lead_time_result.get("lead_times", [])

        # ---- Stage 5: Restock Recommender ----
        restock_result = recommend_restocks(
            products=products,
            demand_models=demand_models,
            seasonal_factors=seasonal_factors,
            lead_times=lead_times,
            current_stock=current_stock,
        )
        if restock_result.get("status") == "error":
            return self._fail(
                f"Restock recommendation failed: {restock_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        recommendations = restock_result.get("recommendations", [])

        # ---- Stage 6: Assemble predictions ----
        # ``urgency`` is forwarded from the recommender so the
        # opt-in tag_applier (Stage 7.5) can bucket on it. Existing
        # callers ignore the extra key; new callers can drive a
        # "show me products about to stock out" view directly off
        # the engine output.
        predictions: list[dict[str, Any]] = []
        for rec in recommendations:
            predictions.append({
                "product_id": rec.get("product_id", ""),
                "predicted_demand_30d": rec.get("predicted_demand_30d", 0.0),
                "predicted_demand_90d": rec.get("predicted_demand_90d", 0.0),
                "restock_date": rec.get("restock_date", ""),
                "restock_qty": rec.get("restock_qty", 0),
                "urgency": rec.get("urgency", "low"),
            })

        # Compute overall confidence
        confidences = [m.get("model_confidence", 0.5) for m in demand_models]
        avg_confidence = (
            round(sum(confidences) / len(confidences), 3)
            if confidences else 0.0
        )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_prediction_result(
            predictions=predictions,
            seasonal_factors=seasonal_factors,
            confidence=avg_confidence,
        )

        # ---- Stage 7.5: Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory urgency classifications.
        # When the caller passes ``data.apply_stock_tags=True``,
        # we push ``shopai-stock-{urgency}`` on every at-risk
        # product via SHOPIFY_ADD_TAGS. Merchants then save
        # admin searches to drive a "products needing restock"
        # worklist; downstream engines (catalog / storefront /
        # paid_ads) can suppress these from featured slots or
        # pause ad spend on products that will stock out
        # before the ads ROI.
        #
        # Only ``critical`` is tagged by default;
        # ``data.include_high=True`` opts in ``high`` too.
        # ``medium`` / ``low`` are noise for the operational
        # worklist.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue via approval queue.
        #   * False -- call SHOPIFY_ADD_TAGS directly.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_stock_tags") is True:
            try:
                from .tag_applier import apply_stock_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                include_high = bool(
                    data.get("include_high", False),
                )
                tag_results = apply_stock_tags(
                    predictions,
                    include_high=include_high,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises
                # out by design.
                import logging
                logging.getLogger(__name__).debug(
                    "stock_prediction tag_applier raised: %s",
                    exc,
                )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "predictions": predictions,
                "seasonal_factors": seasonal_factors,
                "confidence": avg_confidence,
                # Phase 7 writeback: per-product tag results
                # when opted in. Empty otherwise.
                "tag_results": tag_results,
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
