"""Order Webhook Handler — closes the learning loop by recording real revenue outcomes.

When Shopify sends order.paid → this handler:
  1. Extracts revenue data
  2. Calls OutcomeTracker.record_outcome() to link decision→revenue
  3. Calls KPITracker.record_revenue_event() for business metrics
  4. Calls RevenueTracker.record_revenue() for ROI tracking

This is the CRITICAL piece that makes learning real.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("webhooks.order")


_ENV_ENABLE_CJ_FULFILL = "SHOPAI_ENABLE_CJ_FULFILL"


def _shopify_lines_to_cj(items: Any) -> list[dict[str, Any]]:
    """Map Shopify line_items to CJ productId + quantity.

    A Shopify line carries sku/product_id/variant_id; the CJ
    adapter's ``line_items`` entries want productId + quantity.
    We try properties (owner attached cj_product_id via
    line_item properties), then sku, then product_id. Lines
    without any resolvable CJ id are dropped so we never send
    Shopify-internal ids CJ can't understand.
    """
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cj_id = ""
        props = item.get("properties") or []
        if isinstance(props, list):
            for p in props:
                if isinstance(p, dict) and p.get(
                    "name",
                ) == "cj_product_id":
                    cj_id = str(p.get("value") or "")
                    break
        if not cj_id:
            sku = str(item.get("sku") or "")
            if sku.startswith("cj-") or sku.startswith(
                "cj_",
            ):
                cj_id = sku
        if not cj_id:
            continue
        qty = safe_int(item.get("quantity", 1)) or 1
        variant = item.get("variant_id") or ""
        entry: dict[str, Any] = {
            "productId": cj_id,
            "quantity": max(1, int(qty)),
        }
        if variant:
            entry["variantId"] = str(variant)
        out.append(entry)
    return out


class OrderWebhookHandler:
    """Handles order webhooks and records outcomes for learning."""

    def __init__(
        self, *, cj_fulfill_adapter: Any = None,
    ) -> None:
        self._cj_fulfill = cj_fulfill_adapter
        # ``_processed`` is a plain counter but webhooks arrive
        # on multiple threads (HTTP server worker + async
        # dispatch from ShopifyWebhookHandler.handle_async).
        # Pre-audit ``self._processed += 1`` was not
        # thread-safe. Audit pass 42.
        self._lock = threading.Lock()
        self._processed = 0

    def handle_order_paid(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Process a paid order and record as outcome.

        Args:
            order_data: Shopify order payload (or normalized order dict)

        Returns:
            Summary of what was recorded.
        """
        # Defensive coercion of public entry point. Audit pass 42.
        if not isinstance(order_data, dict):
            order_data = {}

        # Extract revenue data
        order_id = str(order_data.get("id") or order_data.get("order_id") or "")
        revenue = safe_float(order_data.get("total_price") or order_data.get("total"))
        subtotal = safe_float(
            order_data.get("subtotal_price") or order_data.get("subtotal") or revenue
        )
        items = order_data.get("line_items") or []
        item_count = len(items) if isinstance(items, list) else safe_int(order_data.get("items"))
        # ``.get("customer", {})`` returns ``{}`` only when the
        # key is MISSING. Shopify sends ``"customer": null`` on
        # guest orders → crashes the chained ``.get("id")``.
        # Same ``or {}`` pattern as pass 32/36/40/41.
        customer = order_data.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}
        customer_id = str(customer.get("id") or order_data.get("customer_id") or "")

        # Attribution: check for campaign/decision tracking
        note_attrs = order_data.get("note_attributes") or []
        decision_id = None
        campaign_id = None
        if isinstance(note_attrs, list):
            for attr in note_attrs:
                if isinstance(attr, dict):
                    if attr.get("name") == "shopai_decision_id":
                        decision_id = attr.get("value")
                    if attr.get("name") == "shopai_campaign_id":
                        campaign_id = attr.get("value")

        # Also check UTM source for attribution
        source = order_data.get("source_name") or order_data.get("referring_site") or ""
        landing = order_data.get("landing_site") or ""

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

        # 4. Brain learners via OutcomeRecorder — closes the
        # v33-v38 feedback loop. Gated by SHOPAI_BRAIN_HOOKS=1
        # internally; always safe to call.
        try:
            from core.attribution.outcome_recorder import (
                OutcomeEvent, OutcomeRecorder,
            )
            OutcomeRecorder().record(OutcomeEvent(
                kind="purchase",
                ok=True,
                revenue=revenue,
                decision_id=str(decision_id or ""),
                # Webhook payload rarely carries the claimed
                # confidence — if the decision pipeline stored
                # it, downstream work will attach it here.
                claimed_confidence=safe_float(
                    order_data.get("shopai_confidence", 0.0),
                ),
                kpi="revenue",
                kpi_value=revenue,
                capability_name=(
                    "launch_sku" if decision_id else ""
                ),
            ))
            recorded["brain_recorded"] = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("brain outcome record failed: %s", exc)
            recorded["brain_recorded"] = False

        # 5. Optional CJ fulfillment dispatch (LX.2 wire-in).
        #    Opt-in via SHOPAI_ENABLE_CJ_FULFILL=1 so owners who
        #    only want analytics don't trigger live supplier
        #    orders on every paid Shopify order.
        fulfill_info = self._dispatch_cj_fulfillment(
            order_id=order_id,
            order_data=order_data,
            items=items,
            customer=customer,
            decision_id=decision_id,
        )
        if fulfill_info is not None:
            recorded["cj_fulfillment"] = fulfill_info

        with self._lock:
            self._processed += 1
            recorded["total_processed"] = self._processed
        return recorded

    # ── CJ fulfillment dispatch ─────────────────────────

    def _dispatch_cj_fulfillment(
        self,
        *,
        order_id: str,
        order_data: dict[str, Any],
        items: Any,
        customer: dict[str, Any],
        decision_id: str | None,
    ) -> dict[str, Any] | None:
        """Place a CJ dropship order for a paid Shopify order.

        No-op unless ``SHOPAI_ENABLE_CJ_FULFILL=1`` AND the
        injected/lazy adapter is_available(). Returns a summary
        dict (status + fulfillment_id or skip reason); None is
        returned only when the step itself raised — callers
        should treat that as a soft skip."""
        if os.environ.get(
            _ENV_ENABLE_CJ_FULFILL, "",
        ) != "1":
            return {"status": "skipped", "reason": "disabled"}
        if not order_id:
            return {
                "status": "skipped",
                "reason": "no order_id",
            }
        try:
            adapter = self._get_cj_fulfill()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cj_fulfill import failed: %s", exc,
            )
            return {"status": "error", "reason": str(exc)}
        if adapter is None or not adapter.is_available():
            return {
                "status": "skipped",
                "reason": "cj adapter unavailable",
            }
        line_items = _shopify_lines_to_cj(items)
        if not line_items:
            return {
                "status": "skipped",
                "reason": "no mappable line items",
            }
        shipping = (
            order_data.get("shipping_address") or {}
        )
        if not isinstance(shipping, dict):
            shipping = {}
        # Guest orders lack customer info; CJ still needs an
        # address, so pass whatever Shopify gave us.
        try:
            order = adapter.place_order(
                shopify_order_number=str(order_id),
                shipping_address=shipping,
                line_items=line_items,
                note=(
                    f"ShopAI order {order_id}"
                    + (
                        f" (decision={decision_id})"
                        if decision_id else ""
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CJ fulfill dispatch raised: %s", exc,
            )
            return {"status": "error", "reason": str(exc)}
        if order is None:
            stats: dict[str, Any] = {}
            try:
                stats = adapter.stats()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "cj_fulfill stats() failed: %s", exc,
                )
            return {
                "status": "error",
                "reason": stats.get("last_error", "unknown"),
            }
        return {
            "status": "placed",
            "fulfillment_id": order.fulfillment_id,
            "cj_status": order.status,
        }

    def _get_cj_fulfill(self) -> Any:
        if self._cj_fulfill is not None:
            return self._cj_fulfill
        from core.adapters.fulfillment import (
            CJFulfillAdapter,
        )
        self._cj_fulfill = CJFulfillAdapter()
        return self._cj_fulfill

    def handle_order_cancelled(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Process a cancelled order — record negative outcome."""
        if not isinstance(order_data, dict):
            order_data = {}
        order_id = str(order_data.get("id") or "")
        revenue = safe_float(order_data.get("total_price") or order_data.get("total"))

        note_attrs = order_data.get("note_attributes") or []
        decision_id = None
        if isinstance(note_attrs, list):
            for attr in note_attrs:
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
                # Feed brain learners as well
                try:
                    from core.attribution.outcome_recorder import (
                        OutcomeRecorder,
                    )
                    OutcomeRecorder().record_cancel(
                        decision_id=str(decision_id),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "brain cancel record failed: %s", exc,
                    )
                return {"order_id": order_id, "outcome_tracked": True, "type": "cancellation"}
            except Exception as exc:  # noqa: BLE001
                logger.debug("order cancellation outcome tracking failed: %s", exc)

        return {"order_id": order_id, "outcome_tracked": False, "type": "cancellation"}

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {"orders_processed": self._processed}
