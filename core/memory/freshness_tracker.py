"""Freshness tracker — last_seen + access_count per memory row.

Track 8 of AGI_HARDENING_PLAN. Memory rows, rules, concepts,
source observations all age — a concept from 3 days ago should
weigh more than one from 6 months ago when informing a live
decision. This module tracks ``(kind, key) → (last_seen,
access_count)`` and returns a freshness factor callers can
multiply into rankings.

Model:

    freshness = decay(now - last_seen) × (1 + log1p(access_count) / 5)

  * ``decay(delta)`` — configurable: ``exponential`` (default)
    uses exp(-delta / decay_s); ``linear`` uses max(0, 1 -
    delta / decay_s); ``step`` uses 1.0 until decay_s then 0.
  * ``access_count`` softly boosts rows that are actively used.
  * Rows with ``last_seen <= 0`` return freshness 0.

Surface:

    tracker.touch(kind, key)          # access event
    tracker.record(kind, key, ts)     # external observation
    tracker.freshness(kind, key)      # 0..~1 score
    tracker.oldest(kind, limit=10)    # sweep candidates
    tracker.stats()

Pure stdlib, SQLite, thread-safe (RLock). Deterministic under
fixed ``now_fn``.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.memory.freshness_tracker")


_DEFAULT_DECAY_S = 30 * 24 * 3600.0
_VALID_CURVES = ("exponential", "linear", "step")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS freshness (
    kind          TEXT NOT NULL,
    key           TEXT NOT NULL,
    last_seen     REAL NOT NULL,
    access_count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS idx_freshness_kind_ts
    ON freshness(kind, last_seen);
"""


@dataclass
class FreshnessRecord:
    kind: str
    key: str
    last_seen: float
    access_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "last_seen": self.last_seen,
            "access_count": self.access_count,
        }


def _decay(
    delta: float,
    *,
    curve: str,
    decay_s: float,
) -> float:
    if delta < 0:
        return 1.0
    if decay_s <= 0:
        return 1.0
    if curve == "linear":
        return max(0.0, 1.0 - delta / decay_s)
    if curve == "step":
        return 1.0 if delta < decay_s else 0.0
    # exponential (default)
    return math.exp(-delta / decay_s)


class FreshnessTracker:
    """Track last-seen and access-count per (kind, key)."""

    def __init__(
        self,
        db_path: str | Path = "data/freshness.db",
        *,
        decay_s: float = _DEFAULT_DECAY_S,
        curve: str = "exponential",
        access_boost_div: float = 5.0,
        now_fn: Any = None,
    ) -> None:
        if decay_s <= 0:
            raise ValueError("decay_s must be > 0")
        if curve not in _VALID_CURVES:
            raise ValueError(
                f"curve must be one of {_VALID_CURVES}",
            )
        if access_boost_div <= 0:
            raise ValueError(
                "access_boost_div must be > 0",
            )
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.RLock()
        self._decay = float(decay_s)
        self._curve = str(curve)
        self._boost_div = float(access_boost_div)
        self._now_fn = now_fn or time.time
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Write ────────────────────────────────────────────

    def touch(
        self, kind: str, key: str,
    ) -> FreshnessRecord:
        """Mark a row as accessed right now. Creates if missing."""
        if not kind or not key:
            raise ValueError(
                "kind and key required",
            )
        now = float(self._now_fn())
        with self._lock:
            row = self._conn.execute(
                "SELECT last_seen, access_count "
                "FROM freshness "
                "WHERE kind=? AND key=?",
                (kind, key),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO freshness("
                    "kind, key, last_seen, access_count) "
                    "VALUES(?, ?, ?, 1)",
                    (kind, key, now),
                )
                count = 1
            else:
                count = int(row[1]) + 1
                self._conn.execute(
                    "UPDATE freshness SET last_seen=?, "
                    "access_count=? "
                    "WHERE kind=? AND key=?",
                    (now, count, kind, key),
                )
            self._conn.commit()
        return FreshnessRecord(
            kind=kind,
            key=key,
            last_seen=now,
            access_count=count,
        )

    def record(
        self,
        kind: str,
        key: str,
        *,
        ts: float,
    ) -> FreshnessRecord:
        """Record an externally-observed freshness timestamp
        (e.g. 'this source was fetched at T')."""
        if not kind or not key:
            raise ValueError(
                "kind and key required",
            )
        if ts <= 0:
            raise ValueError("ts must be > 0")
        with self._lock:
            row = self._conn.execute(
                "SELECT access_count FROM freshness "
                "WHERE kind=? AND key=?",
                (kind, key),
            ).fetchone()
            count = int(row[0]) if row is not None else 0
            if row is None:
                self._conn.execute(
                    "INSERT INTO freshness("
                    "kind, key, last_seen, "
                    "access_count) VALUES(?, ?, ?, ?)",
                    (kind, key, float(ts), count),
                )
            else:
                self._conn.execute(
                    "UPDATE freshness SET last_seen=? "
                    "WHERE kind=? AND key=?",
                    (float(ts), kind, key),
                )
            self._conn.commit()
        return FreshnessRecord(
            kind=kind,
            key=key,
            last_seen=float(ts),
            access_count=count,
        )

    # ── Query ────────────────────────────────────────────

    def freshness(
        self, kind: str, key: str,
    ) -> float:
        rec = self.get(kind, key)
        if rec is None or rec.last_seen <= 0:
            return 0.0
        now = float(self._now_fn())
        delta = max(0.0, now - rec.last_seen)
        base = _decay(
            delta,
            curve=self._curve,
            decay_s=self._decay,
        )
        boost = 1.0 + math.log1p(
            rec.access_count,
        ) / self._boost_div
        return max(0.0, min(1.5, base * boost))

    def get(
        self, kind: str, key: str,
    ) -> FreshnessRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT kind, key, last_seen, access_count "
                "FROM freshness WHERE kind=? AND key=?",
                (kind, key),
            ).fetchone()
        if row is None:
            return None
        return FreshnessRecord(
            kind=row[0],
            key=row[1],
            last_seen=float(row[2]),
            access_count=int(row[3]),
        )

    def oldest(
        self,
        kind: str,
        *,
        limit: int = 10,
    ) -> list[FreshnessRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, key, last_seen, access_count "
                "FROM freshness "
                "WHERE kind=? "
                "ORDER BY last_seen ASC LIMIT ?",
                (kind, int(limit)),
            ).fetchall()
        return [
            FreshnessRecord(
                kind=r[0], key=r[1],
                last_seen=float(r[2]),
                access_count=int(r[3]),
            )
            for r in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            per_kind: dict[str, int] = {}
            for k, c in self._conn.execute(
                "SELECT kind, COUNT(*) FROM freshness "
                "GROUP BY kind",
            ):
                per_kind[k] = int(c)
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM freshness",
            ).fetchone()[0])
        return {
            "total_rows": total,
            "per_kind": per_kind,
            "decay_s": self._decay,
            "curve": self._curve,
            "access_boost_div": self._boost_div,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: FreshnessTracker | None = None
_SINGLETON_LOCK = threading.Lock()


def get_freshness_tracker() -> FreshnessTracker:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = FreshnessTracker()
    return _SINGLETON


def reset_freshness_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset freshness close skipped: %s",
                    exc,
                )
        _SINGLETON = None
