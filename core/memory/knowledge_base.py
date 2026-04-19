"""Structured knowledge base — fact triples.

MemoryIntelligence handles experiential knowledge (events, patterns,
rules). That's great for "launches with urgent tone tend to win" but
poor for "Shopify metafield value is max 5 MB" — the latter is a
static *fact* the brain should cite confidently without pattern
mining.

The knowledge base stores ``(subject, predicate, object)`` triples
plus provenance. It's a separate SQLite DB with its own lifecycle:

    assert_fact("shopify", "max_metafield_mb", 5, source="docs.shopify.com")
    recall("shopify", "max_metafield_mb") → 5

Facts are:
  • Typed — object can be a scalar (int/float/bool/str) or JSON blob.
  • Versioned — re-asserting a fact writes a new row; the reader
    sees the most recent one but history is preserved.
  • Provenanced — every assertion carries a source string the
    Oracle can cite ("per docs.shopify.com, metafield limit is 5 MB").

This module is intentionally small — the oracle + reasoner can
recall facts without bumping into the pattern/rule pipeline.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/knowledge.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    subject   TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_json TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    superseded_by INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fact_sp ON facts(subject, predicate, superseded_by);
CREATE INDEX IF NOT EXISTS idx_fact_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_fact_created_at ON facts(created_at);
"""


_lock = threading.Lock()


@dataclass
class Fact:
    id: int
    subject: str
    predicate: str
    object: Any
    source: str
    created_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "source": self.source,
            "created_at": self.created_at,
        }


class KnowledgeBase:
    """Tiny triple store. Thread-safe."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            conn = sqlite3.connect(str(self._path))
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def assert_fact(
        self,
        subject: str,
        predicate: str,
        object: Any,
        source: str = "",
    ) -> Fact:
        """Write a new fact. Supersedes any previous (subject,predicate)
        so recall returns the fresh value by default."""
        if not subject or not predicate:
            raise ValueError("subject + predicate required")
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                # Mark previous live fact as superseded
                cur.execute(
                    "SELECT id FROM facts "
                    "WHERE subject=? AND predicate=? AND superseded_by=0",
                    (subject, predicate),
                )
                prior = cur.fetchone()
                cur.execute(
                    "INSERT INTO facts(subject, predicate, object_json, "
                    "  source, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        subject, predicate,
                        json.dumps(object, default=str),
                        source,
                        time.time(),
                    ),
                )
                new_id = cur.lastrowid
                if prior:
                    cur.execute(
                        "UPDATE facts SET superseded_by=? WHERE id=?",
                        (new_id, prior[0]),
                    )
                conn.commit()
                cur.execute("SELECT * FROM facts WHERE id=?", (new_id,))
                row = cur.fetchone()
            finally:
                conn.close()
        return self._row_to_fact(row)

    def recall(
        self,
        subject: str,
        predicate: str | None = None,
    ) -> Fact | list[Fact] | None:
        """Recall the most recent fact. When predicate is omitted,
        return all live facts for the subject."""
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                if predicate is None:
                    cur.execute(
                        "SELECT * FROM facts "
                        "WHERE subject=? AND superseded_by=0 "
                        "ORDER BY predicate",
                        (subject,),
                    )
                    return [self._row_to_fact(r) for r in cur.fetchall()]
                cur.execute(
                    "SELECT * FROM facts "
                    "WHERE subject=? AND predicate=? AND superseded_by=0",
                    (subject, predicate),
                )
                row = cur.fetchone()
                return self._row_to_fact(row) if row else None
            finally:
                conn.close()

    def history(self, subject: str, predicate: str) -> list[Fact]:
        """Return the assertion history (oldest first) for auditing."""
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM facts "
                    "WHERE subject=? AND predicate=? "
                    "ORDER BY created_at ASC",
                    (subject, predicate),
                )
                return [self._row_to_fact(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def list_subjects(self) -> list[str]:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT DISTINCT subject FROM facts "
                    "WHERE superseded_by=0 ORDER BY subject",
                )
                return [r[0] for r in cur.fetchall()]
            finally:
                conn.close()

    # ── Internals ───────────────────────────────────────────

    @staticmethod
    def _row_to_fact(row: tuple) -> Fact:
        try:
            obj = json.loads(row[3] or "null")
        except (json.JSONDecodeError, ValueError):
            obj = None
        return Fact(
            id=int(row[0]),
            subject=row[1],
            predicate=row[2],
            object=obj,
            source=row[4] or "",
            created_at=float(row[5] or 0),
        )


# ── Singleton accessor ──────────────────────────────────────

_KB_LOCK = threading.Lock()
_KB: KnowledgeBase | None = None


def knowledge_base() -> KnowledgeBase:
    global _KB
    with _KB_LOCK:
        if _KB is None:
            _KB = KnowledgeBase()
    return _KB


# ── Seed well-known facts — idempotent ───────────────────────

_SEED_FACTS: list[tuple[str, str, Any, str]] = [
    ("shopify", "max_metafield_value_bytes", 5 * 1024 * 1024,
     "docs.shopify.com/api/admin-rest/2024-01/resources/metafield"),
    ("shopify", "rate_limit_calls_per_second", 2,
     "docs.shopify.com — REST Admin API default leaky bucket"),
    ("shopify", "max_products_per_call", 250,
     "docs.shopify.com — /products.json limit"),
    ("meta_ads", "min_daily_budget_usd", 1.0,
     "developers.facebook.com/docs/marketing-api/bidding"),
    ("meta_ads", "conversion_window_hours", 168,
     "Meta Ads Manager default 7d-click window"),
    ("roas", "healthy_threshold", 2.0,
     "ShopAI config/settings.json default scale_roas"),
    ("roas", "kill_threshold", 1.5,
     "ShopAI config/settings.json default kill_roas"),
    ("gemini", "embedding_dim", 3072,
     "Gemini embedding-001 spec"),
    ("pexels", "free_tier_per_hour", 200,
     "pexels.com/api — free tier request cap"),
]


def seed_defaults(kb: KnowledgeBase | None = None) -> int:
    """Idempotently write the default fact set. Returns the count of
    facts that were newly asserted (already-current facts are skipped)."""
    kb = kb or knowledge_base()
    written = 0
    for subject, predicate, obj, source in _SEED_FACTS:
        existing = kb.recall(subject, predicate)
        if isinstance(existing, Fact) and existing.object == obj:
            continue
        kb.assert_fact(subject, predicate, obj, source=source)
        written += 1
    return written
