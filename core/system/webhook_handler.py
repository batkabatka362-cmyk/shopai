"""Webhook Handler — processes real-time Shopify events.

Events: orders/create, products/update, customers/create, etc.
Each event triggers appropriate system response.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import threading as _threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("webhook.handler")


class WebhookHandler:
    """Processes Shopify webhooks and triggers system responses."""

    def __init__(self, secret: str = "") -> None:
        self._secret = secret
        self._events: list[dict] = []
        self._handlers: dict[str, list] = {}

    def register_handler(self, topic: str, handler) -> None:
        """Register a handler for a webhook topic."""
        self._handlers.setdefault(topic, []).append(handler)

    def process(self, topic: str, payload: dict,
                hmac_header: str = "",
                raw_body: bytes | str | None = None) -> dict[str, Any]:
        """Process an incoming webhook.

        W962-39: hardened HMAC verification.
          - When the handler has a secret, the request MUST carry
            a valid HMAC header (fail-closed). Previously a missing
            header silently bypassed verification.
          - HMAC is computed over the RAW REQUEST BODY, not a
            re-serialized payload dict. Pre-fix the json.dumps
            round-trip produced different bytes than Shopify
            signed -> every real webhook rejected.
          - When the handler has NO secret, verification is
            still skipped (dev / test path); operators are
            expected to set the secret before going live.
        """
        if self._secret:
            if not hmac_header:
                return {
                    "status": "rejected",
                    "reason": "missing_hmac_header",
                }
            # Prefer raw bytes when the caller supplied them
            # (HTTP server passes them through). Fall back to
            # re-serializing the payload only if no raw body is
            # available (legacy callers / tests).
            verify_body: bytes
            if raw_body is not None:
                verify_body = (
                    raw_body if isinstance(raw_body, bytes)
                    else raw_body.encode("utf-8")
                )
            else:
                verify_body = json.dumps(
                    payload,
                ).encode("utf-8")
            if not self._verify_hmac_bytes(verify_body, hmac_header):
                return {"status": "rejected", "reason": "invalid_hmac"}

        event = {
            "topic": topic,
            "payload": payload,
            "timestamp": time.time(),
            "processed": False,
        }

        # Route to handler
        responses = []
        if topic in self._handlers:
            for handler in self._handlers[topic]:
                try:
                    result = handler(payload)
                    responses.append(result)
                except Exception as exc:
                    responses.append({"error": str(exc)[:100]})
            event["processed"] = True

        # Auto-handle common events
        auto_result = self._auto_handle(topic, payload)
        if auto_result:
            responses.append(auto_result)
            event["processed"] = True

        event["responses"] = responses
        self._events.append(event)

        return {
            "status": "processed" if event["processed"] else "unhandled",
            "topic": topic,
            "responses": len(responses),
        }

    def _auto_handle(self, topic: str, payload: dict) -> dict | None:
        """Auto-handle common webhook events."""
        if topic == "orders/create":
            return self._handle_new_order(payload)
        elif topic == "products/update":
            return self._handle_product_update(payload)
        elif topic == "customers/create":
            return self._handle_new_customer(payload)
        return None

    def _handle_new_order(self, payload: dict) -> dict:
        order_id = payload.get("id", "")
        total = payload.get("total_price", 0)
        # Record in data architecture
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("result", {
                "action_id": "order_{}".format(order_id),
                "success": True,
                "revenue": float(total),
            }, source="webhook", score=4.5)
        except Exception as exc:
            logger.debug("webhook order DA capture failed: %s", exc)
        # Record in memory
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            mi.create(
                category="order",
                content={"order_id": str(order_id), "total": float(total)},
                action="new_order",
                score=4.5,
                tags=["order", "revenue", "webhook"],
            )
        except Exception as exc:
            logger.debug("webhook order memory write failed: %s", exc)
        logger.info("New order #%s: $%s", order_id, total)
        return {"action": "order_recorded", "order_id": order_id}

    def _handle_product_update(self, payload: dict) -> dict:
        pid = payload.get("id", "")
        title = payload.get("title", "")
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("product", payload, source="webhook", score=3.5)
        except Exception as exc:
            logger.debug("webhook product DA capture failed: %s", exc)
        return {"action": "product_synced", "product_id": pid}

    def _handle_new_customer(self, payload: dict) -> dict:
        cid = payload.get("id", "")
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            mi.create(
                category="customer",
                content={"customer_id": str(cid),
                         "email": payload.get("email", "")},
                action="new_customer",
                score=3.5,
                tags=["customer", "new", "webhook"],
            )
        except Exception as exc:
            logger.debug("webhook customer memory write failed: %s", exc)
        return {"action": "customer_recorded", "customer_id": cid}

    def _verify_hmac(self, body: str, header: str) -> bool:
        """Legacy hex-digest verification kept for back-compat
        with any caller that still uses the old signature.

        W962-39: real Shopify webhooks use BASE64-encoded
        HMAC-SHA256 (verified via _verify_hmac_bytes /
        core.feedback.webhook_security.verify_hmac). The hex
        variant here was wrong against Shopify out of the box;
        production traffic goes through process(... raw_body=)
        which routes to the production verifier.
        """
        digest = hmac.new(
            self._secret.encode(), body.encode(), hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(digest, header)

    def _verify_hmac_bytes(
        self, body: bytes, header: str,
    ) -> bool:
        """W962-39: delegate to the production base64 verifier
        from W57. Same secret + raw body contract Shopify ships."""
        try:
            from core.feedback.webhook_security import (
                verify_hmac,
            )
        except Exception:  # noqa: BLE001
            # Last-ditch fallback to inline base64 compute so the
            # handler never silently passes on broken imports.
            import base64 as _b64
            digest = hmac.new(
                self._secret.encode(), body, hashlib.sha256,
            ).digest()
            expected = _b64.b64encode(digest).decode("utf-8")
            return hmac.compare_digest(
                expected.strip(), (header or "").strip(),
            )
        return verify_hmac(body, header, self._secret)

    def get_events(self, limit: int = 50) -> list[dict]:
        return self._events[-limit:]

    def get_stats(self) -> dict[str, Any]:
        processed = sum(1 for e in self._events if e.get("processed"))
        topics = {}
        for e in self._events:
            t = e.get("topic", "unknown")
            topics[t] = topics.get(t, 0) + 1
        return {"total": len(self._events), "processed": processed, "topics": topics}


_instance = None
_instance_lock = _threading.Lock()


def get_webhook_handler():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WebhookHandler()
    return _instance
