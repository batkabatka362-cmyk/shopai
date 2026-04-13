"""EpisodicMemory — persistent decision memory across sessions.

Remembers "last time we did X in condition Y, outcome was Z."
Unlike OutcomeTracker (in-memory, max 1000), EpisodicMemory:
  - Persists to disk (survives restarts)
  - Stores full context fingerprint (financial + inventory + customer state)
  - Enables retrieval by similarity ("in similar conditions, what happened?")
  - Extracts lessons from failures
  - Feeds into JudgmentAdvisor and FailureContextPrevention
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("memory.episodic")

try:
    from core.memory.storage_config import get_path
    _EPISODES_DIR = get_path("episodes")
except Exception:
    _EPISODES_DIR = "/tmp/shopai_episodes"


def _context_fingerprint(context: dict[str, Any]) -> str:
    """Create a fingerprint from context for similarity matching.

    Buckets continuous values into discrete categories for matching.
    """
    health = context.get("health_grade", "?")
    churn_bucket = "low" if context.get("churn_pct", 0) < 20 else "medium" if context.get("churn_pct", 0) < 50 else "high"
    inventory_risk = "ok" if not context.get("stockout_risk", False) else "risk"
    confidence_bucket = "low" if context.get("confidence_score", 0) < 40 else "medium" if context.get("confidence_score", 0) < 70 else "high"
    margin_bucket = "negative" if context.get("net_margin", 0) < 0 else "low" if context.get("net_margin", 0) < 15 else "healthy"

    fingerprint_str = f"{health}|{churn_bucket}|{inventory_risk}|{confidence_bucket}|{margin_bucket}"
    return hashlib.md5(fingerprint_str.encode()).hexdigest()[:12]


class EpisodicMemory:
    """Persistent episodic memory for decision history.

    Usage:
        memory = EpisodicMemory()
        memory.record_episode(
            decision_type="pricing",
            action="increase_price",
            context={"health_grade": "B", "churn_pct": 15, ...},
            outcome={"success": True, "revenue_change": 0.12},
        )

        # Later:
        similar = memory.recall_similar(current_context)
        lessons = memory.get_lessons("pricing")
        failures = memory.get_failures()
    """

    def __init__(self, episodes_dir: str | None = None) -> None:
        self._dir = episodes_dir or _EPISODES_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.RLock()
        self._episodes: list[dict[str, Any]] = []
        self._load()

    def record_episode(
        self,
        decision_type: str,
        action: str,
        context: dict[str, Any],
        outcome: dict[str, Any],
        goal: str = "",
        confidence_score: float = 0,
    ) -> str:
        """Record a complete decision episode."""
        with self._lock:
            episode_id = f"ep_{int(time.time())}_{len(self._episodes)}"
            fingerprint = _context_fingerprint(context)
            success = outcome.get("success", False)

            episode = {
                "episode_id": episode_id,
                "timestamp": time.time(),
                "decision_type": decision_type,
                "action": action,
                "goal": goal,
                "confidence_score": confidence_score,
                "context": context,
                "context_fingerprint": fingerprint,
                "outcome": outcome,
                "success": success,
                "lesson": self._extract_lesson(decision_type, action, context, outcome, success),
            }

            self._episodes.append(episode)
            self._persist()
            logger.info(
                "Episode recorded: %s (%s) — %s",
                decision_type, "success" if success else "failure", episode_id,
            )
            return episode_id

    def recall_similar(self, current_context: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
        """Find episodes with similar context fingerprints."""
        target_fp = _context_fingerprint(current_context)

        with self._lock:
            # Exact fingerprint matches
            exact = [e for e in self._episodes if e["context_fingerprint"] == target_fp]
            if len(exact) >= limit:
                return sorted(exact, key=lambda e: e["timestamp"], reverse=True)[:limit]

            # Partial matching: compare individual context factors
            scored = []
            for ep in self._episodes:
                score = self._similarity_score(current_context, ep["context"])
                if score > 0.4:  # At least 40% similar
                    scored.append((score, ep))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [ep for _, ep in scored[:limit]]

    def get_lessons(self, decision_type: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get extracted lessons from past episodes."""
        with self._lock:
            episodes = self._episodes
            if decision_type:
                episodes = [e for e in episodes if e["decision_type"] == decision_type]

            lessons = [
                {
                    "episode_id": e["episode_id"],
                    "decision_type": e["decision_type"],
                    "action": e["action"],
                    "success": e["success"],
                    "lesson": e["lesson"],
                    "timestamp": e["timestamp"],
                }
                for e in episodes if e.get("lesson")
            ]
            return lessons[-limit:]

    def get_failures(self, decision_type: str | None = None, max_age_days: int = 180) -> list[dict[str, Any]]:
        """Get past failures, optionally filtered by type and age."""
        cutoff = time.time() - (max_age_days * 86400)
        with self._lock:
            failures = [
                e for e in self._episodes
                if not e["success"]
                and e["timestamp"] > cutoff
                and (decision_type is None or e["decision_type"] == decision_type)
            ]
            return failures

    def get_success_rate(self, decision_type: str | None = None) -> dict[str, Any]:
        """Get success rate statistics."""
        with self._lock:
            episodes = self._episodes
            if decision_type:
                episodes = [e for e in episodes if e["decision_type"] == decision_type]

            if not episodes:
                return {"total": 0, "success_rate": 0, "sample_size": 0}

            successes = sum(1 for e in episodes if e["success"])
            return {
                "total": len(episodes),
                "successes": successes,
                "failures": len(episodes) - successes,
                "success_rate": round(successes / len(episodes) * 100, 1),
                "sample_size": len(episodes),
            }

    def get_stats(self) -> dict[str, Any]:
        """Get episodic memory statistics."""
        with self._lock:
            if not self._episodes:
                return {"total_episodes": 0}

            by_type: dict[str, int] = {}
            for e in self._episodes:
                by_type[e["decision_type"]] = by_type.get(e["decision_type"], 0) + 1

            return {
                "total_episodes": len(self._episodes),
                "by_type": by_type,
                "oldest": self._episodes[0]["timestamp"] if self._episodes else None,
                "newest": self._episodes[-1]["timestamp"] if self._episodes else None,
                "overall_success_rate": self.get_success_rate()["success_rate"],
            }

    def _similarity_score(self, ctx_a: dict[str, Any], ctx_b: dict[str, Any]) -> float:
        """Calculate similarity between two contexts (0-1)."""
        factors = [
            ("health_grade", 0.25),
            ("churn_pct", 0.20),
            ("stockout_risk", 0.20),
            ("confidence_score", 0.15),
            ("net_margin", 0.20),
        ]
        score = 0
        for factor, weight in factors:
            a_val = ctx_a.get(factor)
            b_val = ctx_b.get(factor)
            if a_val is None or b_val is None:
                continue
            if isinstance(a_val, bool):
                score += weight * (1.0 if a_val == b_val else 0.0)
            elif isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
                max_val = max(abs(a_val), abs(b_val), 1)
                diff = abs(a_val - b_val) / max_val
                score += weight * max(0, 1 - diff)
            elif a_val == b_val:
                score += weight
        return round(score, 3)

    def _extract_lesson(
        self, decision_type: str, action: str,
        context: dict[str, Any], outcome: dict[str, Any],
        success: bool,
    ) -> str:
        """Extract a human-readable lesson from this episode."""
        health = context.get("health_grade", "?")
        churn = context.get("churn_pct", 0)
        confidence = context.get("confidence_score", 0)

        if success:
            return (
                f"{decision_type}/{action} succeeded with health={health}, "
                f"churn={churn}%, confidence={confidence}"
            )
        else:
            return (
                f"{decision_type}/{action} FAILED with health={health}, "
                f"churn={churn}%, confidence={confidence}. "
                f"Avoid similar conditions."
            )

    def _persist(self) -> None:
        """Save episodes to disk."""
        try:
            if len(self._episodes) > 5000:
                self._episodes = self._episodes[-5000:]

            path = os.path.join(self._dir, "episodes.json")
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._episodes, f, default=str)
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning("Failed to persist episodes: %s", exc)

    def _load(self) -> None:
        """Load episodes from disk."""
        path = os.path.join(self._dir, "episodes.json")
        try:
            if os.path.exists(path):
                with open(path) as f:
                    self._episodes = json.load(f)
                logger.info("Episodic memory loaded: %d episodes", len(self._episodes))
        except Exception as exc:
            logger.warning("Failed to load episodes: %s", exc)
            self._episodes = []
