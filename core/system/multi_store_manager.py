"""Multi-Store Manager — manage multiple Shopify stores from one AI.

Capabilities:
  - Register/remove stores
  - Run cycles on all stores
  - Share intelligence between stores
  - Compare store performance
  - Global strategy across stores
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("multi_store.manager")


class MultiStoreManager:
    """Manages multiple stores with shared intelligence."""

    def __init__(self) -> None:
        self._stores: dict[str, dict] = {}
        self._cycle_results: dict[str, list] = {}

    def register(self, store_id: str, shop_url: str = "",
                 niche: str = "", store_type: str = "dropshipping") -> dict:
        self._stores[store_id] = {
            "shop_url": shop_url,
            "niche": niche,
            "type": store_type,
            "registered_at": time.time(),
            "cycles_run": 0,
            "last_cycle": 0,
        }
        self._cycle_results[store_id] = []
        return {"registered": store_id, "total_stores": len(self._stores)}

    def run_all(self) -> dict[str, Any]:
        """Run AI cycle on all registered stores."""
        results = {}
        for store_id in self._stores:
            try:
                result = self._run_store(store_id)
                results[store_id] = {
                    "status": "success",
                    "duration": result.get("duration_s", 0),
                    "phases": len(result.get("phases", {})),
                    "insights": result.get("phases", {}).get("layers", {}).get("total_insights", 0),
                }
                self._stores[store_id]["cycles_run"] += 1
                self._stores[store_id]["last_cycle"] = time.time()
                self._cycle_results[store_id].append(result)
                if len(self._cycle_results[store_id]) > 50:
                    self._cycle_results[store_id] = self._cycle_results[store_id][-50:]
            except Exception as exc:
                results[store_id] = {"status": "error", "error": str(exc)[:80]}

        # Share intelligence between stores
        shared = self._share_intelligence()

        return {
            "stores_run": len(results),
            "results": results,
            "intelligence_shared": shared,
        }

    def _run_store(self, store_id: str) -> dict:
        from core.autonomous.controller import AutonomousController
        ac = AutonomousController(auto_approve=False)
        ac.initialize()
        return ac.run_cycle(store_id)

    def _share_intelligence(self) -> dict:
        """Share rules and strategies between stores."""
        try:
            from core.brain.multi_store_brain import get_multi_store
            ms = get_multi_store()

            # Register all stores
            for sid in self._stores:
                ms.register_store(sid, self._stores[sid])

            # Share from each store to all others
            total_shared = 0
            for sid in self._stores:
                shared = ms.share_learning(sid)
                for other_sid in self._stores:
                    if other_sid != sid:
                        result = ms.apply_learning(other_sid, shared)
                        total_shared += result.get("applied_rules", 0)

            return {"rules_shared": total_shared, "stores": len(self._stores)}
        except Exception:
            return {"rules_shared": 0}

    def compare_stores(self) -> dict[str, Any]:
        """Compare performance across stores."""
        comparison = {}
        for sid, results in self._cycle_results.items():
            if not results:
                continue
            last = results[-1]
            phases = last.get("phases", {})
            comparison[sid] = {
                "cycles": self._stores[sid].get("cycles_run", 0),
                "last_duration": last.get("duration_s", 0),
                "health": phases.get("brain", {}).get("health_score", 0),
                "insights": phases.get("layers", {}).get("total_insights", 0),
                "niche": self._stores[sid].get("niche", ""),
            }
        return comparison

    def get_stats(self) -> dict:
        return {
            "stores": len(self._stores),
            "total_cycles": sum(s.get("cycles_run", 0) for s in self._stores.values()),
            "store_list": list(self._stores.keys()),
        }


_instance = None
def get_multi_store_manager():
    global _instance
    if _instance is None:
        _instance = MultiStoreManager()
    return _instance
