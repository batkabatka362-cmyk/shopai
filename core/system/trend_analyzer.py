"""Trend Analyzer — analyzes trends across multiple cycles."""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("trend_analyzer")


class TrendAnalyzer:
    """Tracks and analyzes trends across autonomous cycles."""

    def __init__(self) -> None:
        self._cycle_history: list[dict[str, Any]] = []

    def record_cycle(self, cycle_result: dict) -> None:
        """Record key metrics from a cycle."""
        phases = cycle_result.get("phases", {})
        self._cycle_history.append({
            "cycle": cycle_result.get("cycle_number", 0),
            "duration": cycle_result.get("duration_s", 0),
            "layers": phases.get("layers", {}).get("layers_run", 0),
            "insights": phases.get("layers", {}).get("total_insights", 0),
            "decisions": phases.get("decisions", {}).get("proposed", 0),
            "exec_score": phases.get("smart_execution", {}).get("avg_score", 0),
            "outcomes": phases.get("learning", {}).get("outcomes_recorded", 0),
            "weight_updates": phases.get("learning", {}).get("weight_updates", 0),
            "patterns": phases.get("learning", {}).get("patterns_found", 0),
            "health": phases.get("brain", {}).get("health_score", 0),
            "timestamp": time.time(),
        })
        if len(self._cycle_history) > 500:
            self._cycle_history = self._cycle_history[-500:]

    def analyze(self) -> dict[str, Any]:
        """Analyze trends across recorded cycles."""
        if len(self._cycle_history) < 2:
            return {"status": "insufficient_data", "cycles": len(self._cycle_history)}

        recent = self._cycle_history[-10:]
        first = recent[:len(recent)//2]
        second = recent[len(recent)//2:]

        trends = {}
        for key in ["insights", "outcomes", "weight_updates", "patterns", "exec_score", "duration"]:
            avg_first = sum(c.get(key, 0) for c in first) / max(len(first), 1)
            avg_second = sum(c.get(key, 0) for c in second) / max(len(second), 1)
            if avg_second > avg_first * 1.1:
                trends[key] = "improving"
            elif avg_second < avg_first * 0.9:
                trends[key] = "declining"
            else:
                trends[key] = "stable"

        return {
            "cycles_analyzed": len(self._cycle_history),
            "trends": trends,
            "latest": self._cycle_history[-1] if self._cycle_history else {},
            "health_trend": trends.get("insights", "unknown"),
        }

    def get_stats(self) -> dict[str, Any]:
        return {"cycles_recorded": len(self._cycle_history)}


_instance = None
def get_trend_analyzer():
    global _instance
    if _instance is None:
        _instance = TrendAnalyzer()
    return _instance
