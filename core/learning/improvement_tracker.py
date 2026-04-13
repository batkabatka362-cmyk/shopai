"""ImprovementTracker — tracks what improvements were made and their impact.

Records: what was changed, when, why, and whether it helped.
READ-ONLY analysis — never modifies engine code or system structure.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
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
        # Defensive coercion + uuid id to avoid collision under
        # concurrent calls (pre-audit the millisecond-based id
        # collided whenever two proposals landed in the same
        # millisecond). Audit pass 52.
        if not isinstance(engine_name, str) or not engine_name:
            return ""
        improvement_id = f"imp_{uuid.uuid4().hex[:16]}"
        entry = {
            "id": improvement_id,
            "engine_name": engine_name,
            "type": str(improvement_type or "unknown"),
            "description": str(description or ""),
            "expected_impact": str(expected_impact or ""),
            "source": str(source or "learning_engine"),
            "status": "proposed",
            "proposed_at": time.time(),
            "applied_at": None,
            "impact_measured": None,
        }

        with self._lock:
            self._improvements.append(entry)
            self._persist()

        logger.info("Proposed improvement %s for %s: %s", improvement_id, engine_name, str(description)[:60])
        return improvement_id

    def mark_applied(self, improvement_id: str) -> bool:
        """Mark an improvement as applied (by human operator)."""
        if not isinstance(improvement_id, str) or not improvement_id:
            return False
        with self._lock:
            for imp in self._improvements:
                if imp.get("id") == improvement_id:
                    imp["status"] = "applied"
                    imp["applied_at"] = time.time()
                    self._persist()
                    return True
        return False

    def record_impact(self, improvement_id: str, impact: dict[str, Any]) -> bool:
        """Record the measured impact of an applied improvement."""
        if not isinstance(improvement_id, str) or not improvement_id:
            return False
        if not isinstance(impact, dict):
            impact = {"raw": str(impact)[:500]}
        with self._lock:
            for imp in self._improvements:
                if imp.get("id") == improvement_id:
                    imp["impact_measured"] = impact
                    imp["status"] = "measured"
                    self._persist()
                    return True
        return False

    def list_proposed(self, engine_name: str | None = None) -> list[dict[str, Any]]:
        """List proposed improvements, optionally filtered by engine."""
        with self._lock:
            items = [i for i in self._improvements if i.get("status") == "proposed"]
        if engine_name:
            items = [i for i in items if i.get("engine_name") == engine_name]
        return items

    def list_applied(self) -> list[dict[str, Any]]:
        """List applied improvements."""
        with self._lock:
            return [i for i in self._improvements if i.get("status") in ("applied", "measured")]

    def get_improvement_history(self, engine_name: str) -> list[dict[str, Any]]:
        """Get all improvements for a specific engine."""
        with self._lock:
            return [i for i in self._improvements if i.get("engine_name") == engine_name]

    def summary(self) -> dict[str, Any]:
        """Get summary of all improvements."""
        with self._lock:
            proposed = sum(1 for i in self._improvements if i.get("status") == "proposed")
            applied = sum(1 for i in self._improvements if i.get("status") == "applied")
            measured = sum(1 for i in self._improvements if i.get("status") == "measured")
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
            t = imp.get("type") or "unknown"
            counts[t] = counts.get(t, 0) + 1
        return counts

    def _persist(self) -> None:
        """Atomic write via ``.tmp`` + ``os.replace``.

        Pre-audit wrote directly to the destination path — a
        crash mid-write left a half-written file, and the
        next ``_load()`` silently returned an empty list,
        destroying the entire improvement history. Same data-
        loss pattern as pass 48 feedback_store. Audit pass 52.
        """
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self._improvements[-10000:], f)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("Failed to persist improvements: %s", exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError as exc:
                logger.debug("improvement tracker tmp file cleanup failed: %s", exc)

    def _load(self) -> None:
        """Load with corrupted-file backup (same pattern as
        pass 48 feedback_store). Audit pass 52."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(
                    f"improvements file is {type(data).__name__}, expected list"
                )
            self._improvements = data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            backup = f"{self._path}.corrupted.{int(time.time())}"
            try:
                os.replace(self._path, backup)
                logger.warning(
                    "Corrupted improvements file: %s — moved to %s",
                    exc, backup,
                )
            except OSError:
                logger.warning("Corrupted improvements file: %s", exc)
            self._improvements = []
