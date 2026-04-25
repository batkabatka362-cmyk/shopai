"""Attention calibrator — score attention_filter's ranking vs outcomes.

attention_filter picks the top-N most relevant items per cycle but
nothing verifies whether those were actually the *important* ones in
hindsight. After the fact an item's real importance shows up as an
outcome: a signal caused a decision, a pattern drove a revenue change,
an alert escalated to an owner.

attention_calibrator keeps a log of (cycle_id, item_key, attention_rank,
realised_importance_score) tuples. Over a window it computes:

  • precision@k — fraction of top-k attended items that later showed
    non-trivial importance
  • recall@k — fraction of truly important items that made top-k
  • ndcg_like — rank-weighted relevance
  • avg_miss — average realised_score of items attention missed

These metrics let a meta-learner raise/lower attention_filter's
salience weights or detect "attention drift" (high recall, low
precision → attending to stale things).

Pure stdlib, SQLite-persisted, deterministic.
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


logger = get_logger("brain.attention_calibrator")


_IMPORTANCE_THRESHOLD = 0.3


@dataclass
class AttendedItem:
    cycle_id: str
    item_key: str
    attention_rank: int        # 1-based position attention_filter gave
    attention_score: float     # 0..1 from the filter itself
    realised_importance: float = 0.0   # 0..1 from hindsight
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "item_key": self.item_key,
            "attention_rank": self.attention_rank,
            "attention_score": round(self.attention_score, 4),
            "realised_importance": round(self.realised_importance, 4),
            "ts": self.ts,
        }


@dataclass
class CalibrationReport:
    precision_at_k: float
    recall_at_k: float
    ndcg_like: float
    avg_miss: float
    n_attended: int
    n_important: int
    k: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision_at_k": round(self.precision_at_k, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "ndcg_like": round(self.ndcg_like, 4),
            "avg_miss": round(self.avg_miss, 4),
            "n_attended": self.n_attended,
            "n_important": self.n_important,
            "k": self.k,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS attended (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id             TEXT NOT NULL,
    item_key             TEXT NOT NULL,
    attention_rank       INTEGER NOT NULL,
    attention_score      REAL NOT NULL,
    realised_importance  REAL NOT NULL DEFAULT 0.0,
    ts                   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_att_cycle_item
    ON attended(cycle_id, item_key);
CREATE INDEX IF NOT EXISTS idx_att_ts
    ON attended(ts);
CREATE TABLE IF NOT EXISTS missed (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id             TEXT NOT NULL,
    item_key             TEXT NOT NULL,
    realised_importance  REAL NOT NULL,
    ts                   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_missed_cycle
    ON missed(cycle_id);
"""


