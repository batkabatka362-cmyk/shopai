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


# ── Order-event helpers (LTV + email flow) ──────────────


def _order_ts(order_data: dict[str, Any]) -> float:
    """Best-effort timestamp for an order. Shopify sends
    ISO-8601 in ``created_at`` / ``processed_at``; fall back to
    now when absent or malformed. LTV math tolerates slightly
    stale ts, but a missing one would zero the first_order_at
    pointer."""
    import datetime as _dt
    import time as _time
    for key in ("processed_at", "created_at", "updated_at"):
        raw = order_data.get(key)
        if not raw:
            continue
        try:
            # Shopify uses "2026-04-22T10:30:00-04:00" or
            # "Z" suffix — fromisoformat handles both on 3.11+.
            return _dt.datetime.fromisoformat(
                str(raw).replace("Z", "+00:00"),
            ).timestamp()
        except (ValueError, TypeError):
            continue
    return float(_time.time())


def _cancel_abandoned_cart(
    *,
    customer: dict[str, Any],
    order_data: dict[str, Any],
) -> int:
    """Cancel pending abandoned_cart reminder emails for the
    buyer who just converted. Returns the count cancelled.

    Silent no-op when:
      * no email on the order
      * no pending abandoned_cart rows (common — buyer never
        hit the cart-abandonment trigger)
    """
    from core.engines.email_campaigns import get_engine as _ec

    email = str(
        customer.get("email")
        or order_data.get("email")
        or "",
    ).strip().lower()
    if not email or "@" not in email:
        return 0
    return int(_ec().cancel_flow(
        email, "abandoned_cart",
        reason=f"order {order_data.get('id') or ''} placed",
    ))


