"""Brand Perception Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Brand Data → Mention Tracker → Sentiment Aggregator →
  Reputation Scorer → Perception Reporter → Memory Writer → Output

Engine contract:
  Input:  {status, data: {brand_name, mentions, reviews, social_posts}, meta, error}
  Output: {status, data: {mention_count, sentiment, reputation_score, trends, threats, opportunities}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .mention_tracker import track_mentions
from .sentiment_aggregator import aggregate_sentiment
from .reputation_scorer import score_reputation
from .perception_reporter import report_perception
from .memory_reader import read_past_perceptions
from .memory_writer import write_perception_result


class BrandPerceptionEngine:
    """Brand Perception Engine — orchestrator only, no logic."""

    ENGINE_NAME = "brand_perception"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full brand perception pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BrandPerceptionOutput dict.
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

        brand_name = str(data.get("brand_name", ""))
        if not brand_name:
            return self._fail("brand_name is required", 0.0)

        mentions = data.get("mentions", [])
        reviews = data.get("reviews", [])
        social_posts = data.get("social_posts", [])

        # ---- Stage 1: Read past perceptions (non-blocking) ----
        _past = read_past_perceptions(limit=5)

        # ---- Stage 2: Mention Tracker ----
        tracking_result = track_mentions(
            brand_name=brand_name,
            mentions=mentions,
            reviews=reviews,
            social_posts=social_posts,
        )
        if tracking_result.get("status") == "error":
            return self._fail(
                f"Mention tracking failed: {tracking_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tracking = tracking_result.get("tracking", {})

        # ---- Stage 3: Sentiment Aggregator ----
        sentiment_result = aggregate_sentiment(
            mentions=mentions,
            reviews=reviews,
            social_posts=social_posts,
        )
        if sentiment_result.get("status") == "error":
            return self._fail(
                f"Sentiment aggregation failed: {sentiment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sentiment = sentiment_result.get("sentiment", {})

        # ---- Stage 4: Reputation Scorer ----
        reputation_result = score_reputation(
            tracking=tracking,
            sentiment=sentiment,
        )
        if reputation_result.get("status") == "error":
            return self._fail(
                f"Reputation scoring failed: {reputation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        reputation = reputation_result.get("reputation", {})
        reputation_score = int(reputation.get("reputation_score", 0))

        # ---- Stage 5: Perception Reporter ----
        report_result = report_perception(
            tracking=tracking,
            sentiment=sentiment,
            reputation=reputation,
        )
        if report_result.get("status") == "error":
            return self._fail(
                f"Perception reporting failed: {report_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        report = report_result.get("report", {})
        trends = report.get("trends", [])
        threats = report.get("threats", [])
        opportunities = report.get("opportunities", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        mention_count = int(tracking.get("total_mentions", 0))
        _write_result = write_perception_result(
            mention_count=mention_count,
            sentiment=sentiment,
            reputation_score=reputation_score,
            trends=trends,
            threats=threats,
            opportunities=opportunities,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "mention_count": mention_count,
                "sentiment": {
                    "positive_pct": sentiment.get("positive_pct", 0.0),
                    "negative_pct": sentiment.get("negative_pct", 0.0),
                    "neutral_pct": sentiment.get("neutral_pct", 0.0),
                },
                "reputation_score": reputation_score,
                "trends": trends,
                "threats": threats,
                "opportunities": opportunities,
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
