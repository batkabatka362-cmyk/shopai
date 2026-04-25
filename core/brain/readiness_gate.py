"""Readiness gate — act now, or gather more evidence first?

feasibility_gate asks "can we?" and action_safety_guard asks "is it
safe?". Readiness asks a distinct question: *do we have enough
evidence right now, or should we wait?*

Inputs to a readiness check:

  • evidence_probability  — from evidence_accumulator (0..1)
  • evidence_gap          — how much posterior variance is left
  • knowledge_freshness   — freshness of the supporting facts (0..1)
  • mood_temperature      — from mood_model (higher = take riskier)
  • urgency               — external pressure 0..3

The gate combines these into a ``ReadinessDecision`` with verdict:

  • ``go``          — evidence + freshness comfortable; act
  • ``gather``      — evidence gap too wide; seek more data first
  • ``warm_up``     — freshness too low; refresh supporting facts
  • ``stand_down``  — contradictory evidence; don't act at all

Pure stdlib, deterministic. LLM-free.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from utils.logger import get_logger


logger = get_logger("brain.readiness_gate")


Verdict = Literal["go", "gather", "warm_up", "stand_down"]


@dataclass
class ReadinessInput:
    evidence_probability: float   # 0..1
    evidence_gap: float            # 0..1 (higher = less data)
    knowledge_freshness: float     # 0..1
    mood_temperature: float = 0.3  # 0..1
    urgency: int = 0               # 0..3

    def __post_init__(self) -> None:
        for name, val, lo, hi in (
            ("evidence_probability",
             self.evidence_probability, 0.0, 1.0),
            ("evidence_gap", self.evidence_gap, 0.0, 1.0),
            ("knowledge_freshness",
             self.knowledge_freshness, 0.0, 1.0),
            ("mood_temperature",
             self.mood_temperature, 0.0, 1.0),
        ):
            if not lo <= val <= hi:
                raise ValueError(
                    f"{name} must be in [{lo}, {hi}]",
                )
        if self.urgency < 0:
            raise ValueError("urgency must be ≥ 0")


@dataclass
class ReadinessDecision:
    verdict: Verdict
    score: float                 # composite readiness 0..1
    reason: str
    recommended_wait_s: float    # 0 if go/stand_down
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": round(self.score, 4),
            "reason": self.reason,
            "recommended_wait_s": round(
                self.recommended_wait_s, 1,
            ),
            "ts": self.ts,
        }


@dataclass
class ReadinessThresholds:
    min_probability: float = 0.5
    max_gap: float = 0.35
    min_freshness: float = 0.5
    stand_down_probability: float = 0.25

    def __post_init__(self) -> None:
        for name, val in (
            ("min_probability", self.min_probability),
            ("max_gap", self.max_gap),
            ("min_freshness", self.min_freshness),
            ("stand_down_probability",
             self.stand_down_probability),
        ):
            if not 0.0 <= val <= 1.0:
                raise ValueError(
                    f"{name} must be in [0, 1]",
                )


class ReadinessGate:
    def __init__(
        self,
        *,
        thresholds: ReadinessThresholds | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._thresholds = thresholds or ReadinessThresholds()
        self._history: list[ReadinessDecision] = []

    def thresholds(self) -> ReadinessThresholds:
        with self._lock:
            return self._thresholds

    def set_thresholds(
        self, thresholds: ReadinessThresholds,
    ) -> None:
        with self._lock:
            self._thresholds = thresholds

    # ── Check ────────────────────────────────────────────

    def check(
        self, inp: ReadinessInput,
    ) -> ReadinessDecision:
        t = self.thresholds()
        # Composite score
        score = (
            0.45 * inp.evidence_probability
            + 0.20 * (1.0 - inp.evidence_gap)
            + 0.25 * inp.knowledge_freshness
            + 0.10 * inp.mood_temperature
        )
        # Urgency lowers the effective thresholds slightly
        urgency_relax = min(0.2, 0.05 * inp.urgency)
        min_prob = max(0.0, t.min_probability - urgency_relax)
        max_gap = min(1.0, t.max_gap + urgency_relax)
        min_fresh = max(0.0, t.min_freshness - urgency_relax)
        # Verdicts
        if inp.evidence_probability <= t.stand_down_probability:
            verdict: Verdict = "stand_down"
            reason = (
                f"evidence_probability "
                f"{inp.evidence_probability:.2f} "
                f"≤ stand-down {t.stand_down_probability:.2f}"
            )
            wait = 0.0
        elif inp.knowledge_freshness < min_fresh:
            verdict = "warm_up"
            reason = (
                f"freshness {inp.knowledge_freshness:.2f} "
                f"< floor {min_fresh:.2f}; refresh first"
            )
            wait = max(
                60.0,
                3600.0 * (
                    min_fresh - inp.knowledge_freshness
                ),
            )
        elif (
            inp.evidence_gap > max_gap
            or inp.evidence_probability < min_prob
        ):
            verdict = "gather"
            reason = (
                f"gap {inp.evidence_gap:.2f} > "
                f"{max_gap:.2f} or probability "
                f"{inp.evidence_probability:.2f} < "
                f"{min_prob:.2f} — gather data"
            )
            wait = max(
                300.0,
                3600.0 * max(
                    0.0, inp.evidence_gap - max_gap,
                ),
            )
        else:
            verdict = "go"
            reason = (
                f"score {score:.2f} with gap "
                f"{inp.evidence_gap:.2f} and freshness "
                f"{inp.knowledge_freshness:.2f}"
            )
            wait = 0.0
        decision = ReadinessDecision(
            verdict=verdict,
            score=score,
            reason=reason,
            recommended_wait_s=wait,
            ts=time.time(),
        )
        with self._lock:
            self._history.append(decision)
            if len(self._history) > 200:
                del self._history[: len(self._history) - 200]
        return decision

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[ReadinessDecision]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for d in self._history:
                counts[d.verdict] = counts.get(d.verdict, 0) + 1
            return {
                "total": len(self._history),
                "by_verdict": counts,
                "thresholds": {
                    "min_probability":
                        self._thresholds.min_probability,
                    "max_gap": self._thresholds.max_gap,
                    "min_freshness":
                        self._thresholds.min_freshness,
                    "stand_down_probability":
                        self._thresholds.stand_down_probability,
                },
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
