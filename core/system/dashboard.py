"""Store Analytics Dashboard — aggregated analytics for the store.

Provides snapshot data for dashboards and reporting.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("analytics.dashboard")


class StoreDashboard:
    """Aggregates all system data into dashboard-ready format."""

    def generate(self, cycle_result: dict | None = None) -> dict[str, Any]:
        """Generate full dashboard data."""
        dashboard = {
            "generated_at": time.time(),
            "store": self._store_summary(),
            "memory": self._memory_summary(),
            "intelligence": self._intelligence_summary(),
            "execution": self._execution_summary(),
            "health": self._health_summary(cycle_result),
        }
        return dashboard

    @staticmethod
    def _store_summary() -> dict[str, Any]:
        try:
            from data_pipeline.store.store_manager import StoreManager
            sm = StoreManager()
            products = sm.get_products("deguar") or []
            orders = sm.get_orders("deguar") or []
            customers = sm.get_customers("deguar") or []
            revenue = sum(float(o.get("total_price", o.get("total", 0))) for o in orders)
            return {
                "products": len(products),
                "orders": len(orders),
                "customers": len(customers),
                "revenue": round(revenue, 2),
            }
        except Exception:
            return {}

    @staticmethod
    def _memory_summary() -> dict[str, Any]:
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            s = mi.get_stats()
            return {
                "total_memories": s.get("total_memories", 0),
                "levels": s.get("by_level", {}),
                "avg_score": s.get("avg_score", 0),
                "categories": len(s.get("by_category", {})),
            }
        except Exception:
            return {}

    @staticmethod
    def _intelligence_summary() -> dict[str, Any]:
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            ds = da.get_stats()
            return {
                "data_records": ds.get("total_records", 0),
                "domains": len(ds.get("domains", {})),
                "result_rate": ds.get("result_rate", 0),
            }
        except Exception:
            return {}

    @staticmethod
    def _execution_summary() -> dict[str, Any]:
        try:
            from execution.smart_executor import get_smart_executor
            se = get_smart_executor()
            return se.get_stats()
        except Exception:
            return {}

    @staticmethod
    def _health_summary(cycle_result: dict | None) -> dict[str, Any]:
        if not cycle_result:
            return {}
        phases = cycle_result.get("phases", {})
        return {
            "brain_health": phases.get("brain", {}).get("health_score", 0),
            "data_quality": phases.get("data_quality", {}).get("score", 0),
            "rule_health": phases.get("rule_health", {}).get("health_score", 0),
            "layers": phases.get("layers", {}).get("layers_run", 0),
            "cycle_duration": cycle_result.get("duration_s", 0),
        }


_instance = None
def get_dashboard():
    global _instance
    if _instance is None:
        _instance = StoreDashboard()
    return _instance
