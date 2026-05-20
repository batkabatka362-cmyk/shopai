"""Cross-Sell Engine — orchestrates the full cross-sell pipeline.

This is the FLOW file.  It ONLY orchestrates — no business logic here.
Every step delegates to a dedicated module; this file wires them together.

Pipeline:
  Cart/Purchase Data -> Purchase Analyzer -> Association Finder ->
  Complement Matcher -> Affinity Scorer -> Bundle Builder ->
  Revenue Estimator -> Recommendation Ranker -> Output

Engine contract:
  Input:  {status, data: {current_cart, customer, catalog}, meta, error}
  Output: {status, data: {recommendations, bundles, estimated_aov_increase,
           confidence}, meta: {engine: "cross_sell"}, error}

Model usage summary:
  - Association Finder:       Mistral (co-purchase association mining)
  - Bundle Builder:           Qwen    (bundle composition & discount)
  - Recommendation Ranker:    LLaMA   (ranking optimization & reasons)
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .purchase_analyzer import analyze_purchases
from .association_finder import find_associations
from .complement_matcher import match_complements
from .affinity_scorer import score_affinity
from .bundle_builder import build_bundles
from .revenue_estimator import estimate_revenue
from .recommendation_ranker import rank_recommendations
from .memory_writer import write_to_memory
from .memory_reader import find_past_cross_sells


class CrossSellEngine:
    """Cross-Sell Engine — orchestrator only, no logic."""

    ENGINE_NAME = "cross_sell"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full cross-sell pipeline.

        Accepts a raw dict (will be validated and deep-copied).
        Returns a CrossSellOutput-shaped dict — always structured,
        never raises.
        """
        start = time.monotonic()

        try:
            return self._execute_pipeline(input_payload, start)
        except Exception as exc:
            return self._error_output(
                reason=f"Unexpected pipeline error: {exc}",
                elapsed=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(
        self,
        input_payload: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        """Run each pipeline stage in sequence, short-circuiting on failure."""

        # Stage 0: Input validation and deep copy
        parsed = self._validate_input(input_payload)
        if parsed is None:
            return self._error_output(
                reason=(
                    "Invalid input: requires 'current_cart' (non-empty list of "
                    "products), 'customer', and 'catalog'."
                ),
                elapsed=time.monotonic() - start,
            )

        current_cart: list[dict[str, Any]] = parsed["current_cart"]
        customer: dict[str, Any] = parsed["customer"]
        catalog: list[dict[str, Any]] = parsed["catalog"]

        # Stage 0.5: Check memory for past cross-sell performance
        cart_product_ids = [
            str(item.get("product_id", ""))
            for item in current_cart
            if isinstance(item, dict) and item.get("product_id")
        ]
        prior = find_past_cross_sells(
            cart_product_ids,
            min_confidence=0.1,
            max_results=3,
        )

        # Stage 1: Purchase Analyzer (no model — deterministic)
        analysis_result = analyze_purchases(current_cart, customer, catalog)
        if analysis_result.get("status") != "success":
            return self._error_output(
                reason=analysis_result.get("error", "Purchase analysis failed."),
                elapsed=time.monotonic() - start,
            )
        analysis = analysis_result["analysis"]

        # Stage 2: Association Finder (model: Mistral)
        association_result = find_associations(analysis, catalog, customer)
        if association_result.get("status") != "success":
            return self._error_output(
                reason=association_result.get("error", "Association finding failed."),
                elapsed=time.monotonic() - start,
            )
        associations = association_result["associations"]

        # Stage 3: Complement Matcher (no model — rule-based)
        complement_result = match_complements(analysis, associations, catalog)
        if complement_result.get("status") != "success":
            return self._error_output(
                reason=complement_result.get("error", "Complement matching failed."),
                elapsed=time.monotonic() - start,
            )
        complements = complement_result["complements"]

        # Stage 4: Affinity Scorer (no model — deterministic scoring)
        affinity_result = score_affinity(complements, associations, analysis)
        if affinity_result.get("status") != "success":
            return self._error_output(
                reason=affinity_result.get("error", "Affinity scoring failed."),
                elapsed=time.monotonic() - start,
            )
        scored_products = affinity_result["scored_products"]

        # Stage 5: Bundle Builder (model: Qwen)
        bundle_result = build_bundles(scored_products, analysis)
        if bundle_result.get("status") != "success":
            return self._error_output(
                reason=bundle_result.get("error", "Bundle building failed."),
                elapsed=time.monotonic() - start,
            )
        bundles = bundle_result["bundles"]

        # Stage 6: Revenue Estimator (no model — deterministic)
        revenue_result = estimate_revenue(scored_products, bundles, analysis)
        if revenue_result.get("status") != "success":
            return self._error_output(
                reason=revenue_result.get("error", "Revenue estimation failed."),
                elapsed=time.monotonic() - start,
            )
        estimates = revenue_result["estimates"]
        aggregate = revenue_result.get("aggregate", {})

        # Stage 7: Recommendation Ranker (model: LLaMA)
        ranking_result = rank_recommendations(scored_products, estimates, analysis)
        if ranking_result.get("status") != "success":
            return self._error_output(
                reason=ranking_result.get("error", "Recommendation ranking failed."),
                elapsed=time.monotonic() - start,
            )
        recommendations = ranking_result["recommendations"]

        # Stage 8: Build final output
        elapsed = time.monotonic() - start

        # Compute overall confidence from recommendation scores
        if recommendations:
            avg_score = sum(
                r.get("score", 0) for r in recommendations
            ) / len(recommendations)
            # Normalize: scores vary widely, map to 0-1 confidence
            confidence = min(round(avg_score / 100, 4), 1.0) if avg_score > 0 else 0.0
        else:
            confidence = 0.0

        estimated_aov_increase = aggregate.get("total_aov_increase", 0.0)

        # Stage 7.5: Phase 7 writeback (opt-in) -----------
        # Engines today emit advisory cross-sell
        # recommendations. When the caller passes
        # ``data.apply_cross_sell_tags=True``, we push
        # ``shopai-cross-sell-target`` (additive) on every
        # recommended product via SHOPIFY_ADD_TAGS. Merchants
        # save admin searches for the tag, build smart
        # collections, AND downstream engines (email_marketing
        # / catalog) filter on it to feature cross-sell
        # candidates in "complete the set" campaigns.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue each tag-add via
        #     approval queue. Operator reviews before write
        #     lands.
        #   * False -- call SHOPIFY_ADD_TAGS directly via the
        #     router. Used by cycles that already gate this
        #     engine via the auto-approve allowlist.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        data_in = input_payload.get("data") if isinstance(input_payload, dict) else None
        opt_in = (
            isinstance(data_in, dict)
            and data_in.get("apply_cross_sell_tags") is True
        )
        tag_results: list[dict[str, Any]] = []
        if opt_in:
            try:
                from .tag_applier import apply_cross_sell_tags
                require_approval = bool(
                    (data_in or {}).get("require_approval", True),
                )
                tag_results = apply_cross_sell_tags(
                    recommendations,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises
                # out by design, but a stray import / typo
                # shouldn't poison the engine's primary
                # output.
                import logging
                logging.getLogger(__name__).debug(
                    "cross_sell tag_applier raised: %s", exc,
                )

        output: dict[str, Any] = {
            "status": "success",
            "data": {
                "recommendations": recommendations,
                "bundles": bundles,
                "estimated_aov_increase": estimated_aov_increase,
                "confidence": confidence,
                # Phase 7 writeback: per-product tag results
                # when opted in. Empty otherwise.
                "tag_results": tag_results,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
                "models": {
                    "association_finder": "mistral",
                    "bundle_builder": "qwen",
                    "recommendation_ranker": "llama",
                },
                "pipeline_stats": {
                    "cart_value": analysis.get("total_cart_value", 0.0),
                    "cart_items": len(current_cart),
                    "catalog_size": len(catalog),
                    "associations_found": len(associations.get("rules", [])),
                    "complements_matched": len(complements),
                    "products_scored": len(scored_products),
                    "bundles_built": len(bundles),
                    "recommendations_ranked": len(recommendations),
                },
                "prior_cross_sells_found": len(prior),
            },
            "error": None,
        }

        # Stage 9: Persist to memory
        write_to_memory(output)

        return output

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(
        self, payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Validate and normalise the input into a usable dict.

        Returns ``None`` if the input is unusable.
        Never mutates *payload*.
        """
        if not isinstance(payload, dict):
            return None

        safe = copy.deepcopy(payload)

        # Engine contract: payload is {status, data, meta, error}
        data = safe.get("data", safe)  # fallback to raw dict
        if not isinstance(data, dict):
            return None

        current_cart = data.get("current_cart", [])
        if not isinstance(current_cart, list) or not current_cart:
            return None

        # Validate cart items have at minimum product_id
        valid_items = [
            item for item in current_cart
            if isinstance(item, dict) and item.get("product_id")
        ]
        if not valid_items:
            return None

        customer = data.get("customer", {})
        if not isinstance(customer, dict):
            customer = {}
        customer.setdefault("past_purchases", [])
        customer.setdefault("preferences", [])

        catalog = data.get("catalog", [])
        if not isinstance(catalog, list):
            catalog = []

        # If catalog is empty, build minimal catalog from cart items
        if not catalog:
            catalog = [
                {
                    "product_id": item.get("product_id", ""),
                    "title": item.get("title", ""),
                    "category": item.get("category", "general"),
                    "price": item.get("price", 0),
                    "margin": 0.3,
                }
                for item in valid_items
            ]

        return {
            "current_cart": valid_items,
            "customer": customer,
            "catalog": catalog,
        }

    # ------------------------------------------------------------------
    # Error output helper
    # ------------------------------------------------------------------

    def _error_output(self, *, reason: str, elapsed: float) -> dict[str, Any]:
        """Build a well-formed error response."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
