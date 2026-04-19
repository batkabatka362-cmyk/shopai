"""Typed knowledge graph — ontology over facts.

The knowledge base (v3-D4) stores facts as
``(subject, predicate, object)`` triples. That's fine for lookup
but gives the reasoner no *types* to work with. Asking "list every
*product* whose *supplier* is in China" requires typed entities;
pure string triples can't answer it.

Ontology adds typing:

  • Every entity has a type (``Product``, ``Launch``, ``Supplier``,
    ``Niche``, ``Competitor``, ``Rule``, etc.).
  • Every predicate is typed: ``(SubjectType, predicate_name,
    ObjectType)`` — e.g. ``(Product, supplied_by, Supplier)``.
  • Subtypes are declared: ``Launch ⊑ Product``, so a query for
    Products returns Launches too.
  • Cardinality hints: functional predicates (``name``, ``niche``)
    vs multi-valued (``has_tag``).

Inference:

  • Type propagation — if ``(X, supplied_by, Y)`` and predicate
    requires object type ``Supplier``, then ``Y`` is inferred to
    be a Supplier.
  • Transitive closure for ⊑ (is-a) so a Launch can be queried
    as a Product.

Persistence: ``data/ontology.db`` SQLite. Zero LLM. The oracle
consumes this graph when the owner asks structural questions
("which niches have no launches yet?").
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


_DB_PATH = Path("data/ontology.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT NOT NULL,
    type        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (id, type)
);
CREATE TABLE IF NOT EXISTS triples (
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    source      TEXT,
    created_at  REAL NOT NULL,
    PRIMARY KEY (subject, predicate, object)
);
CREATE TABLE IF NOT EXISTS type_hierarchy (
    child       TEXT NOT NULL,
    parent      TEXT NOT NULL,
    PRIMARY KEY (child, parent)
);
CREATE TABLE IF NOT EXISTS predicate_signatures (
    predicate    TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    object_type  TEXT NOT NULL,
    functional   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_triples_subject
    ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_predicate
    ON triples(predicate);
CREATE INDEX IF NOT EXISTS idx_entities_type
    ON entities(type);
"""


@dataclass
class Entity:
    id: str
    type: str
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type,
                "created_at": self.created_at}


@dataclass
class Triple:
    subject: str
    predicate: str
    object: str
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "source": self.source,
        }


# ── Ontology ────────────────────────────────────────────────

