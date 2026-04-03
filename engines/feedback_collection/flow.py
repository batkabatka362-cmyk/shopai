"""Feedback Collection Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Survey Builder → Channel Aggregator →
  Response Parser → Insight Extractor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {feedback_sources, period, filters}, meta, error}
  Output: {status, data: {feedback, insights, sentiment_summary, action_items}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .survey_builder import build_surveys
from .channel_aggregator import aggregate_channels
from .response_parser import parse_responses
from .insight_extractor import extract_insights
from .memory_reader import read_past_feedback
from .memory_writer import write_feedback_result


class FeedbackCollectionEngine:
    """Feedback Collection Engine — orchestrator only, no logic."""

    ENGINE_NAME = "feedback_collection"

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

        feedback_sources = data.get("feedback_sources", [])
        period = str(data.get("period", "30d"))
        filters = data.get("filters", {})

        if not feedback_sources:
            return self._fail("feedback_sources list is required", 0.0)

        _past = read_past_feedback(limit=5)

        # ---- Survey Builder ----
        survey_result = build_surveys(feedback_sources=feedback_sources, filters=filters)
        if survey_result.get("status") == "error":
            return self._fail(f"Survey building failed: {survey_result.get('error')}", time.monotonic() - start)

        # ---- Channel Aggregator ----
        agg_result = aggregate_channels(feedback_sources=feedback_sources, period=period)
        if agg_result.get("status") == "error":
            return self._fail(f"Channel aggregation failed: {agg_result.get('error')}", time.monotonic() - start)
        feedback = agg_result.get("feedback", [])

        # ---- Response Parser ----
        parse_result = parse_responses(feedback=feedback)
        if parse_result.get("status") == "error":
            return self._fail(f"Response parsing failed: {parse_result.get('error')}", time.monotonic() - start)
        sentiment_summary = parse_result.get("sentiment_summary", {})

        # ---- Insight Extractor ----
        insight_result = extract_insights(sentiment_summary=sentiment_summary, feedback=feedback)
        if insight_result.get("status") == "error":
            return self._fail(f"Insight extraction failed: {insight_result.get('error')}", time.monotonic() - start)
        insights = insight_result.get("insights", [])
        action_items = insight_result.get("action_items", [])

        _write = write_feedback_result(
            sentiment_summary=sentiment_summary, insights_count=len(insights),
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "feedback": feedback,
                "insights": insights,
                "sentiment_summary": sentiment_summary,
                "action_items": action_items,
            },
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
