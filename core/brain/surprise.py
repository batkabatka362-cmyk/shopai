"""Surprise detector — novelty & anomaly signal for the brain.

The world model (v7-D1) predicts P(outcome|action,context) with a
running mean + stdev. An event is *surprising* when it lands
outside that band. Surprise is the signal that should:

  • Force the dual-process router (v7-D7) into System 2.
  • Raise the event's salience inside working memory (v7-D4) so
    the reasoner sees it.
  • Trigger ``deepen(event_id)`` — queue a counterfactual /
    debate / retrospective pass specifically on the anomaly.

Two surprise families:

  1. *Quantitative* — numerical outcome vs world-model mean:
     z = (observed − mean) / stdev. |z| ≥ 2 is the default
     threshold.
  2. *Categorical / structural* — a triple (category, action,
     outcome_kind) never seen before, or seen in <N prior cases.

We also recency-decay: a repeat of a formerly-surprising event is
less surprising the second time. Implemented as a streaming
``seen_count`` per signature.

Persistence: ``data/surprise.db`` — surprises + followup queue.
Thread-safe, zero LLM.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/surprise.db")

_Z_THRESHOLD = 2.0           # |z| ≥ this → surprising
_NOVEL_UNTIL = 3             # seen < this → novel signature

_SCHEMA = """
CREATE TABLE IF NOT EXISTS surprises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      REAL NOT NULL,
    signature       TEXT NOT NULL,
    kind            TEXT NOT NULL,
    z_score         REAL,
    magnitude       REAL NOT NULL,
    observed        REAL,
    expected_mean   REAL,
    expected_stdev  REAL,
    narrative       TEXT,
    followup_state  TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS signatures (
    signature   TEXT PRIMARY KEY,
    seen_count  INTEGER NOT NULL DEFAULT 0,
    last_seen   REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_followup
    ON surprises(followup_state, created_at DESC);
"""


@dataclass
class SurpriseEvent:
    id: int
    created_at: float
    signature: str
    kind: str              # "outlier" | "novel"
    z_score: float | None
    magnitude: float                # 0-1, normalised surprise strength
    observed: float | None
    expected_mean: float | None
    expected_stdev: float | None
    narrative: str
    followup_state: str             # pending | resolved | dismissed

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "signature": self.signature,
            "kind": self.kind,
            "z_score": None if self.z_score is None
                         else round(self.z_score, 2),
            "magnitude": round(self.magnitude, 3),
            "observed": self.observed,
            "expected_mean": self.expected_mean,
            "expected_stdev": self.expected_stdev,
            "narrative": self.narrative,
            "followup_state": self.followup_state,
        }


# ── Detector ────────────────────────────────────────────────

class SurpriseDetector:
    def __init__(
        self,
        db_path: Path | str | None = None,
        z_threshold: float = _Z_THRESHOLD,
        novel_until: int = _NOVEL_UNTIL,
    ) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._z_th = float(z_threshold)
        self._novel_until = int(novel_until)
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Observation ─────────────────────────────────────────

    def observe(
        self,
        signature: str,
        observed: float | None = None,
        expected_mean: float | None = None,
        expected_stdev: float | None = None,
        narrative: str = "",
    ) -> SurpriseEvent | None:
        """Feed one outcome in. Returns a SurpriseEvent iff the
        observation qualifies as surprising, else ``None``."""
        signature = signature.strip()
        if not signature:
            return None
        seen = self._bump_signature(signature)
        # Case 1: numeric outlier
        if (observed is not None and expected_mean is not None
                and expected_stdev is not None
                and expected_stdev > 0):
            z = (observed - expected_mean) / expected_stdev
            if abs(z) >= self._z_th:
                mag = min(1.0, abs(z) / (self._z_th * 2))
                return self._record(
                    signature=signature, kind="outlier", z_score=z,
                    magnitude=mag, observed=observed,
                    expected_mean=expected_mean,
                    expected_stdev=expected_stdev,
                    narrative=narrative or _outlier_narrative(
                        signature, z, observed, expected_mean,
                    ),
                )
        # Case 2: novel signature (first few observations)
        if seen <= self._novel_until:
            mag = max(0.3, 1.0 - (seen - 1) / self._novel_until)
            return self._record(
                signature=signature, kind="novel", z_score=None,
                magnitude=mag, observed=observed,
                expected_mean=expected_mean,
                expected_stdev=expected_stdev,
                narrative=narrative or
                    f"novel signature (seen {seen}x)",
            )
        return None

    # ── Followup queue ─────────────────────────────────────

    def pending_followups(self, limit: int = 20) -> list[SurpriseEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, signature, kind, z_score, "
                "magnitude, observed, expected_mean, expected_stdev, "
                "narrative, followup_state FROM surprises "
                "WHERE followup_state='pending' "
                "ORDER BY magnitude DESC, created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    def resolve(self, surprise_id: int, note: str = "") -> bool:
        return self._set_state(surprise_id, "resolved", note)

    def dismiss(self, surprise_id: int, note: str = "") -> bool:
        return self._set_state(surprise_id, "dismissed", note)

    def _set_state(
        self, surprise_id: int, state: str, note: str,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE surprises SET followup_state=?, "
                "narrative = COALESCE(narrative, '') || "
                "    CASE WHEN ? = '' THEN '' ELSE '\n--\n' || ? END "
                "WHERE id=?",
                (state, note, note, surprise_id),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Introspection ─────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM surprises"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM surprises "
                "WHERE followup_state='pending'"
            ).fetchone()[0]
            top = conn.execute(
                "SELECT signature, COUNT(*) c FROM surprises "
                "GROUP BY signature ORDER BY c DESC LIMIT 5"
            ).fetchall()
        return {
            "total_surprises": int(total or 0),
            "pending_followups": int(pending or 0),
            "top_surprising_signatures": [
                {"signature": s, "count": int(c)} for s, c in top
            ],
        }

    # ── Internals ──────────────────────────────────────────

    def _bump_signature(self, signature: str) -> int:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO signatures (signature, seen_count, last_seen) "
                "VALUES (?, 1, ?) "
                "ON CONFLICT(signature) DO UPDATE SET "
                "  seen_count=seen_count+1, last_seen=?",
                (signature, time.time(), time.time()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT seen_count FROM signatures WHERE signature=?",
                (signature,),
            ).fetchone()
        return int(row[0]) if row else 1

    def _record(
        self,
        *,
        signature: str,
        kind: str,
        z_score: float | None,
        magnitude: float,
        observed: float | None,
        expected_mean: float | None,
        expected_stdev: float | None,
        narrative: str,
    ) -> SurpriseEvent:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO surprises "
                "(created_at, signature, kind, z_score, magnitude, "
                " observed, expected_mean, expected_stdev, narrative) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), signature, kind, z_score, magnitude,
                 observed, expected_mean, expected_stdev, narrative),
            )
            sid = int(cur.lastrowid or 0)
            conn.commit()
        return SurpriseEvent(
            id=sid, created_at=time.time(), signature=signature,
            kind=kind, z_score=z_score, magnitude=magnitude,
            observed=observed, expected_mean=expected_mean,
            expected_stdev=expected_stdev, narrative=narrative,
            followup_state="pending",
        )


def _outlier_narrative(
    signature: str, z: float, observed: float, expected: float,
) -> str:
    direction = "higher" if z > 0 else "lower"
    return (f"{signature}: observed {observed:.2f} is "
            f"{abs(z):.2f}σ {direction} than expected {expected:.2f}")


def _row_to_event(row: tuple) -> SurpriseEvent:
    return SurpriseEvent(
        id=int(row[0]),
        created_at=float(row[1]),
        signature=row[2],
        kind=row[3],
        z_score=None if row[4] is None else float(row[4]),
        magnitude=float(row[5] or 0.0),
        observed=None if row[6] is None else float(row[6]),
        expected_mean=None if row[7] is None else float(row[7]),
        expected_stdev=None if row[8] is None else float(row[8]),
        narrative=row[9] or "",
        followup_state=row[10] or "pending",
    )


# ── Singleton ────────────────────────────────────────────────

_SD_LOCK = threading.Lock()
_SD: SurpriseDetector | None = None


def surprise_detector() -> SurpriseDetector:
    global _SD
    if _SD is None:
        with _SD_LOCK:
            if _SD is None:
                _SD = SurpriseDetector()
    return _SD
