"""Payment Optimization Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Fee Analyzer → Routing Optimizer → Checkout Optimizer →
  Fraud Cost Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {transactions, payment_methods, fees}, meta, error}
  Output: {status, data: {fee_analysis, routing_recommendations, total_savings}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .fee_analyzer import analyze_fees
from .routing_optimizer import optimize_routing
from .checkout_optimizer import optimize_checkout
from .fraud_cost_tracker import track_fraud_costs
from .memory_reader import read_past_payments
from .memory_writer import write_payment_result


class PaymentOptimizationEngine:
    """Payment Optimization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "payment_optimization"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full payment optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            PaymentOutput dict.
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

        transactions = data.get("transactions", [])
        payment_methods = data.get("payment_methods", [])
        fees = data.get("fees", [])

        if not transactions:
            return self._fail("Transaction list is required", 0.0)

        # ---- Stage 1: Read past payments (non-blocking) ----
        _past = read_past_payments(limit=5)

        # ---- Stage 2: Fee Analyzer ----
        fee_result = analyze_fees(
            transactions=transactions,
            payment_methods=payment_methods,
        )
        if fee_result.get("status") == "error":
            return self._fail(
                f"Fee analysis failed: {fee_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        fee_analyses = fee_result.get("analyses", [])

        # ---- Stage 3: Routing Optimizer ----
        routing_result = optimize_routing(
            fee_analyses=fee_analyses,
            fees=fees,
            transactions=transactions,
        )
        if routing_result.get("status") == "error":
            return self._fail(
                f"Routing optimization failed: {routing_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        routing_recommendations = routing_result.get("recommendations", [])

        # ---- Stage 4: Checkout Optimizer ----
        checkout_result = optimize_checkout(
            transactions=transactions,
            payment_methods=payment_methods,
        )
        if checkout_result.get("status") == "error":
            return self._fail(
                f"Checkout optimization failed: {checkout_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        _checkout_optimizations = checkout_result.get("optimizations", [])

        # ---- Stage 5: Fraud Cost Tracker ----
        fraud_result = track_fraud_costs(
            transactions=transactions,
            fees=fees,
        )
        if fraud_result.get("status") == "error":
            return self._fail(
                f"Fraud cost tracking failed: {fraud_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        _fraud_costs = fraud_result.get("fraud_costs", {})

        # ---- Stage 6: Calculate total savings ----
        total_savings = round(
            sum(r.get("monthly_savings", 0.0) for r in routing_recommendations), 2,
        )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_payment_result(
            fee_analysis=fee_analyses,
            routing_recommendations=routing_recommendations,
            total_savings=total_savings,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "fee_analysis": fee_analyses,
                "routing_recommendations": routing_recommendations,
                "total_savings": total_savings,
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
