"""EngineMemory — persistent memory per engine across runs.

Each engine remembers:
  - What inputs it processed before (deduplication)
  - What outputs worked well (quality feedback)
  - Common patterns in its data (learned baselines)

Never modifies engine code. Read-only learning from execution history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("shared_memory.engine")

try:
    from core.memory.storage_config import engine_memory_dir
    _MEMORY_DIR = engine_memory_dir()
except Exception:
    _MEMORY_DIR = "/tmp/shopai_engine_memory"


class EngineMemory:
    """Per-engine persistent memory."""

    def __init__(self, engine_name: str) -> None:
        self._engine_name = engine_name
        self._lock = threading.Lock()
        self._seen_inputs: set[str] = set()
        self._successful_patterns: list[dict[str, Any]] = []
        self._baselines: dict[str, dict[str, float]] = {}
        self._load()

    def remember_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Check if we've seen similar input before. Returns dedup info."""
        data_hash = self._hash_data(data)
        with self._lock:
            is_duplicate = data_hash in self._seen_inputs
            self._seen_inputs.add(data_hash)

        return {
            "is_duplicate": is_duplicate,
            "data_hash": data_hash,
            "similar_runs": self._find_similar(data),
        }

    def remember_success(self, data: dict[str, Any], output: dict[str, Any], quality_score: float) -> None:
        """Remember a successful execution for future reference."""
        if quality_score < 5:
            return

        pattern = {
            "input_keys": sorted(data.keys()),
            "output_keys": sorted(output.keys()),
            "quality_score": quality_score,
            "timestamp": time.time(),
            "input_hash": self._hash_data(data),
        }

        with self._lock:
            self._successful_patterns.append(pattern)
            if len(self._successful_patterns) > 500:
                self._successful_patterns = self._successful_patterns[-500:]
            self._persist()

    def update_baseline(self, metric_name: str, value: float) -> None:
        """Update running baseline for a metric."""
        with self._lock:
            if metric_name not in self._baselines:
                self._baselines[metric_name] = {"sum": 0, "count": 0, "min": value, "max": value}

            b = self._baselines[metric_name]
            b["sum"] += value
            b["count"] += 1
            b["min"] = min(b["min"], value)
            b["max"] = max(b["max"], value)
            b["mean"] = round(b["sum"] / b["count"], 4)

    def get_baseline(self, metric_name: str) -> dict[str, float] | None:
        """Get baseline stats for a metric."""
        with self._lock:
            return copy.deepcopy(self._baselines.get(metric_name))

    def get_all_baselines(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return copy.deepcopy(self._baselines)

    def get_success_patterns(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._successful_patterns[-limit:])

    def _find_similar(self, data: dict[str, Any]) -> int:
        """Count how many similar inputs we've seen."""
        input_keys = frozenset(data.keys())
        count = 0
        with self._lock:
            for p in self._successful_patterns:
                if frozenset(p.get("input_keys", [])) == input_keys:
                    count += 1
        return count

    @staticmethod
    def _hash_data(data: dict[str, Any]) -> str:
        content = json.dumps(sorted(data.items()), default=str, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _persist(self) -> None:
        os.makedirs(_MEMORY_DIR, exist_ok=True)
        path = os.path.join(_MEMORY_DIR, f"{self._engine_name}.json")
        try:
            state = {
                "seen_inputs": list(self._seen_inputs)[-1000:],
                "successful_patterns": self._successful_patterns[-500:],
                "baselines": self._baselines,
            }
            with open(path, "w") as f:
                json.dump(state, f)
        except OSError:
            pass

    def _load(self) -> None:
        path = os.path.join(_MEMORY_DIR, f"{self._engine_name}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    state = json.load(f)
                    self._seen_inputs = set(state.get("seen_inputs", []))
                    self._successful_patterns = state.get("successful_patterns", [])
                    self._baselines = state.get("baselines", {})
            except (json.JSONDecodeError, OSError):
                pass
