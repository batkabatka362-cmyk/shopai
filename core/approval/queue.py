"""ApprovalQueue — stage Shopify-mutating engine output for human approval.

Closes the AGI audit's #2 gap. Phase 6/7 wireups currently default
to ``apply_X=False`` (opt-OUT): the engine emits a recommendation
list, the merchant flips a flag, the writeback fires immediately.
Two ends of a switch, no middle. Real merchants want to *see* what
the engine wants to do, *click* approve or reject per item, and
*then* let it run.

This module is the missing middle. Engines push pending actions
in; merchants list/approve/reject through the API
(``/api/pending-actions``); approved actions execute via the
existing writeback path; the queue records the result and ages
out resolved entries.

Storage is SQLite at ``data/approval_queue.db`` — same pattern as
``memory_intelligence``, ``goals``, ``experience``. Single table,
no migrations yet (this is the v1 schema).

The queue is intentionally independent of the writeback recorder
(``engines._writeback_recorder``): the recorder writes after a
mutation has happened, the queue records *intent before* a
mutation. They both fan into the autonomous loop but at different
phases.

Lifecycle:

    ApprovalStatus.PENDING  →  ApprovalStatus.APPROVED
                            ↘  ApprovalStatus.REJECTED
                            ↘  ApprovalStatus.EXPIRED  (TTL only,
                                                        not auto-applied
                                                        in v1)

After approve, the executor (a follow-up PR will wire the engine
appliers) flips the entry to ``ApprovalStatus.EXECUTED`` or
``ApprovalStatus.FAILED`` via :meth:`ApprovalQueue.attach_result`.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("core.approval.queue")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "approval_queue.db"
_LOCK = threading.RLock()
_INSTANCE: "ApprovalQueue | None" = None


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class ApprovalAction:
    """An action proposal awaiting (or past) human review."""

    id: str
    engine: str
    action_type: str
    capability: str
    params: dict[str, Any]
    narrative: str
    confidence: float | None
    status: ApprovalStatus
    proposed_at: float
    decided_at: float | None
    decided_by: str | None
    decision_reason: str | None
    result: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "engine": self.engine,
            "action_type": self.action_type,
            "capability": self.capability,
            "params": self.params,
            "narrative": self.narrative,
            "confidence": self.confidence,
            "status": self.status.value,
            "proposed_at": self.proposed_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
            "result": self.result,
        }


class ApprovalQueue:
    """SQLite-backed queue of pending engine actions.

    All public methods are thread-safe via the module-level
    ``_LOCK``. The DB is opened with
    ``check_same_thread=False`` so the lone connection can be
    shared across the API server's request-handler threads.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with _LOCK:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id              TEXT PRIMARY KEY,
                    engine          TEXT NOT NULL,
                    action_type     TEXT NOT NULL,
                    capability      TEXT NOT NULL,
                    params_json     TEXT NOT NULL,
                    narrative       TEXT,
                    confidence      REAL,
                    status          TEXT NOT NULL,
                    proposed_at     REAL NOT NULL,
                    decided_at      REAL,
                    decided_by      TEXT,
                    decision_reason TEXT,
                    result_json     TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pending_status
                    ON pending_actions(status, proposed_at);
                CREATE INDEX IF NOT EXISTS idx_pending_engine
                    ON pending_actions(engine, status);
            """)
            self._conn.commit()

    # ── Public API ─────────────────────────────────────────────

    def enqueue(
        self,
        *,
        engine: str,
        action_type: str,
        capability: str,
        params: dict[str, Any],
        narrative: str = "",
        confidence: float | None = None,
    ) -> ApprovalAction:
        """Park a proposed action for human review.

        Returns the persisted :class:`ApprovalAction`. The queue
        does NOT execute anything — the caller still owns the
        downstream effect once approval lands.
        """
        action_id = f"appr_{int(time.time() * 1000)}_{_short_uuid()}"
        now = time.time()
        params_json = _safe_json(params)
        with _LOCK:
            self._conn.execute(
                """INSERT INTO pending_actions
                   (id, engine, action_type, capability, params_json,
                    narrative, confidence, status, proposed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action_id, engine, action_type, capability,
                    params_json, narrative, confidence,
                    ApprovalStatus.PENDING.value, now,
                ),
            )
            self._conn.commit()
        logger.info(
            "approval enqueued: %s engine=%s action=%s",
            action_id, engine, action_type,
        )
        return ApprovalAction(
            id=action_id, engine=engine, action_type=action_type,
            capability=capability, params=params,
            narrative=narrative, confidence=confidence,
            status=ApprovalStatus.PENDING, proposed_at=now,
            decided_at=None, decided_by=None, decision_reason=None,
            result=None,
        )

    def get(self, action_id: str) -> ApprovalAction | None:
        """Fetch a single action by id, regardless of status."""
        with _LOCK:
            row = self._conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,),
            ).fetchone()
        return _row_to_action(row) if row else None

    def list_pending(
        self, *, engine: str | None = None, limit: int = 100,
    ) -> list[ApprovalAction]:
        """Return open (pending) actions oldest-first.

        ``engine`` filters to a single engine namespace; ``limit``
        caps the page size. The API surface uses this to render the
        merchant's review queue.
        """
        with _LOCK:
            if engine:
                rows = self._conn.execute(
                    """SELECT * FROM pending_actions
                       WHERE status = ? AND engine = ?
                       ORDER BY proposed_at ASC LIMIT ?""",
                    (ApprovalStatus.PENDING.value, engine, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT * FROM pending_actions
                       WHERE status = ?
                       ORDER BY proposed_at ASC LIMIT ?""",
                    (ApprovalStatus.PENDING.value, limit),
                ).fetchall()
        return [_row_to_action(r) for r in rows]

    def list_executed(
        self, *, engine: str | None = None, limit: int = 500,
    ) -> list[ApprovalAction]:
        """Return EXECUTED actions newest-first.

        Used by the webhook feedback bridge to match incoming
        Shopify events (orders, refunds) against engine actions
        that already landed on the live store.
        """
        with _LOCK:
            if engine:
                rows = self._conn.execute(
                    """SELECT * FROM pending_actions
                       WHERE status = ? AND engine = ?
                       ORDER BY decided_at DESC LIMIT ?""",
                    (ApprovalStatus.EXECUTED.value, engine, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT * FROM pending_actions
                       WHERE status = ?
                       ORDER BY decided_at DESC LIMIT ?""",
                    (ApprovalStatus.EXECUTED.value, limit),
                ).fetchall()
        return [_row_to_action(r) for r in rows]

    def approve(
        self,
        action_id: str,
        *,
        decided_by: str = "",
        reason: str = "",
    ) -> ApprovalAction | None:
        """Mark a pending action approved.

        Returns the updated :class:`ApprovalAction`, or ``None``
        when the id is unknown or already resolved (idempotent).
        """
        return self._transition(
            action_id,
            from_status=ApprovalStatus.PENDING,
            to_status=ApprovalStatus.APPROVED,
            decided_by=decided_by,
            reason=reason,
        )

    def reject(
        self,
        action_id: str,
        *,
        decided_by: str = "",
        reason: str = "",
    ) -> ApprovalAction | None:
        """Mark a pending action rejected. Same idempotency contract
        as :meth:`approve`."""
        return self._transition(
            action_id,
            from_status=ApprovalStatus.PENDING,
            to_status=ApprovalStatus.REJECTED,
            decided_by=decided_by,
            reason=reason,
        )

    def attach_result(
        self,
        action_id: str,
        *,
        success: bool,
        result: dict[str, Any] | None = None,
    ) -> ApprovalAction | None:
        """Record the outcome of an APPROVED action.

        Flips status APPROVED → EXECUTED on success or APPROVED →
        FAILED on failure. The follow-up PR wires this into the
        engine appliers so merchant-approved writebacks land here.
        """
        target = ApprovalStatus.EXECUTED if success else ApprovalStatus.FAILED
        with _LOCK:
            row = self._conn.execute(
                "SELECT * FROM pending_actions WHERE id = ? AND status = ?",
                (action_id, ApprovalStatus.APPROVED.value),
            ).fetchone()
            if not row:
                logger.debug(
                    "attach_result no-op for %s (not in APPROVED state)",
                    action_id,
                )
                return None
            self._conn.execute(
                """UPDATE pending_actions
                   SET status = ?, result_json = ?
                   WHERE id = ?""",
                (target.value, _safe_json(result or {}), action_id),
            )
            self._conn.commit()
            new_row = self._conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,),
            ).fetchone()
        return _row_to_action(new_row) if new_row else None

    def stats(self) -> dict[str, int]:
        """Counts per status — used by the API status endpoint."""
        with _LOCK:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) as n FROM pending_actions GROUP BY status",
            ).fetchall()
        out = {s.value: 0 for s in ApprovalStatus}
        for r in rows:
            out[r["status"]] = int(r["n"])
        return out

    # ── Internals ─────────────────────────────────────────────

    def _transition(
        self,
        action_id: str,
        *,
        from_status: ApprovalStatus,
        to_status: ApprovalStatus,
        decided_by: str,
        reason: str,
    ) -> ApprovalAction | None:
        now = time.time()
        with _LOCK:
            cur = self._conn.execute(
                """UPDATE pending_actions
                   SET status = ?, decided_at = ?, decided_by = ?,
                       decision_reason = ?
                   WHERE id = ? AND status = ?""",
                (
                    to_status.value, now, decided_by, reason,
                    action_id, from_status.value,
                ),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                logger.debug(
                    "transition no-op for %s (id missing or not in %s)",
                    action_id, from_status.value,
                )
                return None
            row = self._conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,),
            ).fetchone()
        logger.info(
            "approval %s: %s -> %s (by=%s, reason=%s)",
            action_id, from_status.value, to_status.value,
            decided_by or "?", reason or "?",
        )
        return _row_to_action(row) if row else None


