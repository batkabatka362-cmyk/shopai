"""Social Media Engine — orchestrates the full content pipeline.

This is the FLOW file.  It ONLY orchestrates — no business logic here.
Every step delegates to a dedicated module; this file wires them together.

Pipeline:
  Strategy Goal -> Platform Analyzer -> Content Calendar Builder ->
  Post Creator -> Hashtag Generator -> Engagement Predictor ->
  Schedule Optimizer -> Performance Analyzer -> Output

Engine contract:
  Input:  {status, data: SocialMediaInput, meta, error}
  Output: {status, data: {content_calendar, posts, schedule,
           predicted_engagement, trending, confidence}, meta, error}

Model usage summary:
  - Platform Analyzer:       Mistral (analytical platform assessment)
  - Content Calendar Builder: Qwen   (structured calendar generation)
  - Post Creator:            LLaMA  (creative post composition)
  - Engagement Predictor:    Mistral (analytical engagement prediction)
  - Schedule Optimizer:      Qwen   (structured schedule optimization)
  - Performance Analyzer:    Mistral (analytical performance assessment)
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .platform_analyzer import analyze_platforms
from .content_calendar_builder import build_content_calendar
from .post_creator import create_posts
from .hashtag_generator import generate_hashtags
from .engagement_predictor import predict_engagement
from .schedule_optimizer import optimize_schedule
from .performance_analyzer import analyze_performance
from .trend_tracker import track_trends
from .memory_writer import write_to_memory
from .memory_reader import find_past_performance
from engines._shopify_hydrator import hydrate


class SocialMediaEngine:
    """Social Media Engine — orchestrator only, no logic."""

    ENGINE_NAME = "social_media"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full social media pipeline.

        Accepts a raw dict (will be validated and deep-copied).
        Returns a SocialMediaOutput-shaped dict — always structured,
        never raises.
        """
        start = time.monotonic()

        try:
            return self._execute_pipeline(input_payload, start)
        except Exception as exc:
            return self._error_output(
                reason=f"Unexpected pipeline error: {exc}",
                elapsed=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(
        self,
        input_payload: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        """Run each pipeline stage in sequence, short-circuiting on failure."""

        # Stage 0: Input validation and deep copy
        parsed = self._validate_input(input_payload)
        if parsed is None:
            return self._error_output(
                reason=(
                    "Invalid input: requires 'platforms' (non-empty list) "
                    "and 'brand' (dict with 'name')."
                ),
                elapsed=time.monotonic() - start,
            )

        platforms: list[str] = parsed["platforms"]
        products: list[dict[str, Any]] = parsed["products"]
        brand: dict[str, Any] = parsed["brand"]
        goal: str = parsed["goal"]
        posting_frequency: str = parsed["posting_frequency"]
        brand_voice: str = str(brand.get("voice", "professional")).strip()

        # Auto-hydrate products from Shopify when caller left the
        # list empty. products is auxiliary (platforms+brand are
        # gated), but feeds content calendar + post creator. Re-
        # read hydrate kwargs from raw input since _validate_input
        # doesn't carry them through.
        raw_data = (
            input_payload.get("data", {})
            if isinstance(input_payload, dict) else {}
        )
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=raw_data.get("hydrate_limit"),
            query=raw_data.get("hydrate_query"),
        )

        # Stage 0.5: Check memory for past performance
        prior = find_past_performance(goal, min_confidence=0.3, max_results=3)

        # Stage 1: Platform Analyzer  (model: Mistral)
        platform_result = analyze_platforms(platforms, goal, brand_voice)
        if platform_result.get("status") != "success":
            return self._error_output(
                reason=platform_result.get("error", "Platform analysis failed."),
                elapsed=time.monotonic() - start,
            )
        platform_analyses = platform_result["analyses"]

        # Stage 2: Content Calendar Builder  (model: Qwen)
        calendar_result = build_content_calendar(
            platforms, goal, posting_frequency, platform_analyses, products,
        )
        if calendar_result.get("status") != "success":
            return self._error_output(
                reason=calendar_result.get("error", "Content calendar building failed."),
                elapsed=time.monotonic() - start,
            )
        calendar = calendar_result["calendar"]
        calendar_entries = calendar.get("entries", [])

        # Stage 3: Post Creator  (model: LLaMA)
        post_result = create_posts(calendar_entries, brand, goal, products)
        if post_result.get("status") != "success":
            return self._error_output(
                reason=post_result.get("error", "Post creation failed."),
                elapsed=time.monotonic() - start,
            )
        posts = post_result["posts"]

        # Stage 4: Hashtag Generator  (no model — deterministic)
        hashtag_result = generate_hashtags(
            platforms, products, brand, goal, platform_analyses,
        )
        if hashtag_result.get("status") != "success":
            return self._error_output(
                reason=hashtag_result.get("error", "Hashtag generation failed."),
                elapsed=time.monotonic() - start,
            )
        hashtag_sets = hashtag_result["hashtag_sets"]

        # Stage 5: Engagement Predictor  (model: Mistral)
        engagement_result = predict_engagement(
            posts, calendar_entries, goal, platform_analyses,
        )
        if engagement_result.get("status") != "success":
            return self._error_output(
                reason=engagement_result.get("error", "Engagement prediction failed."),
                elapsed=time.monotonic() - start,
            )
        engagement_predictions = engagement_result["predictions"]
        overall_confidence = engagement_result.get("overall_confidence", 0.0)

        # Stage 6: Schedule Optimizer  (model: Qwen)
        schedule_result = optimize_schedule(
            calendar_entries, platform_analyses, engagement_predictions,
        )
        if schedule_result.get("status") != "success":
            return self._error_output(
                reason=schedule_result.get("error", "Schedule optimization failed."),
                elapsed=time.monotonic() - start,
            )
        optimized_schedule = schedule_result["schedule"]

        # Stage 7: Trend Tracker  (no model — deterministic)
        trend_result = track_trends(platforms, goal, products)
        if trend_result.get("status") != "success":
            return self._error_output(
                reason=trend_result.get("error", "Trend tracking failed."),
                elapsed=time.monotonic() - start,
            )
        trending = trend_result["trending"]

        # Stage 8: Performance Analyzer  (model: Mistral)
        perf_result = analyze_performance(
            posts, engagement_predictions, platforms, prior,
        )
        if perf_result.get("status") != "success":
            return self._error_output(
                reason=perf_result.get("error", "Performance analysis failed."),
                elapsed=time.monotonic() - start,
            )
        performance_report = perf_result["report"]

        # Stage 9: Build final output
        elapsed = time.monotonic() - start

        # Aggregate engagement data
        predicted_engagement: dict[str, Any] = {
            "per_post": engagement_predictions,
            "overall_engagement_rate": round(
                sum(p.get("engagement_rate", 0.0) for p in engagement_predictions)
                / max(len(engagement_predictions), 1),
                4,
            ),
            "best_performing_type": performance_report.get("best_performing_type", ""),
            "hashtag_sets": hashtag_sets,
        }

        output: dict[str, Any] = {
            "status": "success",
            "data": {
                "content_calendar": calendar_entries,
                "posts": posts,
                "schedule": optimized_schedule,
                "predicted_engagement": predicted_engagement,
                "trending": trending,
                "confidence": overall_confidence,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
                "models": {
                    "platform_analyzer": "mistral",
                    "content_calendar_builder": "qwen",
                    "post_creator": "llama",
                    "engagement_predictor": "mistral",
                    "schedule_optimizer": "qwen",
                    "performance_analyzer": "mistral",
                },
                "pipeline_stats": {
                    "platforms_analyzed": len(platform_analyses),
                    "calendar_entries": len(calendar_entries),
                    "posts_created": len(posts),
                    "hashtag_sets": len(hashtag_sets),
                    "schedule_slots": len(optimized_schedule.get("slots", [])),
                    "conflicts_resolved": optimized_schedule.get("conflicts_resolved", 0),
                    "trending_items": len(trending),
                    "recommendations": len(performance_report.get("recommendations", [])),
                },
                "prior_records_found": len(prior),
            },
            "error": None,
        }

        # Stage 10: Persist to memory
        write_to_memory(output)

        return output

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and normalise the input into a usable dict.

        Returns ``None`` if the input is unusable.
        Never mutates *payload*.
        """
        if not isinstance(payload, dict):
            return None

        safe = copy.deepcopy(payload)

        # Engine contract: payload is {status, data, meta, error}
        data = safe.get("data", safe)  # fallback to raw dict
        if not isinstance(data, dict):
            return None

        platforms = data.get("platforms", [])
        if not isinstance(platforms, list) or not platforms:
            return None

        brand = data.get("brand", {})
        if not isinstance(brand, dict) or not brand.get("name"):
            return None

        products = data.get("products", [])
        if not isinstance(products, list):
            products = []

        goal = str(data.get("goal", "engagement")).strip().lower() or "engagement"

        posting_frequency = str(data.get("posting_frequency", "daily")).strip().lower() or "daily"

        return {
            "platforms": [str(p).lower().strip() for p in platforms],
            "products": products,
            "brand": brand,
            "goal": goal,
            "posting_frequency": posting_frequency,
        }

    # ------------------------------------------------------------------
    # Error output helper
    # ------------------------------------------------------------------

    def _error_output(self, *, reason: str, elapsed: float) -> dict[str, Any]:
        """Build a well-formed error response."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
