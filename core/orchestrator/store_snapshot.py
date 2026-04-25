"""StoreSnapshot — persistent situation model across cycles.

Captures the full state of the store at a point in time:
financial health, inventory status, marketing performance,
customer risks, product scores, and recent events.

Built once per cycle, shared across all subsystems.
Persisted to disk so state survives restarts.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("orchestrator.snapshot")

try:
    from core.memory.storage_config import get_path
    _SNAPSHOT_PATH = os.path.join(get_path("data"), "store_snapshot.json")
except Exception:
    _SNAPSHOT_PATH = "/tmp/shopai_store_snapshot.json"


class StoreSnapshot:
    """Current state of the store — updated each cycle, persisted to disk.

    Usage:
        snapshot = StoreSnapshot()
        snapshot.update_financial(financial_brain.full_analysis(...))
        snapshot.update_products(intelligence_loop_result)
        snapshot.persist()

        # Later / after restart:
        snapshot = StoreSnapshot.load()
        situation = snapshot.get_situation()
    """

    def __init__(self) -> None:
        self.financial: dict[str, Any] = {}
        self.inventory: dict[str, Any] = {}
        self.marketing: dict[str, Any] = {}
        self.customers: dict[str, Any] = {}
        self.products: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.health: dict[str, Any] = {}
        self.priorities: list[dict[str, Any]] = []
        self.last_updated: float = 0
        self.cycle_id: str = ""
        self._history: list[dict[str, Any]] = []

    def update_financial(self, analysis: dict[str, Any]) -> None:
        """Update financial state from FinancialBrain output."""
        if not analysis or analysis.get("status") in ("error", "unavailable"):
            return
        pnl = analysis.get("pnl", {})
        self.financial = {
            "gross_revenue": pnl.get("gross_revenue", 0),
            "net_profit": pnl.get("net_profit", 0),
            "net_margin": pnl.get("net_margin", 0),
            "gross_margin": pnl.get("gross_margin", 0),
            "total_costs": pnl.get("total_costs", 0),
            "order_count": pnl.get("order_count", 0),
            "aov": pnl.get("aov", 0),
            "status": pnl.get("status", "unknown"),
            "margin_alerts": len(analysis.get("margin_alerts", [])),
            "critical_alerts": sum(
                1 for a in analysis.get("margin_alerts", [])
                if a.get("severity") == "critical"
            ),
            "health_score": analysis.get("health", {}).get("score", 0),
            "health_grade": analysis.get("health", {}).get("grade", "?"),
            "cash_flow": analysis.get("cash_flow", {}),
        }

    def update_products(self, intel_result: dict[str, Any]) -> None:
        """Update product state from IntelligenceLoop output."""
        if not intel_result or intel_result.get("status") == "error":
            return
        decision = intel_result.get("decision", {})
        self.products = {
            "decision": decision.get("action", "none"),
            "confidence": decision.get("confidence", "unknown"),
            "confidence_score": decision.get("confidence_score", 0),
            "options_evaluated": decision.get("options_evaluated", 0),
            "data_quality": intel_result.get("data_quality", 0),
            "stages_completed": intel_result.get("stages_completed", 0),
        }

    def update_inventory(self, products: list[dict[str, Any]]) -> None:
        """Update inventory state from product data."""
        if not products:
            return
        total = len(products)
        low_stock = sum(1 for p in products if (p.get("inventory_quantity") or 0) < 10)
        out_of_stock = sum(1 for p in products if (p.get("inventory_quantity") or 0) <= 0)
        # Use `or 0` instead of `.get("inventory_quantity", 0)` so a
        # product with `inventory_quantity = None` (a common Shopify
        # quirk for items without tracking) doesn't crash the sum
        # with `int + None`. This was inconsistent with the two
        # lines above which already used the `or 0` pattern.
        total_inventory = sum((p.get("inventory_quantity") or 0) for p in products)
        self.inventory = {
            "total_products": total,
            "low_stock_count": low_stock,
            "out_of_stock_count": out_of_stock,
            "total_units": total_inventory,
            "low_stock_pct": round(low_stock / max(total, 1) * 100, 1),
            "stockout_risk": out_of_stock > 0 or low_stock > total * 0.3,
        }

    def update_customers(self, customers: list[dict[str, Any]], orders: list[dict[str, Any]]) -> None:
        """Update customer state from customer and order data."""
        if not customers:
            return
        total = len(customers)
        order_count = len(orders) if orders else 0
        # Simple churn estimate: customers with no recent orders
        customer_ids_with_orders: set = set()
        for o in (orders or []):
            if not isinstance(o, dict):
                continue
            cid = o.get("customer_id")
            if cid is None:
                # `o.get("customer", {})` returns the literal default
                # only when the key is MISSING; if the key exists
                # with value None, .get returns None and the next
                # `.get("id")` would crash with AttributeError. The
                # `or {}` chain coerces None into an empty dict.
                customer_block = o.get("customer") or {}
                if isinstance(customer_block, dict):
                    cid = customer_block.get("id")
            if cid is not None:
                customer_ids_with_orders.add(cid)
        active = len(customer_ids_with_orders)
        self.customers = {
            "total": total,
            "active_recent": active,
            "inactive": total - active,
            "churn_risk_pct": round((total - active) / max(total, 1) * 100, 1),
            "recent_orders": order_count,
        }

    def update_marketing(self, campaign_result: dict[str, Any]) -> None:
        """Update marketing state from campaign analysis.

        ``optimization`` may arrive as either a list of action dicts
        (when campaigns were supplied) or a dict with an ``actions``
        key (when there were none). Handle both — the pre-audit
        code crashed with AttributeError on the list form.
        """
        if not campaign_result or campaign_result.get("status") in ("unavailable", "no_data"):
            return
        opt = campaign_result.get("optimization")
        if isinstance(opt, list):
            optimization_actions = len(opt)
        elif isinstance(opt, dict):
            optimization_actions = len(opt.get("actions", []))
        else:
            optimization_actions = 0
        self.marketing = {
            "optimization_actions": optimization_actions,
            "has_targeting": "targeting" in campaign_result,
            "health": campaign_result.get("health", {}),
        }

    def update_health(self, health_result: dict[str, Any]) -> None:
        """Update system health."""
        if not health_result or health_result.get("status") in ("error", "unavailable"):
            return
        self.health = {
            "overall_grade": health_result.get("overall_grade", "?"),
            "overall_score": health_result.get("overall_score", 0),
            "sections": list(health_result.get("sections", {}).keys()),
        }

    def update_events(self, event_result: dict[str, Any]) -> None:
        """Record events from this cycle."""
        if not event_result:
            return
        self.events = event_result.get("details", [])[-20:]  # Keep last 20

    def set_priorities(self, priorities: list[dict[str, Any]]) -> None:
        """Set computed priorities for this cycle."""
        self.priorities = priorities

    def finalize(self, cycle_id: str) -> None:
        """Mark snapshot as complete for this cycle."""
        self.cycle_id = cycle_id
        self.last_updated = time.time()
        self._history.append({
            "cycle_id": cycle_id,
            "timestamp": self.last_updated,
            "health_grade": self.health.get("overall_grade", "?"),
            "net_profit": self.financial.get("net_profit", 0),
            "decision": self.products.get("decision", "none"),
        })
        # Keep last 100 history entries
        if len(self._history) > 100:
            self._history = self._history[-100:]

    def get_situation(self) -> dict[str, Any]:
        """Get full snapshot as a dictionary."""
        return {
            "cycle_id": self.cycle_id,
            "last_updated": self.last_updated,
            "financial": self.financial,
            "inventory": self.inventory,
            "marketing": self.marketing,
            "customers": self.customers,
            "products": self.products,
            "events": self.events,
            "health": self.health,
            "priorities": self.priorities,
        }

    def get_alerts(self) -> list[dict[str, Any]]:
        """Get active alerts from the snapshot."""
        alerts = []
        if self.financial.get("critical_alerts", 0) > 0:
            alerts.append({
                "type": "financial",
                "severity": "critical",
                "message": f"{self.financial['critical_alerts']} products with negative margin",
            })
        if self.inventory.get("stockout_risk"):
            alerts.append({
                "type": "inventory",
                "severity": "high",
                "message": f"{self.inventory.get('out_of_stock_count', 0)} products out of stock, {self.inventory.get('low_stock_count', 0)} low stock",
            })
        if self.customers.get("churn_risk_pct", 0) > 50:
            alerts.append({
                "type": "customer",
                "severity": "high",
                "message": f"{self.customers['churn_risk_pct']}% customers inactive — churn risk",
            })
        if self.health.get("overall_grade") in ("D", "F"):
            alerts.append({
                "type": "system",
                "severity": "medium",
                "message": f"System health grade: {self.health['overall_grade']}",
            })
        return alerts

    def persist(self) -> None:
        """Save snapshot to disk."""
        self._last_persist_error: str = ""
        try:
            os.makedirs(os.path.dirname(_SNAPSHOT_PATH), exist_ok=True)
            data = {
                **self.get_situation(),
                "_history": self._history[-20:],
            }
            tmp = _SNAPSHOT_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp, _SNAPSHOT_PATH)
        except Exception as exc:  # noqa: BLE001
            # Record the error so the operator (and tests) can
            # detect a silent persist failure instead of trusting
            # the empty snapshot the next load() returns.
            self._last_persist_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Failed to persist snapshot: %s", exc)

    def get_persist_error(self) -> str:
        """Return the last persist error message, or '' if the
        most recent persist call succeeded. Useful for dashboards
        and tests that need to detect silent disk failures."""
        return getattr(self, "_last_persist_error", "")

    @classmethod
    def load(cls) -> StoreSnapshot:
        """Load snapshot from disk.

        On JSON parse errors / schema drift, the corrupted file is
        moved aside as ``<path>.corrupted.<ts>`` BEFORE we fall
        back to an empty snapshot. The previous version silently
        returned an empty snapshot AND left the corrupted file in
        place — the next persist() call would then overwrite it
        with empty data and the original good history would be
        lost forever.
        """
        snap = cls()
        if not os.path.exists(_SNAPSHOT_PATH):
            return snap
        try:
            with open(_SNAPSHOT_PATH) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(
                    f"snapshot file is {type(data).__name__}, expected dict"
                )
            snap.financial = data.get("financial") or {}
            snap.inventory = data.get("inventory") or {}
            snap.marketing = data.get("marketing") or {}
            snap.customers = data.get("customers") or {}
            snap.products = data.get("products") or {}
            snap.events = data.get("events") or []
            snap.health = data.get("health") or {}
            snap.priorities = data.get("priorities") or []
            snap.last_updated = data.get("last_updated", 0)
            snap.cycle_id = data.get("cycle_id", "")
            snap._history = data.get("_history") or []
            logger.info("Snapshot loaded from disk (cycle: %s)", snap.cycle_id)
        except Exception as exc:  # noqa: BLE001
            backup = f"{_SNAPSHOT_PATH}.corrupted.{int(time.time())}"
            try:
                os.replace(_SNAPSHOT_PATH, backup)
                logger.warning(
                    "Snapshot load failed (%s); corrupted file moved to %s",
                    exc, backup,
                )
            except Exception as move_exc:  # noqa: BLE001
                logger.warning(
                    "Snapshot load failed (%s); could not back up "
                    "corrupted file (%s)", exc, move_exc,
                )
        return snap
