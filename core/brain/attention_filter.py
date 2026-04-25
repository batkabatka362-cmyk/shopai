"""Attention filter — cycle-level signal triage.

Every daemon cycle observes hundreds of events (orders, webhook hits,
metrics deltas). Reasoning on all of them is wasteful; reasoning on
none is dangerous. The attention filter ranks events by *salience*
and returns the top-K, so downstream modules (think, counter_argument,
hypothesis) only spend compute on items that matter.

Salience blends five signed signals:

  • recency    — decays with age (half-life configurable)
  • novelty    — against a rolling prototype (unseen kinds score high)
  • stakes     — caller-supplied value 0..1 (dollar at risk, SLA, etc.)
  • surprise   — |actual − expected| on a numeric field when provided
  • urgency    — explicit flag for owner-routed alerts

Each component is weighted; default weights are tuned for commerce
(stakes first, surprise second, urgency third). Callers can override.

Pure stdlib. In-memory rolling window. Deterministic given seed.
"""
from __future__ import annotations

import hashlib
import math
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class AttentionScore:
    event_id: str
    score: float
    components: dict[str, float]
    event: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "score": round(self.score, 4),
            "components": {
                k: round(v, 4) for k, v in self.components.items()
            },
            "event": self.event,
        }


DEFAULT_WEIGHTS = {
    "stakes":   0.35,
    "surprise": 0.25,
    "urgency":  0.20,
    "novelty":  0.15,
    "recency":  0.05,
}


class AttentionFilter:
    def __init__(
        self,
        *,
        half_life_s: float = 3600.0,
        novelty_window: int = 200,
        weights: dict[str, float] | None = None,
    ) -> None:
        if half_life_s <= 0:
            raise ValueError("half_life_s must be positive")
        if novelty_window <= 0:
            raise ValueError("novelty_window must be positive")
        self._half_life_s = float(half_life_s)
        self._novelty_window = int(novelty_window)
        self._kind_history: deque[str] = deque(maxlen=novelty_window)
        self._weights = dict(weights or DEFAULT_WEIGHTS)
        self._normalise_weights()

    def _normalise_weights(self) -> None:
        total = sum(self._weights.values())
        if total <= 0:
            self._weights = dict(DEFAULT_WEIGHTS)
            return
        for k in self._weights:
            self._weights[k] = self._weights[k] / total

    # ── Components ────────────────────────────────────────

    def _recency(self, ts: float, now: float) -> float:
        age = max(0.0, now - float(ts))
        return 0.5 ** (age / self._half_life_s)

    def _novelty(self, kind: str) -> float:
        if not self._kind_history:
            return 1.0
        counts = Counter(self._kind_history)
        seen = counts.get(kind, 0)
        # Laplace: unseen → 1.0, frequent → small
        return 1.0 / (1.0 + math.log1p(seen))

    def _stakes(self, event: dict[str, Any]) -> float:
        v = event.get("stakes")
        if v is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    def _surprise(self, event: dict[str, Any]) -> float:
        pred = event.get("predicted")
        actual = event.get("actual")
        if pred is None or actual is None:
            return 0.0
        try:
            diff = abs(float(actual) - float(pred))
        except (TypeError, ValueError):
            return 0.0
        # Saturating: diff 1.0 → 1.0, 0 → 0, monotone
        return max(0.0, min(1.0, diff))

    def _urgency(self, event: dict[str, Any]) -> float:
        if event.get("urgent"):
            return 1.0
        if event.get("owner_routed"):
            return 0.8
        return 0.0

    # ── Score ─────────────────────────────────────────────

    def score(
        self,
        event: dict[str, Any],
        *,
        now: float | None = None,
    ) -> AttentionScore:
        now = now if now is not None else time.time()
        kind = str(event.get("kind", "unknown"))
        eid = str(event.get("id")) if event.get("id") else (
            hashlib.sha1(repr(sorted(event.items())).encode()).hexdigest()[:12]
        )
        ts = float(event.get("ts", now))
        comps = {
            "recency":  self._recency(ts, now),
            "novelty":  self._novelty(kind),
            "stakes":   self._stakes(event),
            "surprise": self._surprise(event),
            "urgency":  self._urgency(event),
        }
        score = sum(comps[k] * self._weights.get(k, 0.0) for k in comps)
        return AttentionScore(
            event_id=eid, score=score,
            components=comps, event=dict(event),
        )

    def observe(self, kind: str) -> None:
        """Feed the novelty tracker a kind without scoring."""
        if kind:
            self._kind_history.append(str(kind))

    def top_k(
        self,
        events: Iterable[dict[str, Any]],
        *,
        k: int = 5,
        update_history: bool = True,
        now: float | None = None,
    ) -> list[AttentionScore]:
        """Rank events by salience; update novelty tracker after scoring
        so the first occurrence of a novel kind still gets the bonus.
        """
        events = list(events)
        now = now if now is not None else time.time()
        scored = [self.score(ev, now=now) for ev in events]
        if update_history:
            for ev in events:
                self.observe(str(ev.get("kind", "")))
        scored.sort(key=lambda s: -s.score)
        return scored[:k]

    def stats(self) -> dict[str, Any]:
        counts = Counter(self._kind_history)
        return {
            "weights": dict(self._weights),
            "novelty_window": self._novelty_window,
            "seen_kinds": len(counts),
            "most_common_kind": (
                counts.most_common(1)[0] if counts else None
            ),
        }