def _enroll_post_purchase(
    *,
    customer: dict[str, Any],
    order_data: dict[str, Any],
    revenue: float,
    items: list[dict[str, Any]],
) -> None:
    """Enroll the buyer into the post-purchase email flow.

    Context keys consumed by ``flows.post_purchase``:
      first_name, product_name, review_url, store_name,
      recommendations, store_url, discount_code

    Missing keys silently cause the dispatcher to skip a send
    (status=skipped_missing_ctx) — we don't over-validate
    here, let the dispatcher be the source of truth.
    """
    import os as _os
    from core.engines.email_campaigns import get_engine as _ec

    email = str(
        customer.get("email")
        or order_data.get("email")
        or "",
    ).strip().lower()
    if not email or "@" not in email:
        return  # nothing to enroll without a valid address

    first_name = str(
        customer.get("first_name")
        or (email.split("@", 1)[0] or "there"),
    )
    product_name = ""
    if items:
        first_item = items[0] if isinstance(items[0], dict) else {}
        product_name = str(
            first_item.get("title")
            or first_item.get("name")
            or "your order",
        )

    store_url = str(
        _os.environ.get("SHOPAI_SHOPIFY_URL") or "",
    ).strip()
    if store_url and not store_url.startswith("http"):
        store_url = f"https://{store_url}"
    store_name = str(
        _os.environ.get("SHOPAI_STORE_NAME") or "Deguar",
    )
    review_url = f"{store_url}/pages/reviews" if store_url else ""
    recommendations = (
        # Left blank on first send — brain can back-fill when
        # cross-sell engine ships. Empty string is an allowed
        # context value; dispatcher will render it as empty
        # and the email still goes out with a trimmed body.
        "Check our best sellers: " + store_url
        if store_url else "Check our best sellers online."
    )
    discount_code = str(
        _os.environ.get("SHOPAI_EMAIL_COMEBACK_CODE")
        or "COMEBACK10",
    )

    _ec().enroll(
        email, flow="post_purchase",
        context={
            "first_name": first_name,
            "product_name": product_name,
            "review_url": review_url,
            "store_name": store_name,
            "store_url": store_url,
            "recommendations": recommendations,
            "discount_code": discount_code,
        },
    )


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
        # Gate-check marker — set by ready-for-live's 5-order
        # synthetic smoke test. When present we still run the
        # handler (so the import chain is exercised end-to-end)
        # but skip the engine_outcome_bus + feedback_store emits
        # that would otherwise pollute the production learning
        # ledger with 5 fake entries per gate run.
        is_gate_check = False
        if isinstance(note_attrs, list):
            for attr in note_attrs:
                if (
                    isinstance(attr, dict)
                    and attr.get("name") == "shopai_gate_check"
                    and str(attr.get("value", "")).lower() in (
                        "1", "true", "yes",
                    )
                ):
                    is_gate_check = True
                    break
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

        # Agentic channel attribution (Wave B-1 A4).
        # Shopify's Agentic Storefronts are default-on since
        # 24 Mar 2026; ``source_name`` / ``note_attributes``
        # carry ``chatgpt`` | ``perplexity`` | ``copilot`` |
        # ``gemini`` | ``agentic`` when an AI surface
        # originated the order. Classify here so every paid
        # order becomes a per-channel learning signal.
        agentic_channel = ""
        try:
            from core.bridge.agentic_storefront import (
                AgenticStorefrontBridge,
            )
            agentic_channel = (
                AgenticStorefrontBridge.classify_order(
                    order_data,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "agentic classify failed: %s", exc,
            )

        recorded = {"order_id": order_id, "revenue": revenue, "items": item_count}
        if agentic_channel:
            recorded["agentic_channel"] = agentic_channel

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

        # 4a. Refine + learn loop — back-fill the
        #     5-pillar Deliberation that drove this
        #     decision with the actual measured revenue.
        #     CLAUDE.md §4d pillar 4. Soft-fail: missing
        #     module / no matching record → debug log + move
        #     on; never blocks the webhook.
        if decision_id:
            try:
                from core.brain.structured_decision import (
                    record_outcome_for_decision,
                    find_deliberation_by_decision_id,
                )
                back_filled = record_outcome_for_decision(
                    str(decision_id),
                    {
                        "kind": "purchase",
                        "revenue_usd": float(revenue),
                        "subtotal_usd": float(subtotal),
                        "items": int(item_count),
                        "order_id": str(order_id),
                        "agentic_channel": (
                            agentic_channel or ""
                        ),
                    },
                )
                recorded["deliberation_observed"] = (
                    bool(back_filled)
                )
                # 4a.1 Predicted-vs-actual feed so the world
                # model calibrates from real revenue. The
                # Deliberation's OutcomeSpec.value_usd is the
                # prediction the brain committed to; revenue
                # is the actual. EngineOutcome.predicted
                # triggers the world_calibration sink inside
                # the bus (see engine_outcome_bus._get_
                # world_calib). Without this wire,
                # predict_outcome returns uncalibrated
                # estimates forever.
                if back_filled:
                    delib = (
                        find_deliberation_by_decision_id(
                            str(decision_id),
                        )
                    )
                    predicted_usd = float(
                        getattr(
                            getattr(
                                delib, "outcome", None,
                            ),
                            "value_usd", 0.0,
                        ) or 0.0,
                    ) if delib is not None else 0.0
                    if predicted_usd > 0:
                        try:
                            from core.integration.engine_outcome_bus import (  # noqa: E501
                                EngineOutcome,
                                get_engine_outcome_bus,
                            )
                            get_engine_outcome_bus().report(
                                EngineOutcome(
                                    engine=(
                                        "deliberation_"
                                        "calibration"
                                    ),
                                    kpi="revenue",
                                    value=float(revenue),
                                    ok=revenue > 0,
                                    source="order_webhook",
                                    context={
                                        "order_id": order_id,
                                        "decision_id": (
                                            str(decision_id)
                                        ),
                                    },
                                    predicted=predicted_usd,
                                    rationale_id=str(
                                        decision_id,
                                    ),
                                ),
                            )
                            recorded[
                                "calibration_fed"
                            ] = True
                        except Exception as exc:  # noqa: BLE001, E501
                            logger.debug(
                                "calibration feed failed: "
                                "%s", exc,
                            )
                            recorded[
                                "calibration_fed"
                            ] = False
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "deliberation back-fill failed: %s",
                    exc,
                )
                recorded["deliberation_observed"] = False

        # 4b. Agentic channel outcome on the engine bus so
        #     per-channel ROAS rebalancing has real evidence.
        if agentic_channel and not is_gate_check:
            try:
                from core.integration.engine_outcome_bus import (
                    EngineOutcome,
                    get_engine_outcome_bus,
                )
                get_engine_outcome_bus().report(EngineOutcome(
                    engine="agentic_storefront",
                    kpi="gmv",
                    value=float(revenue),
                    ok=revenue > 0,
                    source=agentic_channel,
                    context={
                        "order_id": order_id,
                        "channel": agentic_channel,
                        "items": item_count,
                    },
                    rationale_id=str(decision_id or ""),
                ))
                recorded["agentic_bus_reported"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "agentic bus report failed: %s", exc,
                )
                recorded["agentic_bus_reported"] = False

        # 4c. General order_paid outcome on the engine bus.
        #     Separate from 4b: even organic (non-agentic)
        #     orders feed the learning ledger — feedback_store
        #     + freshness_tracker + pattern_miner benefit from
        #     every outcome, not just attributable ones. Audit
        #     batch 3 wire-up — keeps the replay-orders CLI a
        #     real learning exerciser rather than a silent
        #     no-op for organic payloads.
        if is_gate_check:
            recorded["order_bus_reported"] = False
            recorded["gate_check_skipped_bus"] = True
        else:
            try:
                from core.integration.engine_outcome_bus import (
                    EngineOutcome,
                    get_engine_outcome_bus,
                )
                get_engine_outcome_bus().report(EngineOutcome(
                    engine="order_webhook",
                    kpi="revenue",
                    value=float(revenue),
                    ok=revenue > 0,
                    source=(
                        agentic_channel or "organic"
                    ),
                    context={
                        "order_id": order_id,
                        "items": item_count,
                    },
                    rationale_id=str(decision_id or ""),
                ))
                recorded["order_bus_reported"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "order bus report failed: %s", exc,
                )
                recorded["order_bus_reported"] = False

        # 4.9 Budget+Buyer LTV ingest. Aggregate this order
        # into the per-customer LTV tracker so dormant/win-back
        # logic has live signal. Skip on gate-check synth orders
        # so the production LTV store isn't polluted with 5
        # fake customers per go-live probe.
        if not is_gate_check:
            try:
                from core.engines.budget_buyer import get_engine
                customer_email = str(
                    customer.get("email")
                    or order_data.get("email")
                    or order_data.get("contact_email")
                    or "",
                ).strip().lower()
                if customer_email or customer_id:
                    get_engine().record_order(
                        customer_id=customer_id or customer_email,
                        email=customer_email,
                        amount_usd=float(revenue or 0),
                        ts=_order_ts(order_data),
                    )
                    recorded["ltv_recorded"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "ltv record failed: %s", exc,
                )
                recorded["ltv_recorded"] = False

        # 4.95 Post-purchase email flow auto-enroll. The
        # email_campaigns engine queues the 3-day + 14-day
        # emails; dispatcher fires them on the autopilot
        # cycle. Missing context (no email, no first_name)
        # silently skips — engine is idempotent so re-enrolls
        # on duplicate webhooks are no-ops.
        if not is_gate_check:
            try:
                _enroll_post_purchase(
                    customer=customer, order_data=order_data,
                    revenue=float(revenue or 0),
                    items=items if isinstance(items, list) else [],
                )
                recorded["post_purchase_enrolled"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "post-purchase enroll failed: %s", exc,
                )
                recorded["post_purchase_enrolled"] = False

        # 4.96 Cancel any pending abandoned_cart reminders for
        # this buyer. Without this, someone who abandons then
        # converts 30 min later would get the 1h "you left X
        # behind" email after they already bought. §4b.D
        # idempotency via email_campaigns.engine.cancel_flow.
        if not is_gate_check:
            try:
                _cancel_abandoned_cart(
                    customer=customer, order_data=order_data,
                )
                recorded["abandoned_cart_cancelled"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "abandoned-cart cancel failed: %s", exc,
                )
                recorded["abandoned_cart_cancelled"] = False

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
