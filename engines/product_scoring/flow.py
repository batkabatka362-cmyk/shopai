"""Product Scoring Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Products → Demand Scorer → Margin Scorer → Competition Scorer →
  Composite Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, criteria}, meta, error}
  Output: {status, data: {scored_products, score_distribution, avg_composite_score}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .demand_scorer import score_demand
from .margin_scorer import score_margins
from .competition_scorer import score_competition
from .composite_builder import build_composite
from .memory_reader import read_past_scores
from .memory_writer import write_scoring_result
from engines._shopify_hydrator import hydrate


class ProductScoringEngine:
    """Product Scoring Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_scoring"

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

        _past = read_past_scores(limit=5)

        # Stage 1: Demand Scorer
        demand_result = score_demand(products=products)
        if demand_result.get("status") == "error":
            return self._fail(f"Demand scoring failed: {demand_result.get('error', 'unknown')}", time.monotonic() - start)
        demand_scores = demand_result.get("scores", [])

        # Stage 2: Margin Scorer
        margin_result = score_margins(products=products)
        if margin_result.get("status") == "error":
            return self._fail(f"Margin scoring failed: {margin_result.get('error', 'unknown')}", time.monotonic() - start)
        margin_scores = margin_result.get("scores", [])

        # Stage 3: Competition Scorer
        competition_result = score_competition(products=products)
        if competition_result.get("status") == "error":
            return self._fail(f"Competition scoring failed: {competition_result.get('error', 'unknown')}", time.monotonic() - start)
        competition_scores = competition_result.get("scores", [])

        # Stage 4: Composite Builder
        composite_result = build_composite(
            products=products,
            demand_scores=demand_scores,
            margin_scores=margin_scores,
            competition_scores=competition_scores,
            criteria=criteria,
        )
        if composite_result.get("status") == "error":
            return self._fail(f"Composite build failed: {composite_result.get('error', 'unknown')}", time.monotonic() - start)
        scored_products = composite_result.get("scored_products", [])
        score_distribution = composite_result.get("score_distribution", {})
        avg_score = composite_result.get("avg_composite_score", 0.0)

        _write_result = write_scoring_result(
            scored_products=scored_products,
            score_distribution=score_distribution,
            avg_composite_score=avg_score,
        )

        # ---- Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory tier classifications.
        # When the caller passes ``data.apply_scoring_tags=True``,
        # we push ``shopai-tier-{A|B}`` on every top-tier
        # product via SHOPIFY_ADD_TAGS. Merchants then save
        # admin searches / smart collections to drive an
        # "investment-worthy" worklist; downstream engines
        # (paid_ads / catalog / storefront) prefer A/B tiers
        # for ad spend, featured slots, and homepage
        # carousels.
        #
        # Only ``A`` is tagged by default;
        # ``data.include_b=True`` opts in ``B`` too. ``C`` /
        # ``D`` are noise.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue via approval queue.
        #   * False -- call SHOPIFY_ADD_TAGS directly.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_scoring_tags") is True:
            try:
                from .tag_applier import apply_scoring_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                include_b = bool(data.get("include_b", False))
                tag_results = apply_scoring_tags(
                    scored_products,
                    include_b=include_b,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises
                # out by design.
                import logging
                logging.getLogger(__name__).debug(
                    "product_scoring tag_applier raised: %s",
                    exc,
                )

        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "scored_products": scored_products,
                "score_distribution": score_distribution,
                "avg_composite_score": avg_score,
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
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
