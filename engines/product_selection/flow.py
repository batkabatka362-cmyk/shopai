"""Product Selection Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Market Data → Candidate Generator → Criteria Matcher → Supplier Checker →
  Initial Scorer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {market_data, criteria, suppliers}, meta, error}
  Output: {status, data: {candidates, shortlist, rejected}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .candidate_generator import generate_candidates
from .criteria_matcher import match_criteria
from .supplier_checker import check_suppliers
from .initial_scorer import score_initial
from .memory_reader import read_past_results
from .memory_writer import write_result


class ProductSelectionEngine:
    """Product Selection Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_selection"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full product selection pipeline."""
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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

        market_data = data.get("market_data", [])
        criteria = data.get("criteria", {})
        suppliers = data.get("suppliers", [])

        if not market_data:
            return self._fail("Market data is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Candidate Generator ----
        gen_result = generate_candidates(
            market_data=market_data,
            criteria=criteria,
        )
        if gen_result.get("status") == "error":
            return self._fail(
                f"Candidate generation failed: {gen_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        candidates = gen_result.get("candidates", [])

        # ---- Stage 3: Criteria Matcher ----
        match_result = match_criteria(
            candidates=candidates,
            criteria=criteria,
        )
        if match_result.get("status") == "error":
            return self._fail(
                f"Criteria matching failed: {match_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        matched = match_result.get("matched", [])

        # ---- Stage 4: Supplier Checker ----
        sup_result = check_suppliers(
            candidates=matched,
            suppliers=suppliers,
        )
        if sup_result.get("status") == "error":
            return self._fail(
                f"Supplier checking failed: {sup_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        checked = sup_result.get("checked", [])

        # ---- Stage 5: Initial Scorer ----
        score_result = score_initial(
            candidates=checked,
        )
        if score_result.get("status") == "error":
            return self._fail(
                f"Initial scoring failed: {score_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scored = score_result.get("scored", [])
        shortlist = score_result.get("shortlist", [])
        rejected = score_result.get("rejected", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_result(
            candidates=scored,
            shortlist=shortlist,
            rejected=rejected,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "candidates": [
                    {
                        "product": s.get("name", ""),
                        "score": s.get("initial_score", 0),
                        "supplier": s.get("supplier", {}).get("name", ""),
                    }
                    for s in scored
                ],
                "shortlist": shortlist,
                "rejected": rejected,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

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
