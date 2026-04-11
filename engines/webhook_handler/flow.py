"""Webhook Handler Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Signature Verifier → Event Classifier →
  Payload Parser → Engine Router → Execution Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {webhook, raw_payload, shared_secret}, meta, error}
  Output: {status, data: {webhook_id, verification, event, parsed_payload, routing, execution}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any

from .signature_verifier import verify_signature
from .event_classifier import classify_event
from .payload_parser import parse_payload
from .engine_router import route_to_engines
from .execution_tracker import track_execution
from .memory_reader import read_recent_webhooks, find_duplicate_webhook
from .memory_writer import write_webhook_record


class WebhookHandlerEngine:
    """Webhook Handler Engine — orchestrator only, no logic."""

    ENGINE_NAME = "webhook_handler"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full webhook handler pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            WebhookOutput dict.
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

        webhook = data.get("webhook", {})
        if not isinstance(webhook, dict):
            return self._fail("Input 'data.webhook' must be a dict", 0.0)

        raw_payload = data.get("raw_payload", {})
        shared_secret = str(data.get("shared_secret", ""))

        topic = webhook.get("topic", "")
        webhook_id = webhook.get("webhook_id", "")
        hmac_header = webhook.get("hmac_header", "")

        if not topic:
            return self._fail("Webhook topic is required", 0.0)

        if not webhook_id:
            return self._fail("Webhook ID is required", 0.0)

        # ---- Stage 1: Memory Reader — check for duplicates ----
        _recent = read_recent_webhooks(limit=50)

        duplicate = find_duplicate_webhook(webhook_id)
        if duplicate is not None:
            return self._fail(
                f"Duplicate webhook: {webhook_id} already processed",
                time.monotonic() - start,
            )

        # ---- Stage 2: Signature Verifier ----
        # Serialize raw_payload to bytes for HMAC computation
        if isinstance(raw_payload, dict):
            payload_for_hmac = json.dumps(
                raw_payload, separators=(",", ":"), sort_keys=True,
            )
        else:
            payload_for_hmac = raw_payload

        sig_result = verify_signature(
            raw_payload=payload_for_hmac,
            hmac_header=hmac_header,
            shared_secret=shared_secret,
        )
        if sig_result.get("status") == "error":
            return self._fail(
                f"Signature verification failed: {sig_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        signature_valid = sig_result.get("signature_valid", False)

        if not signature_valid:
            # Write failed attempt to memory (non-fatal)
            _write_result = write_webhook_record(
                webhook_id=webhook_id,
                topic=topic,
                routes=[],
                signature_valid=False,
            )
            return self._fail(
                f"Invalid HMAC signature for webhook {webhook_id}",
                time.monotonic() - start,
            )

        # ---- Stage 3: Event Classifier ----
        event_result = classify_event(
            topic=topic,
            raw_payload=raw_payload,
        )
        if event_result.get("status") == "error":
            return self._fail(
                f"Event classification failed: {event_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        event = event_result.get("event", {})

        # ---- Stage 4: Payload Parser ----
        parse_result = parse_payload(
            raw_payload=raw_payload,
            event=event,
        )
        if parse_result.get("status") == "error":
            return self._fail(
                f"Payload parsing failed: {parse_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        parsed = parse_result.get("parsed", {})

        # ---- Stage 5: Engine Router ----
        route_result = route_to_engines(
            event=event,
            parsed=parsed,
        )
        if route_result.get("status") == "error":
            return self._fail(
                f"Engine routing failed: {route_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        routes = route_result.get("routes", [])

        # ---- Stage 6: Execution Tracker ----
        exec_result = track_execution(
            routes=routes,
            webhook_id=webhook_id,
        )
        if exec_result.get("status") == "error":
            return self._fail(
                f"Execution tracking failed: {exec_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        dispatched_count = exec_result.get("dispatched_count", 0)
        dispatch_status = exec_result.get("dispatch_status", [])

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_webhook_record(
            webhook_id=webhook_id,
            topic=topic,
            routes=routes,
            signature_valid=True,
            entity_type=parsed.get("entity_type", ""),
            entity_id=parsed.get("entity_id", ""),
            dispatched_count=dispatched_count,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "webhook_id": webhook_id,
                "verification": {
                    "signature_valid": True,
                    "hmac_match": True,
                },
                "event": {
                    "topic": event.get("topic", topic),
                    "category": event.get("category", ""),
                    "action": event.get("action", ""),
                    "priority": event.get("priority", ""),
                },
                "parsed_payload": {
                    "entity_type": parsed.get("entity_type", ""),
                    "entity_id": parsed.get("entity_id", ""),
                    "normalized": parsed.get("normalized", {}),
                },
                "routing": {
                    "target_engines": routes,
                },
                "execution": {
                    "dispatched_count": dispatched_count,
                    "dispatch_status": dispatch_status,
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
