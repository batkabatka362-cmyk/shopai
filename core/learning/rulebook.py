"""RuleBook — unified learned-rule ledger.

Track 1 of AGI_HARDENING_PLAN. Sprint 3 had three separate
learners (launch_learner, outcome_recorder, principle_extractor)
that each knew a piece but nobody had the full picture. The
RuleBook is the canonical place where a *promoted* rule lives:

    * origin         — learner that proposed it
    * pattern        — what situation the rule applies to
    * action         — what to do when pattern matches
    * evidence_count — how many episodes support it
    * applied_count  — how many times brain invoked it
    * win_rate_ema   — EMA of outcomes when applied (0..1)
    * status         — proposed | active | deprecated | killed
    * confidence     — derived from evidence + outcome quality

Thread-safe, SQLite-persisted at ``data/rulebook.db``. The
pattern_miner module (Track 1b) writes proposals here; the
outcome_recorder bumps applied_count + outcome_ema; owner
approves via Telegram dispatcher.

Pure stdlib. Deterministic under fixed ``now_fn``.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.learning.rulebook")


_EMA_ALPHA = 0.2
_MIN_EVIDENCE_FOR_ACTIVE = 5
_MIN_WIN_RATE_FOR_ACTIVE = 0.60
_KILL_AFTER_APPLIED = 10
_KILL_WIN_RATE_FLOOR = 0.30

_VALID_STATUS = ("proposed", "active", "deprecated", "killed")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    rule_id         TEXT PRIMARY KEY,
    origin          TEXT NOT NULL,
    pattern         TEXT NOT NULL,
    action          TEXT NOT NULL,
    evidence_count  INTEGER NOT NULL DEFAULT 0,
    applied_count   INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    win_rate_ema    REAL NOT NULL DEFAULT 0.5,
    status          TEXT NOT NULL DEFAULT 'proposed',
    created_ts      REAL NOT NULL,
    updated_ts      REAL NOT NULL,
    note            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_rules_status
    ON rules(status);
CREATE INDEX IF NOT EXISTS idx_rules_origin
    ON rules(origin);
"""


@dataclass
class Rule:
    rule_id: str
    origin: str
    pattern: str
    action: str
    evidence_count: int = 0
    applied_count: int = 0
    wins: int = 0
    win_rate_ema: float = 0.5
    status: str = "proposed"
    created_ts: float = 0.0
    updated_ts: float = 0.0
    note: str = ""

    @property
    def confidence(self) -> float:
        """Bayesian-ish confidence combining sample size +
        outcome quality. Scales 0..1."""
        sample = max(0, self.applied_count)
        # Wilson-style shrinkage toward 0.5
        n = float(sample) + 2.0
        bias = (self.win_rate_ema * sample + 0.5 * 2) / n
        coverage = 1.0 - 1.0 / math.sqrt(sample + 1.0)
        return max(0.0, min(1.0, bias * coverage))

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "origin": self.origin,
            "pattern": self.pattern,
            "action": self.action,
            "evidence_count": self.evidence_count,
            "applied_count": self.applied_count,
            "wins": self.wins,
            "win_rate_ema": round(self.win_rate_ema, 4),
            "status": self.status,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
            "note": self.note,
            "confidence": round(self.confidence, 4),
        }


