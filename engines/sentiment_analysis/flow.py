"""Sentiment Analysis Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data -> Text Preprocessor -> Sentiment Scorer -> Topic Extractor ->
  Trend Detector -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {texts: [{source, text, date}], categories}, meta, error}
  Output: {status, data: {overall_sentiment, sentiment_distribution, topics, trends, alerts}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .text_preprocessor import preprocess_texts
from .sentiment_scorer import score_sentiments
from .topic_extractor import extract_topics
from .trend_detector import detect_trends
from .memory_reader import read_past_sentiments
from .memory_writer import write_sentiment_result


class SentimentAnalysisEngine:
    """Sentiment Analysis Engine — orchestrator only, no logic."""

    ENGINE_NAME = "sentiment_analysis"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full sentiment analysis pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SentimentAnalysisOutput dict.
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

        texts = data.get("texts", [])
        categories = data.get("categories", [])

        if not texts:
            return self._fail("Texts list is required", 0.0)

        # ---- Stage 1: Read past sentiments (non-blocking) ----
        _past = read_past_sentiments(limit=5)

        # ---- Stage 2: Text Preprocessor ----
        preprocess_result = preprocess_texts(texts=texts)
        if preprocess_result.get("status") == "error":
            return self._fail(
                f"Text preprocessing failed: {preprocess_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        processed_texts = preprocess_result.get("processed_texts", [])

        # ---- Stage 3: Sentiment Scorer ----
        sentiment_result = score_sentiments(processed_texts=processed_texts)
        if sentiment_result.get("status") == "error":
            return self._fail(
                f"Sentiment scoring failed: {sentiment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sentiment_scores = sentiment_result.get("sentiment_scores", [])
        overall_sentiment = float(sentiment_result.get("overall_sentiment", 0.0))
        sentiment_distribution = sentiment_result.get("sentiment_distribution", {})

        # ---- Stage 4: Topic Extractor ----
        topic_result = extract_topics(
            processed_texts=processed_texts,
            sentiment_scores=sentiment_scores,
            categories=categories,
        )
        if topic_result.get("status") == "error":
            return self._fail(
                f"Topic extraction failed: {topic_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        topics = topic_result.get("topics", [])

        # ---- Stage 5: Trend Detector ----
        trend_result = detect_trends(
            sentiment_scores=sentiment_scores,
            processed_texts=processed_texts,
        )
        if trend_result.get("status") == "error":
            return self._fail(
                f"Trend detection failed: {trend_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        trends = trend_result.get("trends", [])
        alerts = trend_result.get("alerts", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_sentiment_result(
            overall_sentiment=overall_sentiment,
            sentiment_distribution=sentiment_distribution,
            topics=topics,
            trends=trends,
            alerts=alerts,
        )

        # ---- Stage 7: Return output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "overall_sentiment": overall_sentiment,
                "sentiment_distribution": sentiment_distribution,
                "topics": topics,
                "trends": trends,
                "alerts": alerts,
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
