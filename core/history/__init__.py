"""ResultHistory — persists engine results and tracks trends over time.

Stores every engine run, compares with previous, detects improvements/regressions.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("history")

_HISTORY_DIR = "/tmp/shopai_history"


class ResultHistory:
    """Persistent engine result history with trend detection."""

    _instance = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> ResultHistory:
        with cls._lock_cls:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(_HISTORY_DIR, exist_ok=True)

    def record(self, engine_name: str, result: dict[str, Any]) -> dict[str, Any]:
        """Record an engine result. Returns comparison with previous."""
        entry = {
            "engine": engine_name,
            "timestamp": time.time(),
            "status": result.get("status", "unknown"),
            "score": self._extract_score(result),
            "field_count": len([k for k in result if not k.startswith("_")]),
            "has_intelligence": "_intelligence" in result,
            "confidence": result.get("_intelligence", {}).get("confidence", "unknown"),
            "quality_tier": result.get("_intelligence", {}).get("result_quality", {}).get("tier", "unknown"),
        }

        history = self._load(engine_name)
        previous = history[-1] if history else None
        history.append(entry)

        # Keep last 500 entries
        if len(history) > 500:
            history = history[-500:]
        self._save(engine_name, history)

        comparison = self._compare(entry, previous) if previous else {"first_run": True}
        return {"entry": entry, "comparison": comparison, "total_runs": len(history)}

    def get_history(self, engine_name: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._load(engine_name)[-limit:]

    def get_trend(self, engine_name: str) -> dict[str, Any]:
        """Get performance trend for an engine."""
        history = self._load(engine_name)
        if len(history) < 3:
            return {"engine": engine_name, "trend": "insufficient_data", "runs": len(history)}

        scores = [h.get("score", 0) for h in history if isinstance(h.get("score"), (int, float))]
        if len(scores) < 3:
            return {"engine": engine_name, "trend": "no_scores", "runs": len(history)}

        mid = len(scores) // 2
        old_avg = sum(scores[:mid]) / mid
        new_avg = sum(scores[mid:]) / (len(scores) - mid)
        change = ((new_avg - old_avg) / max(abs(old_avg), 0.01)) * 100

        success_rates = []
        for i in range(0, len(history), max(1, len(history) // 5)):
            chunk = history[i:i + max(1, len(history) // 5)]
            if chunk:
                rate = sum(1 for h in chunk if h.get("status") == "completed") / len(chunk)
                success_rates.append(round(rate, 2))

        return {
            "engine": engine_name,
            "total_runs": len(history),
            "trend": "improving" if change > 5 else "declining" if change < -5 else "stable",
            "score_change_pct": round(change, 1),
            "avg_score_recent": round(new_avg, 2),
            "avg_score_older": round(old_avg, 2),
            "success_rate_history": success_rates,
            "current_success_rate": success_rates[-1] if success_rates else 0,
        }

    def get_dashboard(self) -> dict[str, Any]:
        """Get summary across all engines with history."""
        engines_with_history = []
        if os.path.isdir(_HISTORY_DIR):
            for f in os.listdir(_HISTORY_DIR):
                if f.endswith(".json"):
                    engines_with_history.append(f[:-5])

        summaries = []
        for eng in sorted(engines_with_history)[:50]:
            trend = self.get_trend(eng)
            summaries.append({
                "engine": eng,
                "runs": trend.get("total_runs", 0),
                "trend": trend.get("trend", "?"),
                "score": trend.get("avg_score_recent", 0),
            })

        improving = sum(1 for s in summaries if s["trend"] == "improving")
        declining = sum(1 for s in summaries if s["trend"] == "declining")

        return {
            "engines_tracked": len(engines_with_history),
            "improving": improving,
            "declining": declining,
            "stable": len(summaries) - improving - declining,
            "top_engines": sorted(summaries, key=lambda s: -s["score"])[:5],
            "needs_attention": [s for s in summaries if s["trend"] == "declining"][:5],
        }

    def _compare(self, current: dict, previous: dict) -> dict[str, Any]:
        """Compare current run with previous."""
        score_diff = (current.get("score", 0) or 0) - (previous.get("score", 0) or 0)
        return {
            "score_change": round(score_diff, 2),
            "improved": score_diff > 0.5,
            "regressed": score_diff < -0.5,
            "status_same": current.get("status") == previous.get("status"),
            "time_since_last": round(current["timestamp"] - previous["timestamp"], 1),
        }

    @staticmethod
    def _extract_score(result: dict) -> float:
        for key in ("score", "analysis_score", "confidence_score"):
            val = result.get(key)
            if isinstance(val, (int, float)) and 0 <= val <= 10:
                return float(val)
        return 0.0

    def _load(self, engine_name: str) -> list[dict]:
        path = os.path.join(_HISTORY_DIR, f"{engine_name}.json")
        with self._lock:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
        return []

    def _save(self, engine_name: str, history: list[dict]) -> None:
        path = os.path.join(_HISTORY_DIR, f"{engine_name}.json")
        with self._lock:
            try:
                with open(path, "w") as f:
                    json.dump(history, f)
            except OSError:
                pass
