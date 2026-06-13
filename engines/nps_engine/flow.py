"""NPS Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Survey Manager → Score Calculator → Segment Analyzer →
  Trend Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {responses, segments}, meta, error}
  Output: {status, data: {nps_score, promoters_pct, passives_pct, detractors_pct, segment_breakdown, trends, action_items}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .survey_manager import manage_surveys
from .score_calculator import calculate_score
from .segment_analyzer import analyze_segments
from .trend_tracker import track_trends
from .memory_reader import read_past_nps
from .memory_writer import write_nps_result


class NpsEngine:
    """NPS Engine — orchestrator only, no logic."""

    ENGINE_NAME = "nps_engine"

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

        responses = data.get("responses", [])
        segments = data.get("segments", [])

        if not responses:
            return self._fail("Responses list is required", 0.0)

        _past = read_past_nps(limit=5)

        # Stage 1: Survey Manager
        survey_result = manage_surveys(responses=responses)
        if survey_result.get("status") == "error":
            return self._fail(f"Survey management failed: {survey_result.get('error', 'unknown')}", time.monotonic() - start)
        validated_responses = survey_result.get("validated_responses", [])

        # Stage 2: Score Calculator
        score_result = calculate_score(validated_responses=validated_responses)
        if score_result.get("status") == "error":
            return self._fail(f"Score calculation failed: {score_result.get('error', 'unknown')}", time.monotonic() - start)
        nps_score = score_result.get("nps_score", 0.0)
        promoters_pct = score_result.get("promoters_pct", 0.0)
        passives_pct = score_result.get("passives_pct", 0.0)
        detractors_pct = score_result.get("detractors_pct", 0.0)

        # Stage 3: Segment Analyzer
        seg_result = analyze_segments(validated_responses=validated_responses, segments=segments)
        if seg_result.get("status") == "error":
            return self._fail(f"Segment analysis failed: {seg_result.get('error', 'unknown')}", time.monotonic() - start)
        segment_breakdown = seg_result.get("segment_breakdown", [])

        # Stage 4: Trend Tracker
        trend_result = track_trends(
            validated_responses=validated_responses, nps_score=nps_score,
            segment_breakdown=segment_breakdown,
        )
        if trend_result.get("status") == "error":
            return self._fail(f"Trend tracking failed: {trend_result.get('error', 'unknown')}", time.monotonic() - start)
        trends = trend_result.get("trends", [])
        action_items = trend_result.get("action_items", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_nps_result(
            nps_score=nps_score, segment_breakdown=segment_breakdown,
            trends=trends, action_items=action_items,
        )

        # Phase 7: optional NPS-tier tag apply. Opt-in via
        # data.apply_nps_tags=True. Tags each respondent with
        # their NPS tier (promoter/passive/detractor) via
        # SHOPIFY_TAG_CUSTOMER.
        tagged_nps: list[dict[str, Any]] = []
        if bool(data.get("apply_nps_tags")):
            try:
                from .tag_applier import apply_nps_tags
                tagged_nps = apply_nps_tags(validated_responses)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "nps_engine: apply loop raised: %s", exc,
                )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "nps_score": nps_score,
                "promoters_pct": promoters_pct,
                "passives_pct": passives_pct,
                "detractors_pct": detractors_pct,
                "segment_breakdown": segment_breakdown,
                "trends": trends,
                "action_items": action_items,
                "tagged_nps": tagged_nps,
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
