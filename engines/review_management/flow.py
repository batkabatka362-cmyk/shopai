"""Review Management Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Review Data → Review Aggregator → Sentiment Analyzer → Topic Extractor →
  Rating Analyzer → Response Generator → Insight Extractor →
  Improvement Suggester → Memory Writer → Output

Engine contract:
  Input:  {status, data: {product_id, reviews: [{id, rating, text, date, verified, helpful_votes}]}, meta, error}
  Output: {status, data: {summary, sentiment, topics, trend, responses, insights, improvements, confidence}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .review_aggregator import aggregate_reviews
from .sentiment_analyzer import analyze_sentiment
from .topic_extractor import extract_topics
from .rating_analyzer import analyze_ratings
from .response_generator import generate_responses
from .insight_extractor import extract_insights
from .improvement_suggester import suggest_improvements
from .memory_reader import read_past_analyses
from .memory_writer import write_review_analysis


class ReviewManagementEngine:
    """Review Management Engine — orchestrator only, no logic."""

    ENGINE_NAME = "review_management"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full review management pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ReviewManagementOutput dict.
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

        product_id = str(data.get("product_id", ""))
        reviews = data.get("reviews", [])

        if not isinstance(reviews, list):
            return self._fail("Input 'reviews' must be a list", 0.0)

        if not reviews:
            return self._fail("No reviews provided", 0.0)

        # ---- Stage 1: Read past analyses (non-blocking) ----
        _past = read_past_analyses(product_id=product_id, limit=5)

        # ---- Stage 2: Review Aggregator ----
        agg_result = aggregate_reviews(reviews=reviews)
        if agg_result.get("status") == "error":
            return self._fail(
                f"Review aggregation failed: {agg_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        summary = agg_result.get("summary", {})

        # ---- Stage 3: Sentiment Analyzer ----
        sent_result = analyze_sentiment(reviews=reviews)
        if sent_result.get("status") == "error":
            return self._fail(
                f"Sentiment analysis failed: {sent_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sentiment = sent_result.get("sentiment", {})
        per_review_sentiment = sentiment.get("per_review", [])

        # ---- Stage 4: Topic Extractor ----
        topic_result = extract_topics(
            reviews=reviews,
            sentiment_per_review=per_review_sentiment,
        )
        if topic_result.get("status") == "error":
            return self._fail(
                f"Topic extraction failed: {topic_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        topics = topic_result.get("topics", [])

        # ---- Stage 5: Rating Analyzer ----
        overall_avg = float(summary.get("avg_rating", 0.0))
        rating_result = analyze_ratings(
            reviews=reviews,
            overall_avg=overall_avg,
        )
        if rating_result.get("status") == "error":
            return self._fail(
                f"Rating analysis failed: {rating_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        trend = rating_result.get("trend", {})

        # ---- Stage 6: Response Generator ----
        resp_result = generate_responses(
            reviews=reviews,
            sentiment_per_review=per_review_sentiment,
            topics=topics,
        )
        if resp_result.get("status") == "error":
            return self._fail(
                f"Response generation failed: {resp_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        responses = resp_result.get("responses", [])

        # ---- Stage 7: Insight Extractor ----
        insight_result = extract_insights(
            reviews=reviews,
            sentiment_per_review=per_review_sentiment,
            topics=topics,
            summary=summary,
        )
        if insight_result.get("status") == "error":
            return self._fail(
                f"Insight extraction failed: {insight_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        insights = insight_result.get("insights", [])

        # ---- Stage 8: Improvement Suggester ----
        improve_result = suggest_improvements(
            insights=insights,
            summary=summary,
            sentiment=sentiment,
        )
        if improve_result.get("status") == "error":
            return self._fail(
                f"Improvement suggestion failed: {improve_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        improvements = improve_result.get("improvements", [])

        # ---- Stage 9: Compute confidence ----
        confidence = _compute_confidence(
            total_reviews=int(summary.get("total_reviews", 0)),
            verified_count=int(summary.get("verified_count", 0)),
            avg_helpful=float(summary.get("avg_helpful_votes", 0.0)),
            topic_count=len(topics),
            insight_count=len(insights),
        )

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _write_result = write_review_analysis(
            product_id=product_id,
            avg_rating=overall_avg,
            total_reviews=int(summary.get("total_reviews", 0)),
            sentiment_summary={
                "positive_pct": sentiment.get("positive_pct", 0.0),
                "negative_pct": sentiment.get("negative_pct", 0.0),
                "neutral_pct": sentiment.get("neutral_pct", 0.0),
            },
            trend_direction=str(trend.get("direction", "stable")),
            top_insights=insights[:5],
            confidence=confidence,
        )

        # Phase 7: optional review-health tag apply. Opt-in
        # via data.apply_review_health_tags=True. Tags the
        # product with reviews:poor_rating / negative_sentiment
        # / declining based on engine output.
        tagged_review_health: dict[str, Any] = {}
        if bool(data.get("apply_review_health_tags")) and product_id:
            try:
                from .tag_applier import apply_review_health_tags
                tagged_review_health = apply_review_health_tags(
                    product_id=product_id,
                    summary=summary,
                    sentiment=sentiment,
                    trend=trend,
                    existing_tags=data.get("product_tags") or [],
                )
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "review_management: apply loop raised: %s",
                    exc,
                )
                tagged_review_health = {}

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "summary": {
                    "avg_rating": summary.get("avg_rating", 0.0),
                    "total_reviews": summary.get("total_reviews", 0),
                    "rating_distribution": summary.get("rating_distribution", {}),
                    "verified_count": summary.get("verified_count", 0),
                    "unverified_count": summary.get("unverified_count", 0),
                    "avg_helpful_votes": summary.get("avg_helpful_votes", 0.0),
                },
                "sentiment": {
                    "positive_pct": sentiment.get("positive_pct", 0.0),
                    "negative_pct": sentiment.get("negative_pct", 0.0),
                    "neutral_pct": sentiment.get("neutral_pct", 0.0),
                    "mixed_pct": sentiment.get("mixed_pct", 0.0),
                    "avg_score": sentiment.get("avg_score", 0.0),
                },
                "topics": topics,
                "trend": {
                    "direction": trend.get("direction", "stable"),
                    "recent_avg": trend.get("recent_avg", 0.0),
                    "overall_avg": trend.get("overall_avg", 0.0),
                    "moving_averages": trend.get("moving_averages", []),
                    "velocity": trend.get("velocity", 0.0),
                },
                "responses": responses,
                "insights": insights,
                "improvements": improvements,
                "confidence": confidence,
                "tagged_review_health": tagged_review_health,
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


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_confidence(
    total_reviews: int,
    verified_count: int,
    avg_helpful: float,
    topic_count: int,
    insight_count: int,
) -> float:
    """Compute an overall confidence score (0.0 to 1.0).

    Factors:
    - Review volume (more reviews = higher confidence, diminishing returns)
    - Verified ratio (verified reviews are more trustworthy)
    - Helpful votes (community-validated reviews add signal)
    - Topic coverage (more topics detected = richer analysis)
    - Insight yield (more insights = more actionable analysis)
    """
    if total_reviews == 0:
        return 0.0

    # Volume factor: logarithmic scale, caps around 30+ reviews
    import math
    volume_factor = min(1.0, math.log1p(total_reviews) / math.log1p(30))

    # Verified ratio
    verified_ratio = verified_count / total_reviews if total_reviews > 0 else 0.0

    # Helpful factor: normalized, caps at avg 10+ votes
    helpful_factor = min(1.0, avg_helpful / 10.0)

    # Topic coverage: 7 possible topics
    topic_factor = min(1.0, topic_count / 5.0)

    # Insight yield
    insight_factor = min(1.0, insight_count / 6.0)

    # Weighted blend
    confidence = (
        volume_factor * 0.30
        + verified_ratio * 0.20
        + helpful_factor * 0.15
        + topic_factor * 0.20
        + insight_factor * 0.15
    )

    return round(max(0.0, min(1.0, confidence)), 4)