class AttentionCalibrator:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        importance_threshold: float = _IMPORTANCE_THRESHOLD,
    ) -> None:
        if not 0 < importance_threshold <= 1:
            raise ValueError("importance_threshold must be in (0, 1]")
        self._lock = threading.Lock()
        self._importance_threshold = float(importance_threshold)
        self._attended: list[AttendedItem] = []
        self._missed: list[tuple[str, str, float, float]] = []
        # (cycle_id, item_key, importance, ts)
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
                "SELECT cycle_id, item_key, attention_rank, "
                "attention_score, realised_importance, ts "
                "FROM attended ORDER BY ts ASC",
            ):
                self._attended.append(AttendedItem(
                    cycle_id=row[0],
                    item_key=row[1],
                    attention_rank=int(row[2]),
                    attention_score=float(row[3]),
                    realised_importance=float(row[4]),
                    ts=float(row[5]),
                ))
            for row in self._conn.execute(
                "SELECT cycle_id, item_key, realised_importance, ts "
                "FROM missed ORDER BY ts ASC",
            ):
                self._missed.append(
                    (row[0], row[1], float(row[2]), float(row[3])),
                )

    # ── Intake ────────────────────────────────────────────

    def record_attended(
        self,
        *,
        cycle_id: str,
        ranking: list[tuple[str, float]],
        ts: float | None = None,
    ) -> int:
        """Record what attention_filter ranked for this cycle.

        ``ranking`` is a list of (item_key, score) in descending score
        order. Rank is 1-based index.
        """
        if not cycle_id:
            raise ValueError("cycle_id required")
        if not ranking:
            return 0
        timestamp = float(ts if ts is not None else time.time())
        n = 0
        with self._lock:
            for i, (key, score) in enumerate(ranking):
                if not key:
                    continue
                item = AttendedItem(
                    cycle_id=cycle_id,
                    item_key=str(key),
                    attention_rank=i + 1,
                    attention_score=float(score),
                    realised_importance=0.0,
                    ts=timestamp,
                )
                self._attended.append(item)
                if self._conn is not None:
                    self._conn.execute(
                        "INSERT INTO attended"
                        "(cycle_id, item_key, attention_rank, "
                        " attention_score, realised_importance, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            cycle_id, str(key), i + 1,
                            float(score), 0.0, timestamp,
                        ),
                    )
                n += 1
            if self._conn is not None:
                self._conn.commit()
        return n

    def record_outcome(
        self,
        *,
        cycle_id: str,
        item_key: str,
        realised_importance: float,
        ts: float | None = None,
    ) -> bool:
        """Stamp the hindsight importance on an attended item.

        If the item was never attended, record it as a *miss* —
        ammunition for recall metrics.
        """
        if not cycle_id or not item_key:
            raise ValueError("cycle_id and item_key required")
        importance = max(0.0, min(1.0, float(realised_importance)))
        timestamp = float(ts if ts is not None else time.time())
        matched = False
        with self._lock:
            for item in self._attended:
                if (
                    item.cycle_id == cycle_id
                    and item.item_key == item_key
                ):
                    item.realised_importance = importance
                    matched = True
                    if self._conn is not None:
                        self._conn.execute(
                            "UPDATE attended "
                            "SET realised_importance = ? "
                            "WHERE cycle_id = ? AND item_key = ?",
                            (importance, cycle_id, item_key),
                        )
                    break
            if not matched:
                self._missed.append(
                    (cycle_id, item_key, importance, timestamp),
                )
                if self._conn is not None:
                    self._conn.execute(
                        "INSERT INTO missed"
                        "(cycle_id, item_key, "
                        " realised_importance, ts) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            cycle_id, item_key, importance, timestamp,
                        ),
                    )
            if self._conn is not None:
                self._conn.commit()
        return matched

    # ── Calibration ──────────────────────────────────────

    def calibrate(
        self,
        *,
        k: int = 5,
        since_ts: float | None = None,
    ) -> CalibrationReport:
        if k < 1:
            raise ValueError("k must be ≥ 1")
        with self._lock:
            attended = list(self._attended)
            missed = list(self._missed)
        if since_ts is not None:
            cutoff = float(since_ts)
            attended = [a for a in attended if a.ts >= cutoff]
            missed = [m for m in missed if m[3] >= cutoff]
        top_k = [a for a in attended if a.attention_rank <= k]
        important_in_top = [
            a for a in top_k
            if a.realised_importance >= self._importance_threshold
        ]
        all_important_attended = [
            a for a in attended
            if a.realised_importance >= self._importance_threshold
        ]
        important_missed = [
            m for m in missed
            if m[2] >= self._importance_threshold
        ]
        n_important = (
            len(all_important_attended) + len(important_missed)
        )
        precision = (
            len(important_in_top) / len(top_k) if top_k else 0.0
        )
        recall = (
            len(important_in_top) / n_important if n_important else 0.0
        )
        # rank-weighted relevance (nDCG-like): relevance at rank r is
        # realised_importance / log2(1 + r)
        dcg = 0.0
        for a in top_k:
            rel = a.realised_importance
            dcg += rel / math.log2(1 + a.attention_rank)
        ideal_sorted = sorted(
            (a.realised_importance for a in top_k),
            reverse=True,
        )
        idcg = sum(
            rel / math.log2(1 + r + 1)
            for r, rel in enumerate(ideal_sorted)
        )
        ndcg_like = dcg / idcg if idcg > 0 else 0.0
        avg_miss = (
            sum(m[2] for m in important_missed) / len(important_missed)
            if important_missed else 0.0
        )
        return CalibrationReport(
            precision_at_k=precision,
            recall_at_k=recall,
            ndcg_like=ndcg_like,
            avg_miss=avg_miss,
            n_attended=len(attended),
            n_important=n_important,
            k=k,
        )

    # ── Queries ──────────────────────────────────────────

    def by_cycle(self, cycle_id: str) -> list[AttendedItem]:
        with self._lock:
            out = [
                a for a in self._attended if a.cycle_id == cycle_id
            ]
        out.sort(key=lambda a: a.attention_rank)
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            n_attended = len(self._attended)
            n_missed = len(self._missed)
            cycles = len({a.cycle_id for a in self._attended})
        return {
            "n_attended_records": n_attended,
            "n_missed_records": n_missed,
            "distinct_cycles": cycles,
            "importance_threshold": self._importance_threshold,
        }

    def reset(self) -> int:
        with self._lock:
            n = len(self._attended) + len(self._missed)
            self._attended.clear()
            self._missed.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM attended")
                self._conn.execute("DELETE FROM missed")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
