"""Video Marketing Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Memory Reader → Script Writer → Storyboard Planner →
  Platform Optimizer → Performance Estimator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {product, platform, video_type, duration_seconds, brand_voice}, meta, error}
  Output: {status, data: {script, storyboard, platform_specs, estimated_engagement}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .script_writer import write_script
from .storyboard_planner import plan_storyboard
from .platform_optimizer import optimize_for_platform
from .performance_estimator import estimate_performance
from .memory_reader import read_past_videos
from .memory_writer import write_video_result


class VideoMarketingEngine:
    """Video Marketing Engine — orchestrator only, no logic."""

    ENGINE_NAME = "video_marketing"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full video marketing pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            VideoOutput dict.
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

        product = data.get("product", {})
        platform = str(data.get("platform", "youtube"))
        video_type = str(data.get("video_type", "product_demo"))
        duration_seconds = int(data.get("duration_seconds", 30))
        brand_voice = data.get("brand_voice", {})

        if not product:
            return self._fail("product is required", 0.0)

        # ---- Stage 1: Read past videos (non-blocking) ----
        _past = read_past_videos(limit=5)

        # ---- Stage 2: Script Writer ----
        script_result = write_script(
            product=product,
            video_type=video_type,
            duration_seconds=duration_seconds,
            brand_voice=brand_voice,
        )
        if script_result.get("status") == "error":
            return self._fail(
                f"Script writing failed: {script_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        script = script_result.get("script", {})

        # ---- Stage 3: Storyboard Planner ----
        storyboard_result = plan_storyboard(
            script=script,
            product=product,
            video_type=video_type,
            duration_seconds=duration_seconds,
        )
        if storyboard_result.get("status") == "error":
            return self._fail(
                f"Storyboard planning failed: {storyboard_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        storyboard = storyboard_result.get("storyboard", [])

        # ---- Stage 4: Platform Optimizer ----
        platform_result = optimize_for_platform(
            platform=platform,
            duration_seconds=duration_seconds,
            product=product,
        )
        if platform_result.get("status") == "error":
            return self._fail(
                f"Platform optimization failed: {platform_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        platform_specs = platform_result.get("platform_specs", {})

        # ---- Stage 5: Performance Estimator ----
        perf_result = estimate_performance(
            platform=platform,
            video_type=video_type,
            duration_seconds=duration_seconds,
            script_quality=script,
        )
        if perf_result.get("status") == "error":
            return self._fail(
                f"Performance estimation failed: {perf_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        engagement = perf_result.get("engagement", {})

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_video_result(
            script=script,
            storyboard=storyboard,
            platform=platform,
            engagement=engagement,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "script": script,
                "storyboard": storyboard,
                "platform_specs": platform_specs,
                "estimated_engagement": engagement,
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
