"""Persistent goal agenda — goals that outlive a session.

v4-D1 decomposes a single owner goal into a hierarchical plan per
invocation. What's still missing: the brain doesn't keep an
evolving list of *all* goals the store is pursuing, doesn't
re-prioritise them as context shifts, doesn't notice when one
goal blocks another.

GoalAgenda fixes that. Every goal carries:

  id           — stable across restarts
  title        — owner-authored short label
  description  — full text
  status       — ``pending`` | ``active`` | ``paused`` | ``achieved`` | ``abandoned``
  priority     — 0-100 float; re-scored each cycle based on
                 impact + urgency + confidence
  parent_id    — optional link to a bigger goal
  due_at       — optional deadline
  signals      — last-observed metric values relevant to this goal
  blocks       — list of other goal ids this one blocks
  blocked_by   — list of goal ids blocking this one

API:
  register(title, description, priority=50, ...) → Goal
  update(goal_id, **fields)
  list_active(limit=10)
  reprioritise() — runs every cycle; re-scores every active goal
  mark_achieved / mark_abandoned / mark_paused

Persistence: data/goal_agenda.db — SQLite. Survives restarts, is
thread-safe, and emits ``category=goal_status score=3.0`` memory
events whenever a status changes so the brain's retriever sees the
latest agenda shape.
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

from utils.logger import get_logger


logger = get_logger("brain.goal_agenda")

_DB_PATH = Path("data/goal_agenda.db")
_STATUSES = {"pending", "active", "paused", "achieved", "abandoned"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending',
    priority     REAL NOT NULL DEFAULT 50.0,
    parent_id    TEXT,
    due_at       REAL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    signals      TEXT NOT NULL DEFAULT '{}',
    blocks       TEXT NOT NULL DEFAULT '[]',
    blocked_by   TEXT NOT NULL DEFAULT '[]',
    metadata     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_g_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_g_prio   ON goals(priority);
"""


_lock = threading.Lock()


@dataclass
class Goal:
    id: str
    title: str
    description: str = ""
    status: str = "pending"
    priority: float = 50.0
    parent_id: str | None = None
    due_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": round(self.priority, 2),
            "parent_id": self.parent_id,
            "due_at": self.due_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "signals": self.signals,
            "blocks": self.blocks,
            "blocked_by": self.blocked_by,
            "metadata": self.metadata,
        }


