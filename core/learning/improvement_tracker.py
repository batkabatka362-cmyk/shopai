"""ImprovementTracker — tracks what improvements were made and their impact.

Records: what was changed, when, why, and whether it helped.
READ-ONLY analysis — never modifies engine code or system structure.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("learning.improvement_tracker")

_TRACKER_PATH = "/tmp/shopai_learning/improvements.json"


class ImprovementTracker:
    """Tracks improvement recommendations and their outcomes.

    IMPORTANT: This tracker only RECORDS and RECOMMENDS.
    It NEVER modifies code, deletes files, or changes system structure.
    All changes must be approved and applied by a human operator.
    """

    def __init__(self, tracker_path: str = _TRACKER_PATH) -> None:
        self._path = tracker_path
        self._improvements: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._load()

    def propose(
        self,
        engine_name: str,
        improvement_type: str,
        description: str,
        expected_impact: str,
        source: str = "learning_engine",
    ) -> str:
        """Propose an improvement (does NOT apply it — read-only)."""
        improvement_id = f"imp_{int(time.time() * 1000)}"
        entry = {
            "id": improvement_id,
            "engine_name": engine_name,
            "type": improvement_type,
            "description": description,
            "expected_impact": expected_impact,
            "source": source,
            "status": "proposed",
            "proposed_at": time.time(),
            "applied_at": None,
            "impact_measured": None,
        }

        with self._lock:
            self._improvements.append(entry)
            self._persist()

        logger.info("Proposed improvement %s for %s: %s", improvement_id, engine_name, description[:60])
        return improvement_id

    def mark_applied(self, improvement_id: str) -> bool:
        """Mark an improvement as applied (by human operator)."""
        with self._lock:
            for imp in self._improvements:
                if imp["id"] == improvement_id:
                    imp["status"] = "applied"
                    imp["applied_at"] = time.time()
                    self._persist()
                    return True
        return False

    def record_impact(self, improvement_id: str, impact: dict[str, Any]) -> bool:
        """Record the measured impact of an applied improvement."""
        with self._lock:
            for imp in self._improvements:
                if imp["id"] == improvement_id:
                    imp["impact_measured"] = impact
                    imp["status"] = "measured"
                    self._persist()
                    return True
        return False

    def list_proposed(self, engine_name: str | None = None) -> list[dict[str, Any]]:
        """List proposed improvements, optionally filtered by engine."""
        with self._lock:
            items = [i for i in self._improvements if i["status"] == "proposed"]
        if engine_name:
            items = [i for i in items if i["engine_name"] == engine_name]
        return items

    def list_applied(self) -> list[dict[str, Any]]:
        """List applied improvements."""
        with self._lock:
            return [i for i in self._improvements if i["status"] in ("applied", "measured")]

    def get_improvement_history(self, engine_name: str) -> list[dict[str, Any]]:
        """Get all improvements for a specific engine."""
        with self._lock:
            return [i for i in self._improvements if i["engine_name"] == engine_name]

    def summary(self) -> dict[str, Any]:
        """Get summary of all improvements."""
        with self._lock:
            proposed = sum(1 for i in self._improvements if i["status"] == "proposed")
            applied = sum(1 for i in self._improvements if i["status"] == "applied")
            measured = sum(1 for i in self._improvements if i["status"] == "measured")
            return {
                "total": len(self._improvements),
                "proposed": proposed,
                "applied": applied,
                "measured": measured,
                "by_type": self._count_by_type(),
            }

    def _count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for imp in self._improvements:
            t = imp["type"]
            counts[t] = counts.get(t, 0) + 1
        return counts

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        try:
            with open(self._path, "w") as f:
                json.dump(self._improvements[-10000:], f)
        except OSError as exc:
            logger.warning("Failed to persist improvements: %s", exc)

    def _load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    self._improvements = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._improvements = []
