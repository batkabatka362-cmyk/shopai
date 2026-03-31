"""RevenueTracker — tracks real revenue impact from system decisions.

Connects: engine decision → action taken → revenue result.
Answers: "Did ShopAI actually make money?"
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.revenue")

_REVENUE_DIR = "/tmp/shopai_revenue"


class RevenueTracker:
    """Tracks revenue impact from ShopAI decisions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(_REVENUE_DIR, exist_ok=True)

    def record_action(self, action_type: str, product: str, details: dict[str, Any]) -> str:
        """Record an action taken by ShopAI."""
        action_id = f"act_{int(time.time() * 1000)}"
        entry = {
            "action_id": action_id,
            "action_type": action_type,
            "product": product,
            "details": details,
            "timestamp": time.time(),
            "revenue": None,
            "cost": None,
        }
        self._append("actions", entry)
        return action_id

    def record_revenue(self, action_id: str, revenue: float, cost: float = 0,
                        orders: int = 0, period_days: int = 7) -> bool:
        """Record revenue from an action — thread-safe read-modify-write."""
        with self._lock:
            entries = self._load_unlocked("actions")
            for e in reversed(entries):
                if e.get("action_id") == action_id:
                    e["revenue"] = revenue
                    e["cost"] = cost
                    e["orders"] = orders
                    e["period_days"] = period_days
                    e["profit"] = round(revenue - cost, 2)
                    e["roas"] = round(revenue / max(cost, 0.01), 2) if cost > 0 else 0
                    e["revenue_timestamp"] = time.time()
                    self._save_unlocked("actions", entries)
                    return True
        return False

    def get_roi_summary(self) -> dict[str, Any]:
        """Get total ROI from all tracked actions."""
        entries = self._load("actions")
        with_revenue = [e for e in entries if e.get("revenue") is not None]

        if not with_revenue:
            return {"status": "no_data", "actions_tracked": len(entries)}

        total_revenue = sum(safe_float(e.get("revenue")) for e in with_revenue)
        total_cost = sum(safe_float(e.get("cost")) for e in with_revenue)
        total_orders = sum(int(e.get("orders", 0)) for e in with_revenue)
        total_profit = total_revenue - total_cost

        by_type: dict[str, dict] = {}
        for e in with_revenue:
            t = e.get("action_type", "unknown")
            if t not in by_type:
                by_type[t] = {"revenue": 0.0, "cost": 0.0, "count": 0}
            by_type[t]["revenue"] += safe_float(e.get("revenue"))
            by_type[t]["cost"] += safe_float(e.get("cost"))
            by_type[t]["count"] += 1

        return {
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "total_orders": total_orders,
            "overall_roas": round(total_revenue / max(total_cost, 0.01), 2),
            "actions_tracked": len(entries),
            "with_revenue": len(with_revenue),
            "by_action_type": {k: {**v, "revenue": round(v["revenue"], 2), "cost": round(v["cost"], 2),
                                     "roas": round(v["revenue"] / max(v["cost"], 0.01), 2)}
                                for k, v in by_type.items()},
            "top_product": self._top_product(with_revenue),
        }

    def get_product_performance(self) -> list[dict[str, Any]]:
        """Get revenue by product."""
        entries = self._load("actions")
        products: dict[str, dict] = {}
        for e in entries:
            if e.get("revenue") is None:
                continue
            p = e.get("product", "unknown")
            if p not in products:
                products[p] = {"product": p, "revenue": 0.0, "cost": 0.0, "actions": 0}
            products[p]["revenue"] += safe_float(e.get("revenue"))
            products[p]["cost"] += safe_float(e.get("cost"))
            products[p]["actions"] += 1

        result = sorted(products.values(), key=lambda x: -x["revenue"])
        for r in result:
            r["profit"] = round(r["revenue"] - r["cost"], 2)
            r["revenue"] = round(r["revenue"], 2)
            r["cost"] = round(r["cost"], 2)
        return result

    @staticmethod
    def _top_product(entries: list[dict]) -> dict[str, Any] | None:
        products: dict[str, float] = {}
        for e in entries:
            p = e.get("product", "unknown")
            products[p] = products.get(p, 0) + safe_float(e.get("revenue"))
        if not products:
            return None
        top = max(products.items(), key=lambda x: x[1])
        return {"product": top[0], "revenue": round(top[1], 2)}

    def _append(self, name: str, entry: dict) -> None:
        with self._lock:
            entries = self._load_unlocked(name)
            entries.append(entry)
            if len(entries) > 5000:
                entries = entries[-5000:]
            self._save_unlocked(name, entries)

    def _load(self, name: str) -> list[dict]:
        with self._lock:
            return self._load_unlocked(name)

    def _load_unlocked(self, name: str) -> list[dict]:
        """Load without acquiring lock — caller must hold lock."""
        path = os.path.join(_REVENUE_DIR, f"{name}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Corrupted revenue file %s: %s", path, exc)
        return []

    def _save(self, name: str, entries: list[dict]) -> None:
        with self._lock:
            self._save_unlocked(name, entries)

    def _save_unlocked(self, name: str, entries: list[dict]) -> None:
        """Save without acquiring lock — caller must hold lock. Atomic write."""
        path = os.path.join(_REVENUE_DIR, f"{name}.json")
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(entries, f)
            os.replace(tmp_path, path)
        except OSError as exc:
            logger.error("Failed to save revenue data %s: %s", name, exc)
