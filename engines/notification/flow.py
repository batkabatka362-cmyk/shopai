"""Notification Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Memory Reader → Channel Selector → Template Manager →
  Personalization Engine → Delivery Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {event_type, customer, data, preferences}, meta, error}
  Output: {status, data: {notifications, delivery_status, opt_out_check}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .template_manager import resolve_template
from .channel_selector import select_channel
from .personalization_engine import personalize_content
from .delivery_tracker import track_delivery
from .memory_reader import read_past_notifications
from .memory_writer import write_notification_result


class NotificationEngine:
    """Notification Engine — orchestrator only, no logic."""

    ENGINE_NAME = "notification"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full notification pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            NotificationOutput dict.
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

        event_type = str(data.get("event_type", ""))
        customer = data.get("customer", {})
        event_data = data.get("data", {})
        preferences = data.get("preferences", {})

        if not event_type:
            return self._fail("event_type is required", 0.0)
        if not customer:
            return self._fail("customer is required", 0.0)

        # ---- Stage 1: Read past notifications (non-blocking) ----
        _past = read_past_notifications(limit=5)

        # ---- Stage 2: Channel Selector ----
        channel_result = select_channel(
            event_type=event_type,
            customer=customer,
            preferences=preferences,
        )
        if channel_result.get("status") == "error":
            return self._fail(
                f"Channel selection failed: {channel_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        selection = channel_result.get("selection", {})
        selected_channel = str(selection.get("selected_channel", "email"))
        opt_out_checked = bool(selection.get("opt_out_checked", False))

        if selected_channel == "none":
            # All channels opted out — return empty but successful
            elapsed = time.monotonic() - start
            return {
                "status": "success",
                "data": {
                    "notifications": [],
                    "delivery_status": [],
                    "opt_out_check": True,
                },
                "meta": {
                    "engine": self.ENGINE_NAME,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "elapsed_seconds": round(elapsed, 3),
                },
                "error": None,
            }

        # ---- Stage 3: Template Manager ----
        template_result = resolve_template(
            event_type=event_type,
            channel=selected_channel,
        )
        if template_result.get("status") == "error":
            return self._fail(
                f"Template resolution failed: {template_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        template = template_result.get("template", {})

        # ---- Stage 4: Personalization Engine ----
        personal_result = personalize_content(
            template=template,
            customer=customer,
            event_data=event_data,
        )
        if personal_result.get("status") == "error":
            return self._fail(
                f"Personalization failed: {personal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        content = personal_result.get("content", {})

        # ---- Stage 5: Delivery Tracker ----
        delivery_result = track_delivery(
            channel=selected_channel,
            customer=customer,
            preferences=preferences,
            event_type=event_type,
        )
        if delivery_result.get("status") == "error":
            return self._fail(
                f"Delivery tracking failed: {delivery_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        delivery = delivery_result.get("delivery", {})

        # ---- Stage 6: Build notification items ----
        notification_item: dict[str, Any] = {
            "channel": selected_channel,
            "template": str(template.get("template_id", "")),
            "content": str(content.get("body", "")),
            "personalized": bool(content.get("personalized", False)),
            "scheduled_at": str(delivery.get("scheduled_at", "")),
        }

        notifications = [notification_item]
        delivery_statuses = [delivery]

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_notification_result(
            notifications=notifications,
            delivery_status=delivery_statuses,
            opt_out_check=opt_out_checked,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "notifications": notifications,
                "delivery_status": delivery_statuses,
                "opt_out_check": opt_out_checked,
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
