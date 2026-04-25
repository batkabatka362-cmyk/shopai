"""Time scheduler — calendar-aware "when to run what".

The daemon currently fires every cycle interval. Many things should
fire on a *clock*: weekly digest at 9am Sunday, kill sweep at the
end of every day, refund check every 6 hours. The time scheduler
turns a small DSL into deterministic ``due_at(now)`` calculations.

Schedule kinds:

  • interval(seconds)              — every N seconds since registration
  • daily(hour, minute=0)          — every day at HH:MM UTC
  • weekly(weekday, hour, minute)  — every weekday at HH:MM UTC
  • cron_lite("min hour dow")      — five-field-lite cron with * and N

Per task we keep ``last_run_ts`` so ``due()`` returns only tasks
whose next computed firing time has passed since their last run.

Pure stdlib, deterministic given clock.

Design decision: lives separately from action_queue. The queue is for
ad-hoc actions; this is for cyclic / clock-anchored ones. A scheduler
task can ENQUEUE an action when due — that's the bridge.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.time_scheduler")


Kind = Literal["interval", "daily", "weekly", "cron"]


@dataclass
class ScheduleSpec:
    name: str
    kind: Kind
    seconds: int = 0
    hour: int = 0
    minute: int = 0
    weekday: int = 0
    cron_pattern: str = ""
    last_run_ts: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "seconds": self.seconds,
            "hour": self.hour,
            "minute": self.minute,
            "weekday": self.weekday,
            "cron_pattern": self.cron_pattern,
            "last_run_ts": self.last_run_ts,
            "payload": dict(self.payload),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule (
    name          TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    seconds       INTEGER NOT NULL DEFAULT 0,
    hour          INTEGER NOT NULL DEFAULT 0,
    minute        INTEGER NOT NULL DEFAULT 0,
    weekday       INTEGER NOT NULL DEFAULT 0,
    cron_pattern  TEXT NOT NULL DEFAULT '',
    last_run_ts   REAL NOT NULL DEFAULT 0,
    payload       TEXT NOT NULL DEFAULT '{}'
);
"""


# ── Cron-lite parser ─────────────────────────────────────

_CRON_FIELD = re.compile(r"^(\*|\d+|\*/\d+)$")


def _cron_match(pattern: str, minute: int, hour: int, dow: int) -> bool:
    """Three-field cron-lite: ``minute hour dow``.
    * = any. N = exact match. */N = every N units (minute & hour only).
    """
    fields = pattern.strip().split()
    if len(fields) != 3:
        return False
    for field in fields:
        if not _CRON_FIELD.match(field):
            return False

    def field_hits(field: str, value: int, period: int | None = None) -> bool:
        if field == "*":
            return True
        if field.startswith("*/"):
            step = int(field[2:])
            if step <= 0 or period is None:
                return False
            return value % step == 0
        return int(field) == value

    return (
        field_hits(fields[0], minute, period=60)
        and field_hits(fields[1], hour, period=24)
        and field_hits(fields[2], dow, period=None)
    )


# ── Engine ────────────────────────────────────────────────