class RuleBook:
    """Unified learned-rule ledger (Track 1)."""

    def __init__(
        self,
        db_path: str | Path = "data/rulebook.db",
        *,
        now_fn: Any = None,
        min_evidence_for_active: int = (
            _MIN_EVIDENCE_FOR_ACTIVE
        ),
        min_win_rate_for_active: float = (
            _MIN_WIN_RATE_FOR_ACTIVE
        ),
        kill_after_applied: int = _KILL_AFTER_APPLIED,
        kill_win_rate_floor: float = _KILL_WIN_RATE_FLOOR,
    ) -> None:
        if min_win_rate_for_active < 0 or (
            min_win_rate_for_active > 1
        ):
            raise ValueError(
                "min_win_rate_for_active must be in [0, 1]",
            )
        if min_evidence_for_active < 1:
            raise ValueError(
                "min_evidence_for_active must be ≥ 1",
            )
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        # RLock — `propose` and `record_outcome` hold the lock
        # across an atomic read-modify-write and then call
        # `_load` (which re-acquires) to build the return Rule.
        # A plain Lock would deadlock here.
        self._lock = threading.RLock()
        self._now_fn = now_fn or time.time
        self._min_evidence = int(min_evidence_for_active)
        self._min_wr = float(min_win_rate_for_active)
        self._kill_after = int(kill_after_applied)
        self._kill_floor = float(kill_win_rate_floor)
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Propose ──────────────────────────────────────────

    def propose(
        self,
        *,
        origin: str,
        pattern: str,
        action: str,
        evidence_count: int = 1,
        note: str = "",
    ) -> Rule:
        """Insert a new rule as status=proposed. Idempotent on
        (origin, pattern, action) — existing proposal gains
        evidence_count."""
        if not origin or not pattern or not action:
            raise ValueError(
                "origin + pattern + action required",
            )
        now = float(self._now_fn())
        with self._lock:
            row = self._conn.execute(
                "SELECT rule_id, evidence_count FROM rules "
                "WHERE origin=? AND pattern=? AND action=?",
                (origin, pattern, action),
            ).fetchone()
            if row is not None:
                rid, existing = row[0], int(row[1])
                new_evidence = existing + max(
                    1, int(evidence_count),
                )
                self._conn.execute(
                    "UPDATE rules SET evidence_count=?, "
                    "updated_ts=? WHERE rule_id=?",
                    (new_evidence, now, rid),
                )
                self._conn.commit()
                return self._load(rid)
            rid = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO rules("
                "rule_id, origin, pattern, action, "
                "evidence_count, created_ts, updated_ts, "
                "note) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid, origin, pattern, action,
                    max(1, int(evidence_count)),
                    now, now, note,
                ),
            )
            self._conn.commit()
        return self._load(rid)

    # ── Outcome ──────────────────────────────────────────

    def record_outcome(
        self,
        rule_id: str,
        *,
        won: bool,
    ) -> Rule:
        """Bump applied_count + wins + EMA. Auto-promote /
        auto-demote based on threshold rules."""
        now = float(self._now_fn())
        with self._lock:
            rule = self._load(rule_id)
            applied = rule.applied_count + 1
            wins = rule.wins + (1 if won else 0)
            ema = (
                _EMA_ALPHA * (1.0 if won else 0.0)
                + (1.0 - _EMA_ALPHA) * rule.win_rate_ema
            )
            # Threshold transitions
            status = rule.status
            if (
                status == "proposed"
                and rule.evidence_count
                + applied >= self._min_evidence
                and ema >= self._min_wr
            ):
                status = "active"
            elif (
                status == "active"
                and applied >= self._kill_after
                and ema < self._kill_floor
            ):
                status = "killed"
            self._conn.execute(
                "UPDATE rules SET applied_count=?, "
                "wins=?, win_rate_ema=?, status=?, "
                "updated_ts=? WHERE rule_id=?",
                (
                    applied, wins, ema, status,
                    now, rule_id,
                ),
            )
            self._conn.commit()
        return self._load(rule_id)

    # ── State transitions (owner-driven) ─────────────────

    def set_status(
        self, rule_id: str, status: str,
    ) -> Rule:
        if status not in _VALID_STATUS:
            raise ValueError(
                f"status must be in {_VALID_STATUS}",
            )
        now = float(self._now_fn())
        with self._lock:
            self._conn.execute(
                "UPDATE rules SET status=?, "
                "updated_ts=? WHERE rule_id=?",
                (status, now, rule_id),
            )
            self._conn.commit()
        return self._load(rule_id)

    # ── Queries ──────────────────────────────────────────

    def get(self, rule_id: str) -> Rule | None:
        try:
            return self._load(rule_id)
        except KeyError:
            return None

    def by_status(
        self,
        status: str,
        *,
        limit: int = 100,
    ) -> list[Rule]:
        if status not in _VALID_STATUS:
            raise ValueError(
                f"status must be in {_VALID_STATUS}",
            )
        with self._lock:
            rows = self._conn.execute(
                "SELECT rule_id FROM rules "
                "WHERE status=? "
                "ORDER BY updated_ts DESC LIMIT ?",
                (status, int(limit)),
            ).fetchall()
        return [self._load(r[0]) for r in rows]

    def top_by_confidence(
        self, *, limit: int = 20,
    ) -> list[Rule]:
        rules = [
            self._load(r[0])
            for r in self._all_rule_ids()
        ]
        rules.sort(
            key=lambda r: -r.confidence,
        )
        return rules[:int(limit)]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_status: dict[str, int] = {}
            for s, c in self._conn.execute(
                "SELECT status, COUNT(*) FROM rules "
                "GROUP BY status",
            ):
                by_status[s] = int(c)
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM rules",
            ).fetchone()[0])
        return {
            "total_rules": total,
            "by_status": by_status,
            "min_evidence_for_active": self._min_evidence,
            "min_win_rate_for_active": self._min_wr,
            "kill_after_applied": self._kill_after,
            "kill_win_rate_floor": self._kill_floor,
        }

    # ── Internals ────────────────────────────────────────

    def _load(self, rule_id: str) -> Rule:
        with self._lock:
            row = self._conn.execute(
                "SELECT rule_id, origin, pattern, action, "
                "evidence_count, applied_count, wins, "
                "win_rate_ema, status, created_ts, "
                "updated_ts, note FROM rules "
                "WHERE rule_id=?",
                (rule_id,),
            ).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return Rule(
            rule_id=row[0],
            origin=row[1],
            pattern=row[2],
            action=row[3],
            evidence_count=int(row[4]),
            applied_count=int(row[5]),
            wins=int(row[6]),
            win_rate_ema=float(row[7]),
            status=row[8],
            created_ts=float(row[9]),
            updated_ts=float(row[10]),
            note=row[11],
        )

    def _all_rule_ids(self) -> list[tuple[str]]:
        with self._lock:
            return list(self._conn.execute(
                "SELECT rule_id FROM rules",
            ))

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: RuleBook | None = None
_SINGLETON_LOCK = threading.Lock()


def get_rulebook() -> RuleBook:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = RuleBook()
    return _SINGLETON


def reset_rulebook_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset_rulebook close skipped: %s",
                    exc,
                )
        _SINGLETON = None
