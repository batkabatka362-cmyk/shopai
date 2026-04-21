"""ShopifyWebhooks — receives Shopify webhook events and auto-triggers engines.

When Shopify sends an event (order created, product updated, customer registered),
this module routes it to the right engine(s) and executes automatically.

Security: validates HMAC signature from Shopify to prevent spoofing.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import time
import threading
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id, safe_float, safe_int

logger = get_logger("webhooks.shopify")


# Event → Engine mapping: which engines to trigger for each Shopify event
EVENT_ENGINE_MAP: dict[str, list[dict[str, Any]]] = {
    # Order events
    "orders/create": [
        {"engine": "analytics", "priority": "high", "data_key": "order_data"},
        {"engine": "inventory", "priority": "high", "data_key": "order_data"},
        {"engine": "customer_analytics", "priority": "medium", "data_key": "order_data"},
    ],
    "orders/updated": [
        {"engine": "order_management", "priority": "medium", "data_key": "order_data"},
    ],
    "orders/cancelled": [
        {"engine": "inventory", "priority": "high", "data_key": "order_data"},
        {"engine": "refund_processing", "priority": "high", "data_key": "refund_request"},
    ],
    "orders/fulfilled": [
        {"engine": "shipping_optimization", "priority": "medium", "data_key": "order_data"},
        {"engine": "delivery_feedback", "priority": "low", "data_key": "delivery_data"},
    ],

    # Product events
    "products/create": [
        {"engine": "product_selection", "priority": "medium", "data_key": "products"},
        {"engine": "seo", "priority": "low", "data_key": "page_data"},
        {"engine": "product_description", "priority": "medium", "data_key": "product_data"},
    ],
    "products/update": [
        {"engine": "pricing", "priority": "medium", "data_key": "products"},
        {"engine": "inventory", "priority": "medium", "data_key": "inventory_data"},
    ],
    "products/delete": [
        {"engine": "catalog", "priority": "high", "data_key": "product_data"},
    ],

    # Customer events
    "customers/create": [
        {"engine": "customer_segmentation", "priority": "medium", "data_key": "customer_data"},
        {"engine": "email_marketing", "priority": "low", "data_key": "audience_segment"},
    ],
    "customers/update": [
        {"engine": "customer_analytics", "priority": "low", "data_key": "customer_data"},
    ],

    # Checkout events
    "checkouts/create": [
        {"engine": "conversion_tracking", "priority": "high", "data_key": "funnel_data"},
    ],
    "checkouts/update": [
        {"engine": "cart_recovery", "priority": "high", "data_key": "abandoned_carts"},
    ],

    # Inventory events
    "inventory_levels/update": [
        {"engine": "inventory", "priority": "high", "data_key": "inventory_data"},
        {"engine": "stock_prediction", "priority": "medium", "data_key": "sales_history"},
    ],

    # Refund events
    "refunds/create": [
        {"engine": "refund_processing", "priority": "high", "data_key": "refund_request"},
        {"engine": "returns_management", "priority": "medium", "data_key": "return_requests"},
    ],
}


class WebhookEvent:
    """A received webhook event."""

    def __init__(self, topic: str, payload: dict[str, Any], shop: str = "",
                 hmac_header: str = "", event_id: str | None = None) -> None:
        self.event_id = event_id if isinstance(event_id, str) and event_id else generate_id("wh")
        self.topic = topic if isinstance(topic, str) else ""
        self.payload = payload if isinstance(payload, dict) else {}
        self.shop = shop if isinstance(shop, str) else ""
        self.hmac_header = hmac_header if isinstance(hmac_header, str) else ""
        self.received_at = time.time()
        self.processed = False
        self.results: list[dict[str, Any]] = []


class ShopifyWebhookHandler:
    """Handles incoming Shopify webhooks and routes to engines.

    Security: Shopify signs every webhook's raw body with
    HMAC-SHA256 + base64 in ``X-Shopify-Hmac-SHA256``. When a
    secret is configured we verify against the raw bytes and
    reject mismatches. When no secret is configured we ACCEPT
    every webhook — that's a production hole the instance-
    level secret fixes.

    Resolution order for the secret (first non-empty wins):
      1. ``webhook_secret`` kwarg (explicit)
      2. ``SHOPAI_SHOPIFY_WEBHOOK_SECRET`` env var
      3. ``SHOPIFY_WEBHOOK_SECRET`` env var
         (standard Shopify convention)

    Set ``SHOPAI_WEBHOOK_VERIFY_REQUIRED=1`` to reject every
    incoming webhook when no secret is configured rather than
    silently accepting them — the safe default for production.
    """

    def __init__(
        self, webhook_secret: str = "",
    ) -> None:
        if webhook_secret:
            self._secret = webhook_secret
        else:
            self._secret = (
                os.environ.get(
                    "SHOPAI_SHOPIFY_WEBHOOK_SECRET", "",
                )
                or os.environ.get(
                    "SHOPIFY_WEBHOOK_SECRET", "",
                )
            )
        self._verify_required = (
            os.environ.get(
                "SHOPAI_WEBHOOK_VERIFY_REQUIRED", "",
            ) == "1"
        )
        self._event_log: list[dict[str, Any]] = []
        self._custom_handlers: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()
        self._stats = {"received": 0, "processed": 0, "failed": 0, "skipped": 0}

    def handle(self, topic: str, payload: dict[str, Any],
               hmac_header: str = "", shop: str = "",
               raw_body: bytes | None = None,
               event_id: str | None = None) -> dict[str, Any]:
        """Handle an incoming webhook event.

        Args:
            topic: Shopify webhook topic (e.g. ``"orders/create"``).
            payload: Parsed JSON payload dict.
            hmac_header: value of ``X-Shopify-Hmac-SHA256``.
            shop: value of ``X-Shopify-Shop-Domain``.
            raw_body: the RAW request body bytes. This is what
                Shopify actually signed; HMAC verification must
                run against these exact bytes because Python's
                ``json.dumps(payload)`` produces different
                whitespace / key-order / escaping than Shopify
                sent. Pre-audit the handler re-serialised
                ``payload`` and compared the hex digest against
                a base64 header — HMAC verification was 100%
                broken whenever a secret was configured.
                Audit pass 42 fix.
            event_id: optional pre-assigned id. ``handle_async``
                uses this so the id it returned to the caller
                matches the id that actually gets processed.
        """
        # Defensive coercion of public entry point. Audit pass 42.
        topic = topic if isinstance(topic, str) else ""
        payload = payload if isinstance(payload, dict) else {}
        hmac_header = hmac_header if isinstance(hmac_header, str) else ""
        shop = shop if isinstance(shop, str) else ""
        if not isinstance(event_id, str) or not event_id:
            event_id = generate_id("wh")

        event = WebhookEvent(topic, payload, shop, hmac_header, event_id=event_id)

        with self._lock:
            self._stats["received"] += 1

        # HMAC verification — fail CLOSED when a secret is
        # configured, and (via SHOPAI_WEBHOOK_VERIFY_REQUIRED=1)
        # also when NO secret is set. The optional "required"
        # flag blocks silent-accept in production where the
        # operator forgot to set the secret.
        if not self._secret and self._verify_required:
            with self._lock:
                self._stats["skipped"] += 1
            logger.warning(
                "Webhook %s rejected: no webhook secret set "
                "and SHOPAI_WEBHOOK_VERIFY_REQUIRED=1",
                topic,
            )
            return {
                "event_id": event.event_id,
                "status": "rejected",
                "reason": "webhook_secret_not_configured",
            }
        if self._secret:
            if not hmac_header:
                with self._lock:
                    self._stats["skipped"] += 1
                return {
                    "event_id": event.event_id,
                    "status": "rejected",
                    "reason": "missing_hmac_header",
                }
            if raw_body is None:
                # Without the raw bytes we CANNOT verify —
                # reject rather than fall back to the broken
                # re-serialisation path. Callers must pass the
                # raw request body when a secret is set.
                with self._lock:
                    self._stats["skipped"] += 1
                logger.warning(
                    "Webhook %s rejected: secret configured but raw_body not provided", topic
                )
                return {
                    "event_id": event.event_id,
                    "status": "rejected",
                    "reason": "raw_body_required_for_hmac",
                }
            if not self._verify_hmac(raw_body, hmac_header):
                with self._lock:
                    self._stats["skipped"] += 1
                return {
                    "event_id": event.event_id,
                    "status": "rejected",
                    "reason": "invalid_hmac",
                }

        logger.info("Webhook received: %s from %s (id=%s)", topic, shop, event.event_id)

        # Route to engines
        mappings = EVENT_ENGINE_MAP.get(topic) or []
        if not isinstance(mappings, list) or not mappings:
            with self._lock:
                self._stats["skipped"] += 1
            return {"event_id": event.event_id, "status": "skipped", "reason": f"no_mapping_for_{topic}"}

        # Normalize payload for engines
        normalized = self._normalize_payload(topic, payload)

        # Execute engines
        results = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            engine_name = mapping.get("engine")
            data_key = mapping.get("data_key", "data")
            priority = mapping.get("priority", "medium")
            if not isinstance(engine_name, str) or not engine_name:
                continue

            # Wrap the normalised payload under ``data_key`` so
            # every engine sees a consistent ``{data_key: ...}``
            # envelope. Pre-audit this was list-vs-dict
            # branched, which meant engines for dict-topic
            # payloads never received the expected ``data_key``
            # wrapper.
            engine_data = {data_key: normalized}
            result = self._trigger_engine(engine_name, engine_data, priority, event.event_id)
            results.append(result)

        # Run custom handlers
        with self._lock:
            handlers_snapshot = list(self._custom_handlers.get(topic, []))
        for handler in handlers_snapshot:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("Custom handler failed for %s: %s", topic, exc)

        event.processed = True
        event.results = results

        with self._lock:
            self._stats["processed"] += 1
            self._event_log.append({
                "event_id": event.event_id,
                "topic": topic,
                "shop": shop,
                "engines_triggered": len(results),
                "successful": sum(1 for r in results if r.get("status") == "completed"),
                "timestamp": event.received_at,
            })
            if len(self._event_log) > 5000:
                # Trim in place so any external reference stays
                # valid (same pattern as SmartScheduler pass 38).
                del self._event_log[:len(self._event_log) - 5000]

        return {
            "event_id": event.event_id,
            "status": "processed",
            "topic": topic,
            "engines_triggered": len(results),
            "results": results,
        }

    def handle_async(self, topic: str, payload: dict[str, Any],
                     hmac_header: str = "", shop: str = "",
                     raw_body: bytes | None = None) -> str:
        """Handle webhook asynchronously. Returns event_id immediately.

        The id returned here is the SAME id that ``handle()``
        will stamp on the processed event. Pre-audit the
        background thread generated its own id inside
        ``handle()`` so the caller's id never matched any
        processed event — identical bug pattern to pass-38's
        EventReactor.react_async fix.
        """
        event_id = generate_id("wh")
        thread = threading.Thread(
            target=self.handle,
            args=(topic, payload, hmac_header, shop, raw_body, event_id),
            daemon=True,
        )
        thread.start()
        return event_id

    def register_handler(self, topic: str, handler: Callable) -> None:
        """Register a custom handler for a webhook topic."""
        if not isinstance(topic, str) or not callable(handler):
            return
        with self._lock:
            self._custom_handlers.setdefault(topic, []).append(handler)

    def get_event_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._event_log[-limit:])

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)

    def list_supported_events(self) -> list[dict[str, Any]]:
        """List all supported webhook events and their engine mappings."""
        return [
            {"topic": topic, "engines": [m["engine"] for m in mappings], "count": len(mappings)}
            for topic, mappings in EVENT_ENGINE_MAP.items()
        ]

    def _trigger_engine(self, engine_name: str, data: dict[str, Any],
                        priority: str, event_id: str) -> dict[str, Any]:
        """Trigger an engine with webhook data."""
        try:
            from engines.registry import get_engine, is_registered
            from engines.base.engine_types import EngineInput

            if not is_registered(engine_name):
                return {"engine": engine_name, "status": "skipped", "reason": "not_registered"}

            engine = get_engine(engine_name)
            inp = EngineInput(
                task_id=f"{event_id}_{engine_name}",
                engine_name=engine_name,
                data=copy.deepcopy(data),
            )
            output = engine.run(inp)
            return {
                "engine": engine_name,
                "status": output.status.value,
                "priority": priority,
            }
        except Exception as exc:
            logger.error("Engine trigger failed: %s — %s", engine_name, exc)
            with self._lock:
                self._stats["failed"] += 1
            return {"engine": engine_name, "status": "error", "error": str(exc)}

    def _normalize_payload(self, topic: str, payload: dict[str, Any]) -> Any:
        """Normalize Shopify webhook payload for engine consumption."""
        payload = payload if isinstance(payload, dict) else {}
        if "order" in topic:
            return self._normalize_order(payload)
        if "product" in topic:
            return self._normalize_product(payload)
        if "customer" in topic:
            return self._normalize_customer(payload)
        if "inventory" in topic:
            return [self._normalize_inventory_level(payload)]
        return payload

    @staticmethod
    def _normalize_order(payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return [{}]
        # ``.get("customer", {})`` returns ``{}`` only when the
        # key is MISSING. Shopify sends an explicit
        # ``"customer": null`` on guest orders, which crashes
        # ``.get().get()``. Same ``x or {}`` pattern as passes
        # 32/36/40/41.
        customer = payload.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}
        line_items = payload.get("line_items")
        items_count = len(line_items) if isinstance(line_items, list) else 0
        return [{
            "id": str(payload.get("id", "")),
            "total": safe_float(payload.get("total_price")),
            "subtotal": safe_float(payload.get("subtotal_price")),
            "status": payload.get("financial_status", "") or "",
            "items": items_count,
            "customer_id": str(customer.get("id", "")),
        }]

    @staticmethod
    def _normalize_product(payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return [{}]
        variants = payload.get("variants")
        # Pre-audit did ``payload.get("variants", [{}])[0] if
        # payload.get("variants") else {}`` — if variants was a
        # DICT (not a list) the ``[0]`` access crashed.
        variant: dict[str, Any] = {}
        if isinstance(variants, list) and variants:
            first = variants[0]
            if isinstance(first, dict):
                variant = first
        return [{
            "id": str(payload.get("id", "")),
            "name": payload.get("title", "") or "",
            "price": safe_float(variant.get("price")),
            "cost": safe_float(variant.get("cost")),
            "category": payload.get("product_type", "") or "",
            "inventory_quantity": safe_int(variant.get("inventory_quantity")),
        }]

    @staticmethod
    def _normalize_customer(payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return [{}]
        first = payload.get("first_name") or ""
        last = payload.get("last_name") or ""
        return [{
            "id": str(payload.get("id", "")),
            "name": f"{first} {last}".strip(),
            "email": payload.get("email", "") or "",
            "orders": safe_int(payload.get("orders_count")),
            "total_spent": safe_float(payload.get("total_spent")),
        }]

    @staticmethod
    def _normalize_inventory_level(payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        return {
            "inventory_item_id": str(payload.get("inventory_item_id", "")),
            "location_id": str(payload.get("location_id", "")),
            "available": safe_int(payload.get("available")),
        }

    def _verify_hmac(self, raw_body: bytes, hmac_header: str) -> bool:
        """Verify Shopify HMAC signature.

        Shopify signs the RAW request body with HMAC-SHA256
        using the webhook secret and sends the result
        base64-encoded in ``X-Shopify-Hmac-SHA256``. Pre-audit
        this method used ``hexdigest()`` and compared against
        the base64 header — the two format spaces never
        overlapped so verification always returned False
        (when a secret was configured it rejected all real
        webhooks). Audit pass 42 fix.
        """
        try:
            if not isinstance(raw_body, (bytes, bytearray)):
                return False
            digest = hmac.new(
                self._secret.encode(), bytes(raw_body), hashlib.sha256
            ).digest()
            computed = base64.b64encode(digest).decode()
            return hmac.compare_digest(computed, hmac_header)
        except Exception:  # noqa: BLE001
            return False
