"""Knowledge graph — typed triples + class hierarchy + inheritance.

ShopAI's memory stores events. Facts about the *world* — this SKU is a
product, that product is in the Audio category, Audio is a subcategory
of Electronics — belong in a graph, not an event log. knowledge_graph
is a tiny typed triple store optimised for the kinds of questions the
brain actually asks:

  • Is X a Y?               — ``is_a(subject, class)``
  • What X's are Y?         — ``instances_of(class)``
  • Does X have property P? — ``get(subject, predicate)``
  • Who links to X?         — ``predecessors(subject, predicate)``

Core concepts:

  • Triple = (subject, predicate, object) — object can be a literal
    or another subject id.
  • ``rdfs:subClassOf`` is a first-class predicate — transitively
    inherited by ``is_a()``.
  • ``inverse_of`` lets the caller declare that ``has_category`` is
    the inverse of ``is_category_of`` and the graph will answer
    queries from either side.

SQLite-persisted. Pure stdlib. Deterministic.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_SCHEMA = """
CREATE TABLE IF NOT EXISTS triples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject      TEXT NOT NULL,
    predicate    TEXT NOT NULL,
    object       TEXT NOT NULL,
    is_literal   INTEGER NOT NULL DEFAULT 0,
    confidence   REAL NOT NULL DEFAULT 1.0,
    source       TEXT NOT NULL DEFAULT '',
    UNIQUE(subject, predicate, object)
);
CREATE INDEX IF NOT EXISTS idx_tr_sp ON triples(subject, predicate);
CREATE INDEX IF NOT EXISTS idx_tr_po ON triples(predicate, object);
"""


RDF_TYPE = "rdf:type"
RDFS_SUBCLASS = "rdfs:subClassOf"


@dataclass
class Triple:
    subject: str
    predicate: str
    object: str
    is_literal: bool = False
    confidence: float = 1.0
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "is_literal": self.is_literal,
            "confidence": round(self.confidence, 4),
            "source": self.source,
        }


class KnowledgeGraph:
    def __init__(
        self, db_path: str | Path = "data/knowledge_graph.db",
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._inverse: dict[str, str] = {}
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Inverse predicate declaration ─────────────────────

    def declare_inverse(self, predicate: str, inverse: str) -> None:
        if not predicate or not inverse:
            raise ValueError("both predicate and inverse required")
        self._inverse[predicate] = inverse
        self._inverse[inverse] = predicate

    # ── Assert / retract ──────────────────────────────────

    def assert_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        is_literal: bool = False,
        confidence: float = 1.0,
        source: str = "",
    ) -> None:
        if not subject or not predicate or obj is None:
            raise ValueError("subject, predicate, object required")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO triples"
                "(subject, predicate, object, is_literal, confidence, source)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(subject), str(predicate), str(obj),
                    1 if is_literal else 0,
                    float(max(0.0, min(1.0, confidence))),
                    str(source),
                ),
            )
            self._conn.commit()

    def retract(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        obj: str | None = None,
    ) -> int:
        clauses: list[str] = []
        args: list[Any] = []
        if subject is not None:
            clauses.append("subject=?")
            args.append(subject)
        if predicate is not None:
            clauses.append("predicate=?")
            args.append(predicate)
        if obj is not None:
            clauses.append("object=?")
            args.append(obj)
        if not clauses:
            raise ValueError(
                "retract requires at least one of subject/predicate/object",
            )
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM triples WHERE " + " AND ".join(clauses),
                tuple(args),
            )
            n = int(cur.fetchone()[0])
            self._conn.execute(
                "DELETE FROM triples WHERE " + " AND ".join(clauses),
                tuple(args),
            )
            self._conn.commit()
        return n

    # ── Direct queries ────────────────────────────────────

    def get(
        self,
        subject: str,
        predicate: str | None = None,
    ) -> list[Triple]:
        q = (
            "SELECT subject, predicate, object, is_literal, "
            "confidence, source FROM triples WHERE subject=?"
        )
        args: list[Any] = [subject]
        if predicate is not None:
            q += " AND predicate=?"
            args.append(predicate)
        with self._lock:
            rows = self._conn.execute(q, tuple(args)).fetchall()
        out = [
            Triple(
                subject=r[0], predicate=r[1], object=r[2],
                is_literal=bool(r[3]), confidence=float(r[4]),
                source=r[5] or "",
            )
            for r in rows
        ]
        # Inverse-predicate read: for a queried predicate P, also pull
        # triples where the inverse was asserted in the other direction.
        if predicate and predicate in self._inverse:
            inv = self._inverse[predicate]
            with self._lock:
                rows = self._conn.execute(
                    "SELECT subject, predicate, object, is_literal, "
                    "confidence, source FROM triples "
                    "WHERE object=? AND predicate=?",
                    (subject, inv),
                ).fetchall()
            for r in rows:
                # Present it as if it were P(subject, r[0])
                out.append(Triple(
                    subject=subject,
                    predicate=predicate,
                    object=r[0],
                    is_literal=False,
                    confidence=float(r[4]),
                    source=r[5] or "",
                ))
        return out

    def predecessors(
        self, obj: str, predicate: str | None = None,
    ) -> list[Triple]:
        q = (
            "SELECT subject, predicate, object, is_literal, "
            "confidence, source FROM triples WHERE object=?"
        )
        args: list[Any] = [obj]
        if predicate is not None:
            q += " AND predicate=?"
            args.append(predicate)
        with self._lock:
            rows = self._conn.execute(q, tuple(args)).fetchall()
        return [
            Triple(
                subject=r[0], predicate=r[1], object=r[2],
                is_literal=bool(r[3]), confidence=float(r[4]),
                source=r[5] or "",
            )
            for r in rows
        ]

    # ── Class hierarchy reasoning ─────────────────────────

    def is_a(
        self,
        subject: str,
        target_class: str,
        *,
        max_depth: int = 10,
    ) -> bool:
        """True when subject has an ``rdf:type`` link that reaches
        ``target_class`` via transitive ``rdfs:subClassOf`` edges."""
        # Collect the subject's direct types
        types = [t.object for t in self.get(subject, RDF_TYPE)]
        if target_class in types:
            return True
        # Walk subclass ancestors
        frontier = list(types)
        seen: set[str] = set(types)
        depth = 0
        while frontier and depth < max_depth:
            next_frontier: list[str] = []
            for cls in frontier:
                parents = [
                    t.object for t in self.get(cls, RDFS_SUBCLASS)
                ]
                for p in parents:
                    if p == target_class:
                        return True
                    if p not in seen:
                        seen.add(p)
                        next_frontier.append(p)
            frontier = next_frontier
            depth += 1
        return False

    def instances_of(
        self,
        target_class: str,
        *,
        max_depth: int = 10,
    ) -> list[str]:
        """All subjects that are (directly or transitively) of
        ``target_class``."""
        classes = {target_class}
        # Walk subclass descendants
        frontier = [target_class]
        depth = 0
        while frontier and depth < max_depth:
            next_frontier: list[str] = []
            for cls in frontier:
                kids = [
                    t.subject for t in self.predecessors(cls, RDFS_SUBCLASS)
                ]
                for k in kids:
                    if k not in classes:
                        classes.add(k)
                        next_frontier.append(k)
            frontier = next_frontier
            depth += 1
        # Now collect all rdf:type edges pointing into any member of classes.
        out: set[str] = set()
        for cls in classes:
            for t in self.predecessors(cls, RDF_TYPE):
                out.add(t.subject)
        return sorted(out)

    def ancestors_of(
        self, cls: str, max_depth: int = 10,
    ) -> list[str]:
        """Transitive ancestor classes of ``cls``."""
        out: list[str] = []
        seen: set[str] = set()
        frontier = [cls]
        depth = 0
        while frontier and depth < max_depth:
            next_frontier: list[str] = []
            for c in frontier:
                parents = [
                    t.object for t in self.get(c, RDFS_SUBCLASS)
                ]
                for p in parents:
                    if p not in seen:
                        seen.add(p)
                        out.append(p)
                        next_frontier.append(p)
            frontier = next_frontier
            depth += 1
        return out

    # ── Bulk ingest + stats ──────────────────────────────

    def ingest(self, triples: Iterable[Triple]) -> int:
        n = 0
        for t in triples:
            self.assert_triple(
                t.subject, t.predicate, t.object,
                is_literal=t.is_literal,
                confidence=t.confidence,
                source=t.source,
            )
            n += 1
        return n

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM triples",
            ).fetchone()[0])
            subjects = int(self._conn.execute(
                "SELECT COUNT(DISTINCT subject) FROM triples",
            ).fetchone()[0])
            preds = int(self._conn.execute(
                "SELECT COUNT(DISTINCT predicate) FROM triples",
            ).fetchone()[0])
        return {
            "triples": total,
            "distinct_subjects": subjects,
            "distinct_predicates": preds,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
