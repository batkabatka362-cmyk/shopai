"""Order Quality Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Defect Tracker → Quality Scorer → Inspection Planner →
  Improvement Advisor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {orders, defects, suppliers}, meta, error}
  Output: {status, data: {defect_rates, supplier_quality_scores, inspection_plan, improvement_actions}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .defect_tracker import track_defects
from .quality_scorer import score_quality
from .inspection_planner import plan_inspections
from .improvement_advisor import advise_improvements
from .memory_reader import read_past_quality
from .memory_writer import write_quality_result
from engines._shopify_hydrator import hydrate


class OrderQualityEngine:
    """Order Quality Engine — orchestrator only, no logic."""

    ENGINE_NAME = "order_quality"

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

        orders = data.get("orders", [])
        defects = data.get("defects", [])
        suppliers = data.get("suppliers", [])

        # Auto-hydrate orders from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        orders = hydrate(
            supplied=orders if isinstance(orders, list) else [],
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not orders:
            return self._fail("Orders list is required", 0.0)

        _past = read_past_quality(limit=5)

        # Stage 1: Defect Tracker
        defect_result = track_defects(orders=orders, defects=defects, suppliers=suppliers)
        if defect_result.get("status") == "error":
            return self._fail(f"Defect tracking failed: {defect_result.get('error', 'unknown')}", time.monotonic() - start)
        defect_rates = defect_result.get("defect_rates", [])

        # Stage 2: Quality Scorer
        score_result = score_quality(
            defect_rates=defect_rates, defects=defects,
            suppliers=suppliers, orders=orders,
        )
        if score_result.get("status") == "error":
            return self._fail(f"Quality scoring failed: {score_result.get('error', 'unknown')}", time.monotonic() - start)
        supplier_quality_scores = score_result.get("supplier_quality_scores", [])

        # Stage 3: Inspection Planner
        insp_result = plan_inspections(supplier_quality_scores=supplier_quality_scores)
        if insp_result.get("status") == "error":
            return self._fail(f"Inspection planning failed: {insp_result.get('error', 'unknown')}", time.monotonic() - start)
        inspection_plan = insp_result.get("inspection_plan", [])

        # Stage 4: Improvement Advisor
        improve_result = advise_improvements(
            supplier_quality_scores=supplier_quality_scores,
            defect_rates=defect_rates,
        )
        if improve_result.get("status") == "error":
            return self._fail(f"Improvement advising failed: {improve_result.get('error', 'unknown')}", time.monotonic() - start)
        improvement_actions = improve_result.get("improvement_actions", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_quality_result(
            defect_rates=defect_rates, supplier_quality_scores=supplier_quality_scores,
            inspection_plan=inspection_plan, improvement_actions=improvement_actions,
        )

        # ---- Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory defect rates. When the
        # caller passes ``data.apply_quality_tags=True``, we
        # push ``shopai-defect-high-rate`` on every product
        # with defect_rate >= ``data.min_defect_rate`` (default
        # 0.10) via SHOPIFY_ADD_TAGS. Supplier rollups skipped
        # -- we tag PRODUCTS (Shopify entities), not arbitrary
        # supplier strings.
        #
        # Merchants then save admin searches to drive a "QA
        # hot list" worklist; downstream engines (catalog /
        # storefront / paid_ads) can suppress these from
        # featured slots, pause ads, or trigger
        # supplier-review workflows before promoting.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue via approval queue.
        #   * False -- call SHOPIFY_ADD_TAGS directly.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_quality_tags") is True:
            try:
                from .tag_applier import apply_quality_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                min_defect_rate = float(
                    data.get("min_defect_rate", 0.10) or 0.10,
                )
                tag_results = apply_quality_tags(
                    defect_rates,
                    min_defect_rate=min_defect_rate,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises
                # out by design.
                import logging
                logging.getLogger(__name__).debug(
                    "order_quality tag_applier raised: %s", exc,
                )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "defect_rates": defect_rates,
                "supplier_quality_scores": supplier_quality_scores,
                "inspection_plan": inspection_plan,
                "improvement_actions": improvement_actions,
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
