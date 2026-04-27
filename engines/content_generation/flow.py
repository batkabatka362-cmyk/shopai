"""Content Generation Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Content Request → Brief Analyzer → Tone Selector → Keyword Extractor →
  Copy Writer → SEO Optimizer → Format Adapter → Quality Checker → Output

Engine contract:
  Input:  {status, data: {type, product: {title, features, price, category,
           target_audience}, brand: {name, voice, values}, platform}, meta, error}
  Output: {status, data: {content: {headline, body, bullets, cta,
           meta_description}, seo_score, readability_score, variations,
           confidence}, meta: {engine, ...}, error}

Models: Mistral=analysis/quality, Qwen=formatting, LLaMA=creative writing.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .brief_analyzer import analyze_brief
from .tone_selector import select_tone
from .keyword_extractor import extract_keywords
from .copy_writer import write_copy
from .seo_optimizer import optimize_seo
from .format_adapter import adapt_format
from .quality_checker import check_quality
from .variation_generator import generate_variations
from .memory_reader import read_past_content
from .memory_writer import write_content_result
from .content_applier import apply_description


class ContentGenerationEngine:
    """Content Generation Engine — orchestrator only, no logic."""

    ENGINE_NAME = "content_generation"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full content generation pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ContentGenerationOutput dict.
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

        content_type = str(data.get("type", "product_description")).strip()
        product = data.get("product", {})
        brand = data.get("brand", {})
        platform = str(data.get("platform", "web")).strip()

        if not isinstance(product, dict) or not product:
            return self._fail("No product data provided", 0.0)

        # ---- Stage 1: Read past content (non-blocking) ----
        _past = read_past_content(limit=5, content_type=content_type)

        # ---- Stage 2: Brief Analyzer (Mistral) ----
        brief_result = analyze_brief(content_type, product, brand)
        if brief_result.get("status") == "error":
            return self._fail(
                f"Brief analysis failed: {brief_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        analysis = brief_result.get("analysis", {})

        # ---- Stage 3: Tone Selector ----
        tone_result = select_tone(
            content_type=analysis.get("content_type", content_type),
            brand=brand,
            target_audience=analysis.get("target_audience", "general consumer"),
        )
        if tone_result.get("status") == "error":
            return self._fail(
                f"Tone selection failed: {tone_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tone = tone_result.get("selection", {})

        # ---- Stage 4: Keyword Extractor ----
        kw_result = extract_keywords(product, brand)
        if kw_result.get("status") == "error":
            return self._fail(
                f"Keyword extraction failed: {kw_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        keywords = kw_result.get("extraction", {})

        # ---- Stage 5: Copy Writer (LLaMA) ----
        copy_result = write_copy(
            brief_analysis=analysis,
            tone_selection=tone,
            keyword_extraction=keywords,
            product=product,
            brand=brand,
        )
        if copy_result.get("status") == "error":
            return self._fail(
                f"Copy writing failed: {copy_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        draft = copy_result.get("draft", {})

        # ---- Stage 6: SEO Optimizer ----
        seo_result = optimize_seo(
            draft=draft,
            keyword_extraction=keywords,
            product=product,
        )
        if seo_result.get("status") == "error":
            return self._fail(
                f"SEO optimization failed: {seo_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        seo = seo_result.get("seo", {})

        # ---- Stage 7: Format Adapter (Qwen) ----
        format_result = adapt_format(
            draft=draft,
            seo_result=seo,
            platform=platform,
        )
        if format_result.get("status") == "error":
            return self._fail(
                f"Format adaptation failed: {format_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        formatted = format_result.get("formatted", {})

        # ---- Stage 8: Quality Checker (Mistral) ----
        quality_result = check_quality(
            draft=draft,
            tone_selection=tone,
            keyword_extraction=keywords,
        )
        if quality_result.get("status") == "error":
            return self._fail(
                f"Quality check failed: {quality_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        quality = quality_result.get("quality", {})

        # ---- Stage 9: Variation Generator ----
        var_result = generate_variations(
            draft=draft,
            brief_analysis=analysis,
            max_variations=3,
        )
        variations = var_result.get("variations", [])

        # ---- Stage 10: Assemble content block ----
        seo_score = float(seo.get("seo_score", 0.0))
        readability_score = float(quality.get("readability_score", 0.0))
        overall_quality = float(quality.get("overall_quality", 0.0))

        # Confidence: weighted average of SEO, readability-normalized, quality
        readability_norm = min(readability_score / 100.0, 1.0)
        confidence = round(
            0.3 * seo_score + 0.3 * readability_norm + 0.4 * overall_quality,
            2,
        )

        content_block: dict[str, Any] = {
            "headline": draft.get("headline", ""),
            "body": draft.get("body", ""),
            "bullets": draft.get("bullets", []),
            "cta": draft.get("cta", ""),
            "meta_description": seo.get("meta_description", ""),
        }

        # ---- Stage 10b: Description writeback (opt-in) ----
        # When ``data.apply_content == True`` AND content_type is
        # ``product_description``, push the generated body into
        # SHOPIFY_UPDATE_PRODUCT.descriptionHtml. Default OFF —
        # this overwrites existing product copy and needs explicit
        # opt-in. Optional ``min_seo_score`` /
        # ``min_readability_score`` floors gate on quality.
        apply_result: dict[str, Any] | None = None
        if data.get("apply_content") is True:
            apply_result = apply_description(
                product=product,
                content_block=content_block,
                content_type=analysis.get("content_type", content_type),
                seo_score=seo_score,
                readability_score=readability_score,
                min_seo_score=float(
                    data.get("min_apply_seo_score", 0.0),
                ),
                min_readability_score=float(
                    data.get("min_apply_readability_score", 0.0),
                ),
            )

        # ---- Stage 11: Memory Writer (non-fatal) ----
        _write_result = write_content_result(
            content=content_block,
            seo_score=seo_score,
            readability_score=readability_score,
            content_type=analysis.get("content_type", content_type),
            platform=platform,
            confidence=confidence,
            variation_count=len(variations),
        )

        # ---- Stage 12: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "content": content_block,
                "seo_score": seo_score,
                "readability_score": readability_score,
                "variations": variations,
                "confidence": confidence,
                "apply_result": apply_result,
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
