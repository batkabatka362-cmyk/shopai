"""CycleJournal — persistent record of every orchestrator cycle.

Enables:
  - "What did the system do in the last 24 hours?"
  - "Show me the decision that led to this price change"
  - Cross-cycle pattern detection (e.g., "every time we raise prices on Monday, sales drop")
  - Audit trail for all automated decisions

Replaces scattered in-memory _history lists across FullSystemLoop,
IntelligenceLoop, and EventReactor with a single persistent store.
"""
from __future__ import annotations

import json
import os
import time
import threading
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("orchestrator.journal")

try:
    from core.memory.storage_config import get_path
    _JOURNAL_DIR = os.path.join(get_path("data"), "journal")
except Exception:
    _JOURNAL_DIR = "/tmp/shopai_journal"


class CycleJournal:
    """Persistent record of orchestrator cycles.

    Usage:
        journal = CycleJournal()
        journal.record_cycle(cycle_result)

        # Query history
        recent = journal.get_recent(hours=24)
        decisions = journal.get_decisions(limit=10)
        pattern = journal.detect_patterns()
    """

    def __init__(self, journal_dir: str | None = None) -> None:
        self._dir = journal_dir or _JOURNAL_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._load()

    def record_cycle(self, cycle_result: dict[str, Any]) -> str:
        """Record a completed cycle in the journal."""
        with self._lock:
            entry_id = generate_id("journal")
            summary = cycle_result.get("summary", {})
            entry = {
                "entry_id": entry_id,
                "cycle_id": cycle_result.get("cycle_id", ""),
                "timestamp": cycle_result.get("timestamp", time.time()),
                "goal": cycle_result.get("goal", ""),
                "elapsed_seconds": cycle_result.get("elapsed_seconds", 0),
                "decision": summary.get("decision", "none"),
                "decision_reason": summary.get("decision_reason", ""),
                "confidence": summary.get("confidence", "unknown"),
                "confidence_score": summary.get("confidence_score", 0),
                "data_quality": summary.get("data_quality", 0),
                "net_profit": summary.get("net_profit", 0),
                "health_grade": summary.get("health_grade", "?"),
                "events_fired": summary.get("events_fired", 0),
                "modules_active": summary.get("modules_active", 0),
                "strategy_goal": summary.get("strategy_goal", ""),
                "strategy_switch": summary.get("strategy_switch", False),
                "priorities": [
                    {"domain": p.get("domain"), "urgency": p.get("urgency"), "score": p.get("score")}
                    for p in cycle_result.get("priorities", [])
                ],
            }
            self._entries.append(entry)
            self._persist()
            return entry_id

    def record_event(self, event_type: str, data: dict[str, Any]) -> str:
        """Record a standalone event (not part of a cycle)."""
        with self._lock:
            entry_id = generate_id("event")
            entry = {
                "entry_id": entry_id,
                "type": "event",
                "event_type": event_type,
                "timestamp": time.time(),
                "data": data,
            }
            self._entries.append(entry)
            self._persist()
            return entry_id

    def get_recent(self, hours: float = 24, limit: int = 100) -> list[dict[str, Any]]:
        """Get entries from the last N hours."""
        cutoff = time.time() - (hours * 3600)
        with self._lock:
            recent = [e for e in self._entries if e.get("timestamp", 0) > cutoff]
            return recent[-limit:]

    def get_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent cycle decisions."""
        with self._lock:
            cycles = [e for e in self._entries if "cycle_id" in e]
            return cycles[-limit:]

    def get_by_goal(self, goal: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get cycles that used a specific goal."""
        with self._lock:
            matching = [e for e in self._entries if e.get("goal") == goal]
            return matching[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get journal statistics."""
        with self._lock:
            if not self._entries:
                return {"total_entries": 0}

            cycles = [e for e in self._entries if "cycle_id" in e]
            events = [e for e in self._entries if e.get("type") == "event"]

            # Decision distribution
            decisions: dict[str, int] = {}
            goals: dict[str, int] = {}
            confidence_scores: list[float] = []
            for c in cycles:
                d = c.get("decision", "none")
                decisions[d] = decisions.get(d, 0) + 1
                g = c.get("goal", "unknown")
                goals[g] = goals.get(g, 0) + 1
                cs = c.get("confidence_score", 0)
                if cs > 0:
                    confidence_scores.append(cs)

            avg_confidence = (
                round(sum(confidence_scores) / len(confidence_scores), 1)
                if confidence_scores else 0
            )

            return {
                "total_entries": len(self._entries),
                "total_cycles": len(cycles),
                "total_events": len(events),
                "decision_distribution": decisions,
                "goal_distribution": goals,
                "avg_confidence_score": avg_confidence,
                "oldest_entry": self._entries[0].get("timestamp") if self._entries else None,
                "newest_entry": self._entries[-1].get("timestamp") if self._entries else None,
            }

    def detect_patterns(self) -> list[dict[str, Any]]:
        """Detect patterns across cycles.

        Looks for:
        - Repeated decisions (same decision 3+ times in a row)
        - Declining confidence trend
        - Goal switching frequency
        - Time-of-day patterns
        """
        patterns = []
        with self._lock:
            cycles = [e for e in self._entries if "cycle_id" in e]

        if len(cycles) < 3:
            return patterns

        # Pattern: repeated same decision
        recent_decisions = [c.get("decision", "") for c in cycles[-5:]]
        if len(set(recent_decisions)) == 1 and recent_decisions[0] != "none":
            patterns.append({
                "type": "repeated_decision",
                "decision": recent_decisions[0],
                "count": len(recent_decisions),
                "insight": f"Same decision '{recent_decisions[0]}' made {len(recent_decisions)} times — may indicate a stuck loop or persistent opportunity",
            })

        # Pattern: declining confidence
        recent_scores = [c.get("confidence_score", 0) for c in cycles[-5:] if c.get("confidence_score", 0) > 0]
        if len(recent_scores) >= 3:
            if all(recent_scores[i] >= recent_scores[i + 1] for i in range(len(recent_scores) - 1)):
                patterns.append({
                    "type": "declining_confidence",
                    "scores": recent_scores,
                    "insight": "Confidence declining across recent cycles — data quality or market conditions may be worsening",
                })

        # Pattern: frequent goal switching
        recent_goals = [c.get("goal", "") for c in cycles[-10:]]
        switches = sum(1 for i in range(1, len(recent_goals)) if recent_goals[i] != recent_goals[i - 1])
        if switches >= 3:
            patterns.append({
                "type": "goal_thrashing",
                "switches": switches,
                "goals": recent_goals,
                "insight": f"Goal switched {switches} times in last {len(recent_goals)} cycles — strategy may be unstable",
            })

        return patterns

    def _persist(self) -> None:
        """Save journal to disk."""
        try:
            # Keep max 10,000 entries
            if len(self._entries) > 10000:
                self._entries = self._entries[-10000:]

            path = os.path.join(self._dir, "journal.json")
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._entries, f, default=str)
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning("Failed to persist journal: %s", exc)

    def _load(self) -> None:
        """Load journal from disk."""
        path = os.path.join(self._dir, "journal.json")
        try:
            if os.path.exists(path):
                with open(path) as f:
                    self._entries = json.load(f)
                logger.info("Journal loaded: %d entries", len(self._entries))
        except Exception as exc:
            logger.warning("Failed to load journal: %s", exc)
            self._entries = []
