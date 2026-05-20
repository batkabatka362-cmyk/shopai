"""Customer Effort Score Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Interaction Data -> Effort Calculator -> Touchpoint Scorer ->
  Friction Detector -> Improvement Planner -> Output

Engine contract:
  Input:  {status, data: {interactions: [{customer_id, touchpoint, steps_taken, time_spent, resolved}]}, meta, error}
  Output: {status, data: {ces_score, touchpoint_scores, friction_points, improvements, trend}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .effort_calculator import calculate_effort
from .touchpoint_scorer import score_touchpoints
from .friction_detector import detect_friction
from .improvement_planner import plan_improvements


class CustomerEffortScoreEngine:
    """Customer Effort Score Engine — orchestrator only, no logic."""

    ENGINE_NAME = "customer_effort_score"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full CES pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CES output dict.
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

        interactions = data.get("interactions", [])
        if not interactions:
            return self._fail("Interactions list is required", 0.0)

        # ---- Stage 1: Effort Calculator ----
        effort_result = calculate_effort(interactions=interactions)
        if effort_result.get("status") == "error":
            return self._fail(
                f"Effort calculation failed: {effort_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        ces_score = effort_result.get("ces_score", 0.0)
        interaction_scores = effort_result.get("interaction_scores", [])

        # ---- Stage 2: Touchpoint Scorer ----
        tp_result = score_touchpoints(interaction_scores=interaction_scores)
        if tp_result.get("status") == "error":
            return self._fail(
                f"Touchpoint scoring failed: {tp_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        touchpoint_scores = tp_result.get("touchpoint_scores", [])

        # ---- Stage 3: Friction Detector ----
        friction_result = detect_friction(
            interaction_scores=interaction_scores,
            touchpoint_scores=touchpoint_scores,
        )
        if friction_result.get("status") == "error":
            return self._fail(
                f"Friction detection failed: {friction_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        friction_points = friction_result.get("friction_points", [])

        # ---- Stage 4: Improvement Planner ----
        improvement_result = plan_improvements(
            friction_points=friction_points,
            touchpoint_scores=touchpoint_scores,
            ces_score=ces_score,
        )
        if improvement_result.get("status") == "error":
            return self._fail(
                f"Improvement planning failed: {improvement_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        improvements = improvement_result.get("improvements", [])
        trend = improvement_result.get("trend", "unknown")

        # ---- Stage 4.5: Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory per-interaction effort
        # scores. When the caller passes
        # ``data.apply_ces_tags=True``, we push
        # ``shopai-ces-{bucket}`` on every customer (worst
        # score wins) via SHOPIFY_TAG_CUSTOMER. Merchants
        # then save admin searches to focus support attention
        # or run reach-out campaigns; downstream engines
        # (customer_service / loyalty) filter on the bucket
        # for friction-aware retention plays.
        #
        # Only the "high" bucket is tagged by default --
        # tagging happy customers as "low effort" is noise.
        # ``data.include_low=True`` / ``include_medium=True``
        # opt back in.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue via approval queue.
        #   * False -- call SHOPIFY_TAG_CUSTOMER directly.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_ces_tags") is True:
            try:
                from .tag_applier import apply_ces_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                include_low = bool(
                    data.get("include_low", False),
                )
                include_medium = bool(
                    data.get("include_medium", False),
                )
                tag_results = apply_ces_tags(
                    interaction_scores,
                    include_low=include_low,
                    include_medium=include_medium,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises out
                # by design, but a stray import / typo
                # shouldn't poison the engine's primary
                # output.
                import logging
                logging.getLogger(__name__).debug(
                    "ces tag_applier raised: %s", exc,
                )

        # ---- Stage 5: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "ces_score": ces_score,
                "touchpoint_scores": touchpoint_scores,
                "friction_points": friction_points,
                "improvements": improvements,
                "trend": trend,
                # Phase 7 writeback: per-customer tag results
                # when opted in. Empty otherwise.
                "tag_results": tag_results,
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
