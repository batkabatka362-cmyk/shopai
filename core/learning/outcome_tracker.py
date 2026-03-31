"""OutcomeTracker — tracks real outcomes from system decisions.

Links decisions → outcomes → patterns → future improvements.
This is the LEARNING part — system gets smarter over time.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("learning.outcome")

_OUTCOME_DIR = "/tmp/shopai_outcomes"


class OutcomeTracker:
    """Tracks outcomes and learns winning patterns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(_OUTCOME_DIR, exist_ok=True)

    def record_decision(self, decision_id: str, engine: str, decision: dict[str, Any]) -> None:
        """Record a decision that was made."""
        entry = {
            "decision_id": decision_id,
            "engine": engine,
            "decision": {k: v for k, v in decision.items() if not k.startswith("_") and k not in ("request_id", "model", "role")},
            "timestamp": time.time(),
            "outcome": None,
        }
        self._append(engine, entry)

    def record_outcome(self, decision_id: str, engine: str, outcome: dict[str, Any]) -> bool:
        """Record the real outcome of a decision."""
        entries = self._load(engine)
        for entry in reversed(entries):
            if entry.get("decision_id") == decision_id:
                entry["outcome"] = outcome
                entry["outcome_timestamp"] = time.time()
                entry["success"] = outcome.get("success", outcome.get("revenue", 0) > 0)
                self._save(engine, entries)
                return True
        return False

    def get_winning_patterns(self, engine: str, min_success: int = 1) -> dict[str, Any]:
        """Analyze outcomes to find what works."""
        entries = self._load(engine)
        outcomes = [e for e in entries if e.get("outcome") is not None]

        if not outcomes:
            return {"engine": engine, "patterns": [], "data_points": 0}

        successes = [e for e in outcomes if e.get("success")]
        failures = [e for e in outcomes if not e.get("success")]

        # Find common traits in successful decisions
        patterns = []
        if len(successes) >= min_success:
            # Analyze score ranges
            scores = [e["decision"].get("total_score", e["decision"].get("score", 0))
                      for e in successes if isinstance(e.get("decision"), dict)]
            scores = [s for s in scores if isinstance(s, (int, float))]
            if scores:
                patterns.append({
                    "pattern": "score_range",
                    "detail": f"Successful decisions had avg score {sum(scores)/len(scores):.1f}",
                    "min": round(min(scores), 1),
                    "max": round(max(scores), 1),
                })

            # Analyze common fields in successful decisions
            field_counts: dict[str, int] = {}
            for e in successes:
                if isinstance(e.get("decision"), dict):
                    for k in e["decision"]:
                        field_counts[k] = field_counts.get(k, 0) + 1
            common = [k for k, v in field_counts.items() if v >= len(successes) * 0.8]
            if common:
                patterns.append({
                    "pattern": "common_fields",
                    "detail": f"Successful decisions always include: {common[:5]}",
                })

        # Find what to avoid
        if failures:
            fail_scores = [e["decision"].get("total_score", e["decision"].get("score", 0))
                           for e in failures if isinstance(e.get("decision"), dict)]
            fail_scores = [s for s in fail_scores if isinstance(s, (int, float))]
            if fail_scores:
                patterns.append({
                    "pattern": "avoid_low_scores",
                    "detail": f"Failed decisions had avg score {sum(fail_scores)/len(fail_scores):.1f} — avoid below {min(fail_scores):.1f}",
                })

        return {
            "engine": engine,
            "total_decisions": len(entries),
            "with_outcomes": len(outcomes),
            "successes": len(successes),
            "failures": len(failures),
            "success_rate": round(len(successes) / max(len(outcomes), 1), 2),
            "patterns": patterns,
            "recommendation": self._recommend(len(successes), len(failures), patterns),
        }

    def should_proceed(self, engine: str, decision: dict[str, Any]) -> dict[str, Any]:
        """Use past outcomes to advise on a new decision."""
        patterns = self.get_winning_patterns(engine)
        score = decision.get("total_score", decision.get("score", 5))

        advice = {"proceed": True, "confidence": "medium", "reasons": []}

        if patterns.get("success_rate", 0.5) > 0.7:
            advice["reasons"].append(f"Engine has {patterns['success_rate']:.0%} success rate")
            advice["confidence"] = "high"
        elif patterns.get("success_rate", 0.5) < 0.3:
            advice["reasons"].append(f"Engine has low {patterns['success_rate']:.0%} success rate — proceed cautiously")
            advice["confidence"] = "low"

        # Check score against winning patterns
        for p in patterns.get("patterns", []):
            if p["pattern"] == "score_range":
                if isinstance(score, (int, float)) and score < p.get("min", 0):
                    advice["proceed"] = False
                    advice["reasons"].append(f"Score {score} below winning minimum {p['min']}")

        return advice

    @staticmethod
    def _recommend(successes: int, failures: int, patterns: list) -> str:
        if successes + failures == 0:
            return "No outcome data yet — start tracking to enable learning"
        rate = successes / max(successes + failures, 1)
        if rate > 0.7:
            return "Strong performance — continue current strategy"
        if rate > 0.4:
            return "Mixed results — review failing patterns and adjust"
        return "Poor performance — significant strategy change needed"

    def _append(self, engine: str, entry: dict) -> None:
        entries = self._load(engine)
        entries.append(entry)
        if len(entries) > 1000:
            entries = entries[-1000:]
        self._save(engine, entries)

    def _load(self, engine: str) -> list[dict]:
        path = os.path.join(_OUTCOME_DIR, f"{engine}.json")
        with self._lock:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
        return []

    def _save(self, engine: str, entries: list[dict]) -> None:
        path = os.path.join(_OUTCOME_DIR, f"{engine}.json")
        with self._lock:
            try:
                with open(path, "w") as f:
                    json.dump(entries, f)
            except OSError:
                pass
