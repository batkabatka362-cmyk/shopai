"""Working memory — bounded attention scratchpad per cycle.

Long-term memory (MemoryIntelligence) holds everything; the brain
can't hold everything at once. Humans keep ~7 chunks in focus;
ShopAI should similarly constrain its per-cycle *attention budget*
so the decision chain isn't flooded with 2000 stale events.

Working memory is the cycle-scoped scratchpad:

  Inputs this cycle   (order events, competitor moves, owner pings)
  Salient long-term   (rules retrieved for this decision)
  Active hypotheses   (pending predictions due to resolve)
  Open goals          (top-priority agenda items)
  Draft outputs       (the brain's in-flight plans + decisions)

A salience score ranks every entry; only the top ``capacity``
(default 7) stay in focus. Lower-ranked items spill back to
long-term — nothing is lost, just de-prioritised for this pass.

Salience formula:
    urgency(0-3) × 0.4 + recency(decay) × 0.3
    + owner_relevance(boolean) × 0.2 + score(0-5) × 0.1

Usage:
    wm = working_memory()
    wm.push(kind="order", content={...}, score=4.2)
    wm.push(kind="rule", content={...}, owner_relevant=True)
    focus = wm.focus(capacity=7)
    # hand `focus` to the reasoner / planner / debate
    wm.reset()    # end-of-cycle cleanup

Thread-safe (RLock). Per-cycle; NOT persisted across restarts by
design — working memory is inherently transient.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any


_DEFAULT_CAPACITY = 7
_RECENCY_HALF_LIFE_S = 300.0        # 5 minutes — short for a cycle


@dataclass
class Entry:
    id: int
    kind: str
    content: Any
    pushed_at: float = field(default_factory=time.time)
    urgency: int = 0                      # 0-3
    score: float = 0.0                    # 0-5
    owner_relevant: bool = False
    tags: tuple[str, ...] = ()

    def recency(self, now: float | None = None) -> float:
        now = now or time.time()
        age_s = max(0.0, now - self.pushed_at)
        return math.exp(-age_s / _RECENCY_HALF_LIFE_S)

    def salience(self, now: float | None = None) -> float:
        # 0-1 scale roughly — urgency is max 3, score max 5
        u = self.urgency / 3.0
        r = self.recency(now)
        o = 1.0 if self.owner_relevant else 0.0
        s = self.score / 5.0
        return 0.4 * u + 0.3 * r + 0.2 * o + 0.1 * s

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "content": self.content,
            "urgency": self.urgency,
            "score": round(self.score, 2),
            "owner_relevant": self.owner_relevant,
            "tags": list(self.tags),
            "salience": round(self.salience(), 3),
            "recency": round(self.recency(), 3),
        }


class WorkingMemory:
    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._capacity = int(capacity)
        self._entries: list[Entry] = []
        self._next_id = 1
        self._lock = threading.RLock()

    # ── Writing ─────────────────────────────────────────────

    def push(
        self,
        kind: str,
        content: Any,
        *,
        urgency: int = 0,
        score: float = 0.0,
        owner_relevant: bool = False,
        tags: tuple[str, ...] | list[str] = (),
    ) -> int:
        with self._lock:
            eid = self._next_id
            self._next_id += 1
            self._entries.append(Entry(
                id=eid,
                kind=kind,
                content=content,
                urgency=max(0, min(3, int(urgency))),
                score=max(0.0, min(5.0, float(score))),
                owner_relevant=bool(owner_relevant),
                tags=tuple(tags),
            ))
            return eid

    # ── Reading ─────────────────────────────────────────────

    def focus(
        self,
        capacity: int | None = None,
        kinds: tuple[str, ...] | list[str] | None = None,
    ) -> list[Entry]:
        """Return the top-salience slice. Optionally filter to named
        kinds (e.g. ``kinds=("order","rule")``)."""
        cap = int(capacity) if capacity is not None else self._capacity
        with self._lock:
            now = time.time()
            pool = self._entries[:]
        if kinds:
            wanted = set(kinds)
            pool = [e for e in pool if e.kind in wanted]
        pool.sort(key=lambda e: -e.salience(now))
        return pool[:cap]

    def all(self) -> list[Entry]:
        with self._lock:
            return list(self._entries)

    def snapshot(self) -> dict[str, Any]:
        """Introspection: summary of what's in focus vs spilled."""
        with self._lock:
            items = list(self._entries)
        now = time.time()
        items.sort(key=lambda e: -e.salience(now))
        in_focus = items[:self._capacity]
        spilled = items[self._capacity:]
        return {
            "capacity": self._capacity,
            "total": len(items),
            "in_focus_ids": [e.id for e in in_focus],
            "spilled_ids": [e.id for e in spilled],
            "kinds": sorted({e.kind for e in items}),
        }

    # ── Housekeeping ───────────────────────────────────────

    def reset(self) -> int:
        """End-of-cycle: drop everything. Returns number cleared."""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    def drop_older_than(self, seconds: float) -> int:
        """Evict entries older than ``seconds``. Returns number dropped."""
        now = time.time()
        with self._lock:
            kept = [e for e in self._entries
                    if (now - e.pushed_at) <= seconds]
            n = len(self._entries) - len(kept)
            self._entries = kept
            return n

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# ── Singleton ────────────────────────────────────────────────

_WM_LOCK = threading.Lock()
_WM: WorkingMemory | None = None


def working_memory() -> WorkingMemory:
    global _WM
    if _WM is None:
        with _WM_LOCK:
            if _WM is None:
                _WM = WorkingMemory()
    return _WM
