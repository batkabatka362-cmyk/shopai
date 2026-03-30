"""FeedbackStore — persists engine execution feedback for learning.

Every engine run produces feedback: what worked, what failed, timing, quality scores.
This store accumulates that data so the system can learn from experience.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("learning.feedback_store")

_STORE_DIR = "/tmp/shopai_learning"


class FeedbackStore:
    """Thread-safe feedback storage with file persistence."""

    def __init__(self, store_dir: str = _STORE_DIR) -> None:
        self._store_dir = store_dir
        self._memory: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        os.makedirs(self._store_dir, exist_ok=True)

    def record(
        self,
        engine_name: str,
        task_id: str,
        status: str,
        elapsed_seconds: float,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        step_results: list[dict[str, Any]] | None = None,
        quality_score: float | None = None,
        error: str | None = None,
    ) -> str:
        """Record feedback from an engine execution."""
        feedback_id = f"fb_{int(time.time() * 1000)}_{task_id[-6:]}"
        entry = {
            "feedback_id": feedback_id,
            "engine_name": engine_name,
            "task_id": task_id,
            "status": status,
            "elapsed_seconds": elapsed_seconds,
            "input_keys": list((input_summary or {}).keys()),
            "output_keys": list((output_summary or {}).keys()),
            "step_count": len(step_results) if step_results else 0,
            "failed_steps": [s["step_name"] for s in (step_results or []) if s.get("status") == "failed"],
            "quality_score": quality_score,
            "error": error,
            "timestamp": time.time(),
        }

        with self._lock:
            if engine_name not in self._memory:
                self._memory[engine_name] = self._load_engine(engine_name)
            self._memory[engine_name].append(entry)
            self._persist_engine(engine_name)

        logger.info("Recorded feedback %s for engine=%s status=%s", feedback_id, engine_name, status)
        return feedback_id

    def get_history(self, engine_name: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent feedback for an engine."""
        with self._lock:
            if engine_name not in self._memory:
                self._memory[engine_name] = self._load_engine(engine_name)
            return list(self._memory[engine_name][-limit:])

    def get_stats(self, engine_name: str) -> dict[str, Any]:
        """Get aggregated stats for an engine."""
        history = self.get_history(engine_name, limit=1000)
        if not history:
            return {"engine": engine_name, "total_runs": 0}

        total = len(history)
        completed = sum(1 for h in history if h["status"] == "completed")
        failed = sum(1 for h in history if h["status"] == "failed")
        times = [h.get("elapsed_seconds", 0) for h in history if h.get("elapsed_seconds") is not None]
        scores = [h.get("quality_score", 0) for h in history if h.get("quality_score") is not None]

        return {
            "engine": engine_name,
            "total_runs": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total, 4) if total else 0,
            "avg_elapsed": round(sum(times) / len(times), 3) if times else 0,
            "avg_quality": round(sum(scores) / len(scores), 2) if scores else None,
            "common_errors": self._top_errors(history, n=3),
            "trend": self._calculate_trend(history),
        }

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get stats for all engines that have feedback."""
        with self._lock:
            engine_names = set(self._memory.keys())
        # Also check persisted files
        if os.path.isdir(self._store_dir):
            for f in os.listdir(self._store_dir):
                if f.endswith(".json"):
                    engine_names.add(f[:-5])
        return {name: self.get_stats(name) for name in sorted(engine_names)}

    def _calculate_trend(self, history: list[dict[str, Any]]) -> str:
        """Compare recent vs older performance."""
        if len(history) < 10:
            return "insufficient_data"
        mid = len(history) // 2
        old_rate = sum(1 for h in history[:mid] if h["status"] == "completed") / mid
        new_rate = sum(1 for h in history[mid:] if h["status"] == "completed") / (len(history) - mid)
        if new_rate > old_rate + 0.05:
            return "improving"
        elif new_rate < old_rate - 0.05:
            return "declining"
        return "stable"

    @staticmethod
    def _top_errors(history: list[dict[str, Any]], n: int = 3) -> list[str]:
        counts: dict[str, int] = {}
        for h in history:
            if h.get("error"):
                err = h["error"][:80]
                counts[err] = counts.get(err, 0) + 1
        return sorted(counts, key=counts.get, reverse=True)[:n]

    def _persist_engine(self, engine_name: str) -> None:
        path = os.path.join(self._store_dir, f"{engine_name}.json")
        try:
            with open(path, "w") as f:
                json.dump(self._memory[engine_name][-5000:], f)
        except OSError as exc:
            logger.warning("Failed to persist feedback for %s: %s", engine_name, exc)

    def _load_engine(self, engine_name: str) -> list[dict[str, Any]]:
        path = os.path.join(self._store_dir, f"{engine_name}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []
