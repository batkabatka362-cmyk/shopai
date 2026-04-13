"""OutcomeTracker — tracks real outcomes from system decisions.

Links decisions → outcomes → patterns → future improvements.
This is the LEARNING part — system gets smarter over time.
"""
from __future__ import annotations

import json
import os
import re
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


# Engine names go into the filesystem as ``<engine>.json``. Only
# alphanumeric + ``_-`` are allowed so a caller passing
# ``"../../etc/passwd"`` can't escape ``_OUTCOME_DIR``. This is
# the same path-traversal class bug fixed in pass 50 for
# ``feature_store.delete``. Audit pass 52.
_ENGINE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _valid_engine_name(engine: Any) -> bool:
    return isinstance(engine, str) and bool(_ENGINE_NAME_RE.match(engine))


class OutcomeTracker:
    """Tracks outcomes and learns winning patterns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        os.makedirs(_OUTCOME_DIR, exist_ok=True)

    # Keys we strip from decision dicts before persisting — these
    # are caller bookkeeping, not part of the learnable signal.
    _DECISION_STRIP_KEYS = frozenset({"request_id", "model", "role"})

    def record_decision(self, decision_id: str, engine: str, decision: dict[str, Any]) -> None:
        """Record a decision that was made.

        Defensive against non-dict `decision` arguments — previously
        a string / list / None would crash with AttributeError on
        the `.items()` call inside the dict comprehension. Callers
        in heterogeneous code paths sometimes pass the raw response
        object instead of a dict; we now coerce gracefully.
        """
        if not _valid_engine_name(engine):
            logger.warning("OutcomeTracker.record_decision: invalid engine name %r", engine)
            return
        if not isinstance(decision_id, str) or not decision_id:
            return

        if isinstance(decision, dict):
            clean_decision = {
                k: v for k, v in decision.items()
                if isinstance(k, str)
                and not k.startswith("_")
                and k not in self._DECISION_STRIP_KEYS
            }
        else:
            # Preserve the raw value under a single field so the
            # learner can still see it without crashing.
            clean_decision = {"raw": str(decision)[:500]}
        entry = {
            "decision_id": decision_id,
            "engine": engine,
            "decision": clean_decision,
            "timestamp": time.time(),
            "outcome": None,
        }
        self._append(engine, entry)

    @staticmethod
    def _normalize_success(outcome: dict[str, Any]) -> bool:
        """Coerce an outcome dict's success signal to an explicit
        bool. Previously `outcome.get("success", default)` returned
        None when the key existed with value None, and the
        downstream filters bucket None as "failure" — silently
        misclassifying explicit "outcome unknown" entries.
        """
        if not isinstance(outcome, dict):
            return False
        raw = outcome.get("success")
        if raw is None:
            # Fall back to revenue-as-signal: positive revenue → success.
            return safe_float(outcome.get("revenue")) > 0
        if isinstance(raw, bool):
            return raw
        # Normalize truthy strings/numbers explicitly so a future
        # caller passing "true"/"yes"/1 doesn't mis-bucket.
        if isinstance(raw, str):
            return raw.strip().lower() in {"true", "yes", "ok", "success", "1"}
        return bool(raw)

    def record_outcome(self, decision_id: str, engine: str, outcome: dict[str, Any]) -> bool:
        """Record the real outcome of a decision — thread-safe.

        Returns True iff a matching decision was found AND updated.
        Defensive against non-dict outcome values.
        """
        if not _valid_engine_name(engine):
            logger.warning("OutcomeTracker.record_outcome: invalid engine name %r", engine)
            return False
        if not isinstance(decision_id, str) or not decision_id:
            return False
        if not isinstance(outcome, dict):
            logger.warning(
                "OutcomeTracker.record_outcome: outcome for %s/%s is "
                "%s, not a dict — wrapping",
                engine, decision_id, type(outcome).__name__,
            )
            outcome = {"raw": str(outcome)[:500]}

        success_flag = self._normalize_success(outcome)
        with self._lock:
            entries = self._load_unlocked(engine)
            for entry in reversed(entries):
                if entry.get("decision_id") == decision_id:
                    entry["outcome"] = outcome
                    entry["outcome_timestamp"] = time.time()
                    entry["success"] = success_flag
                    self._save_unlocked(engine, entries)
                    return True
        return False

    def get_winning_patterns(self, engine: str, min_success: int = 1) -> dict[str, Any]:
        """Analyze outcomes with correlation check — only learn REAL patterns."""
        if not _valid_engine_name(engine):
            return {"engine": engine, "patterns": [], "data_points": 0, "error": "invalid_engine_name"}
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
        # Defensive: non-dict decision crashed ``.get()`` chain
        # below. Audit pass 52.
        if not isinstance(decision, dict):
            decision = {}
        patterns = self.get_winning_patterns(engine)
        score = safe_float(
            decision.get("total_score")
            or decision.get("score")
            or decision.get("opportunity_score")
            or 5
        )

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
        """Load without acquiring lock — caller must hold lock.

        On any load failure the corrupted file is moved aside
        as ``<path>.corrupted.<ts>`` before falling back to an
        empty list. Pre-audit the file was silently returned
        as empty and the next ``_save_unlocked`` call then
        overwrote it with the fresh data — destroying the
        engine's entire outcome history forever. Same data-
        loss bug pattern as pass 48 (feedback_store) and
        pass 20 (StoreSnapshot). Audit pass 52.
        """
        if not _valid_engine_name(engine):
            return []
        path = os.path.join(_OUTCOME_DIR, f"{engine}.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(
                    f"outcome file is {type(data).__name__}, expected list"
                )
            return data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            backup = f"{path}.corrupted.{int(time.time())}"
            try:
                os.replace(path, backup)
                logger.warning(
                    "Corrupted outcome file %s: %s — moved to %s",
                    path, exc, backup,
                )
            except OSError as move_exc:
                logger.warning(
                    "Corrupted outcome file %s: %s; backup failed (%s)",
                    path, exc, move_exc,
                )
            return []

    def _save(self, engine: str, entries: list[dict]) -> None:
        with self._lock:
            self._save_unlocked(engine, entries)

    def _save_unlocked(self, engine: str, entries: list[dict]) -> None:
        """Save without acquiring lock — caller must hold lock."""
        if not _valid_engine_name(engine):
            return
        path = os.path.join(_OUTCOME_DIR, f"{engine}.json")
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(entries, f)
            os.replace(tmp_path, path)  # Atomic on POSIX
        except OSError as exc:
            logger.error("Failed to save outcomes for %s: %s", engine, exc)
            # Clean up half-written tmp so we don't leak it.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError as exc:
                logger.debug("outcome tracker tmp file cleanup failed: %s", exc)
