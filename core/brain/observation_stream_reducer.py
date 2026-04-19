"""Observation stream reducer — raw events → situation summaries.

Every cycle the brain sees dozens of raw events (order webhooks,
price changes, ad metrics, competitor moves). The decision_stack
can't reason over hundreds of dicts; it wants a *situation* — a
small set of salient counts + averages + rates that captures *what
is happening right now*.

``ObservationStreamReducer`` ingests events tagged by kind and
reduces them along registered axes:

  • ``count(kind)``                 — how many in the window
  • ``rate_per_hour(kind)``         — events / hour
  • ``distinct(kind, field)``       — unique values seen
  • ``latest(kind, field)``         — most recent value

Reducers are registered at construction; new kinds can add new
reducers without touching the core. Output is a ``Situation`` dict
ready to feed attention_filter/decision_stack.

Pure stdlib, deterministic, LLM-free. Complements context_compactor
(which compacts for an LLM brief) by operating on raw event streams
earlier in the pipeline.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Iterable

from utils.logger import get_logger


logger = get_logger("brain.observation_stream_reducer")


_DEFAULT_WINDOW_S = 15 * 60


@dataclass
class EventRecord:
    kind: str
    fields: dict[str, Any]
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "fields": dict(self.fields),
            "ts": self.ts,
        }


@dataclass
class Situation:
    window_seconds: float
    event_counts: dict[str, int]
    rates_per_hour: dict[str, float]
    distinct_values: dict[str, int]  # key = "kind.field"
    latest_values: dict[str, Any]    # key = "kind.field"
    total_events: int
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_seconds": self.window_seconds,
            "event_counts": dict(self.event_counts),
            "rates_per_hour": {
                k: round(v, 4)
                for k, v in self.rates_per_hour.items()
            },
            "distinct_values": dict(self.distinct_values),
            "latest_values": dict(self.latest_values),
            "total_events": self.total_events,
            "ts": self.ts,
        }


@dataclass
class DistinctReducer:
    """Tracks distinct values for a (kind, field) pair."""
    kind: str
    field: str

    def key(self) -> str:
        return f"{self.kind}.{self.field}"


@dataclass
class LatestReducer:
    kind: str
    field: str

    def key(self) -> str:
        return f"{self.kind}.{self.field}"


class ObservationStreamReducer:
    def __init__(
        self,
        *,
        window_seconds: float = _DEFAULT_WINDOW_S,
        distinct_axes: Iterable[DistinctReducer] = (),
        latest_axes: Iterable[LatestReducer] = (),
        buffer_size: int = 5000,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if buffer_size < 10:
            raise ValueError("buffer_size must be ≥ 10")
        self._lock = threading.Lock()
        self._window = float(window_seconds)
        self._distinct = list(distinct_axes)
        self._latest = list(latest_axes)
        self._events: Deque[EventRecord] = deque(
            maxlen=int(buffer_size),
        )

    # ── Intake ───────────────────────────────────────────

    def ingest(
        self,
        kind: str,
        fields: dict[str, Any] | None = None,
        *,
        ts: float | None = None,
    ) -> EventRecord:
        if not kind:
            raise ValueError("kind required")
        timestamp = float(ts if ts is not None else time.time())
        rec = EventRecord(
            kind=str(kind),
            fields=dict(fields or {}),
            ts=timestamp,
        )
        with self._lock:
            self._events.append(rec)
        return rec

    def ingest_batch(
        self, events: Iterable[dict[str, Any]],
    ) -> int:
        n = 0
        for e in events:
            kind = e.get("kind")
            if not kind:
                continue
            self.ingest(
                kind=str(kind),
                fields=e.get("fields") or e,
                ts=e.get("ts"),
            )
            n += 1
        return n

    # ── Register axes ────────────────────────────────────

    def register_distinct(self, axis: DistinctReducer) -> None:
        with self._lock:
            self._distinct.append(axis)

    def register_latest(self, axis: LatestReducer) -> None:
        with self._lock:
            self._latest.append(axis)

    # ── Reduce ───────────────────────────────────────────

    def reduce(
        self, *, now: float | None = None,
    ) -> Situation:
        at = float(now if now is not None else time.time())
        cutoff = at - self._window
        with self._lock:
            recent = [
                e for e in self._events if e.ts >= cutoff
            ]
            distinct_axes = list(self._distinct)
            latest_axes = list(self._latest)
        counts: dict[str, int] = defaultdict(int)
        distinct_sets: dict[str, set[Any]] = defaultdict(set)
        latest_map: dict[str, tuple[float, Any]] = {}
        for ev in recent:
            counts[ev.kind] += 1
            for axis in distinct_axes:
                if axis.kind != ev.kind:
                    continue
                if axis.field in ev.fields:
                    distinct_sets[axis.key()].add(
                        _hashable(ev.fields[axis.field]),
                    )
            for axis in latest_axes:
                if axis.kind != ev.kind:
                    continue
                if axis.field in ev.fields:
                    key = axis.key()
                    prev = latest_map.get(key)
                    if prev is None or ev.ts >= prev[0]:
                        latest_map[key] = (
                            ev.ts, ev.fields[axis.field],
                        )
        hours = self._window / 3600.0
        rates = {
            k: (v / hours if hours > 0 else 0.0)
            for k, v in counts.items()
        }
        distinct = {
            k: len(v) for k, v in distinct_sets.items()
        }
        latest = {k: v for k, (_, v) in latest_map.items()}
        return Situation(
            window_seconds=self._window,
            event_counts=dict(counts),
            rates_per_hour=rates,
            distinct_values=distinct,
            latest_values=latest,
            total_events=len(recent),
            ts=at,
        )

    # ── Queries ──────────────────────────────────────────

    def buffered(self) -> int:
        with self._lock:
            return len(self._events)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "buffered_events": len(self._events),
                "window_seconds": self._window,
                "distinct_axes": [
                    d.key() for d in self._distinct
                ],
                "latest_axes": [
                    a.key() for a in self._latest
                ],
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._events)
            self._events.clear()
        return n


def _hashable(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted(
            (k, _hashable(vv)) for k, vv in v.items()
        ))
    try:
        hash(v)
        return v
    except TypeError:
        return str(v)
