"""OutcomeTracker — tracks real outcomes from system decisions.

Links decisions → outcomes → patterns → future improvements.
This is the LEARNING part — system gets smarter over time.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("learning.outcome")

try:
    from core.memory.storage_config import outcomes_dir
    _OUTCOME_DIR = outcomes_dir()
except Exception:
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
        """Record the real outcome of a decision — thread-safe."""
        with self._lock:
            entries = self._load_unlocked(engine)
            for entry in reversed(entries):
                if entry.get("decision_id") == decision_id:
                    entry["outcome"] = outcome
                    entry["outcome_timestamp"] = time.time()
                    entry["success"] = outcome.get("success", safe_float(outcome.get("revenue")) > 0)
                    self._save_unlocked(engine, entries)
                    return True
        return False

    def get_winning_patterns(self, engine: str, min_success: int = 1) -> dict[str, Any]:
        """Analyze outcomes with correlation check — only learn REAL patterns."""
        entries = self._load(engine)
        outcomes = [e for e in entries if e.get("outcome") is not None]

        if not outcomes:
            return {"engine": engine, "patterns": [], "data_points": 0}

        successes = [e for e in outcomes if e.get("success")]
        failures = [e for e in outcomes if not e.get("success")]

        patterns = []

        # Extract scores from successes and failures
        success_scores = self._extract_scores(successes)
        fail_scores = self._extract_scores(failures)

        if len(successes) >= min_success and success_scores:
            avg_success = sum(success_scores) / len(success_scores)
            avg_fail = sum(fail_scores) / len(fail_scores) if fail_scores else 0

            # Only create score_range pattern if success scores are HIGHER than failure scores
            # This is the correlation check — prevents false patterns
            if not fail_scores or avg_success > avg_fail:
                patterns.append({
                    "pattern": "score_range",
                    "detail": f"Successful decisions had avg score {avg_success:.1f}",
                    "avg": round(avg_success, 1),
                    "min": round(min(success_scores), 1),
                    "max": round(max(success_scores), 1),
                    "correlation": "confirmed" if fail_scores and avg_success > avg_fail + 1 else "weak",
                })

            # Common fields in successful decisions
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

        # What to avoid — only if there's a clear score difference
        if fail_scores:
            avg_fail = sum(fail_scores) / len(fail_scores)
            avg_success = sum(success_scores) / len(success_scores) if success_scores else 10

            # Only flag avoidance if failure scores are clearly lower
            if avg_fail < avg_success - 0.5:
                patterns.append({
                    "pattern": "avoid_low_scores",
                    "detail": f"Failed decisions had avg score {avg_fail:.1f} — avoid below {min(fail_scores):.1f}",
                    "avg_fail": round(avg_fail, 1),
                    "threshold": round(min(fail_scores), 1),
                })

        # Confidence-based patterns
        success_confidence = self._extract_field(successes, "confidence")
        fail_confidence = self._extract_field(failures, "confidence")
        if success_confidence:
            high_rate = success_confidence.count("high") / len(success_confidence)
            if high_rate > 0.6:
                patterns.append({
                    "pattern": "high_confidence_wins",
                    "detail": f"{high_rate:.0%} of successes had high confidence",
                })

        # Data quality correlation
        success_quality = [safe_float(e.get("decision", {}).get("data_quality")) for e in successes]
        success_quality = [q for q in success_quality if q > 0]
        fail_quality = [safe_float(e.get("decision", {}).get("data_quality")) for e in failures]
        fail_quality = [q for q in fail_quality if q > 0]
        if success_quality and fail_quality:
            avg_sq = sum(success_quality) / len(success_quality)
            avg_fq = sum(fail_quality) / len(fail_quality)
            if avg_sq > avg_fq + 5:
                patterns.append({
                    "pattern": "quality_matters",
                    "detail": f"Better data quality ({avg_sq:.0f} vs {avg_fq:.0f}) correlates with success",
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
        score = safe_float(decision.get("total_score", decision.get("score", decision.get("opportunity_score", 5))))

        advice = {"proceed": True, "confidence": "medium", "reasons": []}

        if patterns.get("success_rate", 0.5) > 0.7:
            advice["reasons"].append(f"Engine has {patterns['success_rate']:.0%} success rate")
            advice["confidence"] = "high"
        elif patterns.get("success_rate", 0.5) < 0.3:
            advice["reasons"].append(f"Engine has low {patterns['success_rate']:.0%} success rate — proceed cautiously")
            advice["confidence"] = "low"

        for p in patterns.get("patterns", []):
            if p["pattern"] == "score_range" and p.get("correlation") == "confirmed":
                if isinstance(score, (int, float)) and score < p.get("min", 0):
                    advice["proceed"] = False
                    advice["reasons"].append(f"Score {score} below proven minimum {p['min']}")
            elif p["pattern"] == "avoid_low_scores":
                threshold = p.get("threshold", 0)
                if isinstance(score, (int, float)) and score < threshold:
                    advice["reasons"].append(f"Score {score} in failure zone (below {threshold})")

        if not advice["reasons"]:
            advice["reasons"].append("No strong patterns yet — standard analysis")

        return advice

    @staticmethod
    def _extract_scores(entries: list[dict]) -> list[float]:
        """Extract numeric scores from entries safely."""
        scores = []
        for e in entries:
            if isinstance(e.get("decision"), dict):
                s = e["decision"].get("total_score", e["decision"].get("score", e["decision"].get("opportunity_score")))
                if isinstance(s, (int, float)):
                    scores.append(float(s))
        return scores

    @staticmethod
    def _extract_field(entries: list[dict], field: str) -> list[Any]:
        """Extract a specific field from decision dicts."""
        values = []
        for e in entries:
            if isinstance(e.get("decision"), dict):
                v = e["decision"].get(field)
                if v is not None:
                    values.append(v)
        return values

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
        with self._lock:
            entries = self._load_unlocked(engine)
            entries.append(entry)
            if len(entries) > 1000:
                entries = entries[-1000:]
            self._save_unlocked(engine, entries)

    def _load(self, engine: str) -> list[dict]:
        with self._lock:
            return self._load_unlocked(engine)

    def _load_unlocked(self, engine: str) -> list[dict]:
        """Load without acquiring lock — caller must hold lock."""
        path = os.path.join(_OUTCOME_DIR, f"{engine}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Corrupted outcome file %s: %s", path, exc)
        return []

    def _save(self, engine: str, entries: list[dict]) -> None:
        with self._lock:
            self._save_unlocked(engine, entries)

    def _save_unlocked(self, engine: str, entries: list[dict]) -> None:
        """Save without acquiring lock — caller must hold lock."""
        path = os.path.join(_OUTCOME_DIR, f"{engine}.json")
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(entries, f)
            os.replace(tmp_path, path)  # Atomic on POSIX
        except OSError as exc:
            logger.error("Failed to save outcomes for %s: %s", engine, exc)
