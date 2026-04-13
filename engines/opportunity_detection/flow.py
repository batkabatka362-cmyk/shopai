"""Opportunity Detection Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Gap Finder → Demand Matcher →
  Feasibility Scorer → Priority Ranker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {market_data, competition, trends}, meta, error}
  Output: {status, data: {opportunities, top_opportunity}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .gap_finder import find_gaps
from .demand_matcher import match_demand
from .feasibility_scorer import score_feasibility
from .priority_ranker import rank_priorities
from .memory_reader import read_past_detections
from .memory_writer import write_detection_result


class OpportunityDetectionEngine:
    """Opportunity Detection Engine — orchestrator only, no logic."""

    ENGINE_NAME = "opportunity_detection"

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

        market_data = data.get("market_data", {})
        competition = data.get("competition", [])
        trends = data.get("trends", [])

        if not market_data:
            return self._fail("market_data is required", 0.0)

        _past = read_past_detections(limit=5)

        gap_result = find_gaps(market_data=market_data, competition=competition)
        if gap_result.get("status") == "error":
            return self._fail(f"Gap finding failed: {gap_result.get('error')}", time.monotonic() - start)
        gaps = gap_result.get("gaps", [])

        demand_result = match_demand(gaps=gaps, trends=trends)
        if demand_result.get("status") == "error":
            return self._fail(f"Demand matching failed: {demand_result.get('error')}", time.monotonic() - start)
        matched = demand_result.get("matched", [])

        feas_result = score_feasibility(matched_gaps=matched)
        if feas_result.get("status") == "error":
            return self._fail(f"Feasibility scoring failed: {feas_result.get('error')}", time.monotonic() - start)
        scored = feas_result.get("scored", [])

        rank_result = rank_priorities(scored_gaps=scored)
        if rank_result.get("status") == "error":
            return self._fail(f"Priority ranking failed: {rank_result.get('error')}", time.monotonic() - start)
        opportunities = rank_result.get("ranked", [])
        top_opportunity = rank_result.get("top_opportunity", {})

        _write = write_detection_result(opportunities=opportunities, top_opportunity=top_opportunity)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "opportunities": opportunities,
                "top_opportunity": top_opportunity,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
