"""Surprise contextualizer — build explanation bundle on surprise.

``surprise`` detects that an outcome deviated from prediction. That
is only useful if the brain can immediately ask: *why was this
surprising, and what do we compare it to?* Without that bundle,
surprise events stay abstract and learning never starts.

When a surprise fires, `SurpriseContextualizer` assembles:

  • expected       — what prediction + source
  • observed       — what actually happened
  • delta          — numerical surprise magnitude
  • situation      — canonical descriptors at the time
  • similar_past   — up to N past surprises with similar situation
  • candidate_causes — list of already-known hypotheses touching
                      this KPI
  • first_action   — recommended investigation step

The bundle is a ``ContextBundle`` dataclass the caller can log to
self_narrative, vault, or decision_rationale_builder. Pure stdlib.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable

from utils.logger import get_logger


logger = get_logger("brain.surprise_contextualizer")


_DEFAULT_HISTORY = 200
_DEFAULT_MATCH_LIMIT = 3


@dataclass
class SurpriseEvent:
    id: str
    kpi: str
    expected: float
    observed: float
    situation: dict[str, Any]
    ts: float

    @property
    def delta(self) -> float:
        return self.observed - self.expected

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kpi": self.kpi,
            "expected": round(self.expected, 4),
            "observed": round(self.observed, 4),
            "delta": round(self.delta, 4),
            "situation": dict(self.situation),
            "ts": self.ts,
        }


@dataclass
class ContextBundle:
    event_id: str
    kpi: str
    expected: float
    observed: float
    delta: float
    situation: dict[str, Any]
    similar_past: list[dict[str, Any]]
    candidate_causes: list[str]
    first_action: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kpi": self.kpi,
            "expected": round(self.expected, 4),
            "observed": round(self.observed, 4),
            "delta": round(self.delta, 4),
            "situation": dict(self.situation),
            "similar_past": list(self.similar_past),
            "candidate_causes": list(self.candidate_causes),
            "first_action": self.first_action,
            "ts": self.ts,
        }


def _jaccard(
    a: dict[str, Any], b: dict[str, Any],
) -> float:
    keys_a = {f"{k}={v}" for k, v in a.items()}
    keys_b = {f"{k}={v}" for k, v in b.items()}
    if not keys_a and not keys_b:
        return 0.0
    return len(keys_a & keys_b) / max(1, len(keys_a | keys_b))


class SurpriseContextualizer:
    def __init__(
        self,
        *,
        history_size: int = _DEFAULT_HISTORY,
        match_limit: int = _DEFAULT_MATCH_LIMIT,
    ) -> None:
        if history_size < 10:
            raise ValueError("history_size must be ≥ 10")
        if match_limit < 1:
            raise ValueError("match_limit must be ≥ 1")
        self._lock = threading.Lock()
        self._events: Deque[SurpriseEvent] = deque(
            maxlen=int(history_size),
        )
        self._match_limit = int(match_limit)
        # kpi → [candidate_cause_hypotheses]
        self._cause_hints: dict[str, list[str]] = {}

    # ── Configure causes ─────────────────────────────────

    def register_cause_hint(
        self, kpi: str, hypothesis: str,
    ) -> None:
        if not kpi or not hypothesis:
            raise ValueError("kpi and hypothesis required")
        with self._lock:
            self._cause_hints.setdefault(kpi, []).append(
                hypothesis,
            )

    # ── Intake ───────────────────────────────────────────

    def contextualise(
        self,
        *,
        kpi: str,
        expected: float,
        observed: float,
        situation: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> ContextBundle:
        if not kpi:
            raise ValueError("kpi required")
        timestamp = float(ts if ts is not None else time.time())
        event = SurpriseEvent(
            id=uuid.uuid4().hex,
            kpi=str(kpi),
            expected=float(expected),
            observed=float(observed),
            situation=dict(situation or {}),
            ts=timestamp,
        )
        with self._lock:
            self._events.append(event)
            past = list(self._events)[:-1]   # exclude current
            causes = list(
                self._cause_hints.get(event.kpi, ()),
            )
        # Find similar past events on same KPI
        matched = [
            (p, _jaccard(event.situation, p.situation))
            for p in past if p.kpi == event.kpi
        ]
        matched.sort(key=lambda pair: -pair[1])
        top_past = [
            p.as_dict() for p, sim in matched[: self._match_limit]
            if sim > 0.0
        ]
        direction = "above" if event.delta > 0 else "below"
        first_action = (
            f"inspect {event.kpi} logs around {int(event.ts)} "
            f"and compare against {len(top_past)} similar past "
            f"surprises (delta={direction})"
        )
        return ContextBundle(
            event_id=event.id,
            kpi=event.kpi,
            expected=event.expected,
            observed=event.observed,
            delta=event.delta,
            situation=event.situation,
            similar_past=top_past,
            candidate_causes=causes,
            first_action=first_action,
            ts=event.ts,
        )

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[SurpriseEvent]:
        with self._lock:
            events = list(self._events)
        events.sort(key=lambda e: -e.ts)
        return events[: max(1, int(limit))]

    def by_kpi(self, kpi: str) -> list[SurpriseEvent]:
        with self._lock:
            return [e for e in self._events if e.kpi == kpi]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_kpi: dict[str, int] = {}
            for e in self._events:
                by_kpi[e.kpi] = by_kpi.get(e.kpi, 0) + 1
            return {
                "buffered": len(self._events),
                "kpis": sorted(by_kpi.keys()),
                "by_kpi_count": by_kpi,
                "registered_cause_hints": {
                    k: len(v)
                    for k, v in self._cause_hints.items()
                },
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._events)
            self._events.clear()
            self._cause_hints.clear()
        return n
