"""Selection Decision Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Decision Matrix → Constraint Checker → Verdict Builder →
  Portfolio Balancer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {ranked_products, constraints}, meta, error}
  Output: {status, data: {selected, rejected, portfolio_balance}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .decision_matrix import build_decision_matrix
from .constraint_checker import check_constraints
from .portfolio_balancer import balance_portfolio
from .verdict_builder import build_verdicts
from .memory_reader import read_past_decisions
from .memory_writer import write_decision_result


class SelectionDecisionEngine:
    """Selection Decision Engine — orchestrator only, no logic."""

    ENGINE_NAME = "selection_decision"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full selection decision pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SelectionOutput dict.
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

        ranked_products = data.get("ranked_products", [])
        constraints = data.get("constraints", [])

        if not ranked_products:
            return self._fail("Ranked product list is required", 0.0)

        # ---- Stage 1: Read past decisions (non-blocking) ----
        _past = read_past_decisions(limit=5)

        # ---- Stage 2: Decision Matrix ----
        matrix_result = build_decision_matrix(
            ranked_products=ranked_products,
        )
        if matrix_result.get("status") == "error":
            return self._fail(
                f"Decision matrix failed: {matrix_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        matrix = matrix_result.get("matrix", [])

        # ---- Stage 3: Constraint Checker ----
        check_result = check_constraints(
            ranked_products=ranked_products,
            constraints=constraints,
        )
        if check_result.get("status") == "error":
            return self._fail(
                f"Constraint checking failed: {check_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        checks = check_result.get("checks", [])

        # ---- Stage 4: Verdict Builder ----
        verdict_result = build_verdicts(
            matrix=matrix,
            checks=checks,
            ranked_products=ranked_products,
        )
        if verdict_result.get("status") == "error":
            return self._fail(
                f"Verdict building failed: {verdict_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        verdicts = verdict_result.get("verdicts", [])

        # ---- Stage 5: Split selected/rejected ----
        prod_map = {str(p.get("id", "")): p for p in ranked_products}
        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for v in verdicts:
            pid = str(v.get("product_id", "unknown"))
            entry = {
                "product_id": pid,
                "title": str(prod_map.get(pid, {}).get("title", "")),
                "verdict": v.get("verdict", "rejected"),
                "confidence": v.get("confidence", 0.0),
                "reasons": v.get("reasons", []),
            }
            if v.get("verdict") == "selected":
                selected.append(entry)
            else:
                rejected.append(entry)

        # ---- Stage 6: Portfolio Balancer ----
        selected_full = [prod_map.get(s["product_id"], {}) for s in selected]
        balance_result = balance_portfolio(
            selected_products=selected_full,
            ranked_products=ranked_products,
        )
        if balance_result.get("status") == "error":
            return self._fail(
                f"Portfolio balancing failed: {balance_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        portfolio_balance = balance_result.get("balance", {})

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_decision_result(
            selected=selected,
            rejected=rejected,
            portfolio_balance=portfolio_balance,
        )

        # ---- Stage 7.5: Phase 7 writeback (opt-in) ----------
        # Engines today emit advisory selection verdicts.
        # When the caller passes
        # ``data.apply_selection_tags=True``, we push
        # ``shopai-selection-selected`` on every product the
        # engine selected via SHOPIFY_ADD_TAGS. Merchants then
        # save admin searches to drive an "AI-approved
        # investment list" worklist; downstream engines
        # (catalog / storefront / paid_ads) can prioritise
        # these for featured slots, ad spend, and homepage
        # carousels.
        #
        # ``data.min_confidence`` (default 0.0 -- all
        # selected) lets callers filter to only
        # high-confidence picks.
        #
        # Two paths, controlled by ``data.require_approval``:
        #   * True (default) -- enqueue via approval queue.
        #   * False -- call SHOPIFY_ADD_TAGS directly.
        #
        # Default OFF preserves the pure-recommendation
        # behavior every existing caller relies on.
        tag_results: list[dict[str, Any]] = []
        if data.get("apply_selection_tags") is True:
            try:
                from .tag_applier import apply_selection_tags
                require_approval = bool(
                    data.get("require_approval", True),
                )
                min_confidence = float(
                    data.get("min_confidence", 0.0) or 0.0,
                )
                tag_results = apply_selection_tags(
                    selected,
                    min_confidence=min_confidence,
                    require_approval=require_approval,
                )
            except Exception as exc:  # noqa: BLE001
                # Belt-and-braces: the applier never raises
                # out by design.
                import logging
                logging.getLogger(__name__).debug(
                    "selection_decision tag_applier raised: %s",
                    exc,
                )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "selected": selected,
                "rejected": rejected,
                "portfolio_balance": portfolio_balance,
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
