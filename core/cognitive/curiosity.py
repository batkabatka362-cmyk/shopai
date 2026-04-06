"""Curiosity — knowledge-gap-driven exploration.

Where SelfModel passively reports "I have low evidence for X" and
GoalManager creates one-shot exploration goals from those gaps,
Curiosity is the active drive: it scores how interesting each gap
is, decides whether to explore or exploit on this cycle, and feeds
the most promising target to the goal pipeline.

Curiosity score per topic combines:

    novelty       fewer observations = more interesting
    relevance     does this topic touch other known capabilities?
    uncertainty   how wide is our uncertainty about it?
    recency       time since we last looked

Exploration vs. exploitation: a multi-armed bandit style epsilon
controls the trade-off. By default we explore 20% of the time and
exploit (run known-good capabilities) 80%. The epsilon adapts:

    - High overall confidence in self-model → explore more (we
      already know what we're good at, so try new things)
    - Low overall confidence            → exploit more (master
      what we already know before branching out)
    - After every successful exploration → temporary boost in epsilon
    - After every failed exploration    → temporary drop

This is decoupled from the actual execution loop. Curiosity
produces *recommendations* (next_target, action_kind, reason);
the cognitive Mind decides what to do with them.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.curiosity")


# ── Tunables ──────────────────────────────────────────────────

# Default exploration probability when self-model is balanced
_BASE_EPSILON = 0.20

# Bonuses / penalties for the adaptive epsilon
_HIGH_CONF_BOOST = 0.10   # explore more when self-model is well-known
_LOW_CONF_PENALTY = 0.10  # explore less when self-model is uncertain
_EPSILON_FLOOR = 0.05
_EPSILON_CEILING = 0.45

# Curiosity score weights
_W_NOVELTY = 0.45
_W_UNCERTAINTY = 0.30
_W_RELEVANCE = 0.15
_W_RECENCY = 0.10

# A topic that hasn't been touched in this many seconds gets the
# full recency bonus. Tunable to adjust how aggressive curiosity is
# about old, mostly-forgotten capabilities.
_RECENCY_FULL_AGE_S = 7 * 86400


@dataclass
class CuriosityCandidate:
    """A topic the AI is curious about."""
    name: str
    novelty: float = 0.0          # 0-1
    uncertainty: float = 0.0      # 0-1
    relevance: float = 0.0        # 0-1
    recency: float = 0.0          # 0-1
    score: float = 0.0            # weighted combination, 0-1
    evidence_count: int = 0
    confidence: float = 0.0       # current SelfModel confidence
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "novelty": round(self.novelty, 3),
            "uncertainty": round(self.uncertainty, 3),
            "relevance": round(self.relevance, 3),
            "recency": round(self.recency, 3),
            "score": round(self.score, 3),
            "evidence_count": self.evidence_count,
            "confidence": round(self.confidence, 3),
            "notes": self.notes,
        }


@dataclass
class CuriosityRecommendation:
    """What Curiosity suggests doing next."""
    action_kind: str              # "explore" or "exploit"
    target: Optional[str] = None  # capability name or None
    reason: str = ""
    epsilon_used: float = 0.0
    candidates: list[CuriosityCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_kind": self.action_kind,
            "target": self.target,
            "reason": self.reason,
            "epsilon_used": round(self.epsilon_used, 3),
            "candidates": [c.to_dict() for c in self.candidates],
        }


class Curiosity:
    """The exploration drive. Reads SelfModel, recommends targets."""

    def __init__(
        self,
        *,
        self_model: Any = None,
        goal_manager: Any = None,
        epsilon: float = _BASE_EPSILON,
        max_epsilon: float = _EPSILON_CEILING,
        rng_seed: Optional[int] = None,
    ) -> None:
        self._self_model = self_model
        self._goal_manager = goal_manager
        # max_epsilon is the hard ceiling. Production callers should
        # leave this at the default to avoid runaway exploration; tests
        # may pass max_epsilon=1.0 to force deterministic explore paths.
        self._max_epsilon = max(_EPSILON_FLOOR, float(max_epsilon))
        self._base_epsilon = max(_EPSILON_FLOOR, min(self._max_epsilon, epsilon))
        self._rng = random.Random(rng_seed)
        self._exploration_outcomes: list[bool] = []  # last few results

    # ── Public API ─────────────────────────────────────────────

    def candidates(self, *, top_n: int = 10) -> list[CuriosityCandidate]:
        """Return ranked curiosity candidates from current SelfModel state.

        A candidate is any capability with non-zero novelty (not
        already saturated). Scored once and sorted high-to-low.
        """
        if self._self_model is None:
            return []
        try:
            caps = self._self_model.capabilities()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Curiosity: capabilities() failed: %s", exc)
            return []

        # Build a relevance index from prefix overlap. Capabilities
        # that share a prefix with many others are more relevant
        # because exploring them informs related ones.
        prefix_counts: dict[str, int] = {}
        for c in caps:
            name = c.get("name", "") if isinstance(c, dict) else ""
            if "." in name:
                prefix = name.split(".", 1)[0]
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

        max_prefix_count = max(prefix_counts.values()) if prefix_counts else 1
        now = time.time()

        scored: list[CuriosityCandidate] = []
        for c in caps:
            if not isinstance(c, dict):
                continue
            name = c.get("name", "")
            if not name:
                continue

            evidence = int(c.get("evidence_count", 0) or 0)
            confidence = float(c.get("confidence", 0.0) or 0.0)
            score_val = float(c.get("score", 0.5) or 0.5)
            last_updated = float(c.get("last_updated", now) or now)

            # ─── Novelty: 1 / (1 + evidence) → drops fast ───────
            # 0 obs → 1.0, 1 → 0.5, 4 → 0.2, 19 → 0.05
            novelty = 1.0 / (1.0 + evidence)

            # ─── Uncertainty: 1 - confidence ──────────────────
            uncertainty = max(0.0, 1.0 - confidence)

            # ─── Relevance: prefix popularity ─────────────────
            prefix = name.split(".", 1)[0] if "." in name else name
            prefix_pop = prefix_counts.get(prefix, 1)
            relevance = prefix_pop / max_prefix_count

            # ─── Recency: tanh(age / full_age) ────────────────
            age = max(0.0, now - last_updated)
            recency = math.tanh(age / _RECENCY_FULL_AGE_S)

            curiosity_score = (
                _W_NOVELTY * novelty
                + _W_UNCERTAINTY * uncertainty
                + _W_RELEVANCE * relevance
                + _W_RECENCY * recency
            )

            scored.append(CuriosityCandidate(
                name=name,
                novelty=novelty,
                uncertainty=uncertainty,
                relevance=relevance,
                recency=recency,
                score=curiosity_score,
                evidence_count=evidence,
                confidence=confidence,
                notes=(
                    f"score={score_val:.2f} prefix={prefix} "
                    f"prefix_pop={prefix_pop}"
                ),
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_n]

    def recommend(self) -> CuriosityRecommendation:
        """Decide whether to explore or exploit, and pick a target.

        Strategy:
          1. Compute the adaptive epsilon
          2. Roll: if random < epsilon → explore (return top candidate)
                   else → exploit (return None target with action=exploit)
          3. If no candidates exist, fall back to exploit
        """
        candidates = self.candidates(top_n=10)
        epsilon = self._adaptive_epsilon()
        roll = self._rng.random()

        if candidates and roll < epsilon:
            target = candidates[0]
            return CuriosityRecommendation(
                action_kind="explore",
                target=target.name,
                reason=(
                    f"explore (roll={roll:.2f} < ε={epsilon:.2f}); "
                    f"top candidate score={target.score:.2f}, "
                    f"only {target.evidence_count} observation(s)"
                ),
                epsilon_used=epsilon,
                candidates=candidates,
            )

        return CuriosityRecommendation(
            action_kind="exploit",
            target=None,
            reason=(
                f"exploit (roll={roll:.2f} ≥ ε={epsilon:.2f}); "
                f"{len(candidates)} candidate(s) waiting for next cycle"
            ),
            epsilon_used=epsilon,
            candidates=candidates,
        )

    def propose_exploration_goal(self) -> Optional[str]:
        """If the recommendation is to explore, create a goal for it.

        Returns the new goal ID, or None if no exploration was
        recommended (or no GoalManager is wired).
        """
        rec = self.recommend()
        if rec.action_kind != "explore" or not rec.target:
            return None
        if self._goal_manager is None:
            return None
        try:
            return self._goal_manager.propose(
                what=f"Explore unknown capability '{rec.target}'",
                why=rec.reason,
                source=f"curiosity:{rec.target}",
                impact=0.5,
                urgency=0.3,
                confidence=0.3,
                cost=0.3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Curiosity: goal propose failed: %s", exc)
            return None

    def record_exploration_outcome(self, success: bool) -> None:
        """Tell Curiosity whether the most recent exploration paid off.

        The outcome history (last 10) influences future epsilon: a
        run of failures lowers it (we're wasting attempts), a run of
        successes raises it (exploration is currently profitable).
        """
        self._exploration_outcomes.append(bool(success))
        if len(self._exploration_outcomes) > 10:
            self._exploration_outcomes = self._exploration_outcomes[-10:]

    # ── Internal ───────────────────────────────────────────────

    def _adaptive_epsilon(self) -> float:
        """Compute the actual exploration probability for this cycle.

        Starts at the base epsilon and shifts based on:
          - SelfModel average confidence (high → explore more)
          - Recent exploration outcome history (success → boost)
        """
        epsilon = self._base_epsilon

        # Self-model confidence shift
        avg_conf = self._average_confidence()
        if avg_conf >= 0.7:
            epsilon += _HIGH_CONF_BOOST
        elif avg_conf <= 0.3:
            epsilon -= _LOW_CONF_PENALTY

        # Outcome history shift
        if self._exploration_outcomes:
            recent = self._exploration_outcomes[-5:]
            success_rate = sum(recent) / len(recent)
            if success_rate >= 0.6:
                epsilon += 0.05
            elif success_rate <= 0.3:
                epsilon -= 0.05

        return max(_EPSILON_FLOOR, min(self._max_epsilon, epsilon))

    def _average_confidence(self) -> float:
        if self._self_model is None:
            return 0.5
        try:
            caps = self._self_model.capabilities()
        except Exception:  # noqa: BLE001
            return 0.5
        if not caps:
            return 0.5
        values = [
            float(c.get("confidence", 0.0) or 0.0)
            for c in caps if isinstance(c, dict)
        ]
        return sum(values) / len(values) if values else 0.5

    def base_epsilon(self) -> float:
        """Expose the configured base epsilon (for tests + dashboards)."""
        return self._base_epsilon


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[Curiosity] = None


def get_curiosity() -> Curiosity:
    global _instance
    if _instance is None:
        _instance = Curiosity()
    return _instance