# ── Module helpers ─────────────────────────────────────────────


def get_approval_queue(db_path: Path | str | None = None) -> ApprovalQueue:
    """Return a process-wide :class:`ApprovalQueue` singleton.

    Tests pass a ``db_path`` to swap in a temp DB; production code
    leaves it ``None`` so every caller shares the same SQLite file.
    """
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None or db_path is not None:
            _INSTANCE = ApprovalQueue(db_path=db_path)
    return _INSTANCE


def reset_approval_queue() -> None:
    """Drop the cached singleton — test fixture only."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None:
            try:
                _INSTANCE._conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("approval queue close failed: %s", exc)
        _INSTANCE = None


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str)
    except Exception:  # noqa: BLE001
        return "{}"


def _short_uuid() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _row_to_action(row: sqlite3.Row) -> ApprovalAction:
    return ApprovalAction(
        id=row["id"],
        engine=row["engine"],
        action_type=row["action_type"],
        capability=row["capability"],
        params=_safe_loads(row["params_json"]),
        narrative=row["narrative"] or "",
        confidence=row["confidence"],
        status=ApprovalStatus(row["status"]),
        proposed_at=row["proposed_at"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        decision_reason=row["decision_reason"],
        result=_safe_loads(row["result_json"]) if row["result_json"] else None,
    )


def _safe_loads(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        loaded = json.loads(payload)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001
        return {}
