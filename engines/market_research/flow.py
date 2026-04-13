"""MarketResearch Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Size Estimator → Gap Analyzer → Trend Synthesizer → Verdict Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {category, competitors, trends, search_data}, meta, error}
  Output: {status, data: {market_size, gaps, trends, verdict}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .size_estimator import estimate_size
from .gap_analyzer import analyze_gaps
from .trend_synthesizer import synthesize_trends
from .verdict_builder import build_verdict
from .memory_reader import read_past_results
from .memory_writer import write_result


class MarketResearchEngine:
    """MarketResearch Engine — orchestrator only, no logic."""

    ENGINE_NAME = "market_research"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full market research pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            MarketResearchOutput dict.
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

        category = str(data.get("category", ""))
        competitors = data.get("competitors", [])
        trends = data.get("trends", [])
        search_data = data.get("search_data", {})

        if not category:
            return self._fail("Category is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Estimate total addressable market ----
        size_estimator_result = estimate_size(
            category=category, competitors=competitors, trends=trends, search_data=search_data,
        )
        if size_estimator_result.get("status") == "error":
            return self._fail(
                f"Estimate total addressable market failed: {size_estimator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        size_estimator_data = size_estimator_result.get("result", {})

        # ---- Stage 3: Analyze market gaps ----
        gap_analyzer_result = analyze_gaps(
            category=category, competitors=competitors, trends=trends, search_data=search_data, size_estimator_data=size_estimator_data,
        )
        if gap_analyzer_result.get("status") == "error":
            return self._fail(
                f"Analyze market gaps failed: {gap_analyzer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        gap_analyzer_data = gap_analyzer_result.get("result", {})

        # ---- Stage 4: Synthesize market trends ----
        trend_synthesizer_result = synthesize_trends(
            category=category, competitors=competitors, trends=trends, search_data=search_data, size_estimator_data=size_estimator_data, gap_analyzer_data=gap_analyzer_data,
        )
        if trend_synthesizer_result.get("status") == "error":
            return self._fail(
                f"Synthesize market trends failed: {trend_synthesizer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        trend_synthesizer_data = trend_synthesizer_result.get("result", {})

        # ---- Stage 5: Build market entry verdict ----
        verdict_builder_result = build_verdict(
            category=category, competitors=competitors, trends=trends, search_data=search_data, size_estimator_data=size_estimator_data, gap_analyzer_data=gap_analyzer_data, trend_synthesizer_data=trend_synthesizer_data,
        )
        if verdict_builder_result.get("status") == "error":
            return self._fail(
                f"Build market entry verdict failed: {verdict_builder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        verdict_builder_data = verdict_builder_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "market_size": verdict_builder_data.get("market_size", {}),
                "gaps": verdict_builder_data.get("gaps", []),
                "trends": verdict_builder_data.get("trends", []),
                "verdict": verdict_builder_data.get("verdict", {}),
        }
        _write_result = write_result(output_data=output_data)

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": output_data,
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
