"""Competitor Social Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Profile Tracker → Engagement Analyzer → Content Classifier →
  Benchmark Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {competitors, platforms, our_metrics}, meta, error}
  Output: {status, data: {competitor_profiles, engagement_comparison, content_breakdown, benchmarks, recommendations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .profile_tracker import track_profiles
from .engagement_analyzer import analyze_engagement
from .content_classifier import classify_content
from .benchmark_builder import build_benchmarks
from .memory_reader import read_past_social
from .memory_writer import write_social_result


class CompetitorSocialEngine:
    """Competitor Social Engine — orchestrator only, no logic."""

    ENGINE_NAME = "competitor_social"

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
        platforms = data.get("platforms", ["instagram", "tiktok", "facebook"])
        our_metrics = data.get("our_metrics", {})

        if not competitors:
            return self._fail("Competitors list is required", 0.0)

        _past = read_past_social(limit=5)

        # Stage 1: Profile Tracker
        profile_result = track_profiles(competitors=competitors, platforms=platforms)
        if profile_result.get("status") == "error":
            return self._fail(f"Profile tracking failed: {profile_result.get('error', 'unknown')}", time.monotonic() - start)
        competitor_profiles = profile_result.get("competitor_profiles", [])

        # Stage 2: Engagement Analyzer
        eng_result = analyze_engagement(
            competitor_profiles=competitor_profiles, our_metrics=our_metrics, platforms=platforms,
        )
        if eng_result.get("status") == "error":
            return self._fail(f"Engagement analysis failed: {eng_result.get('error', 'unknown')}", time.monotonic() - start)
        engagement_comparison = eng_result.get("engagement_comparison", [])

        # Stage 3: Content Classifier
        content_result = classify_content(competitor_profiles=competitor_profiles, competitors=competitors)
        if content_result.get("status") == "error":
            return self._fail(f"Content classification failed: {content_result.get('error', 'unknown')}", time.monotonic() - start)
        content_breakdown = content_result.get("content_breakdown", [])

        # Stage 4: Benchmark Builder
        bench_result = build_benchmarks(
            competitor_profiles=competitor_profiles,
            engagement_comparison=engagement_comparison,
            our_metrics=our_metrics,
        )
        if bench_result.get("status") == "error":
            return self._fail(f"Benchmark building failed: {bench_result.get('error', 'unknown')}", time.monotonic() - start)
        benchmarks = bench_result.get("benchmarks", [])
        recommendations = bench_result.get("recommendations", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_social_result(
            competitor_profiles=competitor_profiles, engagement_comparison=engagement_comparison,
            benchmarks=benchmarks, recommendations=recommendations,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "competitor_profiles": competitor_profiles,
                "engagement_comparison": engagement_comparison,
                "content_breakdown": content_breakdown,
                "benchmarks": benchmarks,
                "recommendations": recommendations,
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
