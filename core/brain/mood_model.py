"""Mood model — brain's internal affective state.

Humans act differently when stressed vs confident. A tired brain
shouldn't be making high-stakes bets; a flowing brain shouldn't be
over-cautious. The mood model tracks two state variables:

  • stress       — 0..1, rises with errors/surprises/overbudget
  • confidence   — 0..1, rises with wins, falls with contradicts/
                   drift alerts

These combine into a *temperature* that callers can use to modulate
exploration/exploitation (high temperature = more exploration;
low = more conservative). The model is a simple leaky integrator:
each observation nudges state, and unaffected state decays toward
a neutral baseline.

Pure stdlib, deterministic. Complements `meta_reasoner` (quality)
and `compute_budget` (cost) by tracking *affect*.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.mood_model")


Event = Literal[
    "error", "surprise", "contradict", "overbudget",
    "win", "confirm", "praise", "criticise",
    "flat",
]

_EVENT_STRESS = {
    "error": +0.25,
    "surprise": +0.10,
    "contradict": +0.20,
    "overbudget": +0.30,
    "criticise": +0.15,
    "win": -0.15,
    "confirm": -0.05,
    "praise": -0.10,
    "flat": 0.0,
}

_EVENT_CONFIDENCE = {
    "win": +0.20,
    "confirm": +0.10,
    "praise": +0.15,
    "flat": 0.0,
    "error": -0.15,
    "surprise": -0.05,
    "contradict": -0.20,
    "overbudget": -0.10,
    "criticise": -0.20,
}

_BASELINE_STRESS = 0.2
_BASELINE_CONFIDENCE = 0.6


@dataclass
class MoodSnapshot:
    stress: float
    confidence: float
    temperature: float
    label: str
    n_events: int
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "stress": round(self.stress, 4),
            "confidence": round(self.confidence, 4),
            "temperature": round(self.temperature, 4),
            "label": self.label,
            "n_events": self.n_events,
            "ts": self.ts,
        }


def _classify(stress: float, confidence: float) -> str:
    if stress > 0.7 and confidence < 0.4:
        return "overwhelmed"
    if stress > 0.6:
        return "stressed"
    if confidence > 0.75 and stress < 0.4:
        return "flow"
    if confidence > 0.6:
        return "confident"
    if confidence < 0.3:
        return "uncertain"
    return "balanced"


class MoodModel:
    def __init__(
        self,
        *,
        decay_per_second: float = 0.01,
        clamp_floor: float = 0.0,
        clamp_ceil: float = 1.0,
    ) -> None:
        if not 0.0 <= decay_per_second <= 1.0:
            raise ValueError(
                "decay_per_second must be in [0, 1]",
            )
        self._lock = threading.Lock()
        self._decay = float(decay_per_second)
        self._floor = float(clamp_floor)
        self._ceil = float(clamp_ceil)
        self._stress = _BASELINE_STRESS
        self._confidence = _BASELINE_CONFIDENCE
        self._last_update = time.time()
        self._n_events = 0

    def _decay_step(self, now: float) -> None:
        elapsed = now - self._last_update
        if elapsed <= 0:
            # Synthetic or out-of-order timestamp — move anchor
            # forward to avoid decaying against a real-time baseline.
            self._last_update = now
            return
        pull = min(1.0, self._decay * elapsed)
        self._stress += (
            (_BASELINE_STRESS - self._stress) * pull
        )
        self._confidence += (
            (_BASELINE_CONFIDENCE - self._confidence) * pull
        )
        self._last_update = now

    def _clamp(self, v: float) -> float:
        return max(self._floor, min(self._ceil, v))

    # ── Intake ───────────────────────────────────────────

    def observe(
        self,
        event: Event,
        *,
        weight: float = 1.0,
        ts: float | None = None,
    ) -> MoodSnapshot:
        if event not in _EVENT_STRESS:
            raise ValueError(
                f"event must be one of {list(_EVENT_STRESS)}",
            )
        if weight < 0:
            raise ValueError("weight must be ≥ 0")
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            self._decay_step(timestamp)
            self._stress = self._clamp(
                self._stress
                + _EVENT_STRESS[event] * float(weight),
            )
            self._confidence = self._clamp(
                self._confidence
                + _EVENT_CONFIDENCE[event] * float(weight),
            )
            self._n_events += 1
            return self._snapshot_locked(timestamp)

    def _snapshot_locked(self, now: float) -> MoodSnapshot:
        temperature = max(
            0.0,
            0.5 * (1.0 - self._confidence) + 0.5 * self._stress,
        )
        return MoodSnapshot(
            stress=self._stress,
            confidence=self._confidence,
            temperature=temperature,
            label=_classify(self._stress, self._confidence),
            n_events=self._n_events,
            ts=now,
        )

    # ── Queries ──────────────────────────────────────────

    def snapshot(
        self, *, now: float | None = None,
    ) -> MoodSnapshot:
        at = float(now if now is not None else time.time())
        with self._lock:
            self._decay_step(at)
            return self._snapshot_locked(at)

    def temperature(
        self, *, now: float | None = None,
    ) -> float:
        return self.snapshot(now=now).temperature

    def is_stressed(
        self,
        *,
        threshold: float = 0.6,
        now: float | None = None,
    ) -> bool:
        return self.snapshot(now=now).stress >= threshold

    def is_confident(
        self,
        *,
        threshold: float = 0.75,
        now: float | None = None,
    ) -> bool:
        return self.snapshot(now=now).confidence >= threshold

    def stats(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "n_events": snap.n_events,
            "label": snap.label,
            "temperature": round(snap.temperature, 4),
        }

    def reset(self) -> int:
        with self._lock:
            n = self._n_events
            self._stress = _BASELINE_STRESS
            self._confidence = _BASELINE_CONFIDENCE
            self._n_events = 0
            self._last_update = time.time()
        return n
