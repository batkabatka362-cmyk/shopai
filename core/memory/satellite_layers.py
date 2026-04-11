"""Satellite memory layers — vector, graph, and signal stores.

Wave 2 #4 in-place improvement. The existing
:class:`UnifiedMemory` multiplexes five legacy backends keyed
by role (shared / brain / experience / cache / persistent).
That's the right primary store: it survives restarts, has
well-understood semantics, and already backs every decision
loop. What it lacks is the side-channels newer subsystems
need:

* **Vector search** for semantic retrieval ("what did we
  learn last month that rhymes with *this* question?")
* **Graph traversal** for relationship queries ("which
  campaigns are linked to which product families and which
  outcomes?")
* **Signal time-series** for rolling metrics ("what's the
  7-day moving average of checkout-latency alerts?")

This module adds three *satellite* layers that sit alongside
the primary store, not instead of it. Each layer has:

1. An **optional backend upgrade** (``sqlite-vec`` / ``networkx``
   / ``duckdb``). When available, the layer uses it.
2. A **pure-Python fallback** so the layers always work. The
   fallback is slower but semantically equivalent for small
   datasets — enough for ShopAI's working set.
3. A **no-op guard**: if the layer is explicitly disabled
   (``enabled=False``) it short-circuits every method so unit
   tests and minimal deployments don't have to reason about
   storage.

The layers are pure in-process (no network, no daemon). They
can be instantiated directly by :class:`UnifiedMemory` or by
anything else that wants semantic / graph / time-series
access without pulling a full DB dependency.

Integration with Wave 2 #3 (``core.memory.quality_engine``):
:meth:`route_record` takes a classified :class:`MemoryRecord`
and dispatches it to the satellite(s) that match its class —
KNOWLEDGE → vector + graph, ERROR → vector + graph,
SIGNAL → signal, NOISE → nothing (noise is deliberately
dropped from satellites to keep semantic search clean).
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.memory.quality_engine import MemoryClass, MemoryRecord
from utils.logger import get_logger

logger = get_logger("memory.satellites")


# ---------------------------------------------------------------------------
# Tokeniser (shared by vector fallback + graph entity extraction)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenise(text: str) -> list[str]:
    """Lowercase word tokens, stripped of punctuation."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _flatten_text(content: Any) -> str:
    """Flatten arbitrary content into a single searchable string.

    Strings stay as-is. Dicts/lists are joined with spaces (keys
    and values alike) so the tokeniser sees every leaf string.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, dict):
        parts: list[str] = []
        for k, v in content.items():
            parts.append(str(k))
            parts.append(_flatten_text(v))
        return " ".join(parts)
    if isinstance(content, (list, tuple, set)):
        return " ".join(_flatten_text(x) for x in content)
    return str(content)


# ---------------------------------------------------------------------------
# VectorLayer — semantic similarity
# ---------------------------------------------------------------------------


@dataclass
class _VectorEntry:
    record_id: str
    text: str
    tokens: dict[str, float]   # tf-idf-style, but just tf for simplicity
    norm: float
    payload: dict[str, Any]
    created_at: float


class VectorLayer:
    """Semantic-similarity satellite.

    Backend priority:

    1. ``sqlite-vec`` — if importable, a SQLite file is used
       with the vec extension loaded. Not implemented in the
       fallback path yet; we keep the hook so future wiring
       doesn't change the public API.
    2. Pure-Python bag-of-words — default. A dict of token
       frequencies per record, cosine similarity at query
       time. ``O(n * avg_tokens)`` per query, fine for ShopAI's
       working set.

    Every record is stored with its flattened text, its token
    bag, and the caller-provided payload so query results can
    return the original content.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._lock = threading.RLock()
        self._entries: dict[str, _VectorEntry] = {}
        self._backend: str = "memory"
        self._try_upgrade_backend()

    def _try_upgrade_backend(self) -> None:
        """Attempt to swap in sqlite-vec if installed.

        Currently a placeholder — we log the detection so
        operators can see the upgrade path works, but the
        actual sqlite-vec wire-up lands in a follow-up
        because it needs a real embedding model to be
        worthwhile. The in-memory bag-of-words fallback
        keeps identical semantics for tests.
        """
        try:
            import sqlite_vec  # noqa: F401
            self._backend = "sqlite-vec-available"
            logger.info("VectorLayer: sqlite-vec detected (using in-memory fallback)")
        except ImportError:
            self._backend = "memory"

    def add(
        self,
        record_id: str,
        content: Any,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Index a record for semantic retrieval."""
        if not self.enabled:
            return
        text = _flatten_text(content)
        tokens = _tokenise(text)
        if not tokens:
            return
        bag: dict[str, float] = {}
        for t in tokens:
            bag[t] = bag.get(t, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in bag.values()))
        with self._lock:
            self._entries[record_id] = _VectorEntry(
                record_id=record_id,
                text=text,
                tokens=bag,
                norm=norm,
                payload=dict(payload or {}),
                created_at=time.time(),
            )

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float = 0.0,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Cosine-similarity query against stored records.

        Returns up to *k* ``(record_id, score, payload)`` tuples
        sorted by score descending. Ties broken by insertion
        order (older first) for deterministic ranking.
        """
        if not self.enabled:
            return []
        q_tokens = _tokenise(query)
        if not q_tokens:
            return []
        q_bag: dict[str, float] = {}
        for t in q_tokens:
            q_bag[t] = q_bag.get(t, 0.0) + 1.0
        q_norm = math.sqrt(sum(v * v for v in q_bag.values()))
        if q_norm == 0:
            return []
        scored: list[tuple[float, float, str, dict[str, Any]]] = []
        with self._lock:
            for entry in self._entries.values():
                if entry.norm == 0:
                    continue
                # cosine = dot / (|a| * |b|)
                dot = 0.0
                # iterate smaller bag for speed
                if len(q_bag) < len(entry.tokens):
                    for t, w in q_bag.items():
                        dot += w * entry.tokens.get(t, 0.0)
                else:
                    for t, w in entry.tokens.items():
                        dot += w * q_bag.get(t, 0.0)
                score = dot / (q_norm * entry.norm)
                if score >= min_score:
                    scored.append((-score, entry.created_at, entry.record_id, entry.payload))
        scored.sort()
        return [(rid, -neg, pl) for neg, _, rid, pl in scored[:k]]

    def remove(self, record_id: str) -> bool:
        """Drop a record; return True if it existed."""
        with self._lock:
            return self._entries.pop(record_id, None) is not None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend":     self._backend,
                "enabled":     self.enabled,
                "total":       len(self._entries),
            }


