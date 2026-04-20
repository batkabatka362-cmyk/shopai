"""Memory consolidator — Episode → Concept → Procedure ladder.

Track 2 of AGI_HARDENING_PLAN. Sprint 1-3 shipped episodic
memory (IntelligentMemory L0-L5) but nobody promotes recurring
episodes into semantic concepts or concepts into procedures. The
consolidator does that ladder walk on a periodic sweep.

Ladder rules (deterministic, tunable):

  * ``episodic → semantic``: when ≥ min_episodes_for_concept
    episodes share the same canonical signature within the
    lookback window, promote to a Concept with evidence_count
    equal to the episode count.
  * ``semantic → procedural``: when a Concept has been
    referenced (by rule applications or recall) ≥
    min_concept_refs_for_procedure times with successful
    outcome ≥ min_success_rate, promote to a Procedure
    (canonical "this is how we do X").
  * ``staleness decay``: memories untouched longer than
    ``stale_after_s`` lose priority (priority halves); rows
    at priority <= cold_floor are archived to the cold table.

Pure stdlib, SQLite-persisted at ``data/memory_consolidator.db``.
Thread-safe (RLock — same pattern as RuleBook: public methods
hold the lock and call private readers that re-acquire).
Deterministic under fixed ``now_fn``.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("core.memory.consolidator")


_DEFAULT_MIN_EPISODES = 3
_DEFAULT_LOOKBACK_S = 30 * 24 * 3600.0
_DEFAULT_MIN_CONCEPT_REFS = 10
_DEFAULT_MIN_SUCCESS_RATE = 0.70
_DEFAULT_STALE_AFTER_S = 90 * 24 * 3600.0
_DEFAULT_COLD_FLOOR = 0.1


_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id   TEXT PRIMARY KEY,
    signature    TEXT NOT NULL,
    outcome_ok   INTEGER NOT NULL DEFAULT 0,
    payload      TEXT NOT NULL DEFAULT '{}',
    ts           REAL NOT NULL,
    consolidated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ep_sig_ts
    ON episodes(signature, ts);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id       TEXT PRIMARY KEY,
    signature        TEXT UNIQUE NOT NULL,
    evidence_count   INTEGER NOT NULL DEFAULT 0,
    refs             INTEGER NOT NULL DEFAULT 0,
    success_count    INTEGER NOT NULL DEFAULT 0,
    fail_count       INTEGER NOT NULL DEFAULT 0,
    priority         REAL NOT NULL DEFAULT 1.0,
    last_access_ts   REAL NOT NULL,
    promoted_ts      REAL NOT NULL,
    promoted_to_procedure INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cc_sig
    ON concepts(signature);

CREATE TABLE IF NOT EXISTS procedures (
    procedure_id   TEXT PRIMARY KEY,
    signature      TEXT UNIQUE NOT NULL,
    from_concept   TEXT NOT NULL,
    refs           INTEGER NOT NULL DEFAULT 0,
    success_rate   REAL NOT NULL DEFAULT 0,
    promoted_ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proc_sig
    ON procedures(signature);

CREATE TABLE IF NOT EXISTS cold_archive (
    memory_id    TEXT PRIMARY KEY,
    layer        TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    archived_ts  REAL NOT NULL
);
"""


@dataclass
class Episode:
    episode_id: str
    signature: str
    outcome_ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0
    consolidated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "signature": self.signature,
            "outcome_ok": self.outcome_ok,
            "payload": dict(self.payload),
            "ts": self.ts,
            "consolidated": self.consolidated,
        }


@dataclass
class Concept:
    concept_id: str
    signature: str
    evidence_count: int
    refs: int = 0
    success_count: int = 0
    fail_count: int = 0
    priority: float = 1.0
    last_access_ts: float = 0.0
    promoted_ts: float = 0.0
    promoted_to_procedure: bool = False

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "signature": self.signature,
            "evidence_count": self.evidence_count,
            "refs": self.refs,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "priority": round(self.priority, 4),
            "success_rate": round(self.success_rate, 4),
            "last_access_ts": self.last_access_ts,
            "promoted_ts": self.promoted_ts,
            "promoted_to_procedure": (
                self.promoted_to_procedure
            ),
        }


