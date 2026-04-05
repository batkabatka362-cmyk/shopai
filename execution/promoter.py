"""Execution Promoter — promotes actions from simulate to dry_run to live.

ADDITIVE ONLY — does not change SmartExecutor logic.
Provides promotion recommendations that SmartExecutor can optionally use.

Promotion criteria:
  simulate → dry_run: 3+ successful simulations of same action type
  dry_run → live: 5+ successful dry_runs + high confidence + rule support
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("execution.promoter")


class ExecutionPromoter:
    """Recommends mode promotions for action types."""

    def __init__(self) -> None:
        self._history: dict[str, list[dict]] = {}  # action_type → results
        self._promotions: list[dict[str, Any]] = []

    def record(self, action_type: str, mode: str, score: float) -> None:
        """Record an execution result for promotion tracking."""
        self._history.setdefault(action_type, []).append({
            "mode": mode,
            "score": score,
            "timestamp": time.time(),
        })

    def recommend_mode(self, action_type: str,
                       default_mode: str = "simulate") -> dict[str, Any]:
        """Recommend execution mode based on history."""
        history = self._history.get(action_type, [])
        if not history:
            return {"mode": default_mode, "reason": "no_history"}

        # Count successes by mode
        sim_success = sum(1 for h in history
                          if h["mode"] == "simulate" and h["score"] >= 3.5)
        dry_success = sum(1 for h in history
                          if h["mode"] == "dry_run" and h["score"] >= 3.5)
        sim_total = sum(1 for h in history if h["mode"] == "simulate")
        dry_total = sum(1 for h in history if h["mode"] == "dry_run")

        # Promote simulate → dry_run
        if default_mode == "simulate" and sim_success >= 3:
            success_rate = sim_success / max(sim_total, 1)
            if success_rate >= 0.7:
                self._promotions.append({
                    "action_type": action_type,
                    "from": "simulate",
                    "to": "dry_run",
                    "evidence": sim_success,
                    "timestamp": time.time(),
                })
                logger.info("Promote %s: simulate → dry_run (%d/%d success)",
                           action_type, sim_success, sim_total)
                return {
                    "mode": "dry_run",
                    "reason": "promoted: {}/{} simulations succeeded".format(sim_success, sim_total),
                    "confidence": round(success_rate, 2),
                }

        # Promote dry_run → live (very cautious)
        if dry_success >= 5:
            success_rate = dry_success / max(dry_total, 1)
            if success_rate >= 0.8:
                # Check if rules support this
                try:
                    from core.memory.intelligence import get_memory_intelligence
                    mi = get_memory_intelligence()
                    rules = mi.get_rules(action_type)
                    prefer_rules = [r for r in rules if r.get("action") == "prefer"]
                    if prefer_rules:
                        self._promotions.append({
                            "action_type": action_type,
                            "from": "dry_run",
                            "to": "live",
                            "evidence": dry_success,
                            "timestamp": time.time(),
                        })
                        logger.info("Promote %s: dry_run → live (%d/%d success, %d rules)",
                                   action_type, dry_success, dry_total, len(prefer_rules))
                        return {
                            "mode": "live",
                            "reason": "promoted: {}/{} dry_runs + {} supporting rules".format(
                                dry_success, dry_total, len(prefer_rules)),
                            "confidence": round(success_rate, 2),
                        }
                except Exception:
                    pass

        return {"mode": default_mode, "reason": "not_yet_promotable"}

    def get_promotions(self) -> list[dict[str, Any]]:
        return list(self._promotions)

    def get_stats(self) -> dict[str, Any]:
        return {
            "action_types_tracked": len(self._history),
            "total_records": sum(len(v) for v in self._history.values()),
            "promotions": len(self._promotions),
        }


_instance: ExecutionPromoter | None = None

def get_execution_promoter() -> ExecutionPromoter:
    global _instance
    if _instance is None:
        _instance = ExecutionPromoter()
    return _instance
