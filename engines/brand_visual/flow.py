"""Brand Visual Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Brand Identity → Color Palette Builder → Typography Selector →
  Imagery Stylist → Style Guide Compiler → Memory Writer → Output

Engine contract:
  Input:  {status, data: {brand_identity, industry, competitors, preferences}, meta, error}
  Output: {status, data: {colors, typography, imagery, style_guide}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .color_palette_builder import build_color_palette
from .typography_selector import select_typography
from .imagery_stylist import define_imagery_style
from .style_guide_compiler import compile_style_guide
from .memory_reader import read_past_visuals
from .memory_writer import write_visual_result


class BrandVisualEngine:
    """Brand Visual Engine — orchestrator only, no logic."""

    ENGINE_NAME = "brand_visual"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full brand visual pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BrandVisualOutput dict.
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

        brand_identity = data.get("brand_identity", {})
        if not isinstance(brand_identity, dict):
            return self._fail("brand_identity must be a dict", 0.0)

        industry = str(data.get("industry", "general"))
        competitors = data.get("competitors", [])
        preferences = data.get("preferences", {})

        # ---- Stage 1: Read past visuals (non-blocking) ----
        _past = read_past_visuals(limit=5)

        # ---- Stage 2: Color Palette Builder ----
        color_result = build_color_palette(
            brand_identity=brand_identity,
            industry=industry,
            preferences=preferences,
        )
        if color_result.get("status") == "error":
            return self._fail(
                f"Color palette building failed: {color_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        colors = color_result.get("colors", {})

        # ---- Stage 3: Typography Selector ----
        typo_result = select_typography(
            brand_identity=brand_identity,
            preferences=preferences,
        )
        if typo_result.get("status") == "error":
            return self._fail(
                f"Typography selection failed: {typo_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        typography = typo_result.get("typography", {})

        # ---- Stage 4: Imagery Stylist ----
        imagery_result = define_imagery_style(
            brand_identity=brand_identity,
            industry=industry,
        )
        if imagery_result.get("status") == "error":
            return self._fail(
                f"Imagery styling failed: {imagery_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        imagery = imagery_result.get("imagery", {})

        # ---- Stage 5: Style Guide Compiler ----
        guide_result = compile_style_guide(
            colors=colors,
            typography=typography,
            imagery=imagery,
            industry=industry,
        )
        if guide_result.get("status") == "error":
            return self._fail(
                f"Style guide compilation failed: {guide_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        style_guide = guide_result.get("style_guide", {})

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_visual_result(
            colors=colors,
            typography=typography,
            imagery=imagery,
            style_guide=style_guide,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "colors": {
                    "primary": colors.get("primary", ""),
                    "secondary": colors.get("secondary", ""),
                    "accent": colors.get("accent", ""),
                    "background": colors.get("background", ""),
                    "text": colors.get("text", ""),
                },
                "typography": {
                    "heading_font": typography.get("heading_font", ""),
                    "body_font": typography.get("body_font", ""),
                    "sizes": typography.get("sizes", {}),
                },
                "imagery": {
                    "style": imagery.get("style", ""),
                    "mood": imagery.get("mood", ""),
                    "composition_rules": imagery.get("composition_rules", []),
                },
                "style_guide": style_guide,
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