@dataclass
class Procedure:
    procedure_id: str
    signature: str
    from_concept: str
    refs: int = 0
    success_rate: float = 0.0
    promoted_ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "signature": self.signature,
            "from_concept": self.from_concept,
            "refs": self.refs,
            "success_rate": round(self.success_rate, 4),
            "promoted_ts": self.promoted_ts,
        }


@dataclass
class ConsolidationReport:
    episodes_seen: int
    concepts_promoted: int
    procedures_promoted: int
    stale_decayed: int
    cold_archived: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "episodes_seen": self.episodes_seen,
            "concepts_promoted": self.concepts_promoted,
            "procedures_promoted": (
                self.procedures_promoted
            ),
            "stale_decayed": self.stale_decayed,
            "cold_archived": self.cold_archived,
        }


class MemoryConsolidator:
    """Episode → Concept → Procedure consolidator (Track 2)."""

    def __init__(
        self,
        db_path: str | Path = (
            "data/memory_consolidator.db"
        ),
        *,
        min_episodes_for_concept: int = (
            _DEFAULT_MIN_EPISODES
        ),
        lookback_s: float = _DEFAULT_LOOKBACK_S,
        min_concept_refs_for_procedure: int = (
            _DEFAULT_MIN_CONCEPT_REFS
        ),
        min_success_rate: float = _DEFAULT_MIN_SUCCESS_RATE,
        stale_after_s: float = _DEFAULT_STALE_AFTER_S,
        cold_floor: float = _DEFAULT_COLD_FLOOR,
        now_fn: Any = None,
    ) -> None:
        for name, v, minimum in (
            (
                "min_episodes_for_concept",
                min_episodes_for_concept, 1,
            ),
            (
                "min_concept_refs_for_procedure",
                min_concept_refs_for_procedure, 1,
            ),
        ):
            if v < minimum:
                raise ValueError(
                    f"{name} must be ≥ {minimum}",
                )
        for name, v in (
            ("min_success_rate", min_success_rate),
            ("cold_floor", cold_floor),
        ):
            if not 0.0 <= v <= 1.0:
                raise ValueError(
                    f"{name} must be in [0, 1]",
                )
        if lookback_s <= 0 or stale_after_s <= 0:
            raise ValueError(
                "lookback_s and stale_after_s must be > 0",
            )
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.RLock()
        self._now_fn = now_fn or time.time
        self._min_ep = int(min_episodes_for_concept)
        self._lookback = float(lookback_s)
        self._min_refs = int(
            min_concept_refs_for_procedure,
        )
        self._min_success = float(min_success_rate)
        self._stale_after = float(stale_after_s)
        self._cold_floor = float(cold_floor)
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Signature helper ─────────────────────────────────

    @staticmethod
    def signature_of(**fields: Any) -> str:
        """Stable canonical signature from arbitrary fields."""
        blob = json.dumps(
            {k: str(v) for k, v in fields.items()},
            sort_keys=True,
        )
        return hashlib.sha1(
            blob.encode("utf-8"),
        ).hexdigest()[:16]

    # ── Record episode ───────────────────────────────────

    def record_episode(
        self,
        *,
        signature: str,
        outcome_ok: bool,
        payload: dict[str, Any] | None = None,
    ) -> Episode:
        if not signature:
            raise ValueError("signature required")
        now = float(self._now_fn())
        eid = uuid.uuid4().hex
        body = json.dumps(payload or {}, sort_keys=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodes("
                "episode_id, signature, outcome_ok, "
                "payload, ts) VALUES(?, ?, ?, ?, ?)",
                (
                    eid, signature,
                    1 if outcome_ok else 0,
                    body, now,
                ),
            )
            self._conn.commit()
        return Episode(
            episode_id=eid,
            signature=signature,
            outcome_ok=outcome_ok,
            payload=dict(payload or {}),
            ts=now,
        )

    def reference_concept(
        self, signature: str, *, success: bool,
    ) -> Concept | None:
        """Called when the brain applies a concept's rule. Bumps
        refs + success/fail counters + refreshes last_access."""
        now = float(self._now_fn())
        with self._lock:
            row = self._conn.execute(
                "SELECT concept_id FROM concepts "
                "WHERE signature=?",
                (signature,),
            ).fetchone()
            if row is None:
                return None
            cid = row[0]
            if success:
                self._conn.execute(
                    "UPDATE concepts SET refs = refs + 1, "
                    "success_count = success_count + 1, "
                    "last_access_ts=? WHERE concept_id=?",
                    (now, cid),
                )
            else:
                self._conn.execute(
                    "UPDATE concepts SET refs = refs + 1, "
                    "fail_count = fail_count + 1, "
                    "last_access_ts=? WHERE concept_id=?",
                    (now, cid),
                )
            self._conn.commit()
        return self._load_concept(cid)

    # ── Consolidate ──────────────────────────────────────

    def consolidate(self) -> ConsolidationReport:
        """Run one ladder sweep: promote episodes → concepts →
        procedures; decay stale; archive cold."""
        now = float(self._now_fn())
        cutoff = now - self._lookback
        report = ConsolidationReport(
            episodes_seen=0,
            concepts_promoted=0,
            procedures_promoted=0,
            stale_decayed=0,
            cold_archived=0,
        )
        # Episode → Concept
        with self._lock:
            rows = self._conn.execute(
                "SELECT signature, COUNT(*), "
                "SUM(outcome_ok) FROM episodes "
                "WHERE consolidated=0 AND ts >= ? "
                "GROUP BY signature HAVING COUNT(*) >= ?",
                (cutoff, self._min_ep),
            ).fetchall()
            report.episodes_seen = sum(
                int(r[1]) for r in rows
            )
            for sig, count, wins in rows:
                count = int(count)
                wins = int(wins or 0)
                existing = self._conn.execute(
                    "SELECT concept_id FROM concepts "
                    "WHERE signature=?",
                    (sig,),
                ).fetchone()
                if existing is None:
                    cid = uuid.uuid4().hex
                    self._conn.execute(
                        "INSERT INTO concepts("
                        "concept_id, signature, "
                        "evidence_count, success_count, "
                        "fail_count, priority, "
                        "last_access_ts, promoted_ts) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            cid, sig, count, wins,
                            count - wins, 1.0, now, now,
                        ),
                    )
                    report.concepts_promoted += 1
                else:
                    cid = existing[0]
                    self._conn.execute(
                        "UPDATE concepts SET "
                        "evidence_count="
                        "evidence_count + ?, "
                        "success_count="
                        "success_count + ?, "
                        "fail_count="
                        "fail_count + ?, "
                        "last_access_ts=? "
                        "WHERE concept_id=?",
                        (
                            count, wins,
                            count - wins, now, cid,
                        ),
                    )
                # Mark the source episodes as consolidated
                self._conn.execute(
                    "UPDATE episodes SET consolidated=1 "
                    "WHERE signature=? AND ts >= ?",
                    (sig, cutoff),
                )
            # Concept → Procedure
            proc_rows = self._conn.execute(
                "SELECT concept_id, signature, refs, "
                "success_count, fail_count FROM concepts "
                "WHERE promoted_to_procedure=0 "
                "AND refs >= ?",
                (self._min_refs,),
            ).fetchall()
            for cid, sig, refs, succ, fail in proc_rows:
                total = int(succ) + int(fail)
                rate = (
                    int(succ) / total if total > 0 else 0.0
                )
                if rate < self._min_success:
                    continue
                pid = uuid.uuid4().hex
                self._conn.execute(
                    "INSERT OR IGNORE INTO procedures("
                    "procedure_id, signature, "
                    "from_concept, refs, success_rate, "
                    "promoted_ts) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        pid, sig, cid,
                        int(refs), rate, now,
                    ),
                )
                self._conn.execute(
                    "UPDATE concepts SET "
                    "promoted_to_procedure=1 "
                    "WHERE concept_id=?",
                    (cid,),
                )
                report.procedures_promoted += 1
            # Staleness decay
            stale_cutoff = now - self._stale_after
            decay_rows = self._conn.execute(
                "SELECT concept_id, priority "
                "FROM concepts "
                "WHERE last_access_ts < ?",
                (stale_cutoff,),
            ).fetchall()
            for cid, prio in decay_rows:
                new_prio = max(
                    0.0, float(prio) * 0.5,
                )
                self._conn.execute(
                    "UPDATE concepts SET priority=? "
                    "WHERE concept_id=?",
                    (new_prio, cid),
                )
                report.stale_decayed += 1
                if new_prio <= self._cold_floor:
                    row = self._conn.execute(
                        "SELECT * FROM concepts "
                        "WHERE concept_id=?",
                        (cid,),
                    ).fetchone()
                    if row is not None:
                        self._conn.execute(
                            "INSERT OR REPLACE INTO "
                            "cold_archive("
                            "memory_id, layer, payload, "
                            "archived_ts) VALUES"
                            "(?, 'concept', ?, ?)",
                            (
                                cid,
                                json.dumps(
                                    {
                                        "signature":
                                            row[1],
                                        "evidence":
                                            row[2],
                                    },
                                ),
                                now,
                            ),
                        )
                        self._conn.execute(
                            "DELETE FROM concepts "
                            "WHERE concept_id=?",
                            (cid,),
                        )
                        report.cold_archived += 1
            self._conn.commit()
        return report

    # ── Queries ──────────────────────────────────────────

    def get_concept(
        self, signature: str,
    ) -> Concept | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT concept_id FROM concepts "
                "WHERE signature=?",
                (signature,),
            ).fetchone()
        return self._load_concept(row[0]) if row else None

    def concepts(
        self, *, limit: int = 50,
    ) -> list[Concept]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT concept_id FROM concepts "
                "ORDER BY priority DESC, "
                "evidence_count DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            self._load_concept(r[0]) for r in rows
        ]

    def procedures(
        self, *, limit: int = 50,
    ) -> list[Procedure]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT procedure_id, signature, "
                "from_concept, refs, success_rate, "
                "promoted_ts FROM procedures "
                "ORDER BY success_rate DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            Procedure(
                procedure_id=r[0],
                signature=r[1],
                from_concept=r[2],
                refs=int(r[3]),
                success_rate=float(r[4]),
                promoted_ts=float(r[5]),
            )
            for r in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            def _count(table: str) -> int:
                return int(self._conn.execute(
                    f"SELECT COUNT(*) FROM {table}",
                ).fetchone()[0])
            return {
                "episodes": _count("episodes"),
                "concepts": _count("concepts"),
                "procedures": _count("procedures"),
                "cold_archive": _count("cold_archive"),
                "min_episodes_for_concept": self._min_ep,
                "min_concept_refs_for_procedure": (
                    self._min_refs
                ),
                "min_success_rate": self._min_success,
                "stale_after_s": self._stale_after,
            }

    # ── Internals ────────────────────────────────────────

    def _load_concept(
        self, concept_id: str,
    ) -> Concept:
        with self._lock:
            row = self._conn.execute(
                "SELECT concept_id, signature, "
                "evidence_count, refs, success_count, "
                "fail_count, priority, last_access_ts, "
                "promoted_ts, promoted_to_procedure "
                "FROM concepts WHERE concept_id=?",
                (concept_id,),
            ).fetchone()
        if row is None:
            raise KeyError(concept_id)
        return Concept(
            concept_id=row[0],
            signature=row[1],
            evidence_count=int(row[2]),
            refs=int(row[3]),
            success_count=int(row[4]),
            fail_count=int(row[5]),
            priority=float(row[6]),
            last_access_ts=float(row[7]),
            promoted_ts=float(row[8]),
            promoted_to_procedure=bool(row[9]),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: MemoryConsolidator | None = None
_SINGLETON_LOCK = threading.Lock()


def get_consolidator() -> MemoryConsolidator:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = MemoryConsolidator()
    return _SINGLETON


def reset_consolidator_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset consolidator close "
                    "skipped: %s",
                    exc,
                )
        _SINGLETON = None
