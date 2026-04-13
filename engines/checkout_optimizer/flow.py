"""Checkout Optimizer Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Checkout Config/Analytics/Payment Methods → Friction Analyzer →
  Form Optimizer → Trust Builder → Payment Optimizer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {checkout_config, analytics, payment_methods}, meta, error}
  Output: {status, data: {friction_points, optimizations, trust_signals, payment_recommendations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .friction_analyzer import analyze_friction
from .form_optimizer import optimize_forms
from .trust_builder import build_trust_signals
from .payment_optimizer import optimize_payments
from .memory_reader import read_past_optimizations
from .memory_writer import write_optimization_result


class CheckoutOptimizerEngine:
    """Checkout Optimizer Engine — orchestrator only, no logic."""

    ENGINE_NAME = "checkout_optimizer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full checkout optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CheckoutOptimizerOutput dict.
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

        checkout_config = data.get("checkout_config", {})
        analytics = data.get("analytics", {})
        payment_methods = data.get("payment_methods", [])

        if not isinstance(checkout_config, dict):
            return self._fail("Checkout config must be a dict", 0.0)

        # ---- Stage 1: Read past optimizations (non-blocking) ----
        _past = read_past_optimizations(limit=5)

        # ---- Stage 2: Friction Analyzer ----
        friction_result = analyze_friction(
            checkout_config=checkout_config,
            analytics=analytics,
        )
        if friction_result.get("status") == "error":
            return self._fail(
                f"Friction analysis failed: {friction_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        friction_points = friction_result.get("friction_points", [])

        # ---- Stage 3: Form Optimizer ----
        form_result = optimize_forms(
            checkout_config=checkout_config,
            friction_points=friction_points,
        )
        if form_result.get("status") == "error":
            return self._fail(
                f"Form optimization failed: {form_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        form_optimizations = form_result.get("optimizations", [])

        # ---- Stage 4: Trust Builder ----
        trust_result = build_trust_signals(
            checkout_config=checkout_config,
            analytics=analytics,
            payment_methods=payment_methods,
        )
        if trust_result.get("status") == "error":
            return self._fail(
                f"Trust signal building failed: {trust_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        trust_signals = trust_result.get("trust_signals", [])

        # ---- Stage 5: Payment Optimizer ----
        payment_result = optimize_payments(
            payment_methods=payment_methods,
            checkout_config=checkout_config,
            analytics=analytics,
        )
        if payment_result.get("status") == "error":
            return self._fail(
                f"Payment optimization failed: {payment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        payment_recommendations = payment_result.get("recommendations", [])

        # ---- Stage 6: Build unified optimizations list ----
        optimizations: list[dict[str, Any]] = []
        for opt in form_optimizations:
            optimizations.append({
                "type": "form",
                "recommendation": str(opt.get("recommendation", "")),
                "expected_lift": float(opt.get("expected_lift", 0.0)),
            })

        # Add friction-based optimizations
        for fp in friction_points:
            if fp.get("severity") in ("critical", "high"):
                optimizations.append({
                    "type": "friction",
                    "recommendation": f"Fix: {fp.get('issue', '')}",
                    "expected_lift": min(float(fp.get("drop_off_rate", 0.0)) * 0.5, 0.15),
                })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_optimization_result(
            friction_points=friction_points,
            optimizations=optimizations,
            trust_signals=trust_signals,
            payment_recommendations=payment_recommendations,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "friction_points": friction_points,
                "optimizations": optimizations,
                "trust_signals": trust_signals,
                "payment_recommendations": payment_recommendations,
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
