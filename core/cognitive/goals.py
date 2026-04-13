"""GoalManager — self-directed goal generation and lifecycle.

Instead of hardcoding what the AI should do, GoalManager lets it
propose its own goals, weigh them, pursue them, and revise them
when evidence contradicts.

A goal has four facets:

    what       — concrete objective (e.g. "increase margin on fashion products")
    why        — the reason it was proposed (trace back to source)
    how        — child sub-goals or tasks decomposing it
    when       — deadline / next check (optional)

Goal sources:

    self_model.weakness       "practice weak engine.X"
    self_model.gap            "explore knowledge.Y"
    memory.pattern            "cart abandonment rate rising → investigate"
    metric.trend              "revenue drop > 20% → recover"
    external.request          a human or another module adds a goal

Lifecycle:

    proposed   ← fresh, not yet committed to
    active     ← picked to work on
    in_progress ← currently being executed
    completed  ← objective met
    failed     ← pursued but couldn't achieve
    abandoned  ← revised away (goal no longer relevant)

Priority scoring (0-1):

    priority = w1 * impact           (expected value if achieved)
             + w2 * urgency          (deadline pressure)
             + w3 * confidence       (do I trust my evidence?)
             - w4 * cost             (execution expense)

GoalManager is storage-backed (SQLite via migration framework) so
goals survive restarts and can be inspected via the CLI later.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.goals")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "goals.db"


# Goal lifecycle states
STATE_PROPOSED = "proposed"
STATE_ACTIVE = "active"
STATE_IN_PROGRESS = "in_progress"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_ABANDONED = "abandoned"

ACTIVE_STATES = frozenset({STATE_PROPOSED, STATE_ACTIVE, STATE_IN_PROGRESS})
TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED, STATE_ABANDONED})

# Priority weight defaults (sum doesn't have to be 1.0 — priority is
# just a ranking score, not a probability)
_W_IMPACT = 1.0
_W_URGENCY = 0.5
_W_CONFIDENCE = 0.5
_W_COST = 0.3


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: goals + goal_events audit log."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS goals (
            id              TEXT PRIMARY KEY,
            parent_id       TEXT DEFAULT '',
            what            TEXT NOT NULL,
            why             TEXT DEFAULT '',
            source          TEXT DEFAULT '',
            state           TEXT NOT NULL DEFAULT 'proposed',

            -- Scoring inputs (all in [0, 1])
            impact          REAL DEFAULT 0.5,
            urgency         REAL DEFAULT 0.5,
            confidence      REAL DEFAULT 0.5,
            cost            REAL DEFAULT 0.5,
            priority        REAL DEFAULT 0.5,

            -- Progress tracking
            progress        REAL DEFAULT 0.0,
            result_notes    TEXT DEFAULT '',

            -- Timestamps
            deadline        REAL DEFAULT 0,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL,
            completed_at    REAL DEFAULT 0
        );

        -- Audit log: every state transition + progress update
        CREATE TABLE IF NOT EXISTS goal_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id         TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            old_value       TEXT DEFAULT '',
            new_value       TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            timestamp       REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_goals_state ON goals(state);
        CREATE INDEX IF NOT EXISTS idx_goals_priority ON goals(priority);
        CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
        CREATE INDEX IF NOT EXISTS idx_goal_events_gid ON goal_events(goal_id);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


class GoalManager:
    """Self-directed goal manager."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        from core.db.migrations import Migrator, register_schema
        Migrator(self._conn(), "goals", _MIGRATIONS).run()
        register_schema("goals", Path(self._db_path), _SCHEMA_VERSION)

    # ── Creating goals ─────────────────────────────────────────

    def propose(
        self,
        what: str,
        *,
        why: str = "",
        source: str = "",
        parent_id: str = "",
        impact: float = 0.5,
        urgency: float = 0.5,
        confidence: float = 0.5,
        cost: float = 0.5,
        deadline: float = 0.0,
    ) -> str:
        """Propose a new goal. Returns the goal ID.

        The goal enters the `proposed` state. Use activate() or
        pick_next() to move it along.
        """
        if not what or not what.strip():
            raise ValueError("Goal must have a 'what' description")

        gid = f"goal_{uuid.uuid4().hex[:12]}"
        now = time.time()
        priority = self._compute_priority(impact, urgency, confidence, cost)

        conn = self._conn()
        conn.execute(
            "INSERT INTO goals "
            "(id, parent_id, what, why, source, state, impact, urgency, "
            " confidence, cost, priority, progress, deadline, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                gid, parent_id, what.strip(), why, source, STATE_PROPOSED,
                self._clamp(impact), self._clamp(urgency),
                self._clamp(confidence), self._clamp(cost),
                priority, 0.0, deadline, now, now,
            ),
        )
        self._log_event(gid, "proposed", "", STATE_PROPOSED, why)
        conn.commit()
        logger.info("Goal proposed: %s [%s] %s", gid, source, what[:60])
        return gid

    def propose_from_self_model(
        self,
        self_model: Any,
        *,
        max_from_weaknesses: int = 3,
        max_from_gaps: int = 3,
    ) -> list[str]:
        """Generate goals automatically from SelfModel state.

        - Each weakness → a "practice" goal with high confidence (we
          *know* it's weak) and medium impact.
        - Each knowledge gap → an "explore" goal with medium impact
          and lower confidence (we don't know what we'll find).

        Duplicate detection: if an active goal already targets the
        same capability, we don't create a duplicate.
        """
        created: list[str] = []
        if self_model is None:
            return created

        active_targets = self._active_goal_targets()

        try:
            weaknesses = self_model.weaknesses(top_n=max_from_weaknesses)
        except Exception:  # noqa: BLE001
            weaknesses = []

        for w in weaknesses:
            name = w.get("name") if isinstance(w, dict) else None
            if not name or f"practice:{name}" in active_targets:
                continue
            gid = self.propose(
                what=f"Improve weak capability '{name}'",
                why=f"SelfModel reports score={w.get('score', 0):.2f}, "
                    f"conf={w.get('confidence', 0):.2f}",
                source=f"self_model.weakness:{name}",
                impact=0.7,
                urgency=0.4,
                confidence=float(w.get("confidence", 0.5) or 0.5),
                cost=0.3,
            )
            created.append(gid)

        try:
            gaps = self_model.knowledge_gaps(top_n=max_from_gaps)
        except Exception:  # noqa: BLE001
            gaps = []

        for g in gaps:
            name = g.get("name") if isinstance(g, dict) else None
            if not name or f"explore:{name}" in active_targets:
                continue
            gid = self.propose(
                what=f"Explore unknown capability '{name}'",
                why=f"SelfModel has only {g.get('evidence_count', 0)} observations",
                source=f"self_model.gap:{name}",
                impact=0.5,
                urgency=0.2,
                confidence=0.3,
                cost=0.2,
            )
            created.append(gid)

        return created

    # ── Lifecycle transitions ──────────────────────────────────

    def activate(self, goal_id: str) -> None:
        self._transition(goal_id, STATE_ACTIVE)

    def start(self, goal_id: str) -> None:
        self._transition(goal_id, STATE_IN_PROGRESS)

    def complete(self, goal_id: str, result_notes: str = "") -> None:
        self._transition(
            goal_id, STATE_COMPLETED, notes=result_notes,
            extra={"progress": 1.0, "completed_at": time.time(),
                   "result_notes": result_notes},
        )

    def fail(self, goal_id: str, reason: str = "") -> None:
        self._transition(
            goal_id, STATE_FAILED, notes=reason,
            extra={"completed_at": time.time(), "result_notes": reason},
        )

    def abandon(self, goal_id: str, reason: str = "") -> None:
        self._transition(
            goal_id, STATE_ABANDONED, notes=reason,
            extra={"completed_at": time.time(), "result_notes": reason},
        )

    def update_progress(
        self, goal_id: str, progress: float, notes: str = "",
    ) -> None:
        """Record incremental progress (0.0 → 1.0)."""
        progress = self._clamp(progress)
        conn = self._conn()
        old = conn.execute(
            "SELECT progress FROM goals WHERE id = ?", (goal_id,),
        ).fetchone()
        if not old:
            return
        now = time.time()
        conn.execute(
            "UPDATE goals SET progress = ?, updated_at = ? WHERE id = ?",
            (progress, now, goal_id),
        )
        self._log_event(
            goal_id, "progress",
            str(round(old["progress"], 3)),
            str(round(progress, 3)),
            notes,
        )
        conn.commit()

    def revise(
        self,
        goal_id: str,
        *,
        impact: Optional[float] = None,
        urgency: Optional[float] = None,
        confidence: Optional[float] = None,
        cost: Optional[float] = None,
        why: str = "",
    ) -> None:
        """Update the scoring inputs of a goal based on new evidence.

        Used when the system gets a signal that changes the cost-benefit
        of a goal (e.g. 'this turned out to be more expensive than
        expected'). The priority is recomputed automatically.
        """
        conn = self._conn()
        row = conn.execute(
            "SELECT impact, urgency, confidence, cost FROM goals WHERE id = ?",
            (goal_id,),
        ).fetchone()
        if not row:
            return

        new_impact = self._clamp(impact) if impact is not None else float(row["impact"])
        new_urgency = self._clamp(urgency) if urgency is not None else float(row["urgency"])
        new_conf = self._clamp(confidence) if confidence is not None else float(row["confidence"])
        new_cost = self._clamp(cost) if cost is not None else float(row["cost"])

        new_priority = self._compute_priority(
            new_impact, new_urgency, new_conf, new_cost,
        )

        conn.execute(
            "UPDATE goals SET impact = ?, urgency = ?, confidence = ?, "
            "cost = ?, priority = ?, updated_at = ? WHERE id = ?",
            (new_impact, new_urgency, new_conf, new_cost, new_priority,
             time.time(), goal_id),
        )
        self._log_event(goal_id, "revised", "", f"priority={new_priority:.3f}", why)
        conn.commit()

    def pick_next(self) -> Optional[dict[str, Any]]:
        """Pick the highest-priority active goal to work on.

        Returns the goal dict (or None if nothing is pending).
        Automatically promotes it from proposed → active if needed.
        """
        row = self._conn().execute(
            "SELECT * FROM goals WHERE state IN ('proposed', 'active') "
            "ORDER BY priority DESC, created_at ASC LIMIT 1",
        ).fetchone()
        if not row:
            return None
        goal = self._row_to_dict(row)
        if goal["state"] == STATE_PROPOSED:
            self.activate(goal["id"])
            goal["state"] = STATE_ACTIVE
        return goal

    # ── Read API ───────────────────────────────────────────────

    def get(self, goal_id: str) -> Optional[dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM goals WHERE id = ?", (goal_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_goals(
        self,
        state: Optional[str] = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List goals, optionally filtered by state."""
        if state:
            rows = self._conn().execute(
                "SELECT * FROM goals WHERE state = ? "
                "ORDER BY priority DESC, created_at DESC LIMIT ?",
                (state, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM goals ORDER BY priority DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def active(self, limit: int = 100) -> list[dict[str, Any]]:
        """Proposed + active + in_progress — anything still live."""
        rows = self._conn().execute(
            "SELECT * FROM goals "
            "WHERE state IN ('proposed', 'active', 'in_progress') "
            "ORDER BY priority DESC, created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def children(self, parent_id: str) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM goals WHERE parent_id = ? ORDER BY priority DESC",
            (parent_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def events(self, goal_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM goal_events WHERE goal_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (goal_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        """Rollup counts by state + average priority."""
        rows = self._conn().execute(
            "SELECT state, COUNT(*) as n, AVG(priority) as avg_p "
            "FROM goals GROUP BY state",
        ).fetchall()
        counts = {r["state"]: int(r["n"]) for r in rows}
        priorities = {r["state"]: float(r["avg_p"] or 0) for r in rows}
        total = sum(counts.values())
        return {
            "total": total,
            "by_state": counts,
            "avg_priority_by_state": priorities,
            "active_count": sum(counts.get(s, 0) for s in ACTIVE_STATES),
            "terminal_count": sum(counts.get(s, 0) for s in TERMINAL_STATES),
        }

    # ── Internal helpers ───────────────────────────────────────

    # Columns the _transition() helper is allowed to update via its
    # `extra` parameter. Anything else is silently dropped — defensive
    # whitelist that prevents arbitrary column names (or worse, raw
    # SQL fragments) from being interpolated into the generated UPDATE
    # statement when a future caller passes attacker-controlled keys.
    _ALLOWED_TRANSITION_EXTRA_COLUMNS = frozenset({
        "progress",
        "completed_at",
        "result_notes",
        "impact",
        "urgency",
        "confidence",
        "cost",
        "priority",
        "deadline",
    })

    def _transition(
        self,
        goal_id: str,
        new_state: str,
        *,
        notes: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        conn = self._conn()
        row = conn.execute(
            "SELECT state FROM goals WHERE id = ?", (goal_id,),
        ).fetchone()
        if not row:
            return
        old_state = row["state"]
        if old_state == new_state:
            return

        now = time.time()
        sets = ["state = ?", "updated_at = ?"]
        params: list[Any] = [new_state, now]
        if extra:
            for k, v in extra.items():
                if k not in self._ALLOWED_TRANSITION_EXTRA_COLUMNS:
                    logger.warning(
                        "Goal _transition: dropping disallowed extra "
                        "column %r (goal=%s)", k, goal_id,
                    )
                    continue
                sets.append(f"{k} = ?")
                params.append(v)
        params.append(goal_id)
        conn.execute(
            f"UPDATE goals SET {', '.join(sets)} WHERE id = ?", params,
        )
        self._log_event(goal_id, "state_change", old_state, new_state, notes)
        conn.commit()

    def _log_event(
        self,
        goal_id: str,
        event_type: str,
        old_value: str,
        new_value: str,
        notes: str,
    ) -> None:
        self._conn().execute(
            "INSERT INTO goal_events (goal_id, event_type, old_value, new_value, notes, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (goal_id, event_type, old_value[:120], new_value[:120], notes[:500], time.time()),
        )

    @staticmethod
    def _compute_priority(
        impact: float, urgency: float, confidence: float, cost: float,
    ) -> float:
        raw = (
            _W_IMPACT * GoalManager._clamp(impact)
            + _W_URGENCY * GoalManager._clamp(urgency)
            + _W_CONFIDENCE * GoalManager._clamp(confidence)
            - _W_COST * GoalManager._clamp(cost)
        )
        # Normalize to [0, 1]: raw range is [-0.3, 2.0]
        normalized = (raw + _W_COST) / (_W_IMPACT + _W_URGENCY + _W_CONFIDENCE + _W_COST)
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, v))

    # Source-prefix → dedup-namespace map. Both SelfModel
    # (`self_model.*`) and Reflection (`reflection.*`) propose goals
    # that target capability subjects, so we normalize them into the
    # same dedup keys (`practice:<subject>` for "improve this thing"
    # goals and `explore:<subject>` for "investigate this thing"
    # goals). Without this, two cognitive paths could each propose a
    # goal for the same subject and neither would notice.
    _SOURCE_PREFIX_TO_NAMESPACE: dict[str, str] = {
        "self_model.weakness:":   "practice",
        "self_model.gap:":        "explore",
        "reflection.weakness:":   "practice",
        "reflection.regression:": "practice",
        "reflection.pattern:":    "explore",
        "reflection.blind_spot:": "explore",
    }

    def _active_goal_targets(self) -> set[str]:
        """Set of dedup keys for currently-active goals.

        Used by propose_from_self_model() — and indirectly by any
        path that wants to avoid duplicating a capability-targeted
        goal — to skip subjects already being worked on. Recognises
        every source prefix in `_SOURCE_PREFIX_TO_NAMESPACE` so the
        dedup is symmetric across SelfModel and Reflection.
        """
        rows = self._conn().execute(
            "SELECT source FROM goals "
            "WHERE state IN ('proposed', 'active', 'in_progress')",
        ).fetchall()
        out: set[str] = set()
        for r in rows:
            src = r["source"] or ""
            for prefix, namespace in self._SOURCE_PREFIX_TO_NAMESPACE.items():
                if src.startswith(prefix):
                    subject = src[len(prefix):].strip()
                    if subject:
                        out.add(f"{namespace}:{subject}")
                    break
        return out

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "parent_id": row["parent_id"] or "",
            "what": row["what"],
            "why": row["why"] or "",
            "source": row["source"] or "",
            "state": row["state"],
            "impact": float(row["impact"]),
            "urgency": float(row["urgency"]),
            "confidence": float(row["confidence"]),
            "cost": float(row["cost"]),
            "priority": float(row["priority"]),
            "progress": float(row["progress"]),
            "result_notes": row["result_notes"] or "",
            "deadline": float(row["deadline"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "completed_at": float(row["completed_at"]),
        }


# ── Singleton accessor ─────────────────────────────────────────

_instance: Optional[GoalManager] = None
_instance_lock = threading.Lock()


def get_goal_manager() -> GoalManager:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = GoalManager()
    return _instance
