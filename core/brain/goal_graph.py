"""Goal graph — concurrent goals with dependencies and progress.

ShopAI juggles many simultaneous objectives: "launch 5 SKUs this week",
"drop acquisition CPA below $12", "refund backlog under 24h". Until now
these lived as scattered variables in engines. goal_graph centralises:

  • Register goals with a parent/child tree and soft/hard deadlines
  • Track progress 0..1 per goal via ``advance(goal_id, progress)``
  • Auto-roll parent progress as a weighted average of children
  • Expose the *active frontier* — open leaf goals that unblock
    when their parents' preconditions are met
  • Emit ``blocked`` / ``stalled`` / ``met`` state transitions so
    the daemon can react (owner notification, repair workflow)

SQLite-persisted. Pure stdlib. Deterministic.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal


Status = Literal["open", "met", "blocked", "cancelled"]


@dataclass
class Goal:
    id: str
    description: str
    parent_id: str | None
    created_at: float
    due_at: float | None
    weight: float               # contribution to parent progress
    progress: float             # 0..1
    status: Status
    updated_at: float
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "due_at": self.due_at,
            "weight": round(self.weight, 3),
            "progress": round(self.progress, 3),
            "status": self.status,
            "updated_at": self.updated_at,
            "tags": list(self.tags),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id           TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    parent_id    TEXT,
    created_at   REAL NOT NULL,
    due_at       REAL,
    weight       REAL NOT NULL DEFAULT 1.0,
    progress     REAL NOT NULL DEFAULT 0.0,
    status       TEXT NOT NULL DEFAULT 'open',
    updated_at   REAL NOT NULL,
    tags_csv     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
"""


def _row_to_goal(row: tuple[Any, ...]) -> Goal:
    tags = tuple(t for t in (row[9] or "").split(",") if t)
    return Goal(
        id=row[0], description=row[1], parent_id=row[2],
        created_at=float(row[3]),
        due_at=(float(row[4]) if row[4] is not None else None),
        weight=float(row[5]), progress=float(row[6]),
        status=row[7], updated_at=float(row[8]),
        tags=tags,
    )


