"""Affiliate Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Program Designer → Partner Evaluator →
  Commission Calculator → Performance Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, sales_data, partners, commission_rules}, meta, error}
  Output: {status, data: {program, partner_scores, commissions_due, top_performers, program_health}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .program_designer import design_program
from .partner_evaluator import evaluate_partners
from .commission_calculator import calculate_commissions
from .performance_tracker import track_performance
from .memory_reader import read_past_affiliate_runs
from .memory_writer import write_affiliate_result


class AffiliateEngine:
    """Affiliate Engine — orchestrator only, no logic."""

    ENGINE_NAME = "affiliate"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full affiliate pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            AffiliateOutput dict.
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
        sales_data = data.get("sales_data", [])
        partners = data.get("partners", [])
        commission_rules = data.get("commission_rules", [])

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past affiliate runs (non-blocking) ----
        _past = read_past_affiliate_runs(limit=5)

        # ---- Stage 2: Program Designer ----
        program_result = design_program(
            products=products,
            commission_rules=commission_rules,
        )
        if program_result.get("status") == "error":
            return self._fail(
                f"Program design failed: {program_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        program = program_result.get("program", {})

        # ---- Stage 3: Partner Evaluator ----
        evaluator_result = evaluate_partners(
            partners=partners,
            sales_data=sales_data,
        )
        if evaluator_result.get("status") == "error":
            return self._fail(
                f"Partner evaluation failed: {evaluator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        partner_scores = evaluator_result.get("partner_scores", [])

        # ---- Stage 4: Commission Calculator ----
        commission_result = calculate_commissions(
            sales_data=sales_data,
            partners=partners,
            commission_rules=commission_rules,
            program=program,
        )
        if commission_result.get("status") == "error":
            return self._fail(
                f"Commission calculation failed: {commission_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        commissions_due = commission_result.get("commissions_due", [])

        # ---- Stage 5: Performance Tracker ----
        performance_result = track_performance(
            partners=partners,
            sales_data=sales_data,
            partner_scores=partner_scores,
        )
        if performance_result.get("status") == "error":
            return self._fail(
                f"Performance tracking failed: {performance_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        top_performers = performance_result.get("top_performers", [])

        # ---- Stage 6: Compute program health ----
        total_partners = len(partners)
        active_partners = sum(
            1 for ps in partner_scores if ps.get("quality_tier") != "inactive"
        )
        total_commission = sum(
            float(c.get("commission_amount", 0.0)) for c in commissions_due
        )
        total_partner_revenue = sum(
            float(c.get("period_sales", 0.0)) for c in commissions_due
        )
        avg_partner_revenue = (
            round(total_partner_revenue / total_partners, 2)
            if total_partners > 0 else 0.0
        )
        program_roi = (
            round((total_partner_revenue - total_commission) / total_commission, 2)
            if total_commission > 0 else 0.0
        )

        program_health: dict[str, Any] = {
            "total_partners": total_partners,
            "active_partners": active_partners,
            "total_commission_paid": round(total_commission, 2),
            "avg_partner_revenue": avg_partner_revenue,
            "program_roi": program_roi,
        }

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_affiliate_result(
            program=program,
            partner_scores=partner_scores,
            commissions_due=commissions_due,
            program_health=program_health,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "program": program,
                "partner_scores": partner_scores,
                "commissions_due": commissions_due,
                "top_performers": top_performers,
                "program_health": program_health,
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