class GoalAgenda:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            conn = sqlite3.connect(str(self._path))
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    # ── CRUD ────────────────────────────────────────────────

    def register(
        self,
        title: str,
        description: str = "",
        priority: float = 50.0,
        parent_id: str | None = None,
        due_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Goal:
        """Register a new goal. Returns it fully-typed."""
        if not title:
            raise ValueError("goal title required")
        gid = f"goal_{uuid.uuid4().hex[:10]}"
        now = time.time()
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                conn.execute(
                    "INSERT INTO goals(id, title, description, status, priority,"
                    " parent_id, due_at, created_at, updated_at, metadata)"
                    " VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
                    (
                        gid, title, description, float(priority),
                        parent_id, due_at, now, now,
                        json.dumps(metadata or {}),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        goal = self.get(gid)
        self._emit_status_change(goal, old_status=None)
        return goal

    def get(self, goal_id: str) -> Goal | None:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM goals WHERE id=?", (goal_id,))
                row = cur.fetchone()
            finally:
                conn.close()
        return self._row_to_goal(row) if row else None

    def update(
        self,
        goal_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: float | None = None,
        due_at: float | None = None,
        signals: dict[str, Any] | None = None,
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Goal | None:
        old = self.get(goal_id)
        if old is None:
            return None
        if status is not None and status not in _STATUSES:
            raise ValueError(f"unknown status {status!r}")
        updates: list[tuple[str, Any]] = [("updated_at", time.time())]
        if title is not None:
            updates.append(("title", title))
        if description is not None:
            updates.append(("description", description))
        if status is not None:
            updates.append(("status", status))
        if priority is not None:
            updates.append(("priority",
                             max(0.0, min(100.0, float(priority)))))
        if due_at is not None:
            updates.append(("due_at", due_at))
        if signals is not None:
            updates.append(("signals", json.dumps(signals)))
        if blocks is not None:
            updates.append(("blocks", json.dumps(blocks)))
        if blocked_by is not None:
            updates.append(("blocked_by", json.dumps(blocked_by)))
        if metadata is not None:
            updates.append(("metadata", json.dumps(metadata)))
        set_clause = ", ".join(f"{k}=?" for k, _ in updates)
        params = [v for _, v in updates] + [goal_id]
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                conn.execute(
                    f"UPDATE goals SET {set_clause} WHERE id=?", params,
                )
                conn.commit()
            finally:
                conn.close()
        goal = self.get(goal_id)
        if goal is not None and status is not None and status != old.status:
            self._emit_status_change(goal, old_status=old.status)
        return goal

    def list_active(self, limit: int = 10) -> list[Goal]:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM goals WHERE status IN ('active', 'pending')"
                    " ORDER BY priority DESC, updated_at DESC LIMIT ?",
                    (int(limit),),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        return [self._row_to_goal(r) for r in rows]

    def list_all(self, status: str | None = None) -> list[Goal]:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                if status:
                    cur.execute(
                        "SELECT * FROM goals WHERE status=? "
                        "ORDER BY priority DESC",
                        (status,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM goals ORDER BY priority DESC",
                    )
                rows = cur.fetchall()
            finally:
                conn.close()
        return [self._row_to_goal(r) for r in rows]

    # ── Status helpers ─────────────────────────────────────

    def mark_achieved(self, goal_id: str) -> Goal | None:
        return self.update(goal_id, status="achieved")

    def mark_abandoned(self, goal_id: str) -> Goal | None:
        return self.update(goal_id, status="abandoned")

    def mark_paused(self, goal_id: str) -> Goal | None:
        return self.update(goal_id, status="paused")

    # ── Reprioritisation ──────────────────────────────────

    def reprioritise(self) -> int:
        """Re-score priority of every active goal based on impact,
        urgency (days_to_due), and confidence (signals we have)."""
        active = self.list_active(limit=100)
        now = time.time()
        updated = 0
        for goal in active:
            # Urgency: 1.0 if due in <=1 day; 0.1 if due in >30 days; 0.5 if no due.
            if goal.due_at:
                days_left = max(0.0, (goal.due_at - now) / 86_400)
                if days_left <= 1:
                    urgency = 1.0
                elif days_left >= 30:
                    urgency = 0.1
                else:
                    urgency = 1.0 - (days_left - 1) / 29.0 * 0.9
            else:
                urgency = 0.5
            # Confidence proxy: more signals → more ready to act.
            signal_count = len(goal.signals)
            confidence = min(1.0, signal_count / 4.0)
            # Impact: previously-registered priority treated as impact.
            impact = goal.priority / 100.0
            new_priority = (urgency * 0.45
                            + impact * 0.45
                            + confidence * 0.10) * 100.0
            new_priority = max(0.0, min(100.0, new_priority))
            if abs(new_priority - goal.priority) < 0.5:
                continue
            self.update(goal.id, priority=new_priority)
            updated += 1
        return updated

    # ── Internals ─────────────────────────────────────────

    @staticmethod
    def _row_to_goal(row: tuple) -> Goal:
        def _loads(text: str, default: Any) -> Any:
            try:
                return json.loads(text or "")
            except (json.JSONDecodeError, ValueError):
                return default
        return Goal(
            id=row[0],
            title=row[1],
            description=row[2] or "",
            status=row[3] or "pending",
            priority=float(row[4]) if row[4] is not None else 50.0,
            parent_id=row[5],
            due_at=row[6],
            created_at=float(row[7]) if row[7] is not None else 0.0,
            updated_at=float(row[8]) if row[8] is not None else 0.0,
            signals=_loads(row[9] or "{}", {}),
            blocks=_loads(row[10] or "[]", []),
            blocked_by=_loads(row[11] or "[]", []),
            metadata=_loads(row[12] or "{}", {}),
        )

    def _emit_status_change(self, goal: Goal, old_status: str | None) -> None:
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
            mi.create(
                category="goal_status",
                content={
                    "goal_id": goal.id,
                    "title": goal.title,
                    "old_status": old_status,
                    "new_status": goal.status,
                    "priority": goal.priority,
                },
                action=f"transition_{goal.status}",
                score=3.0,
                tags=["goal", goal.status, f"goal:{goal.id}"],
            )
        except Exception as exc:
            logger.debug("goal status event emit failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────

_AGENDA_LOCK = threading.Lock()
_AGENDA: GoalAgenda | None = None


def agenda() -> GoalAgenda:
    global _AGENDA
    with _AGENDA_LOCK:
        if _AGENDA is None:
            _AGENDA = GoalAgenda()
    return _AGENDA
