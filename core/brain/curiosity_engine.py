"""Curiosity engine — turn prediction errors into investigation tasks.

Outcome-driven learning only fires when an action is taken and its
result measured. Curiosity fires *before* any action: a
high-prediction-error observation is intrinsically valuable to study,
because it implies the world_model is wrong in a way that could hurt
future decisions.

Flow:

    curiosity.note(
        observation_id="ord_83291",
        predicted=0.6,
        actual=0.95,
        context={"niche": "audio", "price": 29},
    )

Prediction error = |predicted − actual|. Every note is scored and
placed on a priority queue keyed by error magnitude. The ``next_probe()``
call returns the highest-error un-investigated item so the daemon can
pull it into the hypothesis engine.

Two knobs keep the queue useful:
  • dedup  — identical context only enqueued once (higher error replaces)
  • decay  — old items lose priority so we don't investigate history

Pure stdlib. In-memory — no SQLite. The daemon will hand items to the
persistent hypothesis engine for durable tracking.
"""
from __future__ import annotations

import heapq
import itertools
import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class CuriosityItem:
    id: str
    predicted: float
    actual: float
    context: dict[str, Any]
    ts: float
    note: str = ""

    @property
    def error(self) -> float:
        return abs(self.actual - self.predicted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "predicted": round(self.predicted, 4),
            "actual": round(self.actual, 4),
            "error": round(self.error, 4),
            "context": self.context,
            "ts": self.ts,
            "note": self.note,
        }


def _context_signature(ctx: dict[str, Any]) -> str:
    return json.dumps(ctx or {}, sort_keys=True, default=str)


class CuriosityEngine:
    """Priority queue of unexplained observations, keyed by error.

    Thread-safety: not required — callers typically produce and
    consume from the daemon loop. If concurrent use is needed later,
    wrap a threading.Lock around ``note``/``next_probe``.
    """

    def __init__(
        self,
        *,
        min_error: float = 0.1,
        half_life_s: float = 86_400.0,
        max_items: int = 500,
    ) -> None:
        if min_error <= 0 or half_life_s <= 0 or max_items <= 0:
            raise ValueError("all thresholds must be positive")
        self._min_error = float(min_error)
        self._half_life_s = float(half_life_s)
        self._max_items = int(max_items)
        self._heap: list[tuple[float, int, str]] = []
        self._items: dict[str, CuriosityItem] = {}
        self._by_signature: dict[str, str] = {}   # signature → id
        self._done: set[str] = set()
        self._counter = itertools.count()

    # ── Intake ────────────────────────────────────────────

    def note(
        self,
        observation_id: str,
        predicted: float,
        actual: float,
        context: dict[str, Any] | None = None,
        note: str = "",
    ) -> CuriosityItem | None:
        """Submit an observation. Returns the stored item when it was
        worth keeping, None if below ``min_error`` or deduped-away."""
        if not observation_id:
            raise ValueError("observation_id required")
        item = CuriosityItem(
            id=observation_id,
            predicted=float(predicted),
            actual=float(actual),
            context=dict(context or {}),
            ts=time.time(),
            note=note,
        )
        if item.error < self._min_error:
            return None

        sig = _context_signature(item.context)
        prior_id = self._by_signature.get(sig)
        if prior_id is not None and prior_id in self._items:
            prior = self._items[prior_id]
            if prior.error >= item.error:
                return None
            # Higher error replaces the prior: mark old as done so
            # it's skipped on pop; the new item goes on the heap.
            self._done.add(prior_id)

        self._items[item.id] = item
        self._by_signature[sig] = item.id
        # Max-heap via negated priority.
        priority = -item.error
        heapq.heappush(self._heap, (priority, next(self._counter), item.id))
        self._enforce_cap()
        return item

    def _enforce_cap(self) -> None:
        # Keep only the top max_items active items. We lazily prune the
        # oldest (lowest-priority) when over cap.
        active = [
            x for x in self._heap
            if x[2] in self._items and x[2] not in self._done
        ]
        if len(active) <= self._max_items:
            return
        # Sort active by priority ascending (worst first), discard tail
        active.sort()
        drop = active[: len(active) - self._max_items]
        for _, _, item_id in drop:
            self._done.add(item_id)

    # ── Pop / iterate ─────────────────────────────────────

    def _recency_weight(self, ts: float, now: float) -> float:
        age = max(0.0, now - ts)
        return 0.5 ** (age / self._half_life_s)

    def next_probe(self) -> CuriosityItem | None:
        """Pop the next highest-priority item (error × recency)."""
        now = time.time()
        best: CuriosityItem | None = None
        best_score = -1.0
        # Re-score the whole heap once per call; small N (<500).
        for _, _, item_id in self._heap:
            if item_id in self._done:
                continue
            it = self._items.get(item_id)
            if it is None:
                continue
            score = it.error * self._recency_weight(it.ts, now)
            if score > best_score:
                best_score = score
                best = it
        if best is None:
            return None
        self._done.add(best.id)
        return best

    def peek(self, k: int = 5) -> list[CuriosityItem]:
        """Peek at top-k without marking them as investigated."""
        now = time.time()
        scored: list[tuple[float, CuriosityItem]] = []
        for item_id, it in self._items.items():
            if item_id in self._done:
                continue
            scored.append(
                (it.error * self._recency_weight(it.ts, now), it),
            )
        scored.sort(key=lambda pair: -pair[0])
        return [it for _, it in scored[:k]]

    def resolve(self, item_id: str) -> bool:
        """Explicitly mark an item as handled (without popping)."""
        if item_id not in self._items:
            return False
        self._done.add(item_id)
        return True

    def pending(self) -> int:
        return sum(
            1 for i in self._items
            if i not in self._done
        )

    def stats(self) -> dict[str, Any]:
        pending = self.pending()
        return {
            "pending": pending,
            "resolved": len(self._done),
            "total_noted": len(self._items),
            "max_error": round(
                max((self._items[i].error
                     for i in self._items if i not in self._done),
                    default=0.0),
                4,
            ),
        }
