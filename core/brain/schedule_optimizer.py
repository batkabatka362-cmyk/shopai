"""Schedule optimizer — best time to send per entity.

Email blasts at random times get ignored. Every customer and
every channel has an engagement pattern: Alice reads at 8am,
Bob at 10pm, /audio audience is night-skewed, /fashion is
lunchtime. Without an optimiser, every campaign ships at one
uniform time and leaves conversion on the table.

ScheduleOptimizer aggregates (entity_id, event_ts, outcome)
records into a per-entity × per-(hour, weekday) engagement
matrix. For any candidate send window it computes expected
engagement and recommends the top-K slots.

Outcome is a scalar — 1.0 for "opened", 0.5 for "clicked", 0
for "ignored"; caller chooses the scale.

APIs:

  record(entity_id, event_ts, outcome_score)
  best_slot(entity_id, horizon_hours=168)
      → (weekday, hour, expected_engagement)
  top_k_slots(entity_id, k=5)           → sorted list
  global_best_slot(candidates=None)      → cross-entity default
      for cold-start entities
  per_weekday_histogram(entity_id)       → 7 × 24 matrix

Laplace smoothing on the cell so new slots aren't zero by
default; confidence scales with observed samples. Pure stdlib.
"""
from __future__ import annotations

import datetime as dt
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


_ALPHA = 1.0       # Laplace smoothing prior
_MAX_HISTORY = 1000


@dataclass
class Slot:
    weekday: int                  # 0 = Monday
    hour: int
    score: float
    samples: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "weekday": self.weekday,
            "hour": self.hour,
            "score": round(self.score, 3),
            "samples": self.samples,
        }


# ── Optimiser ───────────────────────────────────────────────

class ScheduleOptimizer:
    def __init__(self) -> None:
        # {entity: {(weekday, hour): (sum, count)}}
        self._cells: dict[str, dict[tuple[int, int], list[float]]] = (
            defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
        )
        self._global: dict[tuple[int, int], list[float]] = defaultdict(
            lambda: [0.0, 0],
        )
        self._lock = threading.Lock()

    # ── Recording ──────────────────────────────────────────

    def record(
        self,
        entity_id: str,
        event_ts: float,
        outcome_score: float,
    ) -> None:
        entity_id = entity_id.strip()
        if not entity_id:
            return
        weekday, hour = _slot_of(event_ts)
        score = float(outcome_score)
        with self._lock:
            cell = self._cells[entity_id][(weekday, hour)]
            cell[0] += score
            cell[1] += 1
            gcell = self._global[(weekday, hour)]
            gcell[0] += score
            gcell[1] += 1

    # ── Query ──────────────────────────────────────────────

    def per_weekday_histogram(
        self, entity_id: str,
    ) -> list[list[float]]:
        """7 × 24 matrix of smoothed average scores."""
        with self._lock:
            cells = dict(self._cells.get(entity_id.strip(), {}))
        matrix = [[0.0] * 24 for _ in range(7)]
        for (w, h), (s, n) in cells.items():
            matrix[w][h] = (s + _ALPHA) / (n + _ALPHA * 2)
        return matrix

    def top_k_slots(
        self, entity_id: str, k: int = 5,
    ) -> list[Slot]:
        with self._lock:
            cells = dict(self._cells.get(entity_id.strip(), {}))
        scored: list[Slot] = []
        for (w, h), (s, n) in cells.items():
            if n == 0:
                continue
            mean = (s + _ALPHA) / (n + _ALPHA * 2)
            scored.append(Slot(
                weekday=w, hour=h, score=mean, samples=n,
            ))
        scored.sort(key=lambda sl: (-sl.score, -sl.samples))
        if scored:
            return scored[:k]
        # Cold start fallback — global
        return self._global_topk(k)

    def best_slot(self, entity_id: str) -> Slot | None:
        slots = self.top_k_slots(entity_id, k=1)
        return slots[0] if slots else None

    def global_best_slot(self) -> Slot | None:
        globs = self._global_topk(1)
        return globs[0] if globs else None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            entities = len(self._cells)
            total = sum(
                n for cells in self._cells.values()
                for (_, n) in cells.values()
            )
            global_total = sum(
                n for (_, n) in self._global.values()
            )
        return {
            "entities": entities,
            "total_observations": total,
            "global_observations": global_total,
        }

    # ── Internals ──────────────────────────────────────────

    def _global_topk(self, k: int) -> list[Slot]:
        with self._lock:
            cells = dict(self._global)
        out: list[Slot] = []
        for (w, h), (s, n) in cells.items():
            if n == 0:
                continue
            mean = (s + _ALPHA) / (n + _ALPHA * 2)
            out.append(Slot(
                weekday=w, hour=h, score=mean, samples=n,
            ))
        out.sort(key=lambda sl: (-sl.score, -sl.samples))
        return out[:k]


def _slot_of(ts: float) -> tuple[int, int]:
    d = dt.datetime.utcfromtimestamp(ts)
    return d.weekday(), d.hour