class TimeScheduler:
    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, ScheduleSpec] = {}
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
        import json
        with self._lock:
            for row in self._conn.execute(
                "SELECT name, kind, seconds, hour, minute, weekday, "
                "cron_pattern, last_run_ts, payload FROM schedule",
            ):
                try:
                    payload = json.loads(row[8] or "{}")
                except (json.JSONDecodeError, ValueError):
                    payload = {}
                self._tasks[row[0]] = ScheduleSpec(
                    name=row[0], kind=row[1],
                    seconds=int(row[2]),
                    hour=int(row[3]),
                    minute=int(row[4]),
                    weekday=int(row[5]),
                    cron_pattern=row[6] or "",
                    last_run_ts=float(row[7]),
                    payload=payload,
                )

    # ── Registration ─────────────────────────────────────

    def _persist(self, spec: ScheduleSpec) -> None:
        if self._conn is None:
            return
        import json
        self._conn.execute(
            "INSERT OR REPLACE INTO schedule"
            "(name, kind, seconds, hour, minute, weekday, "
            " cron_pattern, last_run_ts, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                spec.name, spec.kind, spec.seconds, spec.hour,
                spec.minute, spec.weekday, spec.cron_pattern,
                spec.last_run_ts,
                json.dumps(spec.payload, sort_keys=True),
            ),
        )
        self._conn.commit()

    def register_interval(
        self,
        name: str, seconds: int,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ScheduleSpec:
        if not name:
            raise ValueError("name required")
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        spec = ScheduleSpec(
            name=name, kind="interval",
            seconds=int(seconds),
            payload=dict(payload or {}),
        )
        with self._lock:
            self._tasks[name] = spec
            self._persist(spec)
        return spec

    def register_daily(
        self,
        name: str, *,
        hour: int, minute: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> ScheduleSpec:
        if not name:
            raise ValueError("name required")
        if not 0 <= hour < 24:
            raise ValueError("hour must be 0..23")
        if not 0 <= minute < 60:
            raise ValueError("minute must be 0..59")
        spec = ScheduleSpec(
            name=name, kind="daily",
            hour=int(hour), minute=int(minute),
            payload=dict(payload or {}),
        )
        with self._lock:
            self._tasks[name] = spec
            self._persist(spec)
        return spec

    def register_weekly(
        self,
        name: str, *,
        weekday: int, hour: int, minute: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> ScheduleSpec:
        if not name:
            raise ValueError("name required")
        if not 0 <= weekday < 7:
            raise ValueError("weekday must be 0..6 (0=Mon)")
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError("hour/minute out of range")
        spec = ScheduleSpec(
            name=name, kind="weekly",
            weekday=int(weekday),
            hour=int(hour), minute=int(minute),
            payload=dict(payload or {}),
        )
        with self._lock:
            self._tasks[name] = spec
            self._persist(spec)
        return spec

    def register_cron(
        self,
        name: str, pattern: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ScheduleSpec:
        if not name:
            raise ValueError("name required")
        if not _cron_pattern_valid(pattern):
            raise ValueError(
                "cron pattern must be 'min hour dow' "
                "with *, N, or */N",
            )
        spec = ScheduleSpec(
            name=name, kind="cron",
            cron_pattern=pattern.strip(),
            payload=dict(payload or {}),
        )
        with self._lock:
            self._tasks[name] = spec
            self._persist(spec)
        return spec

    def unregister(self, name: str) -> bool:
        with self._lock:
            present = name in self._tasks
            self._tasks.pop(name, None)
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM schedule WHERE name=?", (name,),
                )
                self._conn.commit()
        return present

    def tasks(self) -> list[ScheduleSpec]:
        return list(self._tasks.values())

    # ── Due check ────────────────────────────────────────

    def _is_due(self, spec: ScheduleSpec, now: float) -> bool:
        if spec.kind == "interval":
            return (now - spec.last_run_ts) >= spec.seconds
        struct = time.gmtime(now)
        if spec.kind == "daily":
            # Compute today's anchor; due if anchor passed since
            # last run, and we haven't already run after it.
            anchor = _anchor_today(now, spec.hour, spec.minute)
            return anchor <= now and spec.last_run_ts < anchor
        if spec.kind == "weekly":
            anchor = _anchor_this_week(
                now, spec.weekday, spec.hour, spec.minute,
            )
            return anchor <= now and spec.last_run_ts < anchor
        if spec.kind == "cron":
            # Tick by the calendar minute — fire if pattern matches
            # AND we haven't already fired this minute.
            same_minute = (
                int(spec.last_run_ts // 60) == int(now // 60)
            )
            if same_minute:
                return False
            return _cron_match(
                spec.cron_pattern,
                struct.tm_min, struct.tm_hour, struct.tm_wday,
            )
        return False

    def due(self, now: float | None = None) -> list[ScheduleSpec]:
        now = float(now if now is not None else time.time())
        with self._lock:
            return [s for s in self._tasks.values() if self._is_due(s, now)]

    def mark_ran(
        self, name: str, *, ts: float | None = None,
    ) -> bool:
        ts = float(ts if ts is not None else time.time())
        with self._lock:
            spec = self._tasks.get(name)
            if spec is None:
                return False
            spec.last_run_ts = ts
            self._persist(spec)
        return True

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for s in self._tasks.values():
                counts[s.kind] = counts.get(s.kind, 0) + 1
        return {
            "total_tasks": len(self._tasks),
            "by_kind": counts,
        }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ── Anchor calculations (UTC) ─────────────────────────────

def _anchor_today(now: float, hour: int, minute: int) -> float:
    """Today's UTC HH:MM as a unix timestamp."""
    t = time.gmtime(now)
    midnight = now - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
    return midnight + hour * 3600 + minute * 60


def _anchor_this_week(
    now: float, weekday: int, hour: int, minute: int,
) -> float:
    """The anchor weekday's HH:MM in the current calendar week (UTC).

    weekday uses Python convention: 0=Monday … 6=Sunday.
    """
    t = time.gmtime(now)
    midnight = now - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
    # Roll back to Monday of this week
    monday = midnight - t.tm_wday * 86_400
    return monday + weekday * 86_400 + hour * 3600 + minute * 60


# ── Validation ────────────────────────────────────────────

def _cron_pattern_valid(pattern: str) -> bool:
    fields = (pattern or "").strip().split()
    if len(fields) != 3:
        return False
    for f in fields:
        if not _CRON_FIELD.match(f):
            return False
    return True
