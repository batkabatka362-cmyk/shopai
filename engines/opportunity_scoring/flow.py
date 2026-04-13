"""Opportunity Scoring Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Criteria Evaluator → Risk Assessor →
  ROI Estimator → Composite Scorer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {opportunities, criteria, risk_tolerance}, meta, error}
  Output: {status, data: {scored, ranked_list, recommended}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .criteria_evaluator import evaluate_criteria
from .risk_assessor import assess_risk
from .roi_estimator import estimate_roi
from .composite_scorer import compute_composite
from .memory_reader import read_past_scorings
from .memory_writer import write_scoring_result


class OpportunityScoringEngine:
    """Opportunity Scoring Engine — orchestrator only, no logic."""

    ENGINE_NAME = "opportunity_scoring"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

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

        opportunities = data.get("opportunities", [])
        criteria = data.get("criteria", {})
        risk_tolerance = str(data.get("risk_tolerance", "moderate"))

        if not opportunities:
            return self._fail("Opportunities list is required", 0.0)

        _past = read_past_scorings(limit=5)

        eval_result = evaluate_criteria(opportunities=opportunities, criteria=criteria)
        if eval_result.get("status") == "error":
            return self._fail(f"Criteria evaluation failed: {eval_result.get('error')}", time.monotonic() - start)
        evaluated = eval_result.get("evaluated", [])

        risk_result = assess_risk(evaluated=evaluated, risk_tolerance=risk_tolerance)
        if risk_result.get("status") == "error":
            return self._fail(f"Risk assessment failed: {risk_result.get('error')}", time.monotonic() - start)
        assessed = risk_result.get("assessed", [])

        roi_result = estimate_roi(assessed=assessed)
        if roi_result.get("status") == "error":
            return self._fail(f"ROI estimation failed: {roi_result.get('error')}", time.monotonic() - start)
        estimated = roi_result.get("estimated", [])

        composite_result = compute_composite(estimated=estimated)
        if composite_result.get("status") == "error":
            return self._fail(f"Composite scoring failed: {composite_result.get('error')}", time.monotonic() - start)

        scored = composite_result.get("scored", [])
        ranked_list = composite_result.get("ranked_list", [])
        recommended = composite_result.get("recommended", {})

        _write = write_scoring_result(scored=scored, recommended=recommended)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {"scored": scored, "ranked_list": ranked_list, "recommended": recommended},
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
