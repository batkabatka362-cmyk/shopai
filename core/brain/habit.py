"""Habit formation — turn repeated successful actions into reflexes.

Every cycle re-evaluates every decision from scratch. That's the
right default when stakes are high, but pure reasoning is
expensive when the right answer has already fired successfully
200 times with no counter-evidence. Humans handle this via habits:
once a pattern is established, System 1 fires without thinking.

HabitLayer watches the stream of decisions and their outcomes.
When a ``(context_signature, action)`` pair meets thresholds:

  • fires  ≥ _MIN_FIRES (default 8)
  • win_rate ≥ _MIN_WIN_RATE (default 0.75)
  • zero recent failures in the last _FAILURE_WINDOW (default 14 d)

…it gets promoted to a Habit. A registered habit can be queried
via ``reflex(context_signature)`` for instant look-up, bypassing
the reasoner entirely in the dual-process fast path.

Habits can be *broken* automatically when a single failure
appears, or manually via ``break_habit(id, note)``. Broken habits
stay in the DB with a ``status=broken`` flag so the brain
remembers why it stopped relying on them.

Persistence: ``data/habits.db``. Zero LLM; pure counter math.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/habits.db")

_MIN_FIRES = 8
_MIN_WIN_RATE = 0.75
_FAILURE_WINDOW = 14 * 86_400       # 14 days

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signatures (
    signature       TEXT PRIMARY KEY,
    action          TEXT NOT NULL,
    fires           INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    last_fire       REAL NOT NULL DEFAULT 0,
    last_failure    REAL NOT NULL DEFAULT 0,
    habit_id        TEXT
);
CREATE TABLE IF NOT EXISTS habits (
    id              TEXT PRIMARY KEY,
    signature       TEXT NOT NULL,
    action          TEXT NOT NULL,
    confirmed_at    REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    break_reason    TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_sig_habit ON signatures(habit_id);
CREATE INDEX IF NOT EXISTS idx_habit_status ON habits(status);
"""


@dataclass
class Habit:
    id: str
    signature: str
    action: str
    confirmed_at: float
    status: str                    # active | broken
    break_reason: str = ""
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signature": self.signature,
            "action": self.action,
            "confirmed_at": self.confirmed_at,
            "status": self.status,
            "break_reason": self.break_reason,
            "notes": self.notes,
        }


@dataclass
class SignatureStats:
    signature: str
    action: str
    fires: int
    wins: int
    last_fire: float
    last_failure: float
    habit_id: str | None

    @property
    def win_rate(self) -> float:
        return self.wins / self.fires if self.fires > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "action": self.action,
            "fires": self.fires,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 3),
            "last_fire": self.last_fire,
            "last_failure": self.last_failure,
            "habit_id": self.habit_id,
        }


# ── Layer ───────────────────────────────────────────────────

