"""Customer Service Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Intent Classifier → Order Lookup (if order-related) →
  Knowledge Search → Response Builder → Escalation Router → Memory Writer → Output

Engine contract:
  Input:  {status, data: {message, customer, channel, session_id}, meta, error}
  Output: {status, data: {intent, order_info, knowledge_results, response, escalation}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .intent_classifier import classify_intent
from .order_lookup import lookup_order
from .knowledge_search import search_knowledge
from .response_builder import build_response
from .escalation_router import route_escalation
from .memory_reader import read_interaction_history
from .memory_writer import write_interaction_record


# Intents that require an order lookup
_ORDER_RELATED_INTENTS = frozenset({
    "order_status", "tracking", "return_request", "refund_request",
})


class CustomerServiceEngine:
    """Customer Service Engine — orchestrator only, no logic."""

    ENGINE_NAME = "customer_service"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full customer service pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CustomerServiceOutput dict.
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

        message = str(data.get("message", "")).strip()
        if not message:
            return self._fail("Customer message is required", 0.0)

        customer = data.get("customer", {})
        if not isinstance(customer, dict):
            customer = {}

        channel = str(data.get("channel", "chat"))
        session_id = data.get("session_id")
        customer_id = str(customer.get("customer_id", ""))

        # ---- Stage 1: Memory Reader (non-blocking) ----
        history_result = read_interaction_history(
            customer_id=customer_id if customer_id else None,
            limit=10,
        )

        # ---- Stage 2: Intent Classifier ----
        # Build context from history for the classifier
        context: dict[str, Any] = {}
        past_records = history_result.get("records", [])
        if past_records:
            context["prior_intent"] = past_records[0].get("intent")

        intent_result = classify_intent(
            message=message,
            context=context,
        )
        if intent_result.get("status") == "error":
            return self._fail(
                f"Intent classification failed: {intent_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        primary_intent = str(intent_result.get("primary", "general"))
        entities = intent_result.get("extracted_entities", {})

        # ---- Stage 3: Order Lookup (conditional) ----
        order_result: dict[str, Any] = {"status": "success", "found": False, "order": None}

        if primary_intent in _ORDER_RELATED_INTENTS:
            order_ids = entities.get("order_ids", [])
            if order_ids:
                # Look up the first mentioned order
                order_result = lookup_order(
                    order_id=order_ids[0],
                    customer_id=customer_id if customer_id else None,
                )
                if order_result.get("status") == "error":
                    return self._fail(
                        f"Order lookup failed: {order_result.get('error', 'unknown')}",
                        time.monotonic() - start,
                    )

        # ---- Stage 4: Knowledge Search ----
        knowledge_result = search_knowledge(
            query=message,
            intent=primary_intent,
        )
        if knowledge_result.get("status") == "error":
            return self._fail(
                f"Knowledge search failed: {knowledge_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 5: Response Builder ----
        response_result = build_response(
            intent=intent_result,
            order_info=order_result,
            knowledge=knowledge_result,
            customer=customer,
        )
        if response_result.get("status") == "error":
            return self._fail(
                f"Response building failed: {response_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 6: Escalation Router ----
        escalation_result = route_escalation(
            intent=intent_result,
            customer=customer,
            response=response_result,
            interaction_history=history_result,
        )
        if escalation_result.get("status") == "error":
            return self._fail(
                f"Escalation routing failed: {escalation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_interaction_record(
            customer_id=customer_id,
            message=message,
            intent=primary_intent,
            channel=channel,
            response_message=str(response_result.get("message", "")),
            escalated=bool(escalation_result.get("needed", False)),
            assigned_team=escalation_result.get("assigned_team"),
            session_id=session_id,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "intent": {
                    "primary": intent_result.get("primary"),
                    "secondary": intent_result.get("secondary"),
                    "confidence": intent_result.get("confidence", 0.0),
                    "extracted_entities": intent_result.get("extracted_entities", {}),
                },
                "order_info": {
                    "found": order_result.get("found", False),
                    "order": order_result.get("order"),
                } if primary_intent in _ORDER_RELATED_INTENTS else None,
                "knowledge_results": knowledge_result.get("results", []),
                "response": {
                    "message": response_result.get("message", ""),
                    "tone": response_result.get("tone", "friendly"),
                    "suggested_actions": response_result.get("suggested_actions", []),
                },
                "escalation": {
                    "needed": escalation_result.get("needed", False),
                    "reason": escalation_result.get("reason"),
                    "assigned_team": escalation_result.get("assigned_team"),
                    "priority": escalation_result.get("priority"),
                },
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
