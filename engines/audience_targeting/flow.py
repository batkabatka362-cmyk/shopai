"""Audience Targeting Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data -> Segment Builder -> Rule Matcher -> Size Estimator ->
  Lookalike Builder -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {customers, orders, segments, campaign_goal}, meta, error}
  Output: {status, data: {audiences, recommended_audience, total_reachable}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .segment_builder import build_segments
from .rule_matcher import match_rules
from .size_estimator import estimate_sizes
from .lookalike_builder import build_lookalikes
from .memory_reader import read_past_audiences
from .memory_writer import write_audience_result
from engines._shopify_hydrator import hydrate


class AudienceTargetingEngine:
    """Audience Targeting Engine — orchestrator only, no logic."""

    ENGINE_NAME = "audience_targeting"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full audience targeting pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            AudienceTargetingOutput dict.
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

        customers = data.get("customers", [])
        orders = data.get("orders", [])
        segments = data.get("segments", [])
        campaign_goal = str(data.get("campaign_goal", "conversion"))

        # Auto-hydrate customers + orders from Shopify when caller
        # left the lists empty. Both feed downstream segmentation.
        # Pre-existing failure semantics preserved: empty supplied
        # AND empty hydrated → standard "Customer list is required".
        hydrate_limit = data.get("hydrate_limit")
        hydrate_query = data.get("hydrate_query")
        customers = hydrate(
            supplied=customers if isinstance(customers, list) else [],
            capability_name="SHOPIFY_FETCH_CUSTOMERS",
            list_field="customers",
            limit=hydrate_limit,
            query=hydrate_query,
        )
        orders = hydrate(
            supplied=orders if isinstance(orders, list) else [],
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            limit=hydrate_limit,
            query=hydrate_query,
        )

        if not customers:
            return self._fail("Customer list is required", 0.0)

        # ---- Stage 1: Read past audiences (non-blocking) ----
        _past = read_past_audiences(limit=5)

        # ---- Stage 2: Segment Builder ----
        segment_result = build_segments(
            customers=customers,
            orders=orders,
            segments=segments,
            campaign_goal=campaign_goal,
        )
        if segment_result.get("status") == "error":
            return self._fail(
                f"Segment building failed: {segment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        built_segments = segment_result.get("segments", [])
        total_customers = segment_result.get("total_customers", 0)

        # ---- Stage 3: Rule Matcher ----
        match_result = match_rules(
            segments=built_segments,
            total_customers=total_customers,
        )
        if match_result.get("status") == "error":
            return self._fail(
                f"Rule matching failed: {match_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        match_results = match_result.get("match_results", [])

        # ---- Stage 4: Size Estimator ----
        size_result = estimate_sizes(
            match_results=match_results,
        )
        if size_result.get("status") == "error":
            return self._fail(
                f"Size estimation failed: {size_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        estimates = size_result.get("estimates", [])
        total_reachable = int(size_result.get("total_reachable", 0))

        # ---- Stage 5: Lookalike Builder ----
        lookalike_result = build_lookalikes(
            segments=built_segments,
            customers=customers,
            campaign_goal=campaign_goal,
        )
        if lookalike_result.get("status") == "error":
            return self._fail(
                f"Lookalike building failed: {lookalike_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        lookalikes = lookalike_result.get("lookalikes", [])

        # ---- Stage 6: Assemble audiences ----
        audiences: list[dict[str, Any]] = []

        # Add matched segments as audiences
        est_map = {str(e.get("segment_id", "")): e for e in estimates}
        for match in match_results:
            seg_id = str(match.get("segment_id", ""))
            est = est_map.get(seg_id, {})
            audiences.append({
                "name": str(match.get("name", "")),
                "size": int(est.get("estimated_reachable", match.get("match_count", 0))),
                "criteria": {"segment_id": seg_id, "type": "matched"},
                "match_rate": float(match.get("match_rate", 0.0)),
            })

        # Add lookalike audiences
        for la in lookalikes:
            if la.get("lookalike_size", 0) > 0:
                audiences.append({
                    "name": str(la.get("name", "")),
                    "size": int(la.get("lookalike_size", 0)),
                    "criteria": {"segment_id": la.get("segment_id", ""), "type": "lookalike"},
                    "match_rate": float(la.get("similarity_score", 0.0)),
                })

        # Determine recommended audience (highest match rate with decent size)
        recommended = ""
        best_score = 0.0
        for aud in audiences:
            size = aud.get("size", 0)
            rate = aud.get("match_rate", 0.0)
            score = rate * min(size / 100.0, 1.0)  # Penalize tiny audiences
            if score > best_score:
                best_score = score
                recommended = str(aud.get("name", ""))

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_audience_result(
            audiences=audiences,
            recommended_audience=recommended,
            total_reachable=total_reachable,
        )

        # Phase 7: optional audience-tag apply. Opt-in via
        # data.apply_audience_tags=True. Tags every matched
        # customer with audience:<segment_id> via
        # SHOPIFY_TAG_CUSTOMER (one customer can carry many).
        tagged_audiences: list[dict[str, Any]] = []
        if bool(data.get("apply_audience_tags")):
            try:
                from .tag_applier import apply_audience_tags
                tagged_audiences = apply_audience_tags(match_results)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "audience_targeting: apply loop raised: %s",
                    exc,
                )

        # ---- Stage 8: Return output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "audiences": audiences,
                "recommended_audience": recommended,
                "total_reachable": total_reachable,
                "tagged_audiences": tagged_audiences,
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
