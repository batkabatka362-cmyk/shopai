"""Product Ranking Engine — flow orchestrator.

Pipeline:
  Products -> Weight Calculator -> Rank Builder -> Tie Breaker ->
  Explanation Builder -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {products, criteria}, meta, error}
  Output: {status, data: {ranked_products, total_ranked, top_tier_count}, meta, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .weight_calculator import calculate_weights
from .rank_builder import build_ranks
from .tie_breaker import break_ties
from .explanation_builder import build_explanations
from .memory_reader import read_past_rankings
from .memory_writer import write_ranking_result
from engines._shopify_hydrator import hydrate


class ProductRankingEngine:
    """Product Ranking Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_ranking"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        products = data.get("products", [])
        criteria = data.get("criteria", {})

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

        _past = read_past_rankings(limit=5)

        # Stage 1: Weight Calculator
        weight_result = calculate_weights(products=products, criteria=criteria)
        if weight_result.get("status") == "error":
            return self._fail(f"Weight calculation failed: {weight_result.get('error', 'unknown')}", time.monotonic() - start)
        weighted_products = weight_result.get("weighted_products", [])

        # Stage 2: Rank Builder
        rank_result = build_ranks(weighted_products=weighted_products)
        if rank_result.get("status") == "error":
            return self._fail(f"Rank building failed: {rank_result.get('error', 'unknown')}", time.monotonic() - start)
        ranked_products = rank_result.get("ranked_products", [])

        # Stage 3: Tie Breaker
        tie_result = break_ties(ranked_products=ranked_products)
        if tie_result.get("status") == "error":
            return self._fail(f"Tie breaking failed: {tie_result.get('error', 'unknown')}", time.monotonic() - start)
        final_ranked = tie_result.get("ranked_products", [])

        # Stage 4: Explanation Builder
        explain_result = build_explanations(ranked_products=final_ranked, criteria=criteria)
        if explain_result.get("status") == "error":
            return self._fail(f"Explanation building failed: {explain_result.get('error', 'unknown')}", time.monotonic() - start)
        explained = explain_result.get("ranked_products", [])

        top_tier = sum(1 for p in explained if p.get("rank", 999) <= 3)

        _write = write_ranking_result(
            ranked_products=explained,
            total_ranked=len(explained),
            top_tier_count=top_tier,
        )

        # ---- Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory ranks. When the caller
        # passes ``data.apply_ranking_tags=True``, we push
        # ``shopai-rank-top`` (additive) on every top-N
        # ranked product via SHOPIFY_ADD_TAGS. Merchants then
        # save admin searches / "top picks" smart collections,
        # AND downstream engines (email_marketing /
        # storefront) filter on the tag to feature top-ranked
        # SKUs in homepage carousels, "featured" sections, or
        # upsell slots.
        #
        # ``data.top_n`` (default 10) controls cohort size.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue via approval queue.
        #   * False -- call SHOPIFY_ADD_TAGS directly.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_ranking_tags") is True:
            try:
                from .tag_applier import apply_ranking_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                top_n = int(data.get("top_n", 10) or 10)
                tag_results = apply_ranking_tags(
                    explained,
                    top_n=top_n,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises
                # out by design.
                import logging
                logging.getLogger(__name__).debug(
                    "product_ranking tag_applier raised: %s",
                    exc,
                )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "ranked_products": explained,
                "total_ranked": len(explained),
                "top_tier_count": top_tier,
                # Phase 7 writeback: per-product tag results
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

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
