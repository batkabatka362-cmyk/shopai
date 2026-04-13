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
import threading as _threading
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
        llm: Any = None,
        use_llm: bool = True,
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
        self._llm = llm
        self._use_llm = bool(use_llm)

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
          2. Roll: if random < epsilon → explore
                   else → exploit
          3. When exploring AND an LLM is available, ask the LLM to
             pick the best target out of the top candidates instead
             of just taking the statistical #1. The LLM gets the
             whole candidate list + current strengths so it can
             reason about expected payoff.
          4. If no candidates exist, fall back to exploit.
        """
        candidates = self.candidates(top_n=10)
        epsilon = self._adaptive_epsilon()
        roll = self._rng.random()

        if candidates and roll < epsilon:
            target = candidates[0]
            reason = (
                f"explore (roll={roll:.2f} < ε={epsilon:.2f}); "
                f"top candidate score={target.score:.2f}, "
                f"only {target.evidence_count} observation(s)"
            )

            # LLM picks among candidates if available
            llm_pick = self._llm_pick_target(candidates) if self._use_llm else None
            if llm_pick is not None:
                target_name = llm_pick.get("target") or target.name
                # If LLM picked a name we don't recognize, fall back
                target_obj = next(
                    (c for c in candidates if c.name == target_name), target,
                )
                reason = (
                    f"LLM-picked: {llm_pick.get('reason', '')} "
                    f"(payoff={llm_pick.get('expected_payoff', 'n/a')})"
                )[:200]
                target = target_obj

            return CuriosityRecommendation(
                action_kind="explore",
                target=target.name,
                reason=reason,
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

        Skips creation when an active goal already targets the same
        capability (prevents pile-ups across cycles). Returns the new
        goal ID, or None if no exploration was recommended / a
        duplicate exists / no GoalManager is wired.
        """
        rec = self.recommend()
        if rec.action_kind != "explore" or not rec.target:
            return None
        if self._goal_manager is None:
            return None

        # Dedup: skip when an active goal already targets this capability
        target_source = f"curiosity:{rec.target}"
        try:
            for goal in self._goal_manager.active():
                if not isinstance(goal, dict):
                    continue
                if goal.get("source") == target_source:
                    return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("goal dedup check failed: %s", exc)

        try:
            return self._goal_manager.propose(
                what=f"Explore unknown capability '{rec.target}'",
                why=rec.reason,
                source=target_source,
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

    # ── LLM target picker ─────────────────────────────────────

    def _llm_pick_target(
        self, candidates: list[CuriosityCandidate],
    ) -> Optional[dict[str, Any]]:
        """Ask the LLM which candidate is most worth exploring next.

        Returns the parsed LLM dict (with "target", "reason",
        "expected_payoff", "first_step" keys) or None on any
        failure / when the LLM is unavailable.
        """
        if not candidates:
            return None
        llm = self._get_llm()
        if llm is None:
            return None
        try:
            if not llm.is_available():
                return None
        except Exception:  # noqa: BLE001
            return None

        try:
            from core.system.prompt_library import get_prompt
        except Exception:  # noqa: BLE001
            return None
        template = get_prompt("curiosity.pick_target")
        if template is None:
            return None

        # Build compact JSON for the prompt
        try:
            import json
            cands_json = json.dumps([
                {"name": c.name, "novelty": round(c.novelty, 2),
                 "uncertainty": round(c.uncertainty, 2),
                 "evidence_count": c.evidence_count}
                for c in candidates[:10]
            ])
            strengths_json = "[]"
            if self._self_model is not None:
                try:
                    strengths = self._self_model.strengths(top_n=3)
                    strengths_json = json.dumps([
                        s.get("name") for s in strengths
                    ])
                except Exception as exc:  # noqa: BLE001
                    logger.debug("self-model strengths fetch failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.debug("curiosity prompt render failed: %s", exc)
            return None

        rendered = template.render(
            count=len(candidates),
            candidates_json=cands_json,
            strengths_json=strengths_json,
        )

        try:
            structured = llm.ask_structured(
                role=template.role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Curiosity LLM call failed: %s", exc)
            return None

        if not getattr(structured, "ok", False):
            return None
        data = structured.data or {}
        if not data.get("target"):
            return None
        return data

    def _get_llm(self) -> Any:
        """Lazily resolve the LLM adapter."""
        if self._llm is not None:
            return self._llm
        try:
            from core.system.llm_adapter import get_llm
            return get_llm()
        except Exception:  # noqa: BLE001
            return None


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[Curiosity] = None
_instance_lock = _threading.Lock()


def get_curiosity() -> Curiosity:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Curiosity()
    return _instance
