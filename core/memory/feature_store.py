"""Feature store — cached + versioned feature computation.

Every decision re-derives features from raw memory: average ROAS
over 30 days, niche kill ratio, CVR bucket. That recompute is
cheap for one row and expensive across a cycle. Worse, different
subsystems computed slightly different versions ("avg_roas" was
sometimes over 30 days, sometimes 60), so rules written against
one version quietly misfired elsewhere.

FeatureStore registers *named features* with:

  • compute_fn(entity_id) → value
  • ttl_s                  → cache age before recompute
  • version                → bumped when the compute_fn changes

Callers request ``store.get(feature, entity_id)``. The store
returns the cached value if it's within TTL and the version
matches; otherwise it recomputes, persists, and returns.

Also exposes batch_get (cache-aware) and invalidate for when an
entity changes.

Persistence: ``data/features.db`` SQLite. Thread-safe. Zero LLM.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


_DB_PATH = Path("data/features.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    feature     TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    computed_at REAL NOT NULL,
    PRIMARY KEY (feature, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_feature ON cache(feature);
"""


@dataclass
class FeatureSpec:
    name: str
    compute_fn: Callable[[str], Any]
    ttl_s: float = 3600.0
    version: int = 1
    description: str = ""


@dataclass
class CacheEntry:
    feature: str
    entity_id: str
    value: Any
    version: int
    computed_at: float

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.computed_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "entity_id": self.entity_id,
            "value": self.value,
            "version": self.version,
            "computed_at": self.computed_at,
            "age_s": round(self.age_s, 2),
        }


# ── Store ───────────────────────────────────────────────────

class FeatureStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._specs: dict[str, FeatureSpec] = {}
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Registration ───────────────────────────────────────

    def register(
        self,
        name: str,
        compute_fn: Callable[[str], Any],
        ttl_s: float = 3600.0,
        version: int = 1,
        description: str = "",
    ) -> FeatureSpec:
        name = name.strip()
        if not name:
            raise ValueError("feature name required")
        spec = FeatureSpec(
            name=name, compute_fn=compute_fn,
            ttl_s=float(ttl_s), version=int(version),
            description=description,
        )
        with self._lock:
            self._specs[name] = spec
        return spec

    def registered(self) -> list[str]:
        with self._lock:
            return sorted(self._specs.keys())

    # ── Read ───────────────────────────────────────────────

    def get(
        self, feature: str, entity_id: str, *,
        force: bool = False,
    ) -> Any:
        spec = self._specs.get(feature)
        if spec is None:
            raise KeyError(f"unknown feature {feature!r}")
        entity_id = str(entity_id)
        if not force:
            cached = self._read_cache(feature, entity_id)
            if (cached is not None
                    and cached.version == spec.version
                    and cached.age_s <= spec.ttl_s):
                return cached.value
        value = spec.compute_fn(entity_id)
        self._write_cache(feature, entity_id, value, spec.version)
        return value

    def get_with_metadata(
        self, feature: str, entity_id: str,
    ) -> CacheEntry | None:
        value = self.get(feature, entity_id)
        cached = self._read_cache(feature, str(entity_id))
        if cached is None:
            return None
        cached.value = value   # ensure latest
        return cached

    def batch_get(
        self, feature: str, entity_ids: Iterable[str],
    ) -> dict[str, Any]:
        return {
            eid: self.get(feature, eid)
            for eid in entity_ids
        }

    # ── Invalidation ───────────────────────────────────────

    def invalidate(
        self,
        feature: str | None = None,
        entity_id: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if feature is not None:
            clauses.append("feature=?"); params.append(feature)
        if entity_id is not None:
            clauses.append("entity_id=?"); params.append(str(entity_id))
        with self._lock, self._connect() as conn:
            if clauses:
                where = " WHERE " + " AND ".join(clauses)
                cur = conn.execute(f"DELETE FROM cache{where}",
                                    tuple(params))
            else:
                cur = conn.execute("DELETE FROM cache")
            conn.commit()
            return cur.rowcount or 0

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM cache"
            ).fetchone()[0]
            by_feature = conn.execute(
                "SELECT feature, COUNT(*) FROM cache GROUP BY feature"
            ).fetchall()
        return {
            "total_rows": int(total or 0),
            "by_feature": {f: int(c) for f, c in by_feature},
            "registered": self.registered(),
        }

    # ── Internals ──────────────────────────────────────────

    def _read_cache(
        self, feature: str, entity_id: str,
    ) -> CacheEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json, version, computed_at "
                "FROM cache WHERE feature=? AND entity_id=?",
                (feature, entity_id),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row[0])
        except (json.JSONDecodeError, ValueError):
            return None
        return CacheEntry(
            feature=feature, entity_id=entity_id,
            value=value, version=int(row[1]),
            computed_at=float(row[2]),
        )

    def _write_cache(
        self, feature: str, entity_id: str,
        value: Any, version: int,
    ) -> None:
        payload = json.dumps(value, default=str)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache "
                "(feature, entity_id, value_json, version, computed_at) "
                "VALUES (?,?,?,?,?)",
                (feature, entity_id, payload, version, time.time()),
            )
            conn.commit()


# ── Singleton ────────────────────────────────────────────────

_FS_LOCK = threading.Lock()
_FS: FeatureStore | None = None


def feature_store() -> FeatureStore:
    global _FS
    if _FS is None:
        with _FS_LOCK:
            if _FS is None:
                _FS = FeatureStore()
    return _FS
