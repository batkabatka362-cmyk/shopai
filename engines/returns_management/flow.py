"""Returns Management Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Return Processor → Reason Analyzer →
  Fraud Detector → Cost Calculator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {returns, return_policy}, meta, error}
  Output: {status, data: {processed, reason_breakdown, fraud_flags, total_cost, return_rate}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .return_processor import process_returns
from .reason_analyzer import analyze_reasons
from .fraud_detector import detect_fraud
from .cost_calculator import calculate_costs
from .refund_applier import apply_refunds
from .return_applier import (
    apply_return_tags,
    enqueue_return_tags_for_approval,
)
from .memory_reader import read_past_returns
from .memory_writer import write_returns_result
from engines._shopify_hydrator import hydrate


class ReturnsManagementEngine:
    """Returns Management Engine — orchestrator only, no logic."""

    ENGINE_NAME = "returns_management"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full returns management pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ReturnsOutput dict.
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

        returns = data.get("returns", [])
        return_policy = data.get("return_policy", {})

        # Auto-hydrate returns from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        returns = hydrate(
            supplied=returns if isinstance(returns, list) else [],
            capability_name="SHOPIFY_LIST_RETURNS",
            list_field="returns",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not returns:
            return self._fail("Returns list is required", 0.0)

        # ---- Stage 1: Read past returns (non-blocking) ----
        _past = read_past_returns(limit=5)

        # ---- Stage 2: Return Processor ----
        processor_result = process_returns(
            returns=returns,
            return_policy=return_policy,
        )
        if processor_result.get("status") == "error":
            return self._fail(
                f"Return processing failed: {processor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        processed = processor_result.get("processed", [])

        # ---- Stage 3: Reason Analyzer ----
        reason_result = analyze_reasons(
            returns=returns,
            processed=processed,
        )
        if reason_result.get("status") == "error":
            return self._fail(
                f"Reason analysis failed: {reason_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        reason_breakdown = reason_result.get("reason_breakdown", [])

        # ---- Stage 4: Fraud Detector ----
        fraud_result = detect_fraud(
            returns=returns,
            processed=processed,
        )
        if fraud_result.get("status") == "error":
            return self._fail(
                f"Fraud detection failed: {fraud_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        fraud_flags = fraud_result.get("fraud_flags", [])

        # ---- Stage 5: Cost Calculator ----
        cost_result = calculate_costs(
            processed=processed,
            return_policy=return_policy,
        )
        if cost_result.get("status") == "error":
            return self._fail(
                f"Cost calculation failed: {cost_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        total_cost = cost_result.get("cost_breakdown", {})

        # ---- Stage 6: Compute return rate ----
        total_returns = len(returns)
        eligible_count = sum(1 for p in processed if p.get("eligible", False))
        return_rate = round(eligible_count / total_returns, 3) if total_returns > 0 else 0.0

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_returns_result(
            processed=processed,
            reason_breakdown=reason_breakdown,
            fraud_flags=fraud_flags,
            total_cost=total_cost,
            return_rate=return_rate,
        )

        # ---- Stage 7.5: Order-tag writeback (opt-in) ----
        # Default OFF. Two opt-in modes:
        #
        #   data.apply_return_tags=True + data.require_approval=False
        #     → SHOPIFY_TAG_ORDER immediately per processed return
        #   data.apply_return_tags=True + data.require_approval=True
        #     → enqueue per-return proposals to core.approval
        #
        # Both paths share the same decision-to-tag mapping
        # (approved → shopai-return-approved, rejected →
        # shopai-return-rejected, fraud-flagged → +
        # shopai-return-fraud-flag). Refund issuance is NOT
        # part of this writeback — tagging is the safer first
        # cut; ``refundCreate`` needs transaction-parent lookups
        # the engine doesn't carry yet.
        tag_apply_results: list[dict[str, Any]] = []
        if data.get("apply_return_tags") is True:
            if data.get("require_approval") is True:
                tag_apply_results = enqueue_return_tags_for_approval(
                    processed=processed,
                    fraud_flags=fraud_flags,
                )
            else:
                tag_apply_results = apply_return_tags(
                    processed=processed,
                    fraud_flags=fraud_flags,
                )

        # ---- Stage 7.6: Refund applier (Wave 101) ----
        # Opt-in via data.apply_refunds=True. Default OFF -- this
        # is real money out. Behind 5 safety gates:
        #   1. status=approved
        #   2. refund_amount > 0
        #   3. refund_amount <= cap (env or data.max_refund_usd)
        #   4. fraud_flags.risk_score < cap (env or
        #      data.max_fraud_risk)
        #   5. order has eligible parent transaction
        refund_apply_results: list[dict[str, Any]] = []
        if data.get("apply_refunds") is True:
            refund_apply_results = apply_refunds(
                processed=processed,
                fraud_flags=fraud_flags,
                max_amount=data.get("max_refund_usd"),
                max_fraud_risk=data.get("max_fraud_risk"),
            )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "processed": processed,
                "reason_breakdown": reason_breakdown,
                "fraud_flags": fraud_flags,
                "total_cost": total_cost,
                "return_rate": return_rate,
                # Stage 7.5 output — one entry per processed return
                # when opt-in is on; empty list otherwise.
                "tag_apply_results": tag_apply_results,
                # Stage 7.6 (Wave 101) output -- per-return refund
                # results when data.apply_refunds=True.
                "refund_apply_results": refund_apply_results,
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
