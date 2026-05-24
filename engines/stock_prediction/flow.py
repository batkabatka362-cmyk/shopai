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
        predictions: list[dict[str, Any]] = []
        for rec in recommendations:
            predictions.append({
                "product_id": rec.get("product_id", ""),
                "predicted_demand_30d": rec.get("predicted_demand_30d", 0.0),
                "predicted_demand_90d": rec.get("predicted_demand_90d", 0.0),
                "restock_date": rec.get("restock_date", ""),
                "restock_qty": rec.get("restock_qty", 0),
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

        # Phase 7: optional restock-tag apply. Opt-in via
        # data.apply_restock_tags=True. Tags products with
        # restock_qty > 0.
        tagged_restock: list[dict[str, Any]] = []
        if bool(data.get("apply_restock_tags")):
            try:
                from .tag_applier import apply_restock_tags
                tagged_restock = apply_restock_tags(
                    predictions, products,
                )
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "stock_prediction: apply loop raised: %s",
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
                "tagged_restock": tagged_restock,
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
