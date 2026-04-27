"""Product Lifecycle Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Stage Classifier → Velocity Tracker → Trend Projector →
  Action Advisor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, sales_history}, meta, error}
  Output: {status, data: {lifecycle: [{product_id, stage, velocity, projected_transition}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .stage_classifier import classify_stages
from .velocity_tracker import track_velocity
from .trend_projector import project_trends
from .action_advisor import advise_actions
from .memory_reader import read_past_lifecycles
from .memory_writer import write_lifecycle_result
from engines._shopify_hydrator import hydrate


class ProductLifecycleEngine:
    """Product Lifecycle Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_lifecycle"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full lifecycle pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            LifecycleOutput dict.
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

        products = data.get("products", [])
        sales_history = data.get("sales_history", [])

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past lifecycles (non-blocking) ----
        _past = read_past_lifecycles(limit=5)

        # ---- Stage 2: Stage Classifier ----
        stage_result = classify_stages(
            products=products,
            sales_history=sales_history,
        )
        if stage_result.get("status") == "error":
            return self._fail(
                f"Stage classification failed: {stage_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        classifications = stage_result.get("classifications", [])

        # ---- Stage 3: Velocity Tracker ----
        velocity_result = track_velocity(
            products=products,
            sales_history=sales_history,
        )
        if velocity_result.get("status") == "error":
            return self._fail(
                f"Velocity tracking failed: {velocity_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        velocities = velocity_result.get("velocities", [])

        # ---- Stage 4: Trend Projector ----
        projection_result = project_trends(
            classifications=classifications,
            velocities=velocities,
            sales_history=sales_history,
        )
        if projection_result.get("status") == "error":
            return self._fail(
                f"Trend projection failed: {projection_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        projections = projection_result.get("projections", [])

        # ---- Stage 5: Action Advisor ----
        advice_result = advise_actions(
            classifications=classifications,
            projections=projections,
            velocities=velocities,
        )
        if advice_result.get("status") == "error":
            return self._fail(
                f"Action advising failed: {advice_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        advice_list = advice_result.get("advice", [])

        # ---- Stage 6: Assemble lifecycle output ----
        cls_map = {str(c.get("product_id", "")): c for c in classifications}
        vel_map = {str(v.get("product_id", "")): v for v in velocities}
        proj_map = {str(p.get("product_id", "")): p for p in projections}
        adv_map = {str(a.get("product_id", "")): a for a in advice_list}

        lifecycle: list[dict[str, Any]] = []
        for product in products:
            pid = str(product.get("id", "unknown"))
            cls = cls_map.get(pid, {})
            vel = vel_map.get(pid, {})
            proj = proj_map.get(pid, {})
            adv = adv_map.get(pid, {})

            lifecycle.append({
                "product_id": pid,
                "stage": cls.get("stage", "unknown"),
                "velocity": vel.get("current_velocity", 0.0),
                "projected_transition": proj.get("projected_transition", "unknown"),
                "periods_to_transition": proj.get("periods_to_transition", 0),
                "recommended_actions": adv.get("recommended_actions", []),
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_lifecycle_result(lifecycle=lifecycle)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "lifecycle": lifecycle,
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
