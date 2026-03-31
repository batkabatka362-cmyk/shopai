"""Order Webhook Handler — closes the learning loop by recording real revenue outcomes.

When Shopify sends order.paid → this handler:
  1. Extracts revenue data
  2. Calls OutcomeTracker.record_outcome() to link decision→revenue
  3. Calls KPITracker.record_revenue_event() for business metrics
  4. Calls RevenueTracker.record_revenue() for ROI tracking

This is the CRITICAL piece that makes learning real.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("webhooks.order")


class OrderWebhookHandler:
    """Handles order webhooks and records outcomes for learning."""

    def __init__(self) -> None:
        self._processed = 0

    def handle_order_paid(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Process a paid order and record as outcome.

        Args:
            order_data: Shopify order payload (or normalized order dict)

        Returns:
            Summary of what was recorded.
        """
        # Extract revenue data
        order_id = str(order_data.get("id", order_data.get("order_id", "")))
        revenue = safe_float(order_data.get("total_price", order_data.get("total", 0)))
        subtotal = safe_float(order_data.get("subtotal_price", order_data.get("subtotal", revenue)))
        items = order_data.get("line_items", [])
        item_count = len(items) if isinstance(items, list) else safe_int(order_data.get("items", 0))
        customer_id = str(order_data.get("customer", {}).get("id", order_data.get("customer_id", "")))

        # Attribution: check for campaign/decision tracking
        note_attrs = order_data.get("note_attributes", [])
        decision_id = None
        campaign_id = None
        for attr in note_attrs if isinstance(note_attrs, list) else []:
            if isinstance(attr, dict):
                if attr.get("name") == "shopai_decision_id":
                    decision_id = attr.get("value")
                if attr.get("name") == "shopai_campaign_id":
                    campaign_id = attr.get("value")

        # Also check UTM source for attribution
        source = order_data.get("source_name", order_data.get("referring_site", ""))
        landing = order_data.get("landing_site", "")

        recorded = {"order_id": order_id, "revenue": revenue, "items": item_count}

        # 1. Record to OutcomeTracker — links decision to real outcome
        if decision_id:
            try:
                from core.learning.outcome_tracker import OutcomeTracker
                ot = OutcomeTracker()
                ot.record_outcome(decision_id, "full_system_loop", {
                    "success": True,
                    "revenue": revenue,
                    "order_id": order_id,
                    "items": item_count,
                    "customer_id": customer_id,
                })
                recorded["outcome_tracked"] = True
                logger.info("Order %s linked to decision %s (revenue=$%.2f)", order_id, decision_id, revenue)
            except Exception as exc:
                logger.warning("OutcomeTracker failed: %s", exc)
                recorded["outcome_tracked"] = False
        else:
            recorded["outcome_tracked"] = False
            recorded["note"] = "No decision_id in order — cannot attribute"

        # 2. Record to KPITracker — business metrics
        try:
            from core.intelligence.kpi_tracker import KPITracker
            kpi = KPITracker()
            kpi.record_revenue_event(
                decision_id=decision_id or f"order_{order_id}",
                revenue=revenue,
                cost=0,
                conversion_count=1,
                impression_count=0,
                click_count=0,
            )
            recorded["kpi_tracked"] = True
        except Exception as exc:
            logger.warning("KPITracker failed: %s", exc)
            recorded["kpi_tracked"] = False

        # 3. Record to RevenueTracker — ROI tracking
        try:
            from core.intelligence.revenue_tracker import RevenueTracker
            rt = RevenueTracker()
            action_id = rt.record_action(
                action_type="order_paid",
                product=f"order_{order_id}",
                details={"customer_id": customer_id, "items": item_count, "source": source},
            )
            rt.record_revenue(action_id, revenue=revenue, cost=0, orders=1)
            recorded["revenue_tracked"] = True
        except Exception as exc:
            logger.warning("RevenueTracker failed: %s", exc)
            recorded["revenue_tracked"] = False

        self._processed += 1
        recorded["total_processed"] = self._processed
        return recorded

    def handle_order_cancelled(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Process a cancelled order — record negative outcome."""
        order_id = str(order_data.get("id", ""))
        revenue = safe_float(order_data.get("total_price", order_data.get("total", 0)))

        note_attrs = order_data.get("note_attributes", [])
        decision_id = None
        for attr in note_attrs if isinstance(note_attrs, list) else []:
            if isinstance(attr, dict) and attr.get("name") == "shopai_decision_id":
                decision_id = attr.get("value")

        if decision_id:
            try:
                from core.learning.outcome_tracker import OutcomeTracker
                ot = OutcomeTracker()
                ot.record_outcome(decision_id, "full_system_loop", {
                    "success": False,
                    "revenue": -revenue,
                    "order_id": order_id,
                    "reason": "cancelled",
                })
                return {"order_id": order_id, "outcome_tracked": True, "type": "cancellation"}
            except Exception:
                pass

        return {"order_id": order_id, "outcome_tracked": False, "type": "cancellation"}

    def get_stats(self) -> dict[str, Any]:
        return {"orders_processed": self._processed}
