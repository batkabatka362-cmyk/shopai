"""Search Optimization Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data -> Keyword Analyzer -> Meta Generator -> Content Scorer ->
  Sitemap Builder -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {products, search_queries, current_meta, competitors}, meta, error}
  Output: {status, data: {keyword_analysis, meta_recommendations, content_scores, sitemap}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .keyword_analyzer import analyze_keywords
from .meta_generator import generate_meta
from .content_scorer import score_content
from .sitemap_builder import build_sitemap
from .memory_reader import read_past_optimizations
from .memory_writer import write_optimization_result
from .seo_applier import apply_meta
from engines._shopify_hydrator import hydrate


class SearchOptimizationEngine:
    """Search Optimization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "search_optimization"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full search optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SearchOptimizationOutput dict.
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
        search_queries = data.get("search_queries", [])
        current_meta = data.get("current_meta", [])
        competitors = data.get("competitors", [])

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
            return self._fail("Products list is required", 0.0)

        # ---- Stage 1: Read past optimizations (non-blocking) ----
        _past = read_past_optimizations(limit=5)

        # ---- Stage 2: Keyword Analyzer ----
        keyword_result = analyze_keywords(
            products=products,
            search_queries=search_queries,
            competitors=competitors,
        )
        if keyword_result.get("status") == "error":
            return self._fail(
                f"Keyword analysis failed: {keyword_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        keyword_analysis = keyword_result.get("keyword_analysis", [])

        # ---- Stage 3: Meta Generator ----
        meta_result = generate_meta(
            products=products,
            current_meta=current_meta,
            keyword_analysis=keyword_analysis,
        )
        if meta_result.get("status") == "error":
            return self._fail(
                f"Meta generation failed: {meta_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        meta_recommendations = meta_result.get("meta_recommendations", [])

        # ---- Stage 4: Content Scorer ----
        content_result = score_content(
            products=products,
            current_meta=current_meta,
            keyword_analysis=keyword_analysis,
        )
        if content_result.get("status") == "error":
            return self._fail(
                f"Content scoring failed: {content_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        content_scores = content_result.get("content_scores", [])

        # ---- Stage 5: Sitemap Builder ----
        sitemap_result = build_sitemap(
            products=products,
            content_scores=content_scores,
        )
        if sitemap_result.get("status") == "error":
            return self._fail(
                f"Sitemap building failed: {sitemap_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sitemap = sitemap_result.get("sitemap", [])

        # ---- Stage 5b: SEO meta applier (opt-in writeback) ----
        # Push the proposed meta titles + descriptions into Shopify
        # via SHOPIFY_UPDATE_PRODUCT.seo. Default OFF — opt in via
        # ``data.apply_seo == True``. The current_meta input
        # doubles as the diff base: recommendations matching the
        # current value short-circuit (no API call).
        apply_results: list[dict[str, Any]] = []
        if data.get("apply_seo") is True:
            apply_results = apply_meta(
                recommendations=meta_recommendations,
                current_meta=current_meta,
            )

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_optimization_result(
            keyword_analysis=keyword_analysis,
            meta_recommendations=meta_recommendations,
            content_scores=content_scores,
            sitemap=sitemap,
        )

        # ---- Stage 7: Return output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "keyword_analysis": keyword_analysis,
                "meta_recommendations": meta_recommendations,
                "content_scores": content_scores,
                "sitemap": sitemap,
                "apply_results": apply_results,
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
