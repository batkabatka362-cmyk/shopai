"""Session tracker — stitch interactions into coherent sessions.

The brain processes events one at a time. But an owner asks
"why did this customer drop off?" and the answer spans a whole
*session* — visit, browse, add-to-cart, abandonment, email, click,
retry. Without a session layer, every event is a context-free
atom.

SessionTracker keeps an in-memory + SQLite-backed map of
``actor_id → [Event, Event, ...]``. Events with a gap of more
than ``session_gap_s`` (default 30 min) spawn a new session.

APIs:

  append(actor_id, event)            → returns SessionId
  session(actor_id)                  → current session (list of events)
  sessions(actor_id, limit)          → recent sessions
  close_stale(gap_s=None)             → force-close sessions whose
                                         last event is older than gap;
                                         returns count closed

Each Event carries kind, timestamp, metadata. ``actor_id`` can be
a customer id, owner id, anon visitor id — the tracker doesn't
care. Sessions persist across restarts so cross-day funnel
analysis still works.

Pure Python + SQLite, thread-safe, zero LLM.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/sessions.db")
_SESSION_GAP = 30 * 60            # 30 minutes


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    actor_id     TEXT NOT NULL,
    started_at   REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    event_count  INTEGER NOT NULL DEFAULT 0,
    closed       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_actor ON sessions(actor_id,
                                                   last_seen_at DESC);
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL,
    meta_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_sess ON events(session_id, ts);
"""


@dataclass
class Event:
    kind: str
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ts": self.ts, "meta": self.meta}


@dataclass
class Session:
    id: str
    actor_id: str
    started_at: float
    last_seen_at: float
    event_count: int
    closed: bool = False
    events: list[Event] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.last_seen_at - self.started_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "actor_id": self.actor_id,
            "started_at": self.started_at,
            "last_seen_at": self.last_seen_at,
            "duration_s": round(self.duration_s, 2),
            "event_count": self.event_count,
            "closed": self.closed,
            "events": [e.as_dict() for e in self.events],
        }


# ── Tracker ─────────────────────────────────────────────────

class SessionTracker:
    def __init__(
        self,
        db_path: Path | str | None = None,
        session_gap_s: float = _SESSION_GAP,
    ) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._gap = float(session_gap_s)
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Append ──────────────────────────────────────────────

    def append(
        self, actor_id: str, event: Event | dict[str, Any],
    ) -> str:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("actor_id required")
        ev = (
            event if isinstance(event, Event)
            else Event(
                kind=str(event.get("kind", "event")),
                ts=float(event.get("ts", time.time())),
                meta=dict(event.get("meta", {})),
            )
        )
        with self._lock, self._connect() as conn:
            current = self._active_session(conn, actor_id)
            if current is None or (
                ev.ts - current[2] > self._gap  # last_seen_at
            ) or current[3]:                      # already closed
                sid = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO sessions "
                    "(id, actor_id, started_at, last_seen_at, "
                    " event_count, closed) "
                    "VALUES (?,?,?,?,0,0)",
                    (sid, actor_id, ev.ts, ev.ts),
                )
            else:
                sid = current[0]
            conn.execute(
                "INSERT INTO events (session_id, ts, kind, meta_json) "
                "VALUES (?,?,?,?)",
                (sid, ev.ts, ev.kind,
                 json.dumps(ev.meta, default=str)),
            )
            conn.execute(
                "UPDATE sessions SET last_seen_at=?, "
                "event_count=event_count+1 WHERE id=?",
                (ev.ts, sid),
            )
            conn.commit()
        return sid

    # ── Read ───────────────────────────────────────────────

    def session(self, actor_id: str) -> Session | None:
        """Most recent, still-open session for actor_id."""
        with self._connect() as conn:
            row = self._active_session(conn, actor_id.strip())
            if row is None:
                return None
            return self._load_session(conn, row[0])

    def sessions(
        self, actor_id: str, limit: int = 10,
    ) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM sessions WHERE actor_id=? "
                "ORDER BY last_seen_at DESC LIMIT ?",
                (actor_id.strip(), int(limit)),
            ).fetchall()
            return [self._load_session(conn, r[0]) for r in rows]

    def get(self, session_id: str) -> Session | None:
        with self._connect() as conn:
            return self._load_session(conn, session_id)

    def all_open(self) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM sessions WHERE closed=0 "
                "ORDER BY last_seen_at DESC"
            ).fetchall()
            return [self._load_session(conn, r[0]) for r in rows]

    # ── Maintenance ────────────────────────────────────────

    def close_stale(self, gap_s: float | None = None) -> int:
        cutoff = time.time() - float(gap_s if gap_s is not None else self._gap)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET closed=1 "
                "WHERE closed=0 AND last_seen_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount or 0

    def close_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET closed=1 WHERE id=?",
                (session_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0]
            open_ = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE closed=0"
            ).fetchone()[0]
            events = conn.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
            avg = conn.execute(
                "SELECT AVG(event_count) FROM sessions"
            ).fetchone()[0]
        return {
            "total_sessions": int(total or 0),
            "open_sessions": int(open_ or 0),
            "total_events": int(events or 0),
            "avg_events_per_session": round(float(avg or 0), 2),
        }

    # ── Internals ──────────────────────────────────────────

    def _active_session(
        self, conn: sqlite3.Connection, actor_id: str,
    ) -> tuple | None:
        return conn.execute(
            "SELECT id, started_at, last_seen_at, closed "
            "FROM sessions WHERE actor_id=? "
            "ORDER BY last_seen_at DESC LIMIT 1",
            (actor_id,),
        ).fetchone()

    def _load_session(
        self, conn: sqlite3.Connection, session_id: str,
    ) -> Session | None:
        row = conn.execute(
            "SELECT id, actor_id, started_at, last_seen_at, "
            "event_count, closed FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        ev_rows = conn.execute(
            "SELECT ts, kind, meta_json FROM events "
            "WHERE session_id=? ORDER BY ts",
            (session_id,),
        ).fetchall()
        events: list[Event] = []
        for ts, kind, meta_json in ev_rows:
            try:
                meta = json.loads(meta_json or "{}")
            except (json.JSONDecodeError, ValueError):
                meta = {}
            events.append(Event(
                kind=kind, ts=float(ts), meta=meta,
            ))
        return Session(
            id=row[0], actor_id=row[1],
            started_at=float(row[2]), last_seen_at=float(row[3]),
            event_count=int(row[4] or 0),
            closed=bool(row[5]),
            events=events,
        )
