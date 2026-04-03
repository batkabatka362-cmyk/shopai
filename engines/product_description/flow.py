"""Product Description Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Memory Reader → Feature Extractor → Copy Writer →
  SEO Optimizer → Tone Adjuster → Memory Writer → Output

Engine contract:
  Input:  {status, data: {product, brand_voice, target_keywords, competitors}, meta, error}
  Output: {status, data: {title, subtitle, bullet_points, description, meta_title, meta_description, seo_score, variations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .feature_extractor import extract_features
from .copy_writer import write_copy
from .seo_optimizer import optimize_seo
from .tone_adjuster import adjust_tone
from .memory_reader import read_past_descriptions
from .memory_writer import write_description_result


class ProductDescriptionEngine:
    """Product Description Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_description"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full product description pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ProductDescOutput dict.
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

        product = data.get("product", {})
        brand_voice = data.get("brand_voice", {})
        target_keywords = data.get("target_keywords", [])
        competitors = data.get("competitors", [])

        if not product:
            return self._fail("product is required", 0.0)

        # ---- Stage 1: Read past descriptions (non-blocking) ----
        _past = read_past_descriptions(limit=5)

        # ---- Stage 2: Feature Extractor ----
        feature_result = extract_features(
            product=product,
            competitors=competitors,
        )
        if feature_result.get("status") == "error":
            return self._fail(
                f"Feature extraction failed: {feature_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        features = feature_result.get("features", [])

        # ---- Stage 3: Copy Writer ----
        copy_result = write_copy(
            product=product,
            features=features,
            brand_voice=brand_voice,
            target_keywords=target_keywords,
        )
        if copy_result.get("status") == "error":
            return self._fail(
                f"Copy writing failed: {copy_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        copy_data = copy_result.get("copy", {})

        # ---- Stage 4: SEO Optimizer ----
        seo_result = optimize_seo(
            copy_data=copy_data,
            target_keywords=target_keywords,
            product=product,
        )
        if seo_result.get("status") == "error":
            return self._fail(
                f"SEO optimization failed: {seo_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        seo_data = seo_result.get("seo", {})

        # ---- Stage 5: Tone Adjuster ----
        tone_result = adjust_tone(
            copy_data=copy_data,
            brand_voice=brand_voice,
        )
        if tone_result.get("status") == "error":
            return self._fail(
                f"Tone adjustment failed: {tone_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        variations = tone_result.get("variations", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        title = str(copy_data.get("title", ""))
        subtitle = str(copy_data.get("subtitle", ""))
        bullet_points = list(copy_data.get("bullet_points", []))
        description = str(copy_data.get("description", ""))
        meta_title = str(seo_data.get("meta_title", ""))
        meta_description = str(seo_data.get("meta_description", ""))
        seo_score = float(seo_data.get("seo_score", 0.0))

        _write_result = write_description_result(
            title=title,
            description=description,
            bullet_points=bullet_points,
            seo_score=seo_score,
            variations_count=len(variations),
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "title": title,
                "subtitle": subtitle,
                "bullet_points": bullet_points,
                "description": description,
                "meta_title": meta_title,
                "meta_description": meta_description,
                "seo_score": seo_score,
                "variations": variations,
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