class HabitLayer:
    def __init__(
        self,
        db_path: Path | str | None = None,
        min_fires: int = _MIN_FIRES,
        min_win_rate: float = _MIN_WIN_RATE,
        failure_window_s: float = _FAILURE_WINDOW,
    ) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._min_fires = int(min_fires)
        self._min_win_rate = float(min_win_rate)
        self._failure_window = float(failure_window_s)
        self._lock = threading.RLock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Observation ────────────────────────────────────────

    def observe(
        self,
        signature: str,
        action: str,
        success: bool,
        now: float | None = None,
    ) -> Habit | None:
        """Fold one (context, action, success) observation. Returns
        the Habit if this observation triggered a promotion (or None)."""
        now = now or time.time()
        signature = signature.strip()
        if not signature or not action:
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO signatures "
                "(signature, action, fires, wins, last_fire, last_failure) "
                "VALUES (?, ?, 1, ?, ?, ?) "
                "ON CONFLICT(signature) DO UPDATE SET "
                "  fires=fires+1, wins=wins+?, last_fire=?, "
                "  last_failure = CASE WHEN ? = 0 THEN ? ELSE last_failure END",
                (signature, action, 1 if success else 0, now,
                 0.0 if success else now,
                 1 if success else 0, now,
                 1 if success else 0, now),
            )
            row = conn.execute(
                "SELECT fires, wins, last_failure, habit_id "
                "FROM signatures WHERE signature=?",
                (signature,),
            ).fetchone()
            conn.commit()
        fires, wins, last_failure, habit_id = row
        # Failure inside a habit breaks it automatically
        if habit_id and not success:
            self._break_habit(habit_id, reason="failure after promotion")
            return None
        if habit_id:
            return None   # already promoted
        # Promotion check
        if fires < self._min_fires:
            return None
        win_rate = wins / fires
        if win_rate < self._min_win_rate:
            return None
        if last_failure and (now - last_failure) < self._failure_window:
            return None
        return self._promote(signature, action, now)

    # ── Reflex ─────────────────────────────────────────────

    def reflex(self, signature: str) -> Habit | None:
        """Instant look-up: is this context already a reflex?"""
        signature = signature.strip()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT h.id, h.signature, h.action, h.confirmed_at, "
                "h.status, h.break_reason, h.notes FROM habits h "
                "JOIN signatures s ON s.habit_id=h.id "
                "WHERE s.signature=? AND h.status='active'",
                (signature,),
            ).fetchone()
        return _row_to_habit(row) if row else None

    # ── Promotion / demotion ───────────────────────────────

    def _promote(
        self, signature: str, action: str, now: float,
    ) -> Habit:
        hid = uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO habits (id, signature, action, "
                "confirmed_at, status) VALUES (?,?,?,?, 'active')",
                (hid, signature, action, now),
            )
            conn.execute(
                "UPDATE signatures SET habit_id=? WHERE signature=?",
                (hid, signature),
            )
            conn.commit()
        return Habit(
            id=hid, signature=signature, action=action,
            confirmed_at=now, status="active",
        )

    def _break_habit(self, habit_id: str, reason: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE habits SET status='broken', break_reason=? "
                "WHERE id=?",
                (reason, habit_id),
            )
            conn.execute(
                "UPDATE signatures SET habit_id=NULL WHERE habit_id=?",
                (habit_id,),
            )
            conn.commit()

    def break_habit(
        self, habit_id: str, note: str = "",
    ) -> bool:
        self._break_habit(habit_id, reason=note or "manual")
        return True

    # ── Introspection ─────────────────────────────────────

    def active_habits(self, limit: int = 50) -> list[Habit]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, signature, action, confirmed_at, status, "
                "break_reason, notes FROM habits WHERE status='active' "
                "ORDER BY confirmed_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_habit(r) for r in rows]

    def broken_habits(self, limit: int = 20) -> list[Habit]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, signature, action, confirmed_at, status, "
                "break_reason, notes FROM habits WHERE status='broken' "
                "ORDER BY confirmed_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_habit(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            hab = conn.execute(
                "SELECT status, COUNT(*) FROM habits GROUP BY status"
            ).fetchall()
            sig = conn.execute(
                "SELECT COUNT(*), SUM(fires), SUM(wins) FROM signatures"
            ).fetchone()
        return {
            "habits": {s: int(c) for s, c in hab},
            "signatures": int(sig[0] or 0),
            "total_fires": int(sig[1] or 0),
            "total_wins": int(sig[2] or 0),
        }


def _row_to_habit(row: tuple) -> Habit:
    return Habit(
        id=row[0],
        signature=row[1],
        action=row[2],
        confirmed_at=float(row[3] or 0),
        status=row[4] or "active",
        break_reason=row[5] or "",
        notes=row[6] or "",
    )


# ── Signature helper ────────────────────────────────────────

def signature_for(features: dict[str, Any]) -> str:
    """Canonical signature string for a feature dict — stable across
    key order, lowercased, safe for use as a primary key."""
    parts = sorted(
        (k, str(v).strip().lower()) for k, v in features.items()
        if v is not None
    )
    return "|".join(f"{k}={v}" for k, v in parts)
