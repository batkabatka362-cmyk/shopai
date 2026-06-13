"""Customer Chat Engine — Pattern Q envelope.

One action: respond. Given a customer message, classifies
intent + generates draft response.
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .classifier import classify
from .response_generator import generate_response

logger = logging.getLogger(__name__)


class CustomerChatEngine:
    ENGINE_NAME = "customer_chat"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        message = str(data.get("message") or "").strip()
        if not message:
            return self._fail(
                "message is required",
                time.monotonic() - start,
            )

        intent_result = classify(message)
        draft = generate_response(
            intent=intent_result.intent,
            customer_name=data.get("customer_name"),
            order_id=data.get("order_id"),
            store_name=data.get("store_name"),
            use_llm=bool(data.get("use_llm", False)),
            message=message,
        )

        return self._success(
            {
                "message": message,
                "intent": intent_result.intent,
                "intent_confidence": intent_result.confidence,
                "matched_keywords": intent_result.matched_keywords,
                "draft_response": draft.text,
                "used_llm": draft.used_llm,
                "requires_human_review": draft.requires_human_review,
                "next_action": (
                    "Review the draft. Send via your inbox / "
                    "email tool. For automated send, wire a "
                    "Shopify Inbox adapter (Phase 2)."
                    if not draft.requires_human_review
                    else (
                        "HUMAN REVIEW REQUIRED -- intent="
                        f"{intent_result.intent}. Read the "
                        "draft + customer message carefully "
                        "before sending."
                    )
                ),
            },
            start,
        )

    # ── Internal ──────────────────────────────────────────

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
