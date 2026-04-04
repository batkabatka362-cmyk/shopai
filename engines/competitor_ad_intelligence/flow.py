"""Competitor Ad Intelligence Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Ad Detector → Spend Estimator → Creative Analyzer →
  Strategy Reporter → Memory Writer → Output

Engine contract:
  Input:  {status, data: {competitors, platforms, period}, meta, error}
  Output: {status, data: {ads_detected, spend_estimates, creative_patterns, strategy_report, our_gaps}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .ad_detector import detect_ads
from .spend_estimator import estimate_spend
from .creative_analyzer import analyze_creatives
from .strategy_reporter import report_strategy
from .memory_reader import read_past_ad_intel
from .memory_writer import write_ad_intel_result


class CompetitorAdIntelligenceEngine:
    """Competitor Ad Intelligence Engine — orchestrator only, no logic."""

    ENGINE_NAME = "competitor_ad_intelligence"

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

        competitors = data.get("competitors", [])
        platforms = data.get("platforms", ["facebook", "google", "tiktok"])
        period = str(data.get("period", "30d"))

        if not competitors:
            return self._fail("Competitors list is required", 0.0)

        _past = read_past_ad_intel(limit=5)

        # Stage 1: Ad Detector
        detect_result = detect_ads(competitors=competitors, platforms=platforms, period=period)
        if detect_result.get("status") == "error":
            return self._fail(f"Ad detection failed: {detect_result.get('error', 'unknown')}", time.monotonic() - start)
        ads_detected = detect_result.get("ads_detected", [])

        # Stage 2: Spend Estimator
        spend_result = estimate_spend(ads_detected=ads_detected)
        if spend_result.get("status") == "error":
            return self._fail(f"Spend estimation failed: {spend_result.get('error', 'unknown')}", time.monotonic() - start)
        spend_estimates = spend_result.get("spend_estimates", [])

        # Stage 3: Creative Analyzer
        creative_result = analyze_creatives(ads_detected=ads_detected)
        if creative_result.get("status") == "error":
            return self._fail(f"Creative analysis failed: {creative_result.get('error', 'unknown')}", time.monotonic() - start)
        creative_patterns = creative_result.get("creative_patterns", [])

        # Stage 4: Strategy Reporter
        strategy_result = report_strategy(
            ads_detected=ads_detected, spend_estimates=spend_estimates,
            creative_patterns=creative_patterns,
        )
        if strategy_result.get("status") == "error":
            return self._fail(f"Strategy reporting failed: {strategy_result.get('error', 'unknown')}", time.monotonic() - start)
        strategy_report = strategy_result.get("strategy_report", {})
        our_gaps = strategy_result.get("our_gaps", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_ad_intel_result(
            ads_detected=ads_detected, spend_estimates=spend_estimates,
            creative_patterns=creative_patterns, strategy_report=strategy_report,
            our_gaps=our_gaps,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "ads_detected": ads_detected,
                "spend_estimates": spend_estimates,
                "creative_patterns": creative_patterns,
                "strategy_report": strategy_report,
                "our_gaps": our_gaps,
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