# ---------------------------------------------------------------------------
# GraphLayer — relationship queries
# ---------------------------------------------------------------------------


class GraphLayer:
    """Relationship-graph satellite.

    Backend priority:

    1. ``networkx`` — if importable, wraps a ``DiGraph`` so
       callers get full graph algorithms (shortest path,
       centrality, etc.) for free.
    2. Pure-Python adjacency dict — default. Nodes map to
       attribute dicts; edges are stored as
       ``(src, dst) -> rel_attrs``. BFS for shortest path,
       neighbours returned by lookup.

    The API is the same either way; callers that need raw
    networkx features can call :meth:`backend` to get the
    underlying graph object.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._lock = threading.RLock()
        # Fallback storage
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[tuple[str, str], dict[str, Any]] = {}
        self._adj: dict[str, set[str]] = defaultdict(set)
        self._rev_adj: dict[str, set[str]] = defaultdict(set)
        self._nx = None
        self._backend = "memory"
        self._try_upgrade_backend()

    def _try_upgrade_backend(self) -> None:
        try:
            import networkx as nx  # type: ignore
            self._nx = nx.DiGraph()
            self._backend = "networkx"
            logger.info("GraphLayer: networkx backend loaded")
        except ImportError:
            self._backend = "memory"

    def add_entity(
        self,
        entity_id: str,
        *,
        kind: str = "entity",
        attrs: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        data = {"kind": kind, **(attrs or {})}
        with self._lock:
            self._nodes[entity_id] = data
            if self._nx is not None:
                self._nx.add_node(entity_id, **data)

    def add_relation(
        self,
        from_id: str,
        to_id: str,
        *,
        rel_type: str = "related",
        attrs: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            # Auto-create missing endpoints so callers don't
            # need a separate add_entity for every mention.
            if from_id not in self._nodes:
                self._nodes[from_id] = {"kind": "entity"}
            if to_id not in self._nodes:
                self._nodes[to_id] = {"kind": "entity"}
            edge_data = {"rel_type": rel_type, **(attrs or {})}
            self._edges[(from_id, to_id)] = edge_data
            self._adj[from_id].add(to_id)
            self._rev_adj[to_id].add(from_id)
            if self._nx is not None:
                self._nx.add_node(from_id, **self._nodes[from_id])
                self._nx.add_node(to_id, **self._nodes[to_id])
                self._nx.add_edge(from_id, to_id, **edge_data)

    def neighbors(
        self,
        entity_id: str,
        *,
        direction: str = "out",
    ) -> list[str]:
        """Return neighbouring entity ids.

        *direction* ``"out"`` returns successors, ``"in"``
        returns predecessors, ``"both"`` returns the union.
        """
        with self._lock:
            if direction == "out":
                return sorted(self._adj.get(entity_id, set()))
            if direction == "in":
                return sorted(self._rev_adj.get(entity_id, set()))
            if direction == "both":
                return sorted(
                    self._adj.get(entity_id, set())
                    | self._rev_adj.get(entity_id, set())
                )
            raise ValueError(f"unknown direction: {direction!r}")

    def shortest_path(
        self,
        from_id: str,
        to_id: str,
        *,
        max_depth: int = 6,
    ) -> list[str] | None:
        """BFS shortest path between two entities.

        Returns the node sequence including both endpoints,
        or ``None`` if no path exists within *max_depth* hops.
        """
        with self._lock:
            if from_id not in self._nodes or to_id not in self._nodes:
                return None
            if from_id == to_id:
                return [from_id]
            # BFS
            visited: set[str] = {from_id}
            queue: deque[tuple[str, list[str]]] = deque([(from_id, [from_id])])
            while queue:
                node, path = queue.popleft()
                if len(path) > max_depth:
                    continue
                for nxt in self._adj.get(node, set()):
                    if nxt in visited:
                        continue
                    new_path = path + [nxt]
                    if nxt == to_id:
                        return new_path
                    visited.add(nxt)
                    queue.append((nxt, new_path))
            return None

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            attrs = self._nodes.get(entity_id)
            return dict(attrs) if attrs is not None else None

    def get_relation(
        self, from_id: str, to_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            rel = self._edges.get((from_id, to_id))
            return dict(rel) if rel is not None else None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend":  self._backend,
                "enabled":  self.enabled,
                "nodes":    len(self._nodes),
                "edges":    len(self._edges),
            }

    def backend(self) -> Any:
        """Return the underlying backend object (``networkx.DiGraph``
        when available, else the fallback ``self``)."""
        return self._nx if self._nx is not None else self


# ---------------------------------------------------------------------------
# SignalLayer — time-series metrics
# ---------------------------------------------------------------------------


@dataclass
class _SignalPoint:
    metric: str
    value: float
    tags: dict[str, str]
    ts: float


class SignalLayer:
    """Append-only time-series satellite.

    Backend priority:

    1. ``duckdb`` — if importable, a single-file in-memory
       connection handles the rolling-window queries. (Wired
       up in a follow-up; the in-memory fallback stays the
       authoritative path for unit tests.)
    2. Pure-Python append list capped at *max_points* — default.
       Query paths iterate in reverse so the common
       "last-N-minutes" case is fast.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_points: int = 100_000,
    ) -> None:
        self.enabled = enabled
        self._lock = threading.RLock()
        self._points: deque[_SignalPoint] = deque(maxlen=max_points)
        self._backend = "memory"
        self._try_upgrade_backend()

    def _try_upgrade_backend(self) -> None:
        try:
            import duckdb  # noqa: F401
            self._backend = "duckdb-available"
            logger.info("SignalLayer: duckdb detected (using in-memory fallback)")
        except ImportError:
            self._backend = "memory"

    def record(
        self,
        metric: str,
        value: float,
        *,
        tags: dict[str, str] | None = None,
        ts: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._points.append(_SignalPoint(
                metric=metric,
                value=float(value),
                tags=dict(tags or {}),
                ts=ts if ts is not None else time.time(),
            ))

    def query(
        self,
        metric: str,
        *,
        since: float | None = None,
        tags: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[_SignalPoint]:
        """Return matching points in chronological order.

        ``since`` is a unix timestamp; points older than it
        are skipped. ``tags`` filters by exact tag match
        (all provided tags must match). ``limit`` caps the
        oldest-first result count.
        """
        if not self.enabled:
            return []
        with self._lock:
            out: list[_SignalPoint] = []
            for p in self._points:
                if p.metric != metric:
                    continue
                if since is not None and p.ts < since:
                    continue
                if tags:
                    if any(p.tags.get(k) != v for k, v in tags.items()):
                        continue
                out.append(p)
            if limit is not None:
                out = out[-limit:]
            return out

    def aggregate(
        self,
        metric: str,
        *,
        since: float | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict[str, float]:
        """Return ``{count, sum, min, max, mean}`` for a window."""
        pts = self.query(metric, since=since, tags=tags)
        if not pts:
            return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
        vals = [p.value for p in pts]
        total = sum(vals)
        return {
            "count": float(len(vals)),
            "sum":   total,
            "min":   min(vals),
            "max":   max(vals),
            "mean":  total / len(vals),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend":  self._backend,
                "enabled":  self.enabled,
                "points":   len(self._points),
                "capacity": self._points.maxlen,
            }


# ---------------------------------------------------------------------------
# Router — quality-class → satellite dispatch
# ---------------------------------------------------------------------------


# Class → which satellites receive a record.
_CLASS_ROUTING: dict[MemoryClass, tuple[str, ...]] = {
    MemoryClass.KNOWLEDGE: ("vector", "graph"),
    MemoryClass.ERROR:     ("vector", "graph"),
    MemoryClass.SIGNAL:    ("signal",),
    MemoryClass.NOISE:     (),
}


@dataclass
class SatelliteRouter:
    """Wire a :class:`MemoryRecord` through the satellite layers.

    Owns one instance of each layer and exposes a single
    :meth:`route_record` method that inspects the record's
    class and dispatches to the matching satellite(s).

    The router is deliberately lightweight so it can be owned
    directly by :class:`UnifiedMemory` without adding a new
    indirection layer. Callers that want raw satellite access
    can reach in via ``router.vector``, ``router.graph``,
    ``router.signal``.
    """

    vector: VectorLayer = field(default_factory=VectorLayer)
    graph:  GraphLayer  = field(default_factory=GraphLayer)
    signal: SignalLayer = field(default_factory=SignalLayer)

    def route_record(
        self,
        record: MemoryRecord,
        *,
        record_id: str | None = None,
        memory_class: MemoryClass,
        content: Any = None,
        entities: Iterable[str] | None = None,
        signal_name: str | None = None,
        signal_value: float | None = None,
    ) -> dict[str, Any]:
        """Dispatch a classified record to the matching satellites.

        Parameters
        ----------
        record :
            The canonical :class:`MemoryRecord` — used to derive
            an id (``kind:created_at``) when *record_id* is
            omitted and to stash metadata in the satellite
            payload.
        record_id :
            Explicit id; defaults to ``"<kind>:<created_at>"``.
        memory_class :
            Classification decided upstream (via
            :func:`core.memory.quality_engine.classify`).
        content :
            Semantic content to index. Falls back to
            ``record.payload`` when omitted.
        entities :
            Optional iterable of entity ids the record
            references. The first two are linked as
            ``entities[0] → entities[1] → ...`` in the graph
            so downstream queries can walk from one to another.
        signal_name, signal_value :
            Required for ``SIGNAL`` class records — the metric
            name and numeric value to append to the time-series.

        Returns
        -------
        dict :
            ``{"routed_to": [...], "record_id": ...}`` so
            callers can audit which satellites received the
            write (useful for UnifiedMemory tests).
        """
        rid = record_id or f"{record.kind}:{record.created_at}"
        targets = _CLASS_ROUTING.get(memory_class, ())
        routed: list[str] = []

        if "vector" in targets:
            self.vector.add(
                rid,
                content if content is not None else record.payload,
                payload={
                    "kind":         record.kind,
                    "class":        memory_class.value,
                    "quality":      record.quality,
                    "confidence":   record.confidence,
                    "created_at":   record.created_at,
                },
            )
            routed.append("vector")

        if "graph" in targets:
            ents = list(entities or ())
            # The record itself is a node so searches can hop
            # from an entity back to the memory that mentions it.
            self.graph.add_entity(
                rid,
                kind=f"memory:{record.kind}",
                attrs={
                    "class":      memory_class.value,
                    "created_at": record.created_at,
                },
            )
            for e in ents:
                self.graph.add_entity(e, kind="entity")
                self.graph.add_relation(
                    rid, e, rel_type="mentions",
                )
            # Chain consecutive entities so the caller can walk
            # from the first mention to the last.
            for a, b in zip(ents, ents[1:]):
                self.graph.add_relation(a, b, rel_type="co_mentioned")
            routed.append("graph")

        if "signal" in targets:
            if signal_name is None or signal_value is None:
                logger.debug(
                    "SatelliteRouter: SIGNAL record %r skipped signal "
                    "layer (name/value missing)", rid,
                )
            else:
                self.signal.record(
                    signal_name, signal_value,
                    tags={"kind": record.kind, "class": memory_class.value},
                    ts=record.created_at,
                )
                routed.append("signal")

        return {"record_id": rid, "routed_to": routed}

    def stats(self) -> dict[str, Any]:
        return {
            "vector": self.vector.stats(),
            "graph":  self.graph.stats(),
            "signal": self.signal.stats(),
        }


__all__ = [
    "VectorLayer",
    "GraphLayer",
    "SignalLayer",
    "SatelliteRouter",
]
