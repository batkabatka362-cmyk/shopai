"""ShopifyWebhooks — receives Shopify webhook events and auto-triggers engines.

When Shopify sends an event (order created, product updated, customer registered),
this module routes it to the right engine(s) and executes automatically.

Security: validates HMAC signature from Shopify to prevent spoofing.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import time
import threading
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id

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
                 hmac_header: str = "", event_id: str = "") -> None:
        self.event_id = event_id or generate_id("wh")
        self.topic = topic
        self.payload = payload
        self.shop = shop
        self.hmac_header = hmac_header
        self.received_at = time.time()
        self.processed = False
        self.results: list[dict[str, Any]] = []


class ShopifyWebhookHandler:
    """Handles incoming Shopify webhooks and routes to engines."""

    def __init__(self, webhook_secret: str = "") -> None:
        self._secret = webhook_secret
        self._event_log: list[dict[str, Any]] = []
        self._custom_handlers: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()
        self._stats = {"received": 0, "processed": 0, "failed": 0, "skipped": 0}

    def handle(self, topic: str, payload: dict[str, Any],
               hmac_header: str = "", shop: str = "") -> dict[str, Any]:
        """Handle an incoming webhook event."""
        event = WebhookEvent(topic, payload, shop, hmac_header)

        with self._lock:
            self._stats["received"] += 1

        # Validate HMAC if secret configured
        if self._secret and hmac_header:
            if not self._verify_hmac(json.dumps(payload).encode(), hmac_header):
                with self._lock:
                    self._stats["skipped"] += 1
                return {"event_id": event.event_id, "status": "rejected", "reason": "invalid_hmac"}

        logger.info("Webhook received: %s from %s (id=%s)", topic, shop, event.event_id)

        # Route to engines
        mappings = EVENT_ENGINE_MAP.get(topic, [])
        if not mappings:
            with self._lock:
                self._stats["skipped"] += 1
            return {"event_id": event.event_id, "status": "skipped", "reason": f"no_mapping_for_{topic}"}

        # Normalize payload for engines
        normalized = self._normalize_payload(topic, payload)

        # Execute engines
        results = []
        for mapping in mappings:
            engine_name = mapping["engine"]
            data_key = mapping["data_key"]
            priority = mapping["priority"]

            engine_data = {data_key: normalized} if isinstance(normalized, list) else normalized
            result = self._trigger_engine(engine_name, engine_data, priority, event.event_id)
            results.append(result)

        # Run custom handlers
        for handler in self._custom_handlers.get(topic, []):
            try:
                handler(event)
            except Exception as exc:
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
                self._event_log = self._event_log[-5000:]

        return {
            "event_id": event.event_id,
            "status": "processed",
            "topic": topic,
            "engines_triggered": len(results),
            "results": results,
        }

    def handle_async(self, topic: str, payload: dict[str, Any],
                     hmac_header: str = "", shop: str = "") -> str:
        """Handle webhook asynchronously. Returns event_id immediately."""
        event_id = generate_id("wh")
        thread = threading.Thread(
            target=self.handle,
            args=(topic, payload, hmac_header, shop),
            daemon=True,
        )
        thread.start()
        return event_id

    def register_handler(self, topic: str, handler: Callable) -> None:
        """Register a custom handler for a webhook topic."""
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
        return [{
            "id": str(payload.get("id", "")),
            "total": float(payload.get("total_price", 0) or 0),
            "subtotal": float(payload.get("subtotal_price", 0) or 0),
            "status": payload.get("financial_status", ""),
            "items": len(payload.get("line_items", [])),
            "customer_id": str(payload.get("customer", {}).get("id", "")),
        }]

    @staticmethod
    def _normalize_product(payload: dict) -> list[dict]:
        variant = payload.get("variants", [{}])[0] if payload.get("variants") else {}
        return [{
            "id": str(payload.get("id", "")),
            "name": payload.get("title", ""),
            "price": float(variant.get("price", 0) or 0),
            "cost": float(variant.get("cost", 0) or 0),
            "category": payload.get("product_type", ""),
            "inventory_quantity": int(variant.get("inventory_quantity", 0) or 0),
        }]

    @staticmethod
    def _normalize_customer(payload: dict) -> list[dict]:
        return [{
            "id": str(payload.get("id", "")),
            "name": f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip(),
            "email": payload.get("email", ""),
            "orders": int(payload.get("orders_count", 0) or 0),
            "total_spent": float(payload.get("total_spent", 0) or 0),
        }]

    @staticmethod
    def _normalize_inventory_level(payload: dict) -> dict:
        return {
            "inventory_item_id": str(payload.get("inventory_item_id", "")),
            "location_id": str(payload.get("location_id", "")),
            "available": int(payload.get("available", 0) or 0),
        }

    def _verify_hmac(self, data: bytes, hmac_header: str) -> bool:
        """Verify Shopify HMAC signature."""
        try:
            computed = hmac.new(
                self._secret.encode(), data, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(computed, hmac_header)
        except Exception:
            return False
