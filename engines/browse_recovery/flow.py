"""Browse Recovery Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Session Data → Session Analyzer → Intent Scorer → Offer Builder →
  Sequence Planner → Memory Writer → Output

PURPOSE: Recover customers who browsed but didn't buy (95% of visitors).

Engine contract:
  Input:  {status, data: {sessions: [{user_id, pages_viewed, products_viewed, duration, cart_items}], products}, meta, error}
  Output: {status, data: {recovery_targets, total_recoverable, estimated_revenue}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .session_analyzer import analyze_sessions
from .intent_scorer import score_intent
from .offer_builder import build_offers
from .sequence_planner import plan_sequences
from .memory_reader import read_past_recoveries
from .memory_writer import write_recovery_result


class BrowseRecoveryEngine:
    """Browse Recovery Engine — orchestrator only, no logic."""

    ENGINE_NAME = "browse_recovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full browse recovery pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BrowseRecoveryOutput dict.
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

        sessions = data.get("sessions", [])
        products = data.get("products", [])

        if not sessions:
            return self._fail("Session list is required", 0.0)

        # ---- Stage 1: Read past recoveries (non-blocking) ----
        _past = read_past_recoveries(limit=5)

        # ---- Stage 2: Session Analyzer ----
        session_result = analyze_sessions(sessions=sessions)
        if session_result.get("status") == "error":
            return self._fail(
                f"Session analysis failed: {session_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        analyzed_sessions = session_result.get("sessions", [])
        abandon_count = session_result.get("abandon_count", 0)

        # ---- Stage 3: Intent Scorer ----
        intent_result = score_intent(analyzed_sessions=analyzed_sessions)
        if intent_result.get("status") == "error":
            return self._fail(
                f"Intent scoring failed: {intent_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        intent_scores = intent_result.get("scores", [])

        # ---- Stage 4: Offer Builder ----
        offer_result = build_offers(
            intent_scores=intent_scores,
            sessions=sessions,
            products=products,
        )
        if offer_result.get("status") == "error":
            return self._fail(
                f"Offer building failed: {offer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        offers = offer_result.get("offers", [])

        # ---- Stage 5: Sequence Planner ----
        sequence_result = plan_sequences(
            offers=offers,
            intent_scores=intent_scores,
        )
        if sequence_result.get("status") == "error":
            return self._fail(
                f"Sequence planning failed: {sequence_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sequences = sequence_result.get("sequences", [])

        # ---- Stage 6: Assemble recovery targets ----
        score_map = {str(s.get("user_id", "")): s for s in intent_scores}
        offer_map = {str(o.get("user_id", "")): o for o in offers}
        seq_map = {str(s.get("user_id", "")): s for s in sequences}
        session_map = {str(s.get("user_id", "")): s for s in sessions}

        recovery_targets: list[dict[str, Any]] = []
        total_estimated_revenue = 0.0

        for score_item in intent_scores:
            user_id = str(score_item.get("user_id", ""))
            intent_score = float(score_item.get("intent_score", 0.0))

            session = session_map.get(user_id, {})
            viewed_products = session.get("products_viewed", [])

            offer = offer_map.get(user_id, {})
            sequence = seq_map.get(user_id, {})

            # Estimate revenue: intent_score/100 * avg product value
            # Assume avg product value of $50 if no price data
            estimated_value = intent_score / 100.0 * 50.0
            total_estimated_revenue += estimated_value

            recovery_targets.append({
                "user_id": user_id,
                "intent_score": intent_score,
                "viewed_products": viewed_products,
                "recommended_offer": offer,
                "sequence": sequence,
            })

        total_recoverable = abandon_count

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_recovery_result(
            recovery_targets=recovery_targets,
            total_recoverable=total_recoverable,
            estimated_revenue=round(total_estimated_revenue, 2),
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "recovery_targets": recovery_targets,
                "total_recoverable": total_recoverable,
                "estimated_revenue": round(total_estimated_revenue, 2),
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
