"""Image Optimization Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Memory Reader → Quality Analyzer → Alt Text Generator →
  Size Optimizer → Gallery Planner → Memory Writer → Output

Engine contract:
  Input:  {status, data: {images, product, platform}, meta, error}
  Output: {status, data: {optimizations, gallery_order, missing_types, quality_scores}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .quality_analyzer import analyze_quality
from .alt_text_generator import generate_alt_texts
from .size_optimizer import optimize_sizes
from .gallery_planner import plan_gallery
from .memory_reader import read_past_optimizations
from .memory_writer import write_optimization_result


class ImageOptimizationEngine:
    """Image Optimization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "image_optimization"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full image optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ImageOptOutput dict.
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

        images = data.get("images", [])
        product = data.get("product", {})
        platform = str(data.get("platform", "web"))

        if not images:
            return self._fail("images list is required", 0.0)

        # ---- Stage 1: Read past optimizations (non-blocking) ----
        _past = read_past_optimizations(limit=5)

        # ---- Stage 2: Quality Analyzer ----
        quality_result = analyze_quality(
            images=images,
            platform=platform,
        )
        if quality_result.get("status") == "error":
            return self._fail(
                f"Quality analysis failed: {quality_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        quality_analyses = quality_result.get("analyses", [])
        quality_scores = quality_result.get("quality_scores", {})

        # ---- Stage 3: Alt Text Generator ----
        alt_result = generate_alt_texts(
            images=images,
            product=product,
            quality_analyses=quality_analyses,
        )
        if alt_result.get("status") == "error":
            return self._fail(
                f"Alt text generation failed: {alt_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alt_texts = alt_result.get("alt_texts", [])

        # ---- Stage 4: Size Optimizer ----
        size_result = optimize_sizes(
            images=images,
            platform=platform,
            quality_analyses=quality_analyses,
        )
        if size_result.get("status") == "error":
            return self._fail(
                f"Size optimization failed: {size_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        size_recommendations = size_result.get("recommendations", [])

        # ---- Stage 5: Gallery Planner ----
        gallery_result = plan_gallery(
            images=images,
            quality_analyses=quality_analyses,
            product=product,
        )
        if gallery_result.get("status") == "error":
            return self._fail(
                f"Gallery planning failed: {gallery_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        gallery_order = gallery_result.get("gallery_order", [])
        missing_types = gallery_result.get("missing_types", [])

        # ---- Stage 6: Build unified optimizations list ----
        alt_map = {a["image_id"]: a for a in alt_texts}
        size_map = {s["image_id"]: s for s in size_recommendations}

        optimizations: list[dict[str, Any]] = []
        for i in range(len(images)):
            alt_info = alt_map.get(i, {})
            size_info = size_map.get(i, {})

            # Priority: images with more issues get higher priority
            qa = next((q for q in quality_analyses if q.get("image_id") == i), {})
            issue_count = len(qa.get("issues", []))
            priority = max(1, issue_count + 1)

            optimizations.append({
                "image_id": i,
                "recommended_size": int(size_info.get("recommended_size_bytes", 0)),
                "alt_text": str(alt_info.get("alt_text", "")),
                "compression": str(size_info.get("compression", "none")),
                "priority": priority,
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_optimization_result(
            optimizations=optimizations,
            gallery_order=gallery_order,
            missing_types=missing_types,
            quality_scores=quality_scores,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "optimizations": optimizations,
                "gallery_order": gallery_order,
                "missing_types": missing_types,
                "quality_scores": quality_scores,
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
