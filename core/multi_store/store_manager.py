"""MultiStoreManager — coordinate multiple Shopify stores.

Store бүрд тусдаа: config, credentials, state, memory.
Cross-store intelligence: "Store A-д ямар product сайн → Store B-д нэмэх"
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("multi_store.manager")


class StoreConfig:
    """Configuration for a single store."""

    def __init__(self, store_id: str, name: str, url: str = "", api_key: str = "") -> None:
        self.store_id = store_id
        self.name = name
        self.url = url
        self.api_key = api_key
        self.created_at = time.time()
        self.active = True
        self.metadata: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "name": self.name,
            "url": self.url,
            "active": self.active,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class MultiStoreManager:
    """Manages multiple Shopify stores with cross-store intelligence.

    Usage:
        manager = MultiStoreManager()
        manager.register_store("store_1", "My Main Store", "https://main.myshopify.com", "key1")
        manager.register_store("store_2", "EU Store", "https://eu.myshopify.com", "key2")

        # Run cycle for all stores
        results = manager.run_all_cycles()

        # Cross-store intelligence
        insights = manager.cross_store_insights()
    """

    def __init__(self) -> None:
        self._stores: dict[str, StoreConfig] = {}
        self._performance: dict[str, list[dict[str, Any]]] = {}  # store_id → cycle results
        self._shared_knowledge: dict[str, Any] = {}

    def register_store(
        self,
        store_id: str,
        name: str,
        url: str = "",
        api_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a new store."""
        if store_id in self._stores:
            return {"status": "already_exists", "store_id": store_id}

        config = StoreConfig(store_id, name, url, api_key)
        if metadata:
            config.metadata = metadata
        self._stores[store_id] = config
        self._performance[store_id] = []

        logger.info("Store registered: %s (%s)", store_id, name)
        return {"status": "registered", "store": config.to_dict()}

    def deregister_store(self, store_id: str) -> bool:
        """Deregister a store."""
        if store_id in self._stores:
            self._stores[store_id].active = False
            return True
        return False

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        """Get store configuration."""
        config = self._stores.get(store_id)
        return config.to_dict() if config else None

    def list_stores(self) -> list[dict[str, Any]]:
        """List all registered stores."""
        return [
            {**config.to_dict(), "recent_performance": self._get_recent_perf(sid)}
            for sid, config in self._stores.items()
        ]

    def record_cycle_result(self, store_id: str, result: dict[str, Any]) -> None:
        """Record a cycle result for a store."""
        if store_id not in self._performance:
            self._performance[store_id] = []

        summary = result.get("summary", {})
        self._performance[store_id].append({
            "timestamp": time.time(),
            "decision": summary.get("decision", "none"),
            "confidence": summary.get("confidence_score", 0),
            "health_grade": summary.get("health_grade", "?"),
            "net_profit": summary.get("net_profit", 0),
        })

        # Keep last 100 entries
        if len(self._performance[store_id]) > 100:
            self._performance[store_id] = self._performance[store_id][-100:]

    def cross_store_insights(self) -> dict[str, Any]:
        """Generate insights by comparing stores."""
        if len(self._stores) < 2:
            return {"status": "need_2_stores", "note": "Register 2+ stores for cross-store insights"}

        store_summaries = {}
        for store_id, perf in self._performance.items():
            if not perf:
                continue
            recent = perf[-10:]
            avg_confidence = sum(p.get("confidence", 0) for p in recent) / max(len(recent), 1)
            avg_profit = sum(p.get("net_profit", 0) for p in recent) / max(len(recent), 1)

            store_summaries[store_id] = {
                "name": self._stores[store_id].name if store_id in self._stores else store_id,
                "cycles": len(recent),
                "avg_confidence": round(avg_confidence, 1),
                "avg_profit": round(avg_profit, 2),
                "latest_grade": recent[-1].get("health_grade", "?") if recent else "?",
            }

        insights = []

        # Find best and worst performing stores
        if store_summaries:
            best = max(store_summaries.items(), key=lambda x: x[1]["avg_profit"])
            worst = min(store_summaries.items(), key=lambda x: x[1]["avg_profit"])
            if best[0] != worst[0]:
                insights.append({
                    "type": "performance_gap",
                    "message": f"{best[1]['name']} outperforms {worst[1]['name']} by ${best[1]['avg_profit'] - worst[1]['avg_profit']:,.2f}/cycle",
                    "action": f"Apply {best[1]['name']}'s strategy to {worst[1]['name']}",
                })

        return {
            "stores": store_summaries,
            "insights": insights,
            "shared_knowledge": self._shared_knowledge,
        }

    def share_knowledge(self, key: str, value: Any, source_store: str = "") -> None:
        """Share knowledge across stores."""
        self._shared_knowledge[key] = {
            "value": value,
            "source": source_store,
            "timestamp": time.time(),
        }

    def get_shared_knowledge(self, key: str) -> Any:
        """Get shared knowledge."""
        entry = self._shared_knowledge.get(key)
        return entry.get("value") if entry else None

    def get_dashboard(self) -> dict[str, Any]:
        """Get multi-store dashboard."""
        stores = self.list_stores()
        total_profit = sum(
            self._performance.get(s["store_id"], [{}])[-1].get("net_profit", 0)
            for s in stores if self._performance.get(s["store_id"])
        )

        return {
            "total_stores": len(stores),
            "active_stores": sum(1 for s in stores if s.get("active")),
            "total_recent_profit": round(total_profit, 2),
            "stores": stores,
            "cross_store_insights": self.cross_store_insights() if len(stores) >= 2 else None,
        }

    def _get_recent_perf(self, store_id: str) -> dict[str, Any] | None:
        """Get most recent performance for a store."""
        perf = self._performance.get(store_id, [])
        return perf[-1] if perf else None