class GoalGraph:
    def __init__(self, db_path: str | Path = "data/goal_graph.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── CRUD ──────────────────────────────────────────────

    def add(
        self,
        description: str,
        *,
        parent_id: str | None = None,
        due_at: float | None = None,
        weight: float = 1.0,
        tags: Iterable[str] = (),
    ) -> Goal:
        if not description.strip():
            raise ValueError("description required")
        if weight <= 0:
            raise ValueError("weight must be positive")
        gid = uuid.uuid4().hex
        now = time.time()
        tags_csv = ",".join(str(t).strip() for t in tags if str(t).strip())
        if parent_id is not None and self.get(parent_id) is None:
            raise ValueError(f"unknown parent {parent_id!r}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO goals(id, description, parent_id, "
                "created_at, due_at, weight, progress, status, "
                "updated_at, tags_csv) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    gid, description.strip(), parent_id, now,
                    due_at, float(weight), 0.0, "open",
                    now, tags_csv,
                ),
            )
            self._conn.commit()
        return Goal(
            id=gid, description=description.strip(),
            parent_id=parent_id, created_at=now,
            due_at=due_at, weight=float(weight), progress=0.0,
            status="open", updated_at=now,
            tags=tuple(t for t in tags_csv.split(",") if t),
        )

    def get(self, goal_id: str) -> Goal | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, description, parent_id, created_at, due_at, "
                "weight, progress, status, updated_at, tags_csv "
                "FROM goals WHERE id=?",
                (goal_id,),
            ).fetchone()
        return _row_to_goal(row) if row else None

    def children(self, goal_id: str) -> list[Goal]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, description, parent_id, created_at, due_at, "
                "weight, progress, status, updated_at, tags_csv "
                "FROM goals WHERE parent_id=?",
                (goal_id,),
            ).fetchall()
        return [_row_to_goal(r) for r in rows]

    def roots(self) -> list[Goal]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, description, parent_id, created_at, due_at, "
                "weight, progress, status, updated_at, tags_csv "
                "FROM goals WHERE parent_id IS NULL "
                "ORDER BY created_at ASC",
            ).fetchall()
        return [_row_to_goal(r) for r in rows]

    def by_status(self, status: Status) -> list[Goal]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, description, parent_id, created_at, due_at, "
                "weight, progress, status, updated_at, tags_csv "
                "FROM goals WHERE status=?",
                (status,),
            ).fetchall()
        return [_row_to_goal(r) for r in rows]

    # ── Progress ──────────────────────────────────────────

    def _set(
        self,
        goal_id: str,
        *,
        progress: float | None = None,
        status: Status | None = None,
    ) -> None:
        fields: list[str] = []
        args: list[Any] = []
        if progress is not None:
            fields.append("progress=?")
            args.append(max(0.0, min(1.0, float(progress))))
        if status is not None:
            fields.append("status=?")
            args.append(status)
        fields.append("updated_at=?")
        args.append(time.time())
        args.append(goal_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE goals SET {', '.join(fields)} WHERE id=?",
                tuple(args),
            )
            self._conn.commit()

    def advance(self, goal_id: str, progress: float) -> Goal | None:
        """Set a leaf goal's progress and roll up through ancestors."""
        g = self.get(goal_id)
        if g is None:
            return None
        self._set(
            goal_id, progress=progress,
            status=("met" if progress >= 1.0 else g.status),
        )
        self._roll_up(goal_id)
        return self.get(goal_id)

    def mark_status(
        self, goal_id: str, status: Status,
    ) -> Goal | None:
        g = self.get(goal_id)
        if g is None:
            return None
        self._set(goal_id, status=status)
        self._roll_up(goal_id)
        return self.get(goal_id)

    def _roll_up(self, child_id: str) -> None:
        parent = self._parent_of(child_id)
        while parent is not None:
            kids = self.children(parent.id)
            if not kids:
                break
            total_w = sum(k.weight for k in kids) or 1.0
            roll = sum(k.progress * k.weight for k in kids) / total_w
            all_met = all(k.status == "met" for k in kids)
            any_blocked = any(k.status == "blocked" for k in kids)
            new_status = parent.status
            if all_met and roll >= 0.999:
                new_status = "met"
            elif any_blocked and parent.status != "cancelled":
                new_status = "blocked"
            self._set(parent.id, progress=roll, status=new_status)
            parent = self._parent_of(parent.id)

    def _parent_of(self, goal_id: str) -> Goal | None:
        g = self.get(goal_id)
        if g is None or g.parent_id is None:
            return None
        return self.get(g.parent_id)

    # ── Frontier ──────────────────────────────────────────

    def frontier(self) -> list[Goal]:
        """Open leaf goals (no open children) — the actionable layer."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT g.id, g.description, g.parent_id, g.created_at, "
                "g.due_at, g.weight, g.progress, g.status, g.updated_at, "
                "g.tags_csv "
                "FROM goals g "
                "LEFT JOIN goals c ON c.parent_id = g.id AND c.status='open' "
                "WHERE g.status='open' AND c.id IS NULL",
            ).fetchall()
        return [_row_to_goal(r) for r in rows]

    # ── Health / overdue ─────────────────────────────────

    def overdue(self, now: float | None = None) -> list[Goal]:
        now = now or time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, description, parent_id, created_at, due_at, "
                "weight, progress, status, updated_at, tags_csv "
                "FROM goals "
                "WHERE status='open' AND due_at IS NOT NULL AND due_at < ?",
                (now,),
            ).fetchall()
        return [_row_to_goal(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM goals GROUP BY status",
            ).fetchall()
        counts = {s: int(c) for s, c in rows}
        return {
            "by_status": counts,
            "open": counts.get("open", 0),
            "met": counts.get("met", 0),
            "blocked": counts.get("blocked", 0),
            "overdue": len(self.overdue()),
            "frontier_size": len(self.frontier()),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
