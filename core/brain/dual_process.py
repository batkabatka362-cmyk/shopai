"""Dual-process arbiter — route decisions between fast and slow.

Kahneman's System 1 / System 2: fast pattern-match vs slow
deliberation. ShopAI already has both kinds of engines in the
codebase — cheap rule lookups, and expensive MCTS + debate — but
no layer *chooses* between them. Every decision was routed through
the same "think hard" path, wasting LLM calls on trivial choices
and rushing through high-stakes ones.

DualProcessArbiter decides per-request:

  • ``system1`` — direct rule match or nearest-neighbour memory
    retrieval. O(1), zero cost, sub-ms. Used when a confident
    precedent exists.
  • ``system2`` — MCTS planner + debate + counterfactual review.
    Expensive, slow, high-fidelity. Used when stakes are high or
    confidence is low.

Routing rule (deterministic):

    stakes     = cost_if_wrong_usd / cost_cap
    confidence = 1 - uncertainty(context)
    urgency    = 0..3 (from sentiment module or owner_urgent flag)

    if stakes > 0.5 OR confidence < 0.4:
        → system2
    elif urgency >= 2 AND stakes < 0.2:
        → system1           # must act fast; cheap call is fine
    elif confidence > 0.8:
        → system1           # we've seen this before, high certainty
    else:
        → system2           # default-safe

The arbiter itself is pure routing — no LLM, no DB. It wraps two
injectable callables (system1_fn, system2_fn) so the caller plugs
in whichever concrete engines apply.

Instrumentation: every call logs (route_taken, stakes, confidence,
latency) so metacognition can later detect routing drift ("we
shipped too many system1 decisions, accuracy dropped").
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from utils.logger import get_logger


logger = get_logger("brain.dual_process")


Route = Literal["system1", "system2"]


@dataclass
class Decision:
    route: Route
    answer: Any
    stakes: float
    confidence: float
    urgency: int
    latency_s: float
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "stakes": round(self.stakes, 3),
            "confidence": round(self.confidence, 3),
            "urgency": self.urgency,
            "latency_s": round(self.latency_s, 4),
            "rationale": self.rationale,
            "answer": self.answer,
        }


@dataclass
class RoutingStats:
    system1_count: int = 0
    system2_count: int = 0
    system1_latency_s: float = 0.0
    system2_latency_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        total = self.system1_count + self.system2_count
        s1_avg = self.system1_latency_s / max(1, self.system1_count)
        s2_avg = self.system2_latency_s / max(1, self.system2_count)
        return {
            "total": total,
            "system1_count": self.system1_count,
            "system2_count": self.system2_count,
            "system1_pct": round(self.system1_count / max(1, total), 3),
            "system2_pct": round(self.system2_count / max(1, total), 3),
            "system1_avg_latency_s": round(s1_avg, 4),
            "system2_avg_latency_s": round(s2_avg, 4),
        }


# ── Arbiter ─────────────────────────────────────────────────

class DualProcessArbiter:
    """Route requests between a fast-path callable and a slow-path
    callable. The routing is deterministic; the wrapped callables
    can be anything (rule lookups, MCTS planners, LLM prompts)."""

    def __init__(
        self,
        system1_fn: Callable[..., Any],
        system2_fn: Callable[..., Any],
        stakes_high: float = 0.5,
        confidence_low: float = 0.4,
        confidence_high: float = 0.8,
    ) -> None:
        self._s1 = system1_fn
        self._s2 = system2_fn
        self._stakes_high = stakes_high
        self._confidence_low = confidence_low
        self._confidence_high = confidence_high
        self._stats = RoutingStats()
        self._lock = threading.Lock()

    # ── Routing decision ────────────────────────────────────

    def route_for(
        self,
        *,
        stakes: float = 0.0,
        confidence: float = 0.5,
        urgency: int = 0,
    ) -> Route:
        stakes = max(0.0, min(1.0, float(stakes)))
        confidence = max(0.0, min(1.0, float(confidence)))
        urgency = max(0, min(3, int(urgency)))
        # High-stakes or low-confidence → always deliberate
        if stakes > self._stakes_high or confidence < self._confidence_low:
            return "system2"
        # Low-stakes AND urgent → fast path
        if urgency >= 2 and stakes < 0.2:
            return "system1"
        # Confident precedent → fast path
        if confidence > self._confidence_high:
            return "system1"
        # Default: deliberate
        return "system2"

    def rationale_for(
        self, route: Route, stakes: float,
        confidence: float, urgency: int,
    ) -> str:
        if route == "system2":
            if stakes > self._stakes_high:
                return f"high stakes ({stakes:.2f}) → deliberate"
            if confidence < self._confidence_low:
                return f"low confidence ({confidence:.2f}) → deliberate"
            return "default-safe → deliberate"
        # system1
        if urgency >= 2 and stakes < 0.2:
            return f"urgent ({urgency}) + cheap ({stakes:.2f}) → fast path"
        return f"high confidence ({confidence:.2f}) → fast path"

    # ── Execution ──────────────────────────────────────────

    def decide(
        self,
        *args: Any,
        stakes: float = 0.0,
        confidence: float = 0.5,
        urgency: int = 0,
        override: Route | None = None,
        **kwargs: Any,
    ) -> Decision:
        route: Route = override or self.route_for(
            stakes=stakes, confidence=confidence, urgency=urgency,
        )
        start = time.monotonic()
        try:
            if route == "system1":
                answer = self._s1(*args, **kwargs)
            else:
                answer = self._s2(*args, **kwargs)
        except Exception as exc:
            logger.warning("%s arm raised: %s", route, exc)
            # Fallback: try the other arm once.
            fallback = "system2" if route == "system1" else "system1"
            logger.debug("falling back to %s", fallback)
            try:
                answer = (self._s2 if fallback == "system2"
                          else self._s1)(*args, **kwargs)
                route = fallback
            except Exception as exc2:
                logger.warning("fallback %s also failed: %s",
                               fallback, exc2)
                raise
        latency = time.monotonic() - start
        self._record(route, latency)
        return Decision(
            route=route,
            answer=answer,
            stakes=stakes,
            confidence=confidence,
            urgency=urgency,
            latency_s=latency,
            rationale=self.rationale_for(
                route, stakes, confidence, urgency,
            ),
        )

    # ── Telemetry ──────────────────────────────────────────

    def _record(self, route: Route, latency_s: float) -> None:
        with self._lock:
            if route == "system1":
                self._stats.system1_count += 1
                self._stats.system1_latency_s += latency_s
            else:
                self._stats.system2_count += 1
                self._stats.system2_latency_s += latency_s

    def stats(self) -> RoutingStats:
        with self._lock:
            return RoutingStats(
                system1_count=self._stats.system1_count,
                system2_count=self._stats.system2_count,
                system1_latency_s=self._stats.system1_latency_s,
                system2_latency_s=self._stats.system2_latency_s,
            )

    def reset_stats(self) -> None:
        with self._lock:
            self._stats = RoutingStats()


# ── Confidence estimator (used by callers) ──────────────────

def confidence_from_precedents(
    n_matches: int,
    mean_outcome_score: float,
    variance: float = 0.0,
) -> float:
    """Cheap confidence proxy: many matches with high mean and low
    variance → high confidence. Clamped to [0, 1]."""
    if n_matches == 0:
        return 0.0
    sample_term = min(1.0, n_matches / 10.0)
    score_term = max(0.0, min(1.0, (mean_outcome_score - 2.0) / 3.0))
    variance_penalty = max(0.0, 1.0 - variance)
    return round(sample_term * 0.4 + score_term * 0.4
                  + variance_penalty * 0.2, 3)


def stakes_from_dollar_risk(
    cost_if_wrong_usd: float, cost_cap_usd: float = 100.0,
) -> float:
    """Linear clamp 0..1 with soft ceiling at cost_cap."""
    if cost_cap_usd <= 0:
        return 0.0
    return round(max(0.0, min(1.0, cost_if_wrong_usd / cost_cap_usd)), 3)
