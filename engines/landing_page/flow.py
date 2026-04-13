"""Landing Page Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data -> Page Generator -> Headline Optimizer -> CTA Optimizer ->
  Performance Scorer -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {product, campaign, target_audience, brand_voice}, meta, error}
  Output: {status, data: {pages, best_variant, estimated_conversion}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .page_generator import generate_page
from .headline_optimizer import optimize_headlines
from .cta_optimizer import optimize_ctas
from .performance_scorer import score_performance
from .memory_reader import read_past_pages
from .memory_writer import write_page_result


class LandingPageEngine:
    """Landing Page Engine — orchestrator only, no logic."""

    ENGINE_NAME = "landing_page"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full landing page pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            LandingPageOutput dict.
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
        campaign = data.get("campaign", {})
        target_audience = str(data.get("target_audience", "general"))
        brand_voice = str(data.get("brand_voice", "professional"))

        if not product:
            return self._fail("Product data is required", 0.0)

        # ---- Stage 1: Read past pages (non-blocking) ----
        _past = read_past_pages(limit=5)

        # ---- Stage 2: Page Generator ----
        page_result = generate_page(
            product=product,
            campaign=campaign,
            target_audience=target_audience,
            brand_voice=brand_voice,
        )
        if page_result.get("status") == "error":
            return self._fail(
                f"Page generation failed: {page_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        base_page = page_result.get("page", {})

        # ---- Stage 3: Headline Optimizer ----
        headline_result = optimize_headlines(
            base_page=base_page,
            product=product,
            target_audience=target_audience,
            brand_voice=brand_voice,
        )
        if headline_result.get("status") == "error":
            return self._fail(
                f"Headline optimization failed: {headline_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        headline_variants = headline_result.get("variants", [])

        # ---- Stage 4: CTA Optimizer ----
        cta_result = optimize_ctas(
            base_page=base_page,
            campaign=campaign,
            target_audience=target_audience,
        )
        if cta_result.get("status") == "error":
            return self._fail(
                f"CTA optimization failed: {cta_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        cta_variants = cta_result.get("variants", [])

        # ---- Stage 5: Assemble page variants ----
        pages: list[dict[str, Any]] = []
        for i, headline_var in enumerate(headline_variants):
            cta_var = cta_variants[i] if i < len(cta_variants) else cta_variants[0] if cta_variants else {}
            pages.append({
                "headline": str(headline_var.get("text", base_page.get("headline", ""))),
                "subheadline": str(base_page.get("subheadline", "")),
                "hero_section": str(base_page.get("hero_section", "")),
                "benefits": list(base_page.get("benefits", [])),
                "cta": str(cta_var.get("text", base_page.get("cta", ""))),
                "social_proof": str(base_page.get("social_proof", "")),
            })

        # Ensure at least the base page is present
        if not pages:
            pages.append({
                "headline": str(base_page.get("headline", "")),
                "subheadline": str(base_page.get("subheadline", "")),
                "hero_section": str(base_page.get("hero_section", "")),
                "benefits": list(base_page.get("benefits", [])),
                "cta": str(base_page.get("cta", "")),
                "social_proof": str(base_page.get("social_proof", "")),
            })

        # ---- Stage 6: Performance Scorer ----
        score_result = score_performance(pages=pages)
        if score_result.get("status") == "error":
            return self._fail(
                f"Performance scoring failed: {score_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scores = score_result.get("scores", [])

        # Determine best variant
        best_variant = 0
        best_score = 0.0
        for idx, sc in enumerate(scores):
            overall = float(sc.get("overall", 0.0))
            if overall > best_score:
                best_score = overall
                best_variant = idx

        estimated_conversion = round(best_score * 0.08, 4)  # Scale to realistic %

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_page_result(
            pages=pages,
            best_variant=best_variant,
            estimated_conversion=estimated_conversion,
        )

        # ---- Stage 8: Return output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "pages": pages,
                "best_variant": best_variant,
                "estimated_conversion": estimated_conversion,
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
