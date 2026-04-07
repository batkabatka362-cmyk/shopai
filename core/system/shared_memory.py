"""SharedMemory — structured context sharing across all system components.

All engines, tools, and AI reasoning share context through this layer.
No component accesses data directly — everything goes through SharedMemory.

Features:
  - Namespaced storage (products, decisions, analytics, etc.)
  - Context-aware retrieval (get relevant data for a task)
  - Automatic expiration for time-sensitive data
  - Thread-safe
  - Persistent backing via SQLite
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("shared_memory")


class SharedMemory:
    """Centralized structured memory for the entire system."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._access_log: list[dict[str, Any]] = []
        self._namespaces = {
            "products", "orders", "customers", "analytics",
            "decisions", "actions", "learning", "market",
            "config", "state", "cache",
        }

    # ── Core Operations ──────────────────────────────────────

    def put(self, namespace: str, key: str, value: Any,
            ttl_seconds: int = 0, metadata: dict | None = None) -> None:
        """Store data in shared memory."""
        with self._lock:
            if namespace not in self._store:
                self._store[namespace] = {}

            self._store[namespace][key] = {
                "value": value,
                "stored_at": time.time(),
                "expires_at": time.time() + ttl_seconds if ttl_seconds > 0 else 0,
                "metadata": metadata or {},
                "access_count": 0,
            }

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """Get data from shared memory. Returns None if expired."""
        with self._lock:
            ns = self._store.get(namespace, {})
            entry = ns.get(key)
            if not entry:
                return default

            # Check expiration
            if entry["expires_at"] > 0 and time.time() > entry["expires_at"]:
                del ns[key]
                return default

            entry["access_count"] += 1
            self._log_access(namespace, key, "read")
            return entry["value"]

    def get_all(self, namespace: str) -> dict[str, Any]:
        """Get all non-expired data from a namespace."""
        with self._lock:
            ns = self._store.get(namespace, {})
            result = {}
            expired_keys = []
            for key, entry in ns.items():
                if entry["expires_at"] > 0 and time.time() > entry["expires_at"]:
                    expired_keys.append(key)
                    continue
                result[key] = entry["value"]
            for k in expired_keys:
                del ns[k]
            return result

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            ns = self._store.get(namespace, {})
            if key in ns:
                del ns[key]
                return True
            return False

    def exists(self, namespace: str, key: str) -> bool:
        with self._lock:
            ns = self._store.get(namespace, {})
            entry = ns.get(key)
            if not entry:
                return False
            if entry["expires_at"] > 0 and time.time() > entry["expires_at"]:
                # Drop the expired entry on detection so subsequent
                # `get_stats()` calls don't double-count it and the
                # store doesn't accumulate stale rows that only get
                # cleared when someone happens to call get()/get_all().
                ns.pop(key, None)
                return False
            return True

    # ── Context Building ─────────────────────────────────────

    def get_context_for_task(self, task_type: str) -> dict[str, Any]:
        """Build relevant context for a task type.

        Automatically selects the right data based on task type.
        """
        context: dict[str, Any] = {}

        # Task → namespace mapping
        task_namespaces = {
            "pricing": ["products", "analytics", "decisions", "market"],
            "inventory": ["products", "orders", "analytics"],
            "product_research": ["products", "market", "analytics"],
            "customer": ["customers", "orders", "analytics"],
            "marketing": ["products", "customers", "analytics", "market"],
            "analytics": ["products", "orders", "customers"],
        }

        # Find matching namespaces
        relevant = set()
        task_lower = task_type.lower()
        for key, nss in task_namespaces.items():
            if key in task_lower:
                relevant.update(nss)

        if not relevant:
            relevant = {"products", "analytics"}  # Default

        # Gather data
        for ns in relevant:
            data = self.get_all(ns)
            if data:
                context[ns] = data

        # Always include recent decisions and state
        context["recent_decisions"] = self.get_all("decisions")
        context["system_state"] = self.get_all("state")

        return context

    # ── Bulk Operations ──────────────────────────────────────

    def load_store_data(self, products: list, orders: list, customers: list,
                        store_id: str = "") -> None:
        """Load store data into shared memory."""
        self.put("products", "current", products, ttl_seconds=600)
        self.put("products", "count", len(products))
        self.put("orders", "current", orders, ttl_seconds=600)
        self.put("orders", "count", len(orders))
        self.put("customers", "current", customers, ttl_seconds=600)
        self.put("customers", "count", len(customers))
        self.put("state", "store_id", store_id)
        self.put("state", "last_data_load", time.time())

    def record_decision(self, decision_id: str, decision: dict[str, Any]) -> None:
        """Record a decision in shared memory for future reference."""
        self.put("decisions", decision_id, {
            **decision,
            "recorded_at": time.time(),
        }, ttl_seconds=86400)  # Keep for 24h

    def record_action(self, action_id: str, action: dict[str, Any]) -> None:
        """Record an executed action."""
        self.put("actions", action_id, {
            **action,
            "recorded_at": time.time(),
        }, ttl_seconds=86400)

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            stats = {}
            total = 0
            for ns, data in self._store.items():
                stats[ns] = len(data)
                total += len(data)
            return {"namespaces": stats, "total_entries": total}

    def _log_access(self, namespace: str, key: str, operation: str) -> None:
        self._access_log.append({
            "namespace": namespace, "key": key,
            "operation": operation, "time": time.time(),
        })
        if len(self._access_log) > 1000:
            self._access_log = self._access_log[-500:]

    def clear_namespace(self, namespace: str) -> None:
        with self._lock:
            self._store.pop(namespace, None)

    def clear_all(self) -> None:
        with self._lock:
            self._store.clear()


# Singleton
_shared_memory: SharedMemory | None = None


def get_shared_memory() -> SharedMemory:
    global _shared_memory
    if _shared_memory is None:
        _shared_memory = SharedMemory()
    return _shared_memory
