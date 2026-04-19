"""Webhook dedup — drop duplicate incoming events.

idempotency_store (v15-D1) prevents *outgoing* duplicate writes.
Webhook dedup is the complement: when Shopify / Meta / AutoDS
retries a webhook (they all do, aggressively), the brain sees the
same order twice. Without a dedup layer each one flows through
the whole learning pipeline, skewing reward_model, LTV, and
cohort analysis.

WebhookDedup computes a deterministic hash of the event (payload
+ optional explicit delivery_id) and records first-seen. Repeat
deliveries within the TTL return ``seen=True`` without writing
anything. First-time events record + return the computed digest
so call sites can propagate it as their correlation id.

APIs:

  register(source, payload, delivery_id=None, ttl_s=3600)
      → DedupVerdict(seen, digest, stored_at)
  seen(source, digest) → bool
  purge(source=None, older_than_s=None)

Persistence: ``data/webhook_dedup.db``. SQLite, thread-safe.
Hash is SHA-1 of canonicalised JSON so field-order changes don't
spawn false non-duplicates. Zero LLM.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/webhook_dedup.db")
_DEFAULT_TTL = 3600            # 1 hour

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    source       TEXT NOT NULL,
    digest       TEXT NOT NULL,
    delivery_id  TEXT,
    stored_at    REAL NOT NULL,
    expires_at   REAL NOT NULL,
    PRIMARY KEY (source, digest)
);
CREATE INDEX IF NOT EXISTS idx_exp ON deliveries(expires_at);
CREATE INDEX IF NOT EXISTS idx_source ON deliveries(source);
"""


@dataclass
class DedupVerdict:
    source: str
    digest: str
    seen: bool
    stored_at: float
    delivery_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "digest": self.digest,
            "seen": self.seen,
            "stored_at": self.stored_at,
            "delivery_id": self.delivery_id,
        }


# ── Dedup ───────────────────────────────────────────────────

class WebhookDedup:
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

    # ── Register / query ───────────────────────────────────

    def register(
        self,
        source: str,
        payload: Any,
        delivery_id: str | None = None,
        ttl_s: float = _DEFAULT_TTL,
    ) -> DedupVerdict:
        source = source.strip()
        if not source:
            raise ValueError("source required")
        digest = self._digest(payload, delivery_id)
        now = time.time()
        with self._lock, self._connect() as conn:
            # Purge expired for this (source, digest) first — a new
            # arrival after expiry is allowed to reprocess.
            conn.execute(
                "DELETE FROM deliveries "
                "WHERE source=? AND digest=? AND expires_at < ?",
                (source, digest, now),
            )
            existing = conn.execute(
                "SELECT stored_at, delivery_id FROM deliveries "
                "WHERE source=? AND digest=?",
                (source, digest),
            ).fetchone()
            if existing:
                return DedupVerdict(
                    source=source, digest=digest, seen=True,
                    stored_at=float(existing[0]),
                    delivery_id=existing[1] or "",
                )
            conn.execute(
                "INSERT INTO deliveries "
                "(source, digest, delivery_id, stored_at, expires_at) "
                "VALUES (?,?,?,?,?)",
                (source, digest, delivery_id, now,
                 now + float(ttl_s)),
            )
            conn.commit()
        return DedupVerdict(
            source=source, digest=digest, seen=False,
            stored_at=now, delivery_id=delivery_id or "",
        )

    def seen(self, source: str, digest: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM deliveries "
                "WHERE source=? AND digest=?",
                (source.strip(), digest),
            ).fetchone()
        if not row:
            return False
        return row[0] >= time.time()

    # ── Maintenance ────────────────────────────────────────

    def purge(
        self, source: str | None = None,
        older_than_s: float | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if source is not None:
            clauses.append("source=?"); params.append(source.strip())
        if older_than_s is not None:
            cutoff = time.time() - float(older_than_s)
            clauses.append("stored_at < ?"); params.append(cutoff)
        if not clauses:
            # Default: drop expired entries
            clauses.append("expires_at < ?")
            params.append(time.time())
        where = " WHERE " + " AND ".join(clauses)
        with self._lock, self._connect() as conn:
            cur = conn.execute(f"DELETE FROM deliveries{where}",
                                tuple(params))
            conn.commit()
            return cur.rowcount or 0

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM deliveries"
            ).fetchone()[0]
            live = conn.execute(
                "SELECT COUNT(*) FROM deliveries WHERE expires_at >= ?",
                (now,),
            ).fetchone()[0]
            by_source = conn.execute(
                "SELECT source, COUNT(*) FROM deliveries "
                "WHERE expires_at >= ? GROUP BY source",
                (now,),
            ).fetchall()
        return {
            "total": int(total or 0),
            "live": int(live or 0),
            "by_source": {s: int(c) for s, c in by_source},
        }

    # ── Internals ──────────────────────────────────────────

    @staticmethod
    def _digest(payload: Any, delivery_id: str | None) -> str:
        if delivery_id:
            canonical = f"id:{delivery_id.strip()}"
        else:
            canonical = json.dumps(
                payload, sort_keys=True, default=str,
            )
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


# ── Singleton ────────────────────────────────────────────────

_DD_LOCK = threading.Lock()
_DEDUP: WebhookDedup | None = None


def dedup() -> WebhookDedup:
    global _DEDUP
    if _DEDUP is None:
        with _DD_LOCK:
            if _DEDUP is None:
                _DEDUP = WebhookDedup()
    return _DEDUP
