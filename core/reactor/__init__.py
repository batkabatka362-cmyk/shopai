"""Event Reactor — real-time intelligent response to store events.

When a Shopify event arrives (order, product change, customer activity):
  1. Classify: what kind of event? how urgent?
  2. Deduplicate: have we seen this recently?
  3. Decide: run FullSystemLoop or targeted action?
  4. Execute: dispatch with cooldowns and priority queue
  5. Learn: record outcome for future improvement

This makes ShopAI REACTIVE — like a human store operator who
responds immediately when something happens.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id, safe_float

logger = get_logger("reactor")


class EventReactor:
    """Real-time event processor with priority queue, cooldowns, and dedup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Priority queues: high (immediate), medium (batch), low (when idle)
        self._queues: dict[str, deque] = {
            "critical": deque(maxlen=100),
            "high": deque(maxlen=500),
            "medium": deque(maxlen=1000),
            "low": deque(maxlen=2000),
        }
        # Cooldowns: event_key → last_processed_time
        self._cooldowns: dict[str, float] = {}
        # Dedup: event_hash → timestamp
        self._seen: dict[str, float] = {}
        self._seen_ttl = 300  # 5 min dedup window
        # Handlers: event_type → handler function
        self._handlers: dict[str, Callable] = {}
        # Stats
        self._stats = {
            "received": 0, "processed": 0, "deduplicated": 0,
            "cooled_down": 0, "failed": 0,
        }
        self._results: list[dict[str, Any]] = []
        # Register default handlers
        self._register_defaults()

    # ── Event Submission ──

    def react(self, event_type: str, data: dict[str, Any],
              priority: str = "medium", source: str = "webhook") -> dict[str, Any]:
        """Submit an event for reactive processing.

        Returns immediately with event_id and processing status.
        """
        event_id = generate_id("evt")
        event = {
            "event_id": event_id,
            "type": event_type,
            "data": data,
            "priority": priority,
            "source": source,
            "received_at": time.time(),
        }

        with self._lock:
            self._stats["received"] += 1

        # Dedup check
        event_hash = self._hash_event(event_type, data)
        if self._is_duplicate(event_hash):
            with self._lock:
                self._stats["deduplicated"] += 1
            return {"event_id": event_id, "status": "deduplicated", "reason": "Similar event processed recently"}

        # Cooldown check
        cooldown_key = f"{event_type}:{data.get('id', data.get('product_id', data.get('customer_id', '')))}"
        if self._is_cooled_down(cooldown_key, event_type):
            with self._lock:
                self._stats["cooled_down"] += 1
            return {"event_id": event_id, "status": "cooled_down", "reason": "Action cooldown active"}

        # Process event
        result = self._process_event(event)

        # Record cooldown
        self._cooldowns[cooldown_key] = time.time()

        # Record dedup
        self._seen[event_hash] = time.time()
        self._clean_seen()

        return result

    def react_async(self, event_type: str, data: dict[str, Any],
                    priority: str = "medium") -> str:
        """Submit event for async processing. Returns event_id immediately."""
        event_id = generate_id("evt")
        thread = threading.Thread(
            target=self.react,
            args=(event_type, data, priority),
            daemon=True,
        )
        thread.start()
        return event_id

    # ── Event Processing ──

    def _process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Route event to appropriate handler."""
        event_type = event["type"]
        event_id = event["event_id"]
        data = event["data"]

        handler = self._handlers.get(event_type)
        if handler is None:
            # Try generic handler
            handler = self._handlers.get("*")

        if handler is None:
            return {"event_id": event_id, "status": "no_handler", "type": event_type}

        try:
            result = handler(event_type, data, event)
            with self._lock:
                self._stats["processed"] += 1
                self._results.append({
                    "event_id": event_id,
                    "type": event_type,
                    "status": "processed",
                    "result_summary": str(result)[:200] if result else "",
                    "timestamp": time.time(),
                })
                if len(self._results) > 1000:
                    self._results = self._results[-1000:]

            return {"event_id": event_id, "status": "processed", "type": event_type, "result": result}

        except Exception as exc:
            logger.error("Event %s handler failed: %s", event_type, exc)
            with self._lock:
                self._stats["failed"] += 1
            return {"event_id": event_id, "status": "error", "type": event_type, "error": str(exc)}

    # ── Handler Registration ──

    def register_handler(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type] = handler

    def _register_defaults(self) -> None:
        """Register built-in handlers for common Shopify events."""
        self._handlers["order.paid"] = self._handle_order_paid
        self._handlers["order.cancelled"] = self._handle_order_cancelled
        self._handlers["product.low_stock"] = self._handle_low_stock
        self._handlers["product.out_of_stock"] = self._handle_out_of_stock
        self._handlers["product.price_change"] = self._handle_price_change
        self._handlers["customer.churn_risk"] = self._handle_churn_risk
        self._handlers["campaign.underperform"] = self._handle_campaign_underperform
        self._handlers["revenue.drop"] = self._handle_revenue_drop
        self._handlers["*"] = self._handle_generic

    # ── Built-in Handlers ──

    def _handle_order_paid(self, event_type: str, data: dict, event: dict) -> dict:
        """Order paid → record outcome + trigger post-purchase flow."""
        from core.webhooks.order_handler import OrderWebhookHandler
        owh = OrderWebhookHandler()
        result = owh.handle_order_paid(data)

        # Check if order value warrants special treatment
        revenue = safe_float(data.get("total_price", data.get("total", 0)))
        if revenue > 200:
            result["vip_order"] = True
            result["action"] = "Send VIP thank-you + upsell recommendation"

        return result

    def _handle_order_cancelled(self, event_type: str, data: dict, event: dict) -> dict:
        """Order cancelled → record negative outcome + analyze reason."""
        from core.webhooks.order_handler import OrderWebhookHandler
        return OrderWebhookHandler().handle_order_cancelled(data)

    def _handle_low_stock(self, event_type: str, data: dict, event: dict) -> dict:
        """Low stock → trigger reorder recommendation."""
        product_name = data.get("name", data.get("title", "Unknown"))
        quantity = data.get("inventory_quantity", 0)
        return {
            "action": "reorder_recommendation",
            "product": product_name,
            "current_stock": quantity,
            "recommendation": f"Reorder {product_name} — only {quantity} left",
            "priority": "high" if quantity <= 2 else "medium",
        }

    def _handle_out_of_stock(self, event_type: str, data: dict, event: dict) -> dict:
        """Out of stock → disable listing + emergency reorder."""
        product_name = data.get("name", data.get("title", "Unknown"))
        return {
            "action": "emergency_reorder",
            "product": product_name,
            "actions": [
                {"type": "disable_listing", "reason": "out_of_stock", "priority": "critical"},
                {"type": "reorder", "quantity": data.get("reorder_quantity", 50), "priority": "critical"},
                {"type": "notify_customers", "message": f"{product_name} temporarily unavailable", "priority": "high"},
            ],
        }

    def _handle_price_change(self, event_type: str, data: dict, event: dict) -> dict:
        """Competitor price change → analyze and potentially adjust."""
        try:
            from core.intelligence.competitor_intelligence import CompetitorIntelligence
            ci = CompetitorIntelligence()
            our_price = safe_float(data.get("our_price"))
            competitor_price = safe_float(data.get("competitor_price"))
            competitor = data.get("competitor", "Unknown")

            if competitor_price > 0 and our_price > 0:
                diff_pct = round((our_price - competitor_price) / competitor_price * 100, 1)
                if diff_pct > 15:
                    action = "Consider price reduction — significantly above competitor"
                elif diff_pct < -15:
                    action = "Maintain premium — competitor underpricing"
                else:
                    action = "Monitor — prices are competitive"

                return {
                    "action": "price_analysis",
                    "our_price": our_price,
                    "competitor_price": competitor_price,
                    "competitor": competitor,
                    "diff_pct": diff_pct,
                    "recommendation": action,
                }
        except Exception:
            pass
        return {"action": "monitor", "note": "Insufficient data for price analysis"}

    def _handle_churn_risk(self, event_type: str, data: dict, event: dict) -> dict:
        """Customer at churn risk → trigger retention campaign."""
        customer_name = data.get("name", "Customer")
        days_inactive = data.get("days_since_last_order", 0)
        ltv = safe_float(data.get("total_spent", data.get("ltv", 0)))

        if ltv > 500:
            priority = "critical"
            action = f"VIP win-back: personal outreach + exclusive offer for {customer_name}"
        elif ltv > 100:
            priority = "high"
            action = f"Win-back email campaign for {customer_name} (inactive {days_inactive} days)"
        else:
            priority = "medium"
            action = f"Re-engagement email for {customer_name}"

        return {
            "action": "retention_campaign",
            "customer": customer_name,
            "days_inactive": days_inactive,
            "ltv": ltv,
            "priority": priority,
            "recommendation": action,
        }

    def _handle_campaign_underperform(self, event_type: str, data: dict, event: dict) -> dict:
        """Campaign underperforming → optimize or pause."""
        try:
            from core.intelligence.campaign_optimizer import CampaignOptimizer
            co = CampaignOptimizer()
            actions = co.optimize([data])
            return {"action": "campaign_optimization", "optimizations": actions}
        except Exception:
            return {"action": "monitor_campaign", "note": "Manual review needed"}

    def _handle_revenue_drop(self, event_type: str, data: dict, event: dict) -> dict:
        """Revenue drop detected → emergency analysis."""
        drop_pct = safe_float(data.get("drop_pct", 0))
        period = data.get("period", "daily")

        actions = []
        if drop_pct > 30:
            actions.append({"type": "emergency_review", "priority": "critical"})
            actions.append({"type": "check_site_status", "priority": "critical"})
        if drop_pct > 15:
            actions.append({"type": "check_ad_campaigns", "priority": "high"})
            actions.append({"type": "check_competitor_prices", "priority": "high"})
        actions.append({"type": "generate_report", "priority": "medium"})

        return {
            "action": "revenue_drop_response",
            "drop_pct": drop_pct,
            "period": period,
            "severity": "critical" if drop_pct > 30 else "high" if drop_pct > 15 else "medium",
            "actions": actions,
        }

    def _handle_generic(self, event_type: str, data: dict, event: dict) -> dict:
        """Generic handler for unrecognized events."""
        return {"action": "logged", "event_type": event_type, "note": "No specific handler"}

    # ── Cooldown & Dedup Logic ──

    # Cooldown periods per event type (seconds)
    _COOLDOWN_MAP = {
        "order.paid": 0,  # Always process orders
        "order.cancelled": 0,
        "product.low_stock": 3600,  # 1 hour
        "product.out_of_stock": 1800,  # 30 min
        "product.price_change": 7200,  # 2 hours
        "customer.churn_risk": 86400,  # 24 hours
        "campaign.underperform": 3600,
        "revenue.drop": 1800,
    }

    def _is_cooled_down(self, key: str, event_type: str) -> bool:
        cooldown_period = self._COOLDOWN_MAP.get(event_type, 600)
        if cooldown_period == 0:
            return False
        last = self._cooldowns.get(key, 0)
        return (time.time() - last) < cooldown_period

    def _is_duplicate(self, event_hash: str) -> bool:
        ts = self._seen.get(event_hash, 0)
        return (time.time() - ts) < self._seen_ttl

    @staticmethod
    def _hash_event(event_type: str, data: dict) -> str:
        import hashlib
        key = f"{event_type}:{sorted(data.items())}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def _clean_seen(self) -> None:
        """Remove expired dedup entries."""
        now = time.time()
        expired = [k for k, v in self._seen.items() if now - v > self._seen_ttl]
        for k in expired:
            del self._seen[k]

    # ── Stats & Monitoring ──

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)

    def get_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._results[-limit:])

    def get_active_cooldowns(self) -> dict[str, float]:
        """Get currently active cooldowns with remaining time."""
        now = time.time()
        active = {}
        for key, ts in self._cooldowns.items():
            event_type = key.split(":")[0]
            period = self._COOLDOWN_MAP.get(event_type, 600)
            remaining = period - (now - ts)
            if remaining > 0:
                active[key] = round(remaining, 1)
        return active
