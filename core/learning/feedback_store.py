"""FeedbackStore — persists engine execution feedback for learning.

Every engine run produces feedback: what worked, what failed, timing, quality scores.
This store accumulates that data so the system can learn from experience.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from typing import Any

from utils.logger import get_logger

logger = get_logger("learning.feedback_store")

_STORE_DIR = "/tmp/shopai_learning"


def _safe_keys(value: Any) -> list[str]:
    """Coerce a value into a string-list of dict keys.

    Replaces `list((value or {}).keys())` which crashed with
    AttributeError when callers passed a non-dict (list, string,
    None still OK because of `or {}`). Now any non-dict argument
    yields an empty list instead of taking out the entire record()
    call mid-cycle.
    """
    if isinstance(value, dict):
        return [str(k) for k in value.keys()]
    return []


class FeedbackStore:
    """Thread-safe feedback storage with file persistence."""

    def __init__(self, store_dir: str = _STORE_DIR) -> None:
        self._store_dir = store_dir
        self._memory: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        # Per-engine persist error tracking, mirrors the
        # observability hooks added in audit passes 20 / 22.
        self._persist_errors: dict[str, str] = {}
        os.makedirs(self._store_dir, exist_ok=True)

    def get_persist_errors(self) -> dict[str, str]:
        """Return per-engine persist error messages, or empty dict
        if every recent persist call succeeded."""
        with self._lock:
            return dict(self._persist_errors)

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
        # uuid instead of millisecond timestamp + last 6 chars of
        # task_id: the previous form collided whenever two engines
        # ran with the same / empty task_id within the same ms.
        feedback_id = f"fb_{uuid.uuid4().hex[:16]}"
        # Defensive: callers occasionally pass non-dict summaries
        # (raw response strings, lists, …). The previous
        # `(value or {}).keys()` form crashed with AttributeError.
        failed_steps = []
        if isinstance(step_results, list):
            for s in step_results:
                if isinstance(s, dict) and s.get("status") == "failed":
                    name = s.get("step_name") or s.get("name") or "unnamed"
                    failed_steps.append(name)
        entry = {
            "feedback_id": feedback_id,
            "engine_name": engine_name,
            "task_id": task_id,
            "status": status,
            "elapsed_seconds": elapsed_seconds,
            "input_keys": _safe_keys(input_summary),
            "output_keys": _safe_keys(output_summary),
            "step_count": len(step_results) if isinstance(step_results, list) else 0,
            "failed_steps": failed_steps,
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
        """Get recent feedback for an engine.

        Returns deep copies so caller mutation can't poison the
        in-memory store. Same defensive-copy pattern as audit
        passes 12 / 17 / 18 / 19 / 22.
        """
        with self._lock:
            if engine_name not in self._memory:
                self._memory[engine_name] = self._load_engine(engine_name)
            return [copy.deepcopy(e) for e in self._memory[engine_name][-limit:]]

    def get_stats(self, engine_name: str) -> dict[str, Any]:
        """Get aggregated stats for an engine."""
        history = self.get_history(engine_name, limit=1000)
        if not history:
            return {"engine": engine_name, "total_runs": 0}

        total = len(history)
        # `.get("status")` so a malformed entry without the field
        # doesn't crash the whole stats call with KeyError.
        completed = sum(1 for h in history if h.get("status") == "completed")
        failed = sum(1 for h in history if h.get("status") == "failed")
        # Type-check before sum so a string elapsed_seconds can't
        # crash `sum() / len()`.
        times = [
            float(h["elapsed_seconds"]) for h in history
            if isinstance(h.get("elapsed_seconds"), (int, float))
        ]
        scores = [
            float(h["quality_score"]) for h in history
            if isinstance(h.get("quality_score"), (int, float))
        ]

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
        # `.get("status")` so a malformed entry doesn't crash trend
        # calculation with KeyError.
        old_rate = sum(1 for h in history[:mid] if h.get("status") == "completed") / mid
        new_rate = sum(1 for h in history[mid:] if h.get("status") == "completed") / (len(history) - mid)
        if new_rate > old_rate + 0.05:
            return "improving"
        elif new_rate < old_rate - 0.05:
            return "declining"
        return "stable"

    @staticmethod
    def _top_errors(history: list[dict[str, Any]], n: int = 3) -> list[str]:
        counts: dict[str, int] = {}
        for h in history:
            err_val = h.get("error")
            if err_val:
                err = str(err_val)[:80]
                counts[err] = counts.get(err, 0) + 1
        return sorted(counts, key=lambda k: counts[k], reverse=True)[:n]

    def _persist_engine(self, engine_name: str) -> None:
        """Save an engine's feedback log to disk via atomic rename.

        Previous version wrote directly to the destination path —
        a process crash mid-write left the file half-written and
        the next _load_engine() returned [] (silent data loss).
        Now we write to a `.tmp` sibling and atomic-rename into
        place, mirroring the StoreSnapshot / CycleJournal patterns
        from audit passes 20 / 22.
        """
        path = os.path.join(self._store_dir, f"{engine_name}.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self._memory[engine_name][-5000:], f)
            os.replace(tmp, path)
            # Successful persist clears any prior error for this
            # engine.
            self._persist_errors.pop(engine_name, None)
        except OSError as exc:
            self._persist_errors[engine_name] = f"{type(exc).__name__}: {exc}"
            logger.warning("Failed to persist feedback for %s: %s", engine_name, exc)
            # Best-effort cleanup of the half-written tmp file so
            # we don't leak it on the next attempt.
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _load_engine(self, engine_name: str) -> list[dict[str, Any]]:
        """Load an engine's feedback log from disk.

        On JSON parse errors / wrong-shape data, the corrupted
        file is moved aside as `<path>.corrupted.<ts>` BEFORE
        we fall back to the empty list. The previous version
        silently returned [] AND left the corrupted file in
        place — the next _persist_engine() then overwrote it
        with empty data, destroying the engine's entire learning
        history forever. Same data-loss bug pattern fixed in
        StoreSnapshot.load() (pass 20) and CycleJournal._load
        (pass 22).
        """
        path = os.path.join(self._store_dir, f"{engine_name}.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(
                    f"feedback file is {type(data).__name__}, expected list"
                )
            return data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            backup = f"{path}.corrupted.{int(time.time())}"
            try:
                os.replace(path, backup)
                logger.warning(
                    "Feedback load failed for %s (%s); corrupted file moved to %s",
                    engine_name, exc, backup,
                )
            except OSError as move_exc:
                logger.warning(
                    "Feedback load failed for %s (%s); could not back "
                    "up corrupted file (%s)", engine_name, exc, move_exc,
                )
            return []
