"""Behavioral Data Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Click Tracker → Session Analyzer →
  Engagement Scorer → Heatmap Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {sessions, events, product_views}, meta, error}
  Output: {status, data: {behavior_summary, engagement_scores, heatmaps, top_products}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .click_tracker import track_clicks
from .session_analyzer import analyze_sessions
from .engagement_scorer import score_engagement
from .heatmap_builder import build_heatmaps
from .memory_reader import read_past_behavioral
from .memory_writer import write_behavioral_result


class BehavioralDataEngine:
    """Behavioral Data Engine — orchestrator only, no logic."""

    ENGINE_NAME = "behavioral_data"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full behavioral data pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BehavioralDataOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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

        sessions = data.get("sessions", [])
        events = data.get("events", [])
        product_views = data.get("product_views", [])

        if not sessions and not events and not product_views:
            return self._fail("At least one of sessions, events, or product_views is required", 0.0)

        # ---- Stage 1: Read past behavioral (non-blocking) ----
        _past = read_past_behavioral(limit=5)

        # ---- Stage 2: Click Tracker ----
        click_result = track_clicks(
            events=events,
            product_views=product_views,
        )
        if click_result.get("status") == "error":
            return self._fail(
                f"Click tracking failed: {click_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        click_summaries = click_result.get("summaries", [])

        # ---- Stage 3: Session Analyzer ----
        session_result = analyze_sessions(
            sessions=sessions,
        )
        if session_result.get("status") == "error":
            return self._fail(
                f"Session analysis failed: {session_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        session_patterns = session_result.get("patterns", [])
        session_aggregate = session_result.get("aggregate", {})

        # ---- Stage 4: Engagement Scorer ----
        engagement_result = score_engagement(
            sessions=session_patterns,
            click_summaries=click_summaries,
        )
        if engagement_result.get("status") == "error":
            return self._fail(
                f"Engagement scoring failed: {engagement_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        engagement_scores = engagement_result.get("scores", [])

        # ---- Stage 5: Heatmap Builder ----
        heatmap_result = build_heatmaps(
            events=events,
            product_views=product_views,
        )
        if heatmap_result.get("status") == "error":
            return self._fail(
                f"Heatmap building failed: {heatmap_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        heatmaps = heatmap_result.get("heatmap", [])

        # ---- Stage 6: Identify top products ----
        top_products = click_summaries[:10]

        # ---- Stage 7: Build behavior summary ----
        behavior_summary: dict[str, Any] = {
            "total_sessions": session_aggregate.get("total_sessions", 0),
            "avg_session_duration": session_aggregate.get("avg_duration_seconds", 0),
            "bounce_rate_pct": session_aggregate.get("bounce_rate_pct", 0),
            "conversion_rate_pct": session_aggregate.get("conversion_rate_pct", 0),
            "total_views": click_result.get("total_views", 0),
            "total_clicks": click_result.get("total_clicks", 0),
            "total_interactions": heatmap_result.get("total_interactions", 0),
        }

        # ---- Stage 8: Memory Writer (non-fatal) ----
        _write_result = write_behavioral_result(
            behavior_summary=behavior_summary,
            engagement_scores=engagement_scores,
            heatmaps=heatmaps,
            top_products=top_products,
        )

        # ---- Stage 9: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "behavior_summary": behavior_summary,
                "engagement_scores": engagement_scores,
                "heatmaps": heatmaps,
                "top_products": top_products,
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
