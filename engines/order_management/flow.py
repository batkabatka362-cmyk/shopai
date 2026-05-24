"""Order Management Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Validation → Memory Reader → Order Validator → Fraud Screener →
  Inventory Checker → Fulfillment Router → Shipping Handler →
  Tracking Manager → Status Updater → Notification Dispatcher →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {order, action}, meta, error}
  Output: {status, data: {order_id, order_status, validation, fraud_screen,
           inventory, fulfillment, shipping, tracking, notification}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .order_validator import validate_order
from .fraud_screener import screen_for_fraud
from .inventory_checker import check_inventory
from .fulfillment_router import route_fulfillment
from .shipping_handler import handle_shipping
from .tracking_manager import create_tracking
from .status_updater import update_status
from .notification_dispatcher import dispatch_notification
from .memory_reader import read_order_history
from .memory_writer import write_order_record


class OrderManagementEngine:
    """Order Management Engine — orchestrator only, no logic."""

    ENGINE_NAME = "order_management"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full order management pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            OrderOutput dict.
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

        order = data.get("order", {})
        if not isinstance(order, dict) or not order:
            return self._fail("Order data is required", 0.0)

        order_id = str(order.get("id", "unknown"))
        customer = order.get("customer", {})
        customer_id = str(customer.get("id", ""))

        # ---- Stage 1: Read order history (non-blocking) ----
        _history = read_order_history(customer_id=customer_id, limit=5)

        # ---- Stage 2: Order Validator ----
        validation_result = validate_order(order=order)
        if validation_result.get("status") == "error":
            return self._fail(
                f"Order validation failed: {validation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        if not validation_result.get("is_valid", False):
            errors = validation_result.get("errors", [])
            return self._fail(
                f"Order is invalid: {'; '.join(errors)}",
                time.monotonic() - start,
            )

        # ---- Stage 3: Fraud Screener ----
        fraud_result = screen_for_fraud(order=order)
        if fraud_result.get("status") == "error":
            return self._fail(
                f"Fraud screening failed: {fraud_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # Early return if fraud screener recommends rejection
        if fraud_result.get("recommendation") == "reject":
            # Update status to cancelled
            cancel_status = update_status(
                order_id=order_id,
                new_status="cancelled",
                current_status="pending",
            )

            cancel_notification = dispatch_notification(
                order=order,
                order_status="cancelled",
            )

            # Phase 7: tag the rejected order so it's discoverable
            # in the Shopify admin (and any review queue).
            tagged_fraud_reject: dict[str, Any] = {}
            if bool(data.get("apply_fraud_tags")):
                try:
                    from .tag_applier import apply_fraud_tags
                    tagged_fraud_reject = apply_fraud_tags(
                        order_id, fraud_result,
                    )
                except Exception as exc:  # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).debug(
                        "order_management: apply loop raised: %s",
                        exc,
                    )

            return {
                "status": "success",
                "data": {
                    "order_id": order_id,
                    "order_status": "cancelled",
                    "validation": validation_result,
                    "fraud_screen": fraud_result,
                    "inventory": None,
                    "fulfillment": None,
                    "shipping": None,
                    "tracking": None,
                    "notification": cancel_notification,
                    "rejection_reason": "Fraud screening rejected this order",
                    "tagged_fraud": tagged_fraud_reject,
                },
                "meta": {
                    "engine": self.ENGINE_NAME,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "elapsed_seconds": round(time.monotonic() - start, 3),
                },
                "error": None,
            }

        # ---- Stage 4: Inventory Checker ----
        line_items = order.get("line_items", [])
        inventory_result = check_inventory(line_items=line_items)
        if inventory_result.get("status") == "error":
            return self._fail(
                f"Inventory check failed: {inventory_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # Note shortages but continue processing
        all_in_stock = inventory_result.get("all_in_stock", False)

        # ---- Stage 5: Fulfillment Router ----
        fulfillment_result = route_fulfillment(
            order=order,
            inventory_status=inventory_result,
        )
        if fulfillment_result.get("status") == "error":
            return self._fail(
                f"Fulfillment routing failed: {fulfillment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 6: Shipping Handler ----
        shipping_result = handle_shipping(
            order=order,
            fulfillment=fulfillment_result,
        )
        if shipping_result.get("status") == "error":
            return self._fail(
                f"Shipping handling failed: {shipping_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 7: Tracking Manager ----
        tracking_result = create_tracking(
            order_id=order_id,
            carrier=shipping_result.get("carrier", ""),
            shipping=shipping_result,
        )
        if tracking_result.get("status") == "error":
            return self._fail(
                f"Tracking creation failed: {tracking_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 8: Status Updater ----
        status_result = update_status(
            order_id=order_id,
            new_status="confirmed",
            current_status="pending",
        )
        if status_result.get("status") == "error":
            return self._fail(
                f"Status update failed: {status_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        current_order_status = status_result.get("current_status", "confirmed")

        # ---- Stage 9: Notification Dispatcher ----
        notification_result = dispatch_notification(
            order=order,
            order_status=current_order_status,
            tracking=tracking_result,
        )
        if notification_result.get("status") == "error":
            return self._fail(
                f"Notification dispatch failed: {notification_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _write_result = write_order_record(
            order_id=order_id,
            customer_id=customer_id,
            status=current_order_status,
            fulfillment=fulfillment_result,
            shipping=shipping_result,
            tracking=tracking_result,
            fraud_screen=fraud_result,
            inventory=inventory_result,
            notification=notification_result,
        )

        # Phase 7: optional fraud-tag apply on the non-rejected
        # path (medium-risk "review" orders). High-risk reject
        # orders already got tagged above.
        tagged_fraud: dict[str, Any] = {}
        if bool(data.get("apply_fraud_tags")):
            try:
                from .tag_applier import apply_fraud_tags
                tagged_fraud = apply_fraud_tags(
                    order_id, fraud_result,
                )
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "order_management: apply loop raised: %s", exc,
                )

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        output_data: dict[str, Any] = {
            "order_id": order_id,
            "order_status": current_order_status,
            "validation": validation_result,
            "fraud_screen": fraud_result,
            "inventory": inventory_result,
            "fulfillment": fulfillment_result,
            "shipping": shipping_result,
            "tracking": tracking_result,
            "notification": notification_result,
            "tagged_fraud": tagged_fraud,
        }

        if not all_in_stock:
            output_data["inventory_warning"] = (
                "Some items have inventory shortages — see inventory.shortages"
            )

        return {
            "status": "success",
            "data": output_data,
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
