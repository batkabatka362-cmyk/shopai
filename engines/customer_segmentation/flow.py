"""Customer Segmentation Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Customer Data → Data Normalizer → RFM Analyzer → Behavioral Clusterer →
  Lifecycle Classifier → Value Scorer → Segment Builder → Strategy Mapper →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {customers: [{id, first_purchase, last_purchase,
           total_orders, total_spent, avg_order_value, days_since_last,
           categories_bought, email_opens, cart_abandons}]}, meta, error}
  Output: {status, data: {segments, segment_distribution, high_value_count,
           at_risk_count, churn_predictions}, meta: {engine, ...}, error}

Models: Mistral=RFM analysis/churn, Qwen=segment building, LLaMA=strategy mapping.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data_normalizer import normalize_customers
from .rfm_analyzer import analyze_rfm
from .behavioral_clusterer import cluster_behaviors
from .lifecycle_classifier import classify_lifecycle
from .value_scorer import score_values
from .churn_predictor import predict_churn
from .segment_builder import build_segments
from .strategy_mapper import map_strategies
from .customer_applier import (
    apply_segment_tags,
    enqueue_segment_tags_for_approval,
)
from .memory_reader import read_past_segmentations
from .memory_writer import write_segmentation_result
from engines._shopify_hydrator import hydrate


class CustomerSegmentationEngine:
    """Customer Segmentation Engine — orchestrator only, no logic."""

    ENGINE_NAME = "customer_segmentation"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full customer segmentation pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SegmentationOutput dict.
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

        customers = data.get("customers", [])
        if not isinstance(customers, list):
            customers = []
        # Auto-hydrate customers from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        customers = hydrate(
            supplied=customers,
            capability_name="SHOPIFY_FETCH_CUSTOMERS",
            list_field="customers",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )
        if not customers:
            # W963-161: cold-start success-skip.
            return {
                "status": "success",
                "data": {
                    "segments": [],
                    "total_customers": 0,
                    "applied_tags": [],
                    "skipped": True,
                    "skip_reason": (
                        "no_customers_yet (cold-start)"
                    ),
                },
                "meta": {
                    "engine": self.ENGINE_NAME,
                    "timestamp": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                    ),
                    "elapsed_seconds": 0.0,
                },
                "error": None,
            }

        # ---- Stage 1: Read past segmentations (non-blocking) ----
        _past = read_past_segmentations(limit=5)

        # ---- Stage 2: Data Normalizer ----
        norm_result = normalize_customers(customers)
        if norm_result.get("status") == "error":
            return self._fail(
                f"Normalization failed: {norm_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        normalized = norm_result.get("customers", [])
        if not normalized:
            return self._fail("No valid customers after normalization", time.monotonic() - start)

        total_customers = len(normalized)

        # ---- Stage 3: RFM Analyzer (Mistral) ----
        rfm_result = analyze_rfm(normalized)
        if rfm_result.get("status") == "error":
            return self._fail(
                f"RFM analysis failed: {rfm_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        rfm_scores = rfm_result.get("rfm_scores", [])

        # ---- Stage 4: Behavioral Clusterer ----
        cluster_result = cluster_behaviors(normalized)
        if cluster_result.get("status") == "error":
            return self._fail(
                f"Behavioral clustering failed: {cluster_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        clusters = cluster_result.get("clusters", [])

        # ---- Stage 5: Lifecycle Classifier ----
        lifecycle_result = classify_lifecycle(normalized)
        if lifecycle_result.get("status") == "error":
            return self._fail(
                f"Lifecycle classification failed: {lifecycle_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        stages = lifecycle_result.get("stages", [])

        # ---- Stage 6: Value Scorer ----
        value_result = score_values(normalized)
        if value_result.get("status") == "error":
            return self._fail(
                f"Value scoring failed: {value_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        value_scores = value_result.get("scores", [])

        # ---- Stage 7: Churn Predictor (Mistral) ----
        churn_result = predict_churn(normalized)
        if churn_result.get("status") == "error":
            return self._fail(
                f"Churn prediction failed: {churn_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        churn_predictions = churn_result.get("predictions", [])

        # ---- Stage 8: Segment Builder (Qwen) ----
        segment_result = build_segments(
            rfm_scores=rfm_scores,
            clusters=clusters,
            stages=stages,
            value_scores=value_scores,
        )
        if segment_result.get("status") == "error":
            return self._fail(
                f"Segment building failed: {segment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        segments = segment_result.get("segments", [])
        segment_distribution = segment_result.get("segment_distribution", {})
        high_value_count = segment_result.get("high_value_count", 0)
        at_risk_count = segment_result.get("at_risk_count", 0)

        # ---- Stage 9: Strategy Mapper (LLaMA) ----
        strategy_result = map_strategies(segments)
        if strategy_result.get("status") == "error":
            return self._fail(
                f"Strategy mapping failed: {strategy_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        # Strategy mapper returns updated segments with strategy field set
        final_segments = strategy_result.get("segments", segments)

        # ---- Stage 9.5: Segment-tag writeback (opt-in) ----
        # Default OFF — existing callers keep their pure-
        # recommendation contract. Two opt-in modes mirror the
        # established Phase 6/7 pattern:
        #
        #   data.apply_segment_tags=True + data.require_approval=False
        #     → SHOPIFY_TAG_CUSTOMER immediately per customer
        #   data.apply_segment_tags=True + data.require_approval=True
        #     → enqueue per-customer to core.approval; merchant
        #       approves before each mutation lands
        #
        # Both paths share the same upfront filters: skip blank
        # customer ids and skip the ``Unclassified`` fallback
        # bucket. Per-customer results so the engine output is
        # explicit about what was written and what was skipped.
        segment_apply_results: list[dict[str, Any]] = []
        if data.get("apply_segment_tags") is True:
            if data.get("require_approval") is True:
                segment_apply_results = enqueue_segment_tags_for_approval(
                    segments=final_segments,
                )
            else:
                segment_apply_results = apply_segment_tags(
                    segments=final_segments,
                )

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _write_result = write_segmentation_result(
            segments=final_segments,
            segment_distribution=segment_distribution,
            high_value_count=high_value_count,
            at_risk_count=at_risk_count,
            total_customers=total_customers,
        )

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "segments": final_segments,
                "segment_distribution": segment_distribution,
                "high_value_count": high_value_count,
                "at_risk_count": at_risk_count,
                "churn_predictions": churn_predictions,
                # Stage 9.5 output. Empty list when the opt-in
                # flag is off; one entry per customer otherwise
                # (carries pending_action_id when the approval-
                # queue branch fired).
                "segment_apply_results": segment_apply_results,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
                "total_customers": total_customers,
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
                "total_customers": 0,
            },
            "error": reason,
        }
