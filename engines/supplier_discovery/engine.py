"""Supplier Discovery Engine — orchestrates 5 supplier research modules.

Flow: input → supplier_search → supplier_scorer → moq_analyzer → lead_time → cost_negotiation → output

Engine contract:
  Input:  {status, data: {product_type, target_price, ...}, meta, error}
  Output: {status, data: {sources, scored, moq, lead_time, negotiation}, meta, error}
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.supplier_search.code import search_suppliers
from .modules.supplier_scorer.code import score_supplier
from .modules.moq_analyzer.code import analyze_moq
from .modules.lead_time.code import analyze_lead_time
from .modules.cost_negotiation.code import plan_negotiation


class SupplierDiscoveryEngine:
    """Supplier Discovery Engine — orchestrator only."""

    ENGINE_NAME = "supplier_discovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        results: dict[str, Any] = {}

        # Module 1: Search supplier sources
        results["sources"] = search_suppliers({"status": "success", "data": data, "meta": {}, "error": None})

        # Module 2: Score top suppliers (if individual supplier data provided)
        suppliers = data.get("suppliers", [])
        if suppliers:
            scored = []
            for s in suppliers[:10]:
                score_result = score_supplier({"status": "success", "data": {"supplier": s}, "meta": {}, "error": None})
                if score_result.get("status") == "success":
                    scored.append(score_result["data"])
            results["scored_suppliers"] = scored
        else:
            results["scored_suppliers"] = []

        # Module 3: MOQ analysis
        top_source = results["sources"].get("data", {}).get("top_recommendation", {})
        results["moq_analysis"] = analyze_moq({
            "status": "success",
            "data": {
                "moq": top_source.get("typical_moq", 100),
                "unit_cost": top_source.get("estimated_unit_cost", data.get("target_price", 30) * 0.3),
                "monthly_demand": data.get("estimated_monthly_demand", 50),
                "budget": data.get("budget", 5000),
                "storage_cost_per_unit": data.get("storage_cost", 0.50),
            },
            "meta": {},
            "error": None,
        })

        # Module 4: Lead time analysis
        results["lead_time"] = analyze_lead_time({
            "status": "success",
            "data": {
                "supplier_type": top_source.get("type", "manufacturer"),
                "origin_country": data.get("origin_country", "china"),
                "destination_country": data.get("destination_country", "us"),
                "production_days": top_source.get("lead_time_days", {}).get("typical", 30),
                "shipping_method": data.get("shipping_method", "sea_freight"),
                "weight_kg": data.get("product_weight_kg", 1.0),
            },
            "meta": {},
            "error": None,
        })

        # Module 5: Cost negotiation planning
        results["negotiation"] = plan_negotiation({
            "status": "success",
            "data": {
                "retail_price": data.get("target_price", 30),
                "target_margin": data.get("target_margin", 0.50),
                "current_quote": top_source.get("estimated_unit_cost", 10),
                "order_quantity": data.get("target_quantity", 200),
                "supplier_type": top_source.get("type", "manufacturer"),
            },
            "meta": {},
            "error": None,
        })

        elapsed = time.monotonic() - start

        output = format_output(
            engine_name=self.ENGINE_NAME,
            results=results,
            data=data,
            elapsed=elapsed,
        )

        validation = validate_result(output)
        if not validation["valid"]:
            return {
                "status": "fail", "data": None,
                "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": _now()},
                "error": {"reason": validation["reason"]},
            }

        return output


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
