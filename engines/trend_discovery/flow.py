"""TrendDiscovery Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Search Trend Analyzer → Social Signal Tracker → Marketplace Scanner → Synthesis Engine → Memory Writer → Output

Engine contract:
  Input:  {status, data: {category, search_data, social_data, marketplace_data}, meta, error}
  Output: {status, data: {trends, emerging_niches, hot_products}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .search_trend_analyzer import analyze_search_trends
from .social_signal_tracker import track_social_signals
from .marketplace_scanner import scan_marketplace
from .synthesis_engine import synthesize_signals
from .memory_reader import read_past_results
from .memory_writer import write_result


class TrendDiscoveryEngine:
    """TrendDiscovery Engine — orchestrator only, no logic."""

    ENGINE_NAME = "trend_discovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full trend discovery pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            TrendDiscoveryOutput dict.
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
        search_data = data.get("search_data", {})
        social_data = data.get("social_data", {})
        marketplace_data = data.get("marketplace_data", {})

        if not category:
            return self._fail("Category is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Analyze search trend data ----
        search_trend_analyzer_result = analyze_search_trends(
            category=category, search_data=search_data, social_data=social_data, marketplace_data=marketplace_data,
        )
        if search_trend_analyzer_result.get("status") == "error":
            return self._fail(
                f"Analyze search trend data failed: {search_trend_analyzer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        search_trend_analyzer_data = search_trend_analyzer_result.get("result", {})

        # ---- Stage 3: Track social media signals ----
        social_signal_tracker_result = track_social_signals(
            category=category, search_data=search_data, social_data=social_data, marketplace_data=marketplace_data, search_trend_analyzer_data=search_trend_analyzer_data,
        )
        if social_signal_tracker_result.get("status") == "error":
            return self._fail(
                f"Track social media signals failed: {social_signal_tracker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        social_signal_tracker_data = social_signal_tracker_result.get("result", {})

        # ---- Stage 4: Scan marketplace for emerging products ----
        marketplace_scanner_result = scan_marketplace(
            category=category, search_data=search_data, social_data=social_data, marketplace_data=marketplace_data, search_trend_analyzer_data=search_trend_analyzer_data, social_signal_tracker_data=social_signal_tracker_data,
        )
        if marketplace_scanner_result.get("status") == "error":
            return self._fail(
                f"Scan marketplace for emerging products failed: {marketplace_scanner_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        marketplace_scanner_data = marketplace_scanner_result.get("result", {})

        # ---- Stage 5: Synthesize signals into trend insights ----
        synthesis_engine_result = synthesize_signals(
            category=category, search_data=search_data, social_data=social_data, marketplace_data=marketplace_data, search_trend_analyzer_data=search_trend_analyzer_data, social_signal_tracker_data=social_signal_tracker_data, marketplace_scanner_data=marketplace_scanner_data,
        )
        if synthesis_engine_result.get("status") == "error":
            return self._fail(
                f"Synthesize signals into trend insights failed: {synthesis_engine_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        synthesis_engine_data = synthesis_engine_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "trends": synthesis_engine_data.get("trends", []),
                "emerging_niches": synthesis_engine_data.get("emerging_niches", []),
                "hot_products": synthesis_engine_data.get("hot_products", []),
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
