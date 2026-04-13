"""Feedback Processing Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Feedback Data → Categorizer → Priority Scorer → Trend Spotter →
  Action Recommender → Memory Writer → Output

Engine contract:
  Input:  {status, data: {feedback, categories}, meta, error}
  Output: {status, data: {categorized, priorities, trends, recommended_actions}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .categorizer import categorize_feedback
from .priority_scorer import score_priorities
from .trend_spotter import spot_trends
from .action_recommender import recommend_actions
from .memory_reader import read_past_feedback
from .memory_writer import write_feedback_result


class FeedbackProcessingEngine:
    """Feedback Processing Engine — orchestrator only, no logic."""

    ENGINE_NAME = "feedback_processing"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full feedback processing pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            FeedbackOutput dict.
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

        feedback = data.get("feedback", [])
        categories = data.get("categories", [])

        if not feedback:
            return self._fail("Feedback list is required", 0.0)

        # ---- Stage 1: Read past feedback (non-blocking) ----
        _past = read_past_feedback(limit=5)

        # ---- Stage 2: Categorizer ----
        cat_result = categorize_feedback(
            feedback=feedback,
            categories=categories if categories else None,
        )
        if cat_result.get("status") == "error":
            return self._fail(
                f"Categorization failed: {cat_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        categorized = cat_result.get("categorized", [])

        # ---- Stage 3: Priority Scorer ----
        prio_result = score_priorities(
            categorized=categorized,
            feedback=feedback,
        )
        if prio_result.get("status") == "error":
            return self._fail(
                f"Priority scoring failed: {prio_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        priorities = prio_result.get("priorities", [])

        # ---- Stage 4: Trend Spotter ----
        trend_result = spot_trends(
            categorized=categorized,
            feedback=feedback,
        )
        if trend_result.get("status") == "error":
            return self._fail(
                f"Trend spotting failed: {trend_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        trends = trend_result.get("trends", [])

        # ---- Stage 5: Action Recommender ----
        action_result = recommend_actions(
            categorized=categorized,
            priorities=priorities,
            trends=trends,
        )
        if action_result.get("status") == "error":
            return self._fail(
                f"Action recommendation failed: {action_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        recommended_actions = action_result.get("recommended_actions", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_feedback_result(
            categorized=categorized,
            priorities=priorities,
            trends=trends,
            recommended_actions=recommended_actions,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "categorized": categorized,
                "priorities": priorities,
                "trends": trends,
                "recommended_actions": recommended_actions,
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
