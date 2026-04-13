"""Store Design Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Brand/Products/Analytics → Layout Optimizer → Color Recommender →
  Navigation Builder → Mobile Optimizer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {brand, products, analytics}, meta, error}
  Output: {status, data: {layout_recommendations, color_palette, navigation, mobile_optimizations, estimated_conversion_lift}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .layout_optimizer import optimize_layouts
from .color_recommender import recommend_colors
from .navigation_builder import build_navigation
from .mobile_optimizer import optimize_mobile
from .memory_reader import read_past_designs
from .memory_writer import write_design_result


class StoreDesignEngine:
    """Store Design Engine — orchestrator only, no logic."""

    ENGINE_NAME = "store_design"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full store design pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            StoreDesignOutput dict.
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

        brand = data.get("brand", {})
        products = data.get("products", [])
        analytics = data.get("analytics", {})

        if not isinstance(brand, dict):
            return self._fail("Brand info is required", 0.0)

        # ---- Stage 1: Read past designs (non-blocking) ----
        _past = read_past_designs(limit=5)

        # ---- Stage 2: Layout Optimizer ----
        layout_result = optimize_layouts(
            products=products,
            analytics=analytics,
            brand=brand,
        )
        if layout_result.get("status") == "error":
            return self._fail(
                f"Layout optimization failed: {layout_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        layout_recommendations = layout_result.get("recommendations", [])

        # ---- Stage 3: Color Recommender ----
        color_result = recommend_colors(
            brand=brand,
            products=products,
        )
        if color_result.get("status") == "error":
            return self._fail(
                f"Color recommendation failed: {color_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        color_palette = color_result.get("palette", {})

        # ---- Stage 4: Navigation Builder ----
        nav_result = build_navigation(
            products=products,
            brand=brand,
        )
        if nav_result.get("status") == "error":
            return self._fail(
                f"Navigation building failed: {nav_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        navigation = nav_result.get("navigation", {})

        # ---- Stage 5: Mobile Optimizer ----
        mobile_result = optimize_mobile(
            analytics=analytics,
            products=products,
            brand=brand,
        )
        if mobile_result.get("status") == "error":
            return self._fail(
                f"Mobile optimization failed: {mobile_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        mobile_optimizations = mobile_result.get("optimizations", [])

        # ---- Stage 6: Compute estimated conversion lift ----
        total_lift = 0.0
        lift_count = 0
        for rec in layout_recommendations:
            # Extract percentage from expected_impact strings like "10-15%"
            impact = str(rec.get("expected_impact", ""))
            # Find patterns like "10-15%" or "20%"
            import re
            pct_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*%", impact)
            for match in pct_matches:
                vals = [float(v) for v in match if v]
                if vals:
                    total_lift += sum(vals) / len(vals) / 100.0
                    lift_count += 1

        estimated_conversion_lift = round(
            total_lift / max(lift_count, 1), 4,
        )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_design_result(
            layout_recommendations=layout_recommendations,
            color_palette=color_palette,
            navigation=navigation,
            mobile_optimizations=mobile_optimizations,
            estimated_conversion_lift=estimated_conversion_lift,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "layout_recommendations": layout_recommendations,
                "color_palette": color_palette,
                "navigation": navigation,
                "mobile_optimizations": mobile_optimizations,
                "estimated_conversion_lift": estimated_conversion_lift,
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
