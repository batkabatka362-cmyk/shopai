"""Profit Optimization Layer — tracks revenue, costs, profit.

System-ийн жинхэнэ зорилго: АШИГ нэмэгдүүлэх.

Энэ layer:
  - Бүх action-ийн ашигт байдлыг хянана
  - Ашиггүй action-г зогсооно
  - Ашигтай action-г scale хийнэ
  - Budget limit барина
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


try:
    from core.memory.storage_config import get_path
    _PROFIT_DIR = get_path("brain")
except Exception:
    _PROFIT_DIR = "/tmp/shopai_brain"


class ProfitTracker:
    """Track profit across all system actions."""

    def __init__(self, profit_dir: str | None = None) -> None:
        self._dir = profit_dir or _PROFIT_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.Lock()
        self._actions: list[dict[str, Any]] = []
        self._load()

    def record_action(
        self,
        action_type: str,
        engine: str,
        revenue: float = 0,
        cost: float = 0,
        description: str = "",
    ) -> dict[str, Any]:
        """Record a profit-impacting action."""
        with self._lock:
            profit = revenue - cost
            entry = {
                "id": f"profit_{int(time.time())}_{len(self._actions)}",
                "action_type": action_type,
                "engine": engine,
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "profit": round(profit, 2),
                "margin_pct": round(profit / max(revenue, 0.01) * 100, 1),
                "description": description,
                "timestamp": time.time(),
            }
            self._actions.append(entry)
            self._persist()
            return entry

    def get_summary(self, days: int = 30) -> dict[str, Any]:
        """Get profit summary for last N days."""
        with self._lock:
            cutoff = time.time() - (days * 86400)
            recent = [a for a in self._actions if a["timestamp"] > cutoff]

            total_revenue = sum(a["revenue"] for a in recent)
            total_cost = sum(a["cost"] for a in recent)
            total_profit = sum(a["profit"] for a in recent)

            # By action type
            by_type: dict[str, dict] = {}
            for a in recent:
                at = a["action_type"]
                if at not in by_type:
                    by_type[at] = {"revenue": 0, "cost": 0, "profit": 0, "count": 0}
                by_type[at]["revenue"] += a["revenue"]
                by_type[at]["cost"] += a["cost"]
                by_type[at]["profit"] += a["profit"]
                by_type[at]["count"] += 1

            # Profitable vs unprofitable
            profitable = [a for a in recent if a["profit"] > 0]
            unprofitable = [a for a in recent if a["profit"] <= 0]

            return {
                "period_days": days,
                "total_actions": len(recent),
                "total_revenue": round(total_revenue, 2),
                "total_cost": round(total_cost, 2),
                "total_profit": round(total_profit, 2),
                "profit_margin_pct": round(total_profit / max(total_revenue, 0.01) * 100, 1),
                "profitable_actions": len(profitable),
                "unprofitable_actions": len(unprofitable),
                "by_action_type": by_type,
                "status": "profitable" if total_profit > 0 else "break_even" if total_profit == 0 else "losing",
            }

    def check_action_profitability(self, action_type: str) -> dict[str, Any]:
        """Should we continue this action type? Based on historical profitability."""
        with self._lock:
            actions = [a for a in self._actions if a["action_type"] == action_type]
            if not actions:
                return {"verdict": "unknown", "reason": "No historical data for this action type"}

            total_profit = sum(a["profit"] for a in actions)
            avg_profit = total_profit / len(actions)
            profit_rate = sum(1 for a in actions if a["profit"] > 0) / len(actions)

            if profit_rate >= 0.7 and avg_profit > 0:
                verdict = "scale"
                reason = f"Profitable {profit_rate*100:.0f}% of the time (avg ${avg_profit:.2f}/action). Scale up."
            elif profit_rate >= 0.4:
                verdict = "continue"
                reason = f"Marginal ({profit_rate*100:.0f}% profitable). Continue but optimize."
            else:
                verdict = "stop"
                reason = f"Unprofitable ({profit_rate*100:.0f}% profitable, avg ${avg_profit:.2f}). Stop or redesign."

            return {
                "verdict": verdict,
                "reason": reason,
                "total_actions": len(actions),
                "profit_rate": round(profit_rate * 100, 1),
                "avg_profit": round(avg_profit, 2),
                "total_profit": round(total_profit, 2),
            }

    def get_top_performers(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get most profitable action types."""
        with self._lock:
            by_type: dict[str, float] = {}
            for a in self._actions:
                by_type[a["action_type"]] = by_type.get(a["action_type"], 0) + a["profit"]

            ranked = sorted(by_type.items(), key=lambda x: x[1], reverse=True)
            return [{"action_type": k, "total_profit": round(v, 2)} for k, v in ranked[:limit]]

    def get_loss_leaders(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get action types causing losses."""
        with self._lock:
            by_type: dict[str, float] = {}
            for a in self._actions:
                by_type[a["action_type"]] = by_type.get(a["action_type"], 0) + a["profit"]

            losses = [(k, v) for k, v in by_type.items() if v < 0]
            losses.sort(key=lambda x: x[1])
            return [{"action_type": k, "total_loss": round(v, 2)} for k, v in losses[:limit]]

    def _persist(self) -> None:
        if len(self._actions) > 10000:
            self._actions = self._actions[-10000:]
        try:
            path = os.path.join(self._dir, "profit_tracking.json")
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._actions, f, default=str)
            os.replace(tmp, path)
        except Exception:
            pass

    def _load(self) -> None:
        try:
            path = os.path.join(self._dir, "profit_tracking.json")
            if os.path.exists(path):
                with open(path) as f:
                    self._actions = json.load(f)
        except Exception:
            self._actions = []
