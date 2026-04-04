"""LayerDispatcher — connects all 12 layers to the autonomous cycle.

Layers group engines by domain. Each layer runs its engines sequentially.
LayerDispatcher runs all layers in the correct order:
  data → analysis → product → pricing → customer → marketing →
  sales → operations → financial → intelligence → execution → scaling

Each layer receives the accumulated data from previous layers.
Failures in one layer don't stop the next — results are merged.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("layer_dispatcher")

# Layer execution order (domain pipeline)
LAYER_ORDER = [
    ("data", "DataLayerFlow"),
    ("analysis", "AnalysisLayerFlow"),
    ("product", "ProductLayerFlow"),
    ("pricing", "PricingLayerFlow"),
    ("customer", "CustomerLayerFlow"),
    ("marketing", "MarketingLayerFlow"),
    ("sales", "SalesLayerFlow"),
    ("operations", "OperationsLayerFlow"),
    ("financial", "FinancialLayerFlow"),
    ("intelligence", "IntelligenceLayerFlow"),
    ("execution", "ExecutionLayerFlow"),
    ("scaling", "ScalingLayerFlow"),
]


class LayerDispatcher:
    """Runs all 12 layers in sequence during analysis phase."""

    def __init__(self) -> None:
        self._layers: dict[str, Any] = {}
        self._initialized = False

    def initialize(self) -> int:
        """Load all layer flows. Returns count loaded."""
        try:
            from layers import (
                DataLayerFlow, AnalysisLayerFlow, ProductLayerFlow,
                PricingLayerFlow, CustomerLayerFlow, MarketingLayerFlow,
                SalesLayerFlow, OperationsLayerFlow, FinancialLayerFlow,
                IntelligenceLayerFlow, ExecutionLayerFlow, ScalingLayerFlow,
            )
            layer_classes = {
                "data": DataLayerFlow, "analysis": AnalysisLayerFlow,
                "product": ProductLayerFlow, "pricing": PricingLayerFlow,
                "customer": CustomerLayerFlow, "marketing": MarketingLayerFlow,
                "sales": SalesLayerFlow, "operations": OperationsLayerFlow,
                "financial": FinancialLayerFlow, "intelligence": IntelligenceLayerFlow,
                "execution": ExecutionLayerFlow, "scaling": ScalingLayerFlow,
            }
            for name, cls in layer_classes.items():
                self._layers[name] = cls()
        except Exception as exc:
            logger.warning("Layer initialization partial: %s", exc)

        self._initialized = True
        logger.info("LayerDispatcher: %d layers loaded", len(self._layers))
        return len(self._layers)

    def run_all(self, store_data: dict[str, Any]) -> dict[str, Any]:
        """Run all 12 layers in order. Returns merged results."""
        if not self._initialized:
            self.initialize()

        start = time.monotonic()
        results: dict[str, Any] = {}
        layers_ok = 0
        total_insights = 0

        # Build engine-compatible input from store data
        accumulated = self._build_layer_input(store_data)

        for layer_name, _ in LAYER_ORDER:
            layer = self._layers.get(layer_name)
            if not layer:
                continue

            try:
                layer_result = layer.run(accumulated)
                if isinstance(layer_result, dict):
                    status = layer_result.get("status", "unknown")
                    if status != "error":
                        layers_ok += 1
                        # Count insights from layer
                        layer_data = layer_result.get("data", {})
                        if isinstance(layer_data, dict):
                            for v in layer_data.values():
                                if isinstance(v, list):
                                    total_insights += len(v)
                        # Merge layer output into accumulated data for next layer
                        if isinstance(layer_data, dict):
                            accumulated.setdefault("data", {}).update(layer_data)

                    results[layer_name] = {
                        "status": status,
                        "insights": self._count_insights(layer_result),
                    }
                else:
                    results[layer_name] = {"status": "non_dict"}

            except Exception as exc:
                results[layer_name] = {"status": "error", "error": str(exc)[:100]}
                logger.debug("Layer %s error: %s", layer_name, exc)

        elapsed = time.monotonic() - start
        return {
            "layers_run": layers_ok,
            "total_layers": len(LAYER_ORDER),
            "total_insights": total_insights,
            "duration_s": round(elapsed, 3),
            "results": results,
        }

    def run_layer(self, layer_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run a single layer."""
        if not self._initialized:
            self.initialize()

        layer = self._layers.get(layer_name)
        if not layer:
            return {"status": "error", "error": f"Layer not found: {layer_name}"}

        try:
            input_data = self._build_layer_input(data)
            return layer.run(input_data)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @staticmethod
    def _build_layer_input(store_data: dict[str, Any]) -> dict[str, Any]:
        """Convert store data to engine-compatible format for layers."""
        products = store_data.get("products", [])
        orders = store_data.get("order_data", store_data.get("orders", []))
        customers = store_data.get("customer_data", store_data.get("customers", []))

        product = products[0] if products else {}
        if product:
            product = dict(product)
            product.setdefault("cogs", product.get("cost", 0))

        return {
            "status": "success",
            "data": {
                "product": product,
                "products": products,
                "order_data": orders,
                "customer_data": customers,
            },
            "meta": {"source": "layer_dispatcher"},
            "error": None,
        }

    @staticmethod
    def _count_insights(result: dict) -> int:
        data = result.get("data", {})
        if not isinstance(data, dict):
            return 0
        count = 0
        for v in data.values():
            if isinstance(v, list):
                count += len(v)
        return count
