"""RealtimeMonitor — continuous store monitoring with instant reactions.

Runs in background. Watches:
  - Store data changes (via periodic sync)
  - Order events (new sales!)
  - Inventory alerts (stockout danger)
  - Performance metrics

Triggers brain decisions when something important happens.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("realtime_monitor")


class RealtimeMonitor:
    """Continuous store monitoring with brain-powered reactions."""

    def __init__(self, store_manager: Any = None) -> None:
        self._sm = store_manager
        self._running = False
        self._thread: threading.Thread | None = None
        self._check_interval = 60  # seconds between checks
        self._brain = None
        self._last_state: dict[str, Any] = {}
        self._event_log: list[dict[str, Any]] = []
        self._callbacks: list[Any] = []

    def _init_brain(self) -> None:
        if not self._brain:
            from core.brain.decision_brain import DecisionBrain
            self._brain = DecisionBrain()

    # ── Start/Stop ───────────────────────────────────────────

    def start(self, interval: int = 60) -> dict[str, Any]:
        if self._running:
            return {"status": "already_running"}

        self._init_brain()
        self._check_interval = interval
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="shopai-monitor"
        )
        self._thread.start()
        logger.info("Realtime monitor started (every %ds)", interval)
        return {"status": "started", "interval": interval}

    def stop(self) -> dict[str, Any]:
        self._running = False
        logger.info("Realtime monitor stopped")
        return {"status": "stopped", "events_logged": len(self._event_log)}

    def on_event(self, callback: Any) -> None:
        """Register callback for events."""
        self._callbacks.append(callback)

    # ── Monitor Loop ─────────────────────────────────────────

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_cycle()
            except Exception as exc:
                logger.error("Monitor error: %s", exc)

            for _ in range(self._check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _check_cycle(self) -> None:
        """One monitoring check cycle."""
        if not self._sm:
            return

        stores = self._sm.list_stores()
        for store in stores:
            sid = store["store_id"]

            # Sync latest data
            try:
                from data_pipeline.store.sync_service import SyncService
                SyncService(self._sm).sync_store(sid)
            except Exception as exc:
                logger.debug("sync service failed for %s: %s", sid, exc)

            # Get current state
            products = self._sm.get_products(sid)
            orders = self._sm.get_orders(sid)
            customers = self._sm.get_customers(sid)

            current = {
                "products": products,
                "order_data": orders,
                "customer_data": customers,
                "store_id": sid,
            }

            # Detect changes
            changes = self._detect_changes(sid, current)

            if changes:
                self._handle_changes(sid, current, changes)

            # Store state for next comparison
            self._last_state[sid] = {
                "product_count": len(products),
                "order_count": len(orders),
                "customer_count": len(customers),
                "timestamp": time.time(),
            }

    # ── Change Detection ─────────────────────────────────────

    def _detect_changes(self, store_id: str, current: dict) -> list[dict[str, Any]]:
        """Detect meaningful changes since last check."""
        changes = []
        prev = self._last_state.get(store_id, {})
        if not prev:
            return [{"type": "first_check", "detail": "Initial monitoring scan"}]

        # New orders
        curr_orders = len(current.get("order_data", []))
        prev_orders = prev.get("order_count", 0)
        if curr_orders > prev_orders:
            changes.append({
                "type": "new_orders",
                "count": curr_orders - prev_orders,
                "detail": f"{curr_orders - prev_orders} new order(s)!",
                "severity": "important",
            })

        # New customers
        curr_customers = len(current.get("customer_data", []))
        prev_customers = prev.get("customer_count", 0)
        if curr_customers > prev_customers:
            changes.append({
                "type": "new_customers",
                "count": curr_customers - prev_customers,
                "detail": f"{curr_customers - prev_customers} new customer(s)",
                "severity": "info",
            })

        # Product count changed
        curr_products = len(current.get("products", []))
        prev_products = prev.get("product_count", 0)
        if curr_products != prev_products:
            changes.append({
                "type": "product_change",
                "detail": f"Products: {prev_products} → {curr_products}",
                "severity": "info",
            })

        # Stockout detection
        for p in current.get("products", []):
            qty = int(p.get("inventory_quantity", 0) or 0)
            if qty == 0:
                changes.append({
                    "type": "stockout",
                    "product": p.get("name", "?"),
                    "detail": f"OUT OF STOCK: {p.get('name', '?')}",
                    "severity": "critical",
                })

        return changes

    # ── Handle Changes ───────────────────────────────────────

    def _handle_changes(self, store_id: str, data: dict, changes: list) -> None:
        """React to detected changes."""
        for change in changes:
            self._log_event(store_id, change)

        # If critical or important changes, trigger brain
        important = [c for c in changes if c.get("severity") in ("critical", "important")]
        if important and self._brain:
            thought = self._brain.think(data)
            self._log_event(store_id, {
                "type": "brain_activated",
                "trigger": [c["type"] for c in important],
                "decisions": len(thought.get("decisions", [])),
                "top_action": thought.get("action_plan", [{}])[0] if thought.get("action_plan") else {},
            })

        # Fire callbacks
        for cb in self._callbacks:
            try:
                cb(store_id, changes)
            except Exception as exc:
                logger.debug("realtime callback failed: %s", exc)

    def _log_event(self, store_id: str, event: dict) -> None:
        event["store_id"] = store_id
        event["timestamp"] = time.time()
        self._event_log.append(event)
        if len(self._event_log) > 500:
            self._event_log = self._event_log[-500:]

        severity = event.get("severity", "info")
        if severity == "critical":
            logger.warning("MONITOR [%s]: %s", store_id, event.get("detail", event.get("type", "")))
        else:
            logger.info("MONITOR [%s]: %s", store_id, event.get("detail", event.get("type", "")))

    # ── Query ────────────────────────────────────────────────

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._event_log[-limit:]

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "interval": self._check_interval,
            "events": len(self._event_log),
            "stores_monitored": len(self._last_state),
        }
