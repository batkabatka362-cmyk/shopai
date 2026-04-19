"""Action queue — durable priority queue of pending actions.

workflow_dag runs a graph *now*. action_queue stores the actions that
should fire *eventually* — between cycles, after a delay, when a
dependency completes. It survives daemon restarts, supports
priorities + delays + dependencies + retries, and exposes a clean
``next_due()`` API the daemon polls.

Each action has:

  • id         — caller-supplied or auto-generated
  • kind       — opaque label (e.g. "kill_ad", "publish_product")
  • payload    — dict the executor receives
  • priority   — higher = sooner (default 0)
  • run_at     — unix ts; defaults to "now"
  • depends_on — tuple of action ids that must reach "done" first
  • retries    — remaining attempt budget after the first try
  • status     — pending | running | done | failed | cancelled

Status transitions are explicit: ``mark_running``, ``mark_done``,
``mark_failed``, ``cancel``. Retries are decremented on
``mark_failed`` — when the budget is exhausted the action stops.

SQLite-persisted, thread-safe, deterministic. Pure stdlib.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal


Status = Literal["pending", "running", "done", "failed", "cancelled"]


@dataclass
class QueuedAction:
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    run_at: float = 0.0
    depends_on: tuple[str, ...] = ()
    retries: int = 0
    status: Status = "pending"
    last_error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "priority": self.priority,
            "run_at": self.run_at,
            "depends_on": list(self.depends_on),
            "retries": self.retries,
            "status": self.status,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    priority     INTEGER NOT NULL DEFAULT 0,
    run_at       REAL NOT NULL,
    depends_on   TEXT NOT NULL DEFAULT '',
    retries      INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',
    last_error   TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_status_run
    ON actions(status, run_at);
CREATE INDEX IF NOT EXISTS idx_actions_kind
    ON actions(kind);
"""


def _row_to_action(row: tuple[Any, ...]) -> QueuedAction:
    try:
        payload = json.loads(row[2] or "{}")
    except (json.JSONDecodeError, ValueError):
        payload = {}
    deps = tuple(s for s in str(row[5] or "").split(",") if s)
    return QueuedAction(
        id=row[0], kind=row[1], payload=payload,
        priority=int(row[3]),
        run_at=float(row[4]),
        depends_on=deps,
        retries=int(row[6]),
        status=row[7],
        last_error=row[8] or "",
        created_at=float(row[9]),
        updated_at=float(row[10]),
    )


class ActionQueue:
    def __init__(
        self,
        db_path: str | Path = "data/action_queue.db",
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Enqueue ──────────────────────────────────────────

    def enqueue(
        self,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        delay_s: float = 0.0,
        run_at: float | None = None,
        depends_on: Iterable[str] = (),
        retries: int = 0,
        action_id: str | None = None,
    ) -> QueuedAction:
        if not kind:
            raise ValueError("kind required")
        if retries < 0:
            raise ValueError("retries must be ≥ 0")
        now = time.time()
        rid = action_id or uuid.uuid4().hex
        scheduled = (
            float(run_at) if run_at is not None
            else now + max(0.0, float(delay_s))
        )
        deps = tuple(str(d) for d in depends_on if d)
        action = QueuedAction(
            id=rid, kind=kind,
            payload=dict(payload or {}),
            priority=int(priority),
            run_at=scheduled,
            depends_on=deps,
            retries=int(retries),
            status="pending",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO actions(id, kind, payload, priority, "
                "run_at, depends_on, retries, status, last_error, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid, kind, json.dumps(action.payload),
                    action.priority, action.run_at,
                    ",".join(deps), action.retries,
                    action.status, action.last_error,
                    action.created_at, action.updated_at,
                ),
            )
            self._conn.commit()
        return action

    # ── Lookups ──────────────────────────────────────────

    def get(self, action_id: str) -> QueuedAction | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, kind, payload, priority, run_at, "
                "depends_on, retries, status, last_error, "
                "created_at, updated_at FROM actions WHERE id=?",
                (action_id,),
            ).fetchone()
        return _row_to_action(row) if row else None

    def by_status(
        self, status: Status,
        *, limit: int = 100,
    ) -> list[QueuedAction]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, kind, payload, priority, run_at, "
                "depends_on, retries, status, last_error, "
                "created_at, updated_at FROM actions "
                "WHERE status=? ORDER BY run_at ASC LIMIT ?",
                (status, int(limit)),
            ).fetchall()
        return [_row_to_action(r) for r in rows]

    def next_due(
        self, now: float | None = None, limit: int = 10,
    ) -> list[QueuedAction]:
        """Pending actions whose run_at has passed AND whose
        dependencies are all 'done'. Sorted by priority desc, then
        run_at asc."""
        now = now if now is not None else time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, kind, payload, priority, run_at, "
                "depends_on, retries, status, last_error, "
                "created_at, updated_at FROM actions "
                "WHERE status='pending' AND run_at <= ? "
                "ORDER BY priority DESC, run_at ASC",
                (now,),
            ).fetchall()
        candidates = [_row_to_action(r) for r in rows]
        ready: list[QueuedAction] = []
        for a in candidates:
            if not a.depends_on:
                ready.append(a)
                if len(ready) >= limit:
                    break
                continue
            ok = True
            for dep_id in a.depends_on:
                dep = self.get(dep_id)
                if dep is None or dep.status != "done":
                    ok = False
                    break
            if ok:
                ready.append(a)
                if len(ready) >= limit:
                    break
        return ready

    # ── State transitions ────────────────────────────────

    def _set_status(
        self,
        action_id: str,
        status: Status,
        *,
        last_error: str | None = None,
        retries: int | None = None,
    ) -> bool:
        fields = ["status=?", "updated_at=?"]
        args: list[Any] = [status, time.time()]
        if last_error is not None:
            fields.append("last_error=?")
            args.append(last_error)
        if retries is not None:
            fields.append("retries=?")
            args.append(int(retries))
        args.append(action_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE actions SET {', '.join(fields)} WHERE id=?",
                tuple(args),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_running(self, action_id: str) -> bool:
        return self._set_status(action_id, "running")

    def mark_done(self, action_id: str) -> bool:
        return self._set_status(action_id, "done")

    def mark_failed(
        self, action_id: str, error: str = "",
    ) -> bool:
        action = self.get(action_id)
        if action is None:
            return False
        if action.retries > 0:
            # Schedule retry
            return self._set_status(
                action_id, "pending",
                last_error=error,
                retries=action.retries - 1,
            )
        return self._set_status(
            action_id, "failed", last_error=error,
        )

    def cancel(self, action_id: str) -> bool:
        return self._set_status(action_id, "cancelled")

    # ── Maintenance ──────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM actions GROUP BY status",
            ).fetchall()
        counts = {s: int(c) for s, c in rows}
        return {
            "by_status": counts,
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
        }

    def prune_terminal(self, older_than_s: float = 86_400.0) -> int:
        cutoff = time.time() - float(older_than_s)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM actions "
                "WHERE status IN ('done', 'failed', 'cancelled') "
                "AND updated_at < ?",
                (cutoff,),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
