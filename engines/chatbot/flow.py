"""Chatbot Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Memory Reader → Intent Router → Response Generator →
  Conversation Manager → Escalation Handler → Memory Writer → Output

Engine contract:
  Input:  {status, data: {message, customer, conversation_history, context}, meta, error}
  Output: {status, data: {response, intent, confidence, suggested_actions, escalate, conversation_state}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .intent_router import route_intent
from .response_generator import generate_response
from .conversation_manager import manage_conversation
from .escalation_handler import check_escalation
from .memory_reader import read_past_conversations
from .memory_writer import write_chatbot_result


class ChatbotEngine:
    """Chatbot Engine — orchestrator only, no logic."""

    ENGINE_NAME = "chatbot"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full chatbot pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ChatbotOutput dict.
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

        message = str(data.get("message", ""))
        customer = data.get("customer", {})
        conversation_history = data.get("conversation_history", [])
        context = data.get("context", {})

        if not message:
            return self._fail("message is required", 0.0)

        # ---- Stage 1: Read past conversations (non-blocking) ----
        _past = read_past_conversations(limit=5)

        # ---- Stage 2: Intent Router ----
        intent_result_raw = route_intent(
            message=message,
            conversation_history=conversation_history,
            context=context,
        )
        if intent_result_raw.get("status") == "error":
            return self._fail(
                f"Intent routing failed: {intent_result_raw.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        intent_result = intent_result_raw.get("intent_result", {})

        # ---- Stage 3: Response Generator ----
        response_result = generate_response(
            intent_result=intent_result,
            message=message,
            customer=customer,
            context=context,
        )
        if response_result.get("status") == "error":
            return self._fail(
                f"Response generation failed: {response_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        generated = response_result.get("generated", {})

        # ---- Stage 4: Conversation Manager ----
        convo_result = manage_conversation(
            message=message,
            conversation_history=conversation_history,
            intent_result=intent_result,
        )
        if convo_result.get("status") == "error":
            return self._fail(
                f"Conversation management failed: {convo_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        conversation_state = convo_result.get("conversation_state", {})

        # ---- Stage 5: Escalation Handler ----
        escalation_result = check_escalation(
            message=message,
            intent_result=intent_result,
            conversation_state=conversation_state,
            customer=customer,
        )
        if escalation_result.get("status") == "error":
            return self._fail(
                f"Escalation check failed: {escalation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        escalation = escalation_result.get("escalation", {})

        # ---- Stage 6: Extract final values ----
        response_text = str(generated.get("response", ""))
        intent = str(intent_result.get("intent", "general"))
        confidence = float(intent_result.get("confidence", 0.0))
        suggested_actions = list(generated.get("suggested_actions", []))
        escalate = bool(escalation.get("escalate", False))

        # If escalating, append escalation info to response
        if escalate:
            dept = str(escalation.get("department", "support"))
            response_text += (
                f" I'm connecting you with our {dept.replace('_', ' ')} team "
                f"for further assistance."
            )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_chatbot_result(
            intent=intent,
            confidence=confidence,
            response_length=len(response_text),
            escalated=escalate,
            turn_count=int(conversation_state.get("turn_count", 1)),
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "response": response_text,
                "intent": intent,
                "confidence": confidence,
                "suggested_actions": suggested_actions,
                "escalate": escalate,
                "conversation_state": conversation_state,
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
