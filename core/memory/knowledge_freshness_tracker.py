"""Knowledge freshness tracker — stale knowledge is dangerous.

Every fact the brain holds (rule threshold, niche stat, buyer-segment
model) was true *at the time it was learned*. Markets drift. Without
a staleness signal the brain happily applies a rule built from
three-month-old data to today's decision. The assumption holds
exactly until it doesn't.

``KnowledgeFreshnessTracker`` maintains per-item:

  • last_refreshed_ts       — most recent confirmation or update
  • evidence_count          — how many supporting observations
  • half_life_seconds        — configurable per-kind; default 30 days
  • current_freshness        — exp-decay function of time elapsed
  • confirm_count / contradict_count

Queries:

  * ``freshness(key) → 0..1`` — how fresh right now
  * ``stale(cutoff) → list[key]`` — items under a freshness floor
  * ``refresh(key, confirm=True)`` — stamp a new observation
  * ``contradict(key)``          — mark that reality disagreed

Pure stdlib, SQLite-persisted, deterministic. Complements
``concept_drift_detector`` (distribution-level) and
``world_model_updater`` (prediction drift) by tracking individual
*facts* not distributions or predictors.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("memory.knowledge_freshness_tracker")


_DEFAULT_HALF_LIFE_S = 30 * 24 * 3600


@dataclass
class KnowledgeItem:
    key: str
    kind: str                  # "rule" / "stat" / "model" / "belief"
    first_ts: float
    last_refreshed_ts: float
    evidence_count: int
    confirm_count: int
    contradict_count: int
    half_life_seconds: float
    note: str = ""

    def freshness_at(self, now: float) -> float:
        elapsed = max(0.0, now - self.last_refreshed_ts)
        if self.half_life_seconds <= 0:
            return 1.0
        return 0.5 ** (elapsed / self.half_life_seconds)

    def as_dict(self) -> dict[str, Any]:
        now = time.time()
        return {
            "key": self.key,
            "kind": self.kind,
            "first_ts": self.first_ts,
            "last_refreshed_ts": self.last_refreshed_ts,
            "evidence_count": self.evidence_count,
            "confirm_count": self.confirm_count,
            "contradict_count": self.contradict_count,
            "half_life_seconds": self.half_life_seconds,
            "freshness": round(self.freshness_at(now), 4),
            "note": self.note,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_items (
    key                 TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    first_ts            REAL NOT NULL,
    last_refreshed_ts   REAL NOT NULL,
    evidence_count      INTEGER NOT NULL,
    confirm_count       INTEGER NOT NULL,
    contradict_count    INTEGER NOT NULL,
    half_life_seconds   REAL NOT NULL,
    note                TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_kf_kind
    ON knowledge_items(kind);
"""


class KnowledgeFreshnessTracker:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        default_half_life_s: float = _DEFAULT_HALF_LIFE_S,
    ) -> None:
        if default_half_life_s <= 0:
            raise ValueError(
                "default_half_life_s must be > 0",
            )
        self._lock = threading.Lock()
        self._default_half_life = float(default_half_life_s)
        self._items: dict[str, KnowledgeItem] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT key, kind, first_ts, last_refreshed_ts, "
                "evidence_count, confirm_count, "
                "contradict_count, half_life_seconds, note "
                "FROM knowledge_items",
            ):
                self._items[row[0]] = KnowledgeItem(
                    key=row[0],
                    kind=row[1],
                    first_ts=float(row[2]),
                    last_refreshed_ts=float(row[3]),
                    evidence_count=int(row[4]),
                    confirm_count=int(row[5]),
                    contradict_count=int(row[6]),
                    half_life_seconds=float(row[7]),
                    note=row[8] or "",
                )

    def _persist(self, item: KnowledgeItem) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO knowledge_items("
            "  key, kind, first_ts, last_refreshed_ts, "
            "  evidence_count, confirm_count, "
            "  contradict_count, half_life_seconds, note"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.key, item.kind, item.first_ts,
                item.last_refreshed_ts, item.evidence_count,
                item.confirm_count, item.contradict_count,
                item.half_life_seconds, item.note,
            ),
        )
        self._conn.commit()

    # ── Intake ───────────────────────────────────────────

    def register(
        self,
        *,
        key: str,
        kind: str = "belief",
        half_life_seconds: float | None = None,
        note: str = "",
        ts: float | None = None,
    ) -> KnowledgeItem:
        if not key:
            raise ValueError("key required")
        if not kind:
            raise ValueError("kind required")
        hl = float(
            half_life_seconds if half_life_seconds is not None
            else self._default_half_life,
        )
        if hl <= 0:
            raise ValueError(
                "half_life_seconds must be > 0",
            )
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            if key in self._items:
                return self._items[key]
            item = KnowledgeItem(
                key=key, kind=kind,
                first_ts=timestamp,
                last_refreshed_ts=timestamp,
                evidence_count=1,
                confirm_count=0,
                contradict_count=0,
                half_life_seconds=hl,
                note=note,
            )
            self._items[key] = item
            self._persist(item)
            return item

    def refresh(
        self,
        key: str,
        *,
        confirm: bool = True,
        ts: float | None = None,
    ) -> KnowledgeItem:
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            item = self._items.get(key)
            if item is None:
                raise ValueError(
                    f"unknown knowledge item {key!r}",
                )
            item.last_refreshed_ts = timestamp
            item.evidence_count += 1
            if confirm:
                item.confirm_count += 1
            self._persist(item)
            return item

    def contradict(
        self,
        key: str,
        *,
        ts: float | None = None,
    ) -> KnowledgeItem:
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            item = self._items.get(key)
            if item is None:
                raise ValueError(
                    f"unknown knowledge item {key!r}",
                )
            item.contradict_count += 1
            item.evidence_count += 1
            # Contradictions reset freshness (last_refreshed stays
            # where it was — a contradict doesn't freshen the fact;
            # it erodes it). We halve half_life to make the item
            # decay faster going forward.
            item.half_life_seconds = max(
                60.0, item.half_life_seconds / 2.0,
            )
            self._persist(item)
            return item

    # ── Queries ──────────────────────────────────────────

    def get(self, key: str) -> KnowledgeItem | None:
        with self._lock:
            return self._items.get(key)

    def freshness(
        self, key: str, *, now: float | None = None,
    ) -> float:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return 0.0
            return item.freshness_at(
                float(now if now is not None else time.time()),
            )

    def stale(
        self,
        *,
        cutoff: float = 0.3,
        now: float | None = None,
    ) -> list[KnowledgeItem]:
        if not 0.0 < cutoff <= 1.0:
            raise ValueError("cutoff must be in (0, 1]")
        at = float(now if now is not None else time.time())
        with self._lock:
            items = list(self._items.values())
        stale = [
            i for i in items if i.freshness_at(at) < cutoff
        ]
        stale.sort(key=lambda i: i.freshness_at(at))
        return stale

    def by_kind(self, kind: str) -> list[KnowledgeItem]:
        with self._lock:
            return [
                i for i in self._items.values() if i.kind == kind
            ]

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            kinds: dict[str, int] = {}
            for i in self._items.values():
                kinds[i.kind] = kinds.get(i.kind, 0) + 1
            fresh_vals = [
                i.freshness_at(now) for i in self._items.values()
            ]
        avg_fresh = (
            sum(fresh_vals) / len(fresh_vals)
            if fresh_vals else 0.0
        )
        return {
            "total": len(fresh_vals),
            "by_kind": kinds,
            "average_freshness": round(avg_fresh, 4),
            "default_half_life_s": self._default_half_life,
        }

    def reset(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM knowledge_items",
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
