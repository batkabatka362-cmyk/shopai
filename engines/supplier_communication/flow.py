"""Supplier Communication Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Supplier Data → PO Generator → Message Builder → Tracking Monitor →
  Negotiation Helper → Memory Writer → Output

PURPOSE: Manage supplier communications and purchase orders.

Engine contract:
  Input:  {status, data: {suppliers, reorder_plan, inventory_status, communication_history}, meta, error}
  Output: {status, data: {purchase_orders, messages, tracking_updates, negotiation_tips}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .po_generator import generate_purchase_orders
from .message_builder import build_messages
from .tracking_monitor import monitor_tracking
from .negotiation_helper import generate_negotiation_tips
from .memory_reader import read_past_communications
from .memory_writer import write_communication_result


class SupplierCommunicationEngine:
    """Supplier Communication Engine — orchestrator only, no logic."""

    ENGINE_NAME = "supplier_communication"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full supplier communication pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SupplierCommOutput dict.
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

        suppliers = data.get("suppliers", [])
        reorder_plan = data.get("reorder_plan", [])
        inventory_status = data.get("inventory_status", [])
        communication_history = data.get("communication_history", [])

        if not suppliers:
            return self._fail("Supplier list is required", 0.0)

        # ---- Stage 1: Read past communications (non-blocking) ----
        _past = read_past_communications(limit=5)

        # ---- Stage 2: PO Generator ----
        po_result = generate_purchase_orders(
            reorder_plan=reorder_plan,
            suppliers=suppliers,
        )
        if po_result.get("status") == "error":
            return self._fail(
                f"PO generation failed: {po_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        purchase_orders = po_result.get("purchase_orders", [])

        # ---- Stage 3: Message Builder ----
        message_result = build_messages(
            purchase_orders=purchase_orders,
            suppliers=suppliers,
            communication_history=communication_history,
        )
        if message_result.get("status") == "error":
            return self._fail(
                f"Message building failed: {message_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        messages = message_result.get("messages", [])

        # ---- Stage 4: Tracking Monitor ----
        tracking_result = monitor_tracking(
            purchase_orders=purchase_orders,
            inventory_status=inventory_status,
        )
        if tracking_result.get("status") == "error":
            return self._fail(
                f"Tracking monitoring failed: {tracking_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tracking_updates = tracking_result.get("tracking_updates", [])

        # ---- Stage 5: Negotiation Helper ----
        negotiation_result = generate_negotiation_tips(
            purchase_orders=purchase_orders,
            suppliers=suppliers,
            communication_history=communication_history,
        )
        if negotiation_result.get("status") == "error":
            return self._fail(
                f"Negotiation analysis failed: {negotiation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        negotiation_tips = negotiation_result.get("negotiation_tips", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_communication_result(
            purchase_orders=purchase_orders,
            messages=messages,
            tracking_updates=tracking_updates,
            negotiation_tips=negotiation_tips,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "purchase_orders": purchase_orders,
                "messages": messages,
                "tracking_updates": tracking_updates,
                "negotiation_tips": negotiation_tips,
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