class Ontology:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Schema ──────────────────────────────────────────────

    def declare_subtype(self, child: str, parent: str) -> None:
        """Record ``child ⊑ parent``. Idempotent."""
        if child == parent:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO type_hierarchy "
                "(child, parent) VALUES (?, ?)",
                (child, parent),
            )
            conn.commit()

    def declare_predicate(
        self,
        name: str,
        subject_type: str,
        object_type: str,
        functional: bool = False,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO predicate_signatures "
                "(predicate, subject_type, object_type, functional) "
                "VALUES (?,?,?,?)",
                (name, subject_type, object_type, 1 if functional else 0),
            )
            conn.commit()

    def predicate_sig(self, name: str) -> tuple[str, str, bool] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT subject_type, object_type, functional "
                "FROM predicate_signatures WHERE predicate=?",
                (name,),
            ).fetchone()
        if not row:
            return None
        return (row[0], row[1], bool(row[2]))

    # ── Entities ───────────────────────────────────────────

    def upsert_entity(self, entity_id: str, entity_type: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO entities (id, type, created_at) "
                "VALUES (?, ?, ?)",
                (entity_id, entity_type, time.time()),
            )
            conn.commit()

    def types_of(self, entity_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT type FROM entities WHERE id=?",
                (entity_id,),
            ).fetchall()
        return {r[0] for r in rows}

    # ── Triples ────────────────────────────────────────────

    def assert_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        source: str = "",
    ) -> bool:
        """Insert a triple; returns True if new."""
        # Auto-type subject/object from predicate signature if known.
        sig = self.predicate_sig(predicate)
        with self._lock, self._connect() as conn:
            if sig:
                sub_t, obj_t, functional = sig
                conn.execute(
                    "INSERT OR IGNORE INTO entities "
                    "(id, type, created_at) VALUES (?,?,?)",
                    (subject, sub_t, time.time()),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO entities "
                    "(id, type, created_at) VALUES (?,?,?)",
                    (obj, obj_t, time.time()),
                )
                if functional:
                    # Remove prior values for this subject/predicate
                    conn.execute(
                        "DELETE FROM triples "
                        "WHERE subject=? AND predicate=? AND object!=?",
                        (subject, predicate, obj),
                    )
            cur = conn.execute(
                "INSERT OR IGNORE INTO triples "
                "(subject, predicate, object, source, created_at) "
                "VALUES (?,?,?,?,?)",
                (subject, predicate, obj, source, time.time()),
            )
            conn.commit()
            return cur.rowcount > 0

    def retract_triple(
        self, subject: str, predicate: str, obj: str,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM triples "
                "WHERE subject=? AND predicate=? AND object=?",
                (subject, predicate, obj),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Queries ────────────────────────────────────────────

    def query(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        obj: str | None = None,
    ) -> list[Triple]:
        conds, params = [], []
        if subject is not None:
            conds.append("subject=?"); params.append(subject)
        if predicate is not None:
            conds.append("predicate=?"); params.append(predicate)
        if obj is not None:
            conds.append("object=?"); params.append(obj)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT subject, predicate, object, source "
                f"FROM triples{where}",
                tuple(params),
            ).fetchall()
        return [Triple(*r) for r in rows]

    def entities_of_type(
        self, t: str, include_subtypes: bool = True,
    ) -> list[Entity]:
        types = {t}
        if include_subtypes:
            types |= self._descendants(t)
        if not types:
            return []
        placeholders = ",".join("?" * len(types))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, type, created_at FROM entities "
                f"WHERE type IN ({placeholders})",
                tuple(types),
            ).fetchall()
        return [Entity(r[0], r[1], r[2]) for r in rows]

    def is_a(self, entity_id: str, t: str) -> bool:
        """Does this entity have type ``t`` (transitively)?"""
        direct = self.types_of(entity_id)
        if t in direct:
            return True
        targets = {t} | self._descendants(t)
        return bool(direct & targets)

    # ── Inference ──────────────────────────────────────────

    def _descendants(self, t: str) -> set[str]:
        """All types ``x`` such that ``x ⊑* t``. BFS over the
        hierarchy."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT child, parent FROM type_hierarchy"
            ).fetchall()
        children_of: dict[str, set[str]] = defaultdict(set)
        for c, p in rows:
            children_of[p].add(c)
        seen: set[str] = set()
        queue: deque[str] = deque([t])
        while queue:
            cur = queue.popleft()
            for c in children_of.get(cur, ()):
                if c not in seen:
                    seen.add(c)
                    queue.append(c)
        return seen

    def subtypes_of(self, t: str) -> set[str]:
        return self._descendants(t)

    def supertypes_of(self, t: str) -> set[str]:
        """Transitive ancestors of ``t``."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT child, parent FROM type_hierarchy"
            ).fetchall()
        parent_of: dict[str, set[str]] = defaultdict(set)
        for c, p in rows:
            parent_of[c].add(p)
        seen: set[str] = set()
        queue: deque[str] = deque([t])
        while queue:
            cur = queue.popleft()
            for p in parent_of.get(cur, ()):
                if p not in seen:
                    seen.add(p)
                    queue.append(p)
        return seen

    # ── Introspection ─────────────────────────────────────

    def size(self) -> dict[str, int]:
        with self._connect() as conn:
            ents = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            trips = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
            sigs = conn.execute(
                "SELECT COUNT(*) FROM predicate_signatures"
            ).fetchone()[0]
            hier = conn.execute(
                "SELECT COUNT(*) FROM type_hierarchy"
            ).fetchone()[0]
        return {
            "entities": ents, "triples": trips,
            "predicates": sigs, "subtype_edges": hier,
        }

    def bulk_assert(
        self, triples: Iterable[tuple[str, str, str]],
        source: str = "",
    ) -> int:
        count = 0
        for s, p, o in triples:
            if self.assert_triple(s, p, o, source):
                count += 1
        return count


# ── Singleton ────────────────────────────────────────────────

_ONT_LOCK = threading.Lock()
_ONT: Ontology | None = None


def ontology() -> Ontology:
    global _ONT
    if _ONT is None:
        with _ONT_LOCK:
            if _ONT is None:
                _ONT = Ontology()
    return _ONT
