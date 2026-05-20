"""Upsell Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Memory Reader → Product Analyzer → Upgrade Finder → Price Gap Analyzer →
  Value Proposition Builder → Conversion Estimator → Timing Optimizer →
  Recommendation Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {current_product, customer, catalog}, meta, error}
  Output: {status, data: {upsells, best_upsell, estimated_revenue_increase, confidence}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .product_analyzer import analyze_product
from .upgrade_finder import find_upgrades
from .price_gap_analyzer import analyze_price_gaps
from .value_proposition_builder import build_value_propositions
from .conversion_estimator import estimate_conversions
from .timing_optimizer import optimize_timing
from .recommendation_builder import build_recommendations
from .memory_reader import read_past_upsells
from .memory_writer import write_upsell_result


class UpsellEngine:
    """Upsell Engine — orchestrator only, no logic."""

    ENGINE_NAME = "upsell"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full upsell pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            UpsellOutput dict.
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

        current_product = data.get("current_product", {})
        customer = data.get("customer", {})
        catalog = data.get("catalog", [])

        if not current_product:
            return self._fail("current_product is required", 0.0)
        if not catalog:
            return self._fail("catalog is required (at least one product)", 0.0)

        current_price = float(current_product.get("price", 0))
        category = str(current_product.get("category", "general"))
        current_features = current_product.get("features", [])

        # ---- Stage 1: Memory Reader (non-blocking) ----
        _past = read_past_upsells(limit=5, category=category)

        # ---- Stage 2: Product Analyzer ----
        analysis_result = analyze_product(current_product=current_product)
        if analysis_result.get("status") == "error":
            return self._fail(
                f"Product analysis failed: {analysis_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        analysis = analysis_result.get("analysis", {})

        # ---- Stage 3: Upgrade Finder (Mistral) ----
        upgrade_result = find_upgrades(
            analysis=analysis,
            catalog=catalog,
            current_features=current_features,
        )
        if upgrade_result.get("status") == "error":
            return self._fail(
                f"Upgrade finding failed: {upgrade_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        candidates = upgrade_result.get("candidates", [])

        if not candidates:
            # No upgrade candidates — return empty but successful result
            elapsed = time.monotonic() - start
            return {
                "status": "success",
                "data": {
                    "upsells": [],
                    "best_upsell": None,
                    "estimated_revenue_increase": 0.0,
                    "confidence": 0.0,
                },
                "meta": {
                    "engine": self.ENGINE_NAME,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "elapsed_seconds": round(elapsed, 3),
                    "candidates_evaluated": 0,
                    "candidates_recommended": 0,
                },
                "error": None,
            }

        # ---- Stage 4: Price Gap Analyzer ----
        gap_result = analyze_price_gaps(
            candidates=candidates,
            current_price=current_price,
            customer_aov=float(customer.get("avg_order_value", 0)),
        )
        if gap_result.get("status") == "error":
            return self._fail(
                f"Price gap analysis failed: {gap_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_gaps = gap_result.get("analyses", [])

        # ---- Stage 5: Value Proposition Builder (LLaMA) ----
        prop_result = build_value_propositions(
            candidates=candidates,
            price_gaps=price_gaps,
            current_product=current_product,
        )
        if prop_result.get("status") == "error":
            return self._fail(
                f"Value proposition building failed: {prop_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        value_propositions = prop_result.get("propositions", [])

        # ---- Stage 6: Conversion Estimator ----
        conv_result = estimate_conversions(
            candidates=candidates,
            price_gaps=price_gaps,
            customer=customer,
            category=category,
        )
        if conv_result.get("status") == "error":
            return self._fail(
                f"Conversion estimation failed: {conv_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        conversion_estimates = conv_result.get("estimates", [])

        # ---- Stage 7: Timing Optimizer ----
        timing_result = optimize_timing(
            candidates=candidates,
            price_gaps=price_gaps,
            conversion_estimates=conversion_estimates,
            category=category,
            customer_orders=int(customer.get("total_orders", 0)),
        )
        if timing_result.get("status") == "error":
            return self._fail(
                f"Timing optimization failed: {timing_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        timing_recommendations = timing_result.get("recommendations", [])

        # ---- Stage 8: Recommendation Builder (Qwen) ----
        rec_result = build_recommendations(
            candidates=candidates,
            price_gaps=price_gaps,
            value_propositions=value_propositions,
            conversion_estimates=conversion_estimates,
            timing_recommendations=timing_recommendations,
            current_price=current_price,
        )
        if rec_result.get("status") == "error":
            return self._fail(
                f"Recommendation building failed: {rec_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        upsells = rec_result.get("upsells", [])
        best_upsell = rec_result.get("best_upsell")
        estimated_revenue_increase = float(rec_result.get("estimated_revenue_increase", 0.0))
        confidence = float(rec_result.get("confidence", 0.0))

        # ---- Stage 9: Memory Writer (non-fatal) ----
        _write = write_upsell_result(
            upsells=upsells,
            best_upsell=best_upsell,
            estimated_revenue_increase=estimated_revenue_increase,
            confidence=confidence,
            current_product_id=str(current_product.get("id", "")),
            current_price=current_price,
            category=category,
            candidates_evaluated=len(candidates),
            candidates_recommended=len(upsells),
        )

        # ---- Stage 9.5: Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory upsell recommendations.
        # When the caller passes ``data.apply_upsell_tags=True``,
        # we push ``shopai-upsell-target`` (additive) on every
        # recommended upgrade product via SHOPIFY_ADD_TAGS.
        # Merchants then save admin searches for the tag, build
        # smart collections, AND downstream engines
        # (email_marketing / catalog) filter on it to feature
        # upsell candidates in upgrade-themed campaigns.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue each tag-add via approval
        #     queue. Operator reviews before write lands.
        #   * False -- call SHOPIFY_ADD_TAGS directly via the
        #     router. Used by cycles that already gate this
        #     engine via the auto-approve allowlist.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_upsell_tags") is True:
            try:
                from .tag_applier import apply_upsell_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                tag_results = apply_upsell_tags(
                    upsells,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises out
                # by design, but a stray import / typo shouldn't
                # poison the engine's primary output.
                import logging
                logging.getLogger(__name__).debug(
                    "upsell tag_applier raised: %s", exc,
                )

        # ---- Stage 10: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "upsells": upsells,
                "best_upsell": best_upsell,
                "estimated_revenue_increase": estimated_revenue_increase,
                "confidence": confidence,
                # Phase 7 writeback: per-product tag results
                # when opted in. Empty otherwise.
                "tag_results": tag_results,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
                "candidates_evaluated": len(candidates),
                "candidates_recommended": len(upsells),
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
