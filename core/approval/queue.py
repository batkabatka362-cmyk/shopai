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


def _emit_hook(event_name: str, payload: dict[str, Any]) -> None:
    """Fan ``event_name`` out through the hooks dispatcher.

    Lazy-import so a missing / broken hooks module can't crash
    the queue's hot path. The hooks system has its own test-mode
    bypass and per-handler isolation, so we just delegate.
    """
    try:
        from core.hooks import emit as _emit
    except Exception as exc:  # noqa: BLE001
        # Hooks layer not importable for some reason — silently
        # skip. The queue's persistence already happened.
        logger.debug("hooks import failed: %s", exc)
        return
    try:
        _emit(event_name, payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("hook emit raised for %s: %s", event_name, exc)

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
    store_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "engine": self.engine,
            "action_type": self.action_type,
            "capability": self.capability,
            "params": self.params,
            "narrative": self.narrative,
            "confidence": self.confidence,
            "store_id": self.store_id,
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
                    result_json     TEXT,
                    store_id        TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pending_status
                    ON pending_actions(status, proposed_at);
                CREATE INDEX IF NOT EXISTS idx_pending_engine
                    ON pending_actions(engine, status);

                -- Downstream business outcomes for each executed
                -- action (one row per Shopify webhook that matched
                -- the action's minted code or other linkable id).
                -- Append-only — multiple outcomes per action are
                -- expected (one mint → many redemptions, plus any
                -- refunds).
                CREATE TABLE IF NOT EXISTS action_outcomes (
                    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id     TEXT NOT NULL,
                    topic         TEXT NOT NULL,
                    polarity      TEXT NOT NULL,
                    metrics_json  TEXT,
                    source_event  TEXT,
                    recorded_at   REAL NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES pending_actions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_outcomes_action
                    ON action_outcomes(action_id, recorded_at);

                -- Append-only audit trail of every status transition.
                -- `pending_actions.decided_by`/`decision_reason` carry
                -- only the LATEST decision; this table preserves the
                -- full history so an operator who rejects then
                -- changes their mind doesn't erase the rejection
                -- rationale, and compliance auditors can reconstruct
                -- who decided what when.
                CREATE TABLE IF NOT EXISTS decision_log (
                    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id     TEXT NOT NULL,
                    decision      TEXT NOT NULL,
                    decided_by    TEXT,
                    reason        TEXT,
                    occurred_at   REAL NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES pending_actions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_action
                    ON decision_log(action_id, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_decisions_actor
                    ON decision_log(decided_by, occurred_at);
            """)
            self._conn.commit()
            # Idempotent migration for pre-existing DBs that were
            # created before the ``store_id`` column was part of
            # the schema. New DBs get the column from the CREATE
            # TABLE above; older DBs need an ALTER TABLE that we
            # only run when the column is genuinely missing.
            cols = {
                r["name"] for r in self._conn.execute(
                    "PRAGMA table_info(pending_actions)",
                ).fetchall()
            }
            if "store_id" not in cols:
                self._conn.execute(
                    "ALTER TABLE pending_actions "
                    "ADD COLUMN store_id TEXT"
                )
            # Index creation is safe on both new and migrated DBs
            # since the column now exists in both cases.
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_store "
                "ON pending_actions(store_id, status)",
            )
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
        store_id: str | None = None,
    ) -> ApprovalAction:
        """Park a proposed action for human review.

        Returns the persisted :class:`ApprovalAction`. The queue
        does NOT execute anything — the caller still owns the
        downstream effect once approval lands.

        ``store_id`` is optional but recommended at multi-store
        scale. When supplied, the action is filterable by store
        on every read surface (``list_by_status``, retrieval,
        world-model snapshot's approvals/decisions sections).
        Callers that don't know which store an action belongs
        to (most engines today) can omit it; the row is still
        queryable cross-engine.
        """
        action_id = f"appr_{int(time.time() * 1000)}_{_short_uuid()}"
        now = time.time()
        params_json = _safe_json(params)
        with _LOCK:
            self._conn.execute(
                """INSERT INTO pending_actions
                   (id, engine, action_type, capability, params_json,
                    narrative, confidence, status, proposed_at,
                    store_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action_id, engine, action_type, capability,
                    params_json, narrative, confidence,
                    ApprovalStatus.PENDING.value, now,
                    store_id,
                ),
            )
            self._conn.commit()
        logger.info(
            "approval enqueued: %s engine=%s action=%s store=%s",
            action_id, engine, action_type, store_id or "-",
        )
        action = ApprovalAction(
            id=action_id, engine=engine, action_type=action_type,
            capability=capability, params=params,
            narrative=narrative, confidence=confidence,
            status=ApprovalStatus.PENDING, proposed_at=now,
            decided_at=None, decided_by=None, decision_reason=None,
            result=None, store_id=store_id,
        )
        _emit_hook("approval.queued", {
            "action_id": action_id,
            "engine": engine,
            "action_type": action_type,
            "capability": capability,
            "narrative": narrative,
            "confidence": confidence,
        })

        # Auto-approve evaluator (PR #161). Safe defaults — engines
        # opt in per-namespace via the allowlist; pytest is gated
        # so test seeds never trigger a live auto-transition.
        # Refresh ``action`` from the DB after the maybe-approve so
        # the returned object reflects the auto-decision (otherwise
        # callers see status=PENDING for an already-APPROVED row).
        auto_approved = False
        try:
            from core.approval.auto_approve import maybe_auto_approve
            decision = maybe_auto_approve(
                queue=self, action_id=action_id,
                engine=engine, confidence=confidence,
            )
            if decision.should_auto:
                auto_approved = True
                refreshed = self.get(action_id)
                if refreshed is not None:
                    action = refreshed
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "auto-approve hook raised for %s: %s",
                action_id, exc,
            )

        # Quarantine evaluator (PR #162). Only checked when the
        # auto-approve hook didn't already transition the action —
        # an engine that just auto-approved had a healthy ratio at
        # eval time, so the quarantine check would be redundant
        # work and an unnecessary attempt to reject an APPROVED row.
        if not auto_approved:
            try:
                from core.approval.quarantine import maybe_quarantine
                q_decision = maybe_quarantine(
                    queue=self, action_id=action_id, engine=engine,
                )
                if q_decision.should_quarantine:
                    refreshed = self.get(action_id)
                    if refreshed is not None:
                        action = refreshed
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "quarantine hook raised for %s: %s",
                    action_id, exc,
                )

        return action

    def get(self, action_id: str) -> ApprovalAction | None:
        """Fetch a single action by id, regardless of status."""
        with _LOCK:
            row = self._conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,),
            ).fetchone()
        return _row_to_action(row) if row else None

    def list_pending(
        self, *, engine: str | None = None, limit: int = 100,
        store_id: str | None = None,
    ) -> list[ApprovalAction]:
        """Return open (pending) actions oldest-first.

        ``engine`` filters to a single engine namespace; ``limit``
        caps the page size. ``store_id`` filters to a single
        store (post-launch addition; rows enqueued before the
        column existed have store_id=NULL and are excluded from
        the filtered result). The API surface uses this to
        render the merchant's review queue.
        """
        clauses = ["status = ?"]
        params: list[Any] = [ApprovalStatus.PENDING.value]
        if engine:
            clauses.append("engine = ?")
            params.append(engine)
        if store_id is not None:
            clauses.append("store_id = ?")
            params.append(store_id)
        params.append(limit)
        sql = (
            "SELECT * FROM pending_actions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY proposed_at ASC LIMIT ?"
        )
        with _LOCK:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_action(r) for r in rows]

    def list_by_status(
        self,
        status: "ApprovalStatus",
        *,
        engine: str | None = None,
        limit: int = 500,
        store_id: str | None = None,
    ) -> list[ApprovalAction]:
        """Return actions in a given status, newest-first by decision
        time (falling back to proposed_at for PENDING which has no
        decision yet).

        Generalisation of :meth:`list_pending` / :meth:`list_executed`
        for operator triage queries — "show me the last 5 FAILED
        actions" / "what expired this week?" — where the existing
        pair didn't cover REJECTED / FAILED / EXPIRED.

        ``store_id`` filters to one store (post-launch addition;
        rows enqueued before the column existed have store_id=NULL
        and are excluded from the filtered result).
        """
        order_by = (
            "proposed_at" if status == ApprovalStatus.PENDING
            else "decided_at"
        )
        # Sort PENDING oldest-first (review queue), everything else
        # newest-first (recent activity feed).
        direction = "ASC" if status == ApprovalStatus.PENDING else "DESC"
        clauses = ["status = ?"]
        params: list[Any] = [status.value]
        if engine:
            clauses.append("engine = ?")
            params.append(engine)
        if store_id is not None:
            clauses.append("store_id = ?")
            params.append(store_id)
        params.append(limit)
        sql = (
            "SELECT * FROM pending_actions WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY {order_by} {direction} LIMIT ?"
        )
        with _LOCK:
            rows = self._conn.execute(sql, params).fetchall()
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
        Emits ``approval.approved`` hook on a real transition.
        """
        action = self._transition(
            action_id,
            from_status=ApprovalStatus.PENDING,
            to_status=ApprovalStatus.APPROVED,
            decided_by=decided_by,
            reason=reason,
        )
        if action is not None:
            _emit_hook("approval.approved", {
                "action_id": action.id,
                "engine": action.engine,
                "action_type": action.action_type,
                "capability": action.capability,
                "decided_by": decided_by,
                "reason": reason,
            })
        return action

    def reject(
        self,
        action_id: str,
        *,
        decided_by: str = "",
        reason: str = "",
    ) -> ApprovalAction | None:
        """Mark a pending action rejected. Same idempotency contract
        as :meth:`approve`. Emits ``approval.rejected`` hook on a
        real transition.
        """
        action = self._transition(
            action_id,
            from_status=ApprovalStatus.PENDING,
            to_status=ApprovalStatus.REJECTED,
            decided_by=decided_by,
            reason=reason,
        )
        if action is not None:
            _emit_hook("approval.rejected", {
                "action_id": action.id,
                "engine": action.engine,
                "action_type": action.action_type,
                "capability": action.capability,
                "decided_by": decided_by,
                "reason": reason,
            })
        return action

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
        Emits ``approval.executed`` or ``approval.failed`` hook on
        a real transition.
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
            # Audit-trail row: who/why is unknown for an executor
            # transition (the executor is the system, not a human),
            # but the timestamp + decision name are still load-
            # bearing for a compliance reader.
            self._conn.execute(
                """INSERT INTO decision_log
                   (action_id, decision, decided_by, reason, occurred_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    action_id, target.value, "system",
                    None if success else "execution_failed",
                    time.time(),
                ),
            )
            self._conn.commit()
            new_row = self._conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,),
            ).fetchone()
        action = _row_to_action(new_row) if new_row else None
        if action is not None:
            hook_name = (
                "approval.executed" if success else "approval.failed"
            )
            _emit_hook(hook_name, {
                "action_id": action.id,
                "engine": action.engine,
                "action_type": action.action_type,
                "capability": action.capability,
                "success": success,
                "result": result or {},
            })
        return action

    def expire_stale(self, *, max_age_seconds: float) -> list[ApprovalAction]:
        """Bulk-transition PENDING actions older than ``max_age_seconds``
        to EXPIRED. Returns the list of just-expired actions (newest
        first), or ``[]`` if nothing matched.

        Emits ``approval.expired`` for each transition. The lifecycle
        docstring at the top of this module flagged EXPIRED as "TTL
        only, not auto-applied in v1"; this method is the v2 sweep —
        callers (a cron, the CLI ``approvals sweep`` verb) decide when
        to invoke it.
        """
        cutoff = time.time() - max_age_seconds
        now = time.time()
        with _LOCK:
            rows = self._conn.execute(
                """SELECT * FROM pending_actions
                   WHERE status = ? AND proposed_at < ?
                   ORDER BY proposed_at ASC""",
                (ApprovalStatus.PENDING.value, cutoff),
            ).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            ttl_reason = f"ttl_exceeded ({int(max_age_seconds)}s)"
            self._conn.execute(
                f"""UPDATE pending_actions
                   SET status = ?, decided_at = ?,
                       decision_reason = ?
                   WHERE id IN ({placeholders})""",
                (
                    ApprovalStatus.EXPIRED.value,
                    now,
                    ttl_reason,
                    *ids,
                ),
            )
            self._conn.executemany(
                """INSERT INTO decision_log
                   (action_id, decision, decided_by, reason, occurred_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        aid, ApprovalStatus.EXPIRED.value, "system",
                        ttl_reason, now,
                    )
                    for aid in ids
                ],
            )
            self._conn.commit()
            new_rows = self._conn.execute(
                f"""SELECT * FROM pending_actions
                   WHERE id IN ({placeholders})
                   ORDER BY decided_at DESC""",
                ids,
            ).fetchall()

        expired = [_row_to_action(r) for r in new_rows]
        for a in expired:
            _emit_hook("approval.expired", {
                "action_id": a.id,
                "engine": a.engine,
                "action_type": a.action_type,
                "capability": a.capability,
                "age_seconds": int(now - a.proposed_at),
            })
        logger.info(
            "expire_stale: %d PENDING actions older than %ds → EXPIRED",
            len(expired), int(max_age_seconds),
        )
        return expired

    def stats_by_engine(self) -> dict[str, dict[str, int]]:
        """Counts per engine x status. Used by ``shopai approvals
        stats --by-engine`` and the API endpoint that surfaces
        per-engine triage signal (which engines have growing
        rejection / expiry rates).

        Returns a nested dict ``{engine: {status: count}}``. Engines
        with no queue activity are absent; each present engine has
        an entry per :class:`ApprovalStatus` (zeros included).
        """
        with _LOCK:
            rows = self._conn.execute(
                """SELECT engine, status, COUNT(*) as n
                   FROM pending_actions
                   GROUP BY engine, status""",
            ).fetchall()

        all_statuses = [s.value for s in ApprovalStatus]
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            engine = r["engine"]
            if engine not in out:
                out[engine] = {s: 0 for s in all_statuses}
            out[engine][r["status"]] = int(r["n"])
        return out

    def record_outcome(
        self,
        action_id: str,
        *,
        topic: str,
        polarity: str = "neutral",
        metrics: dict[str, Any] | None = None,
        source_event: str | None = None,
    ) -> bool:
        """Annotate an action with a downstream business outcome.

        Called by the webhook-feedback bridge after it matches a
        Shopify event (orders/create, refunds/create, ...) back to
        the action that minted the discount code. Lets operators see
        "this action drove $X" when they ``shopai approvals show``
        the executed action.

        Args:
            action_id: The action this outcome belongs to.
            topic: Shopify webhook topic ("orders/create", ...).
            polarity: "positive", "negative", or "neutral" (matches
                the bridge's polarity mapping).
            metrics: Optional dict of business numbers (revenue,
                refund_amount, etc.) — surfaced verbatim on read.
            source_event: Optional Shopify event id for trace-back.

        Returns:
            True if the outcome row was inserted; False on no-op
            (unknown action id — outcomes for unknown actions are
            silently dropped rather than orphan-inserted).
        """
        if not isinstance(action_id, str) or not action_id:
            return False
        if not isinstance(topic, str) or not topic:
            return False
        if polarity not in ("positive", "negative", "neutral"):
            polarity = "neutral"

        with _LOCK:
            # Look up engine/action_type for the hook payload AND
            # verify action exists (orphan outcomes are useless and
            # would mask data bugs).
            row = self._conn.execute(
                """SELECT engine, action_type
                   FROM pending_actions WHERE id = ? LIMIT 1""",
                (action_id,),
            ).fetchone()
            if not row:
                logger.debug(
                    "record_outcome no-op: unknown action %s",
                    action_id,
                )
                return False
            self._conn.execute(
                """INSERT INTO action_outcomes
                   (action_id, topic, polarity, metrics_json,
                    source_event, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    action_id, topic, polarity,
                    _safe_json(metrics or {}),
                    source_event, time.time(),
                ),
            )
            self._conn.commit()
        logger.info(
            "outcome recorded: action=%s topic=%s polarity=%s",
            action_id, topic, polarity,
        )
        # Fan out so goal feedback (and any other consumer) can
        # refine the brain stack's effectiveness EMA with the real
        # downstream signal — not just "the mutation succeeded".
        _emit_hook("approval.outcome.recorded", {
            "action_id": action_id,
            "engine": row["engine"],
            "action_type": row["action_type"],
            "topic": topic,
            "polarity": polarity,
            "metrics": dict(metrics or {}),
            "source_event": source_event,
        })
        return True

    def get_outcomes(self, action_id: str) -> list[dict[str, Any]]:
        """Return all outcome rows for an action, oldest-first.

        Each row is a dict with topic / polarity / metrics /
        source_event / recorded_at. Empty list when nothing has
        downstream-matched yet (most actions, in steady state).
        """
        if not isinstance(action_id, str) or not action_id:
            return []
        with _LOCK:
            rows = self._conn.execute(
                """SELECT topic, polarity, metrics_json,
                          source_event, recorded_at
                   FROM action_outcomes
                   WHERE action_id = ?
                   ORDER BY recorded_at ASC""",
                (action_id,),
            ).fetchall()
        return [{
            "topic": r["topic"],
            "polarity": r["polarity"],
            "metrics": _safe_loads(r["metrics_json"]),
            "source_event": r["source_event"],
            "recorded_at": r["recorded_at"],
        } for r in rows]

    def engine_outcome_stats(
        self, engine_name: str,
    ) -> dict[str, Any]:
        """Aggregate outcomes for a single engine — the per-engine
        effectiveness signal that goal-level EMA misses.

        Joins ``action_outcomes`` with ``pending_actions`` on
        ``engine = engine_name``. Counts positive / negative /
        neutral polarities, sums revenue across rows, and computes
        ``outcome_score`` = positive / (positive + negative) when
        there's at least one polarised event, else ``None``.

        Returns:
            {
              "positive_count": int,
              "negative_count": int,
              "neutral_count":  int,
              "total_outcomes": int,
              "total_revenue":  float,  # net of refunds
              "outcome_score":  float | None,  # [0.0, 1.0]
            }

        Used by the engine recommender as a per-engine tiebreaker
        within a goal cluster: two engines mapped to the same goal
        with the same goal-level EMA can still be differentiated
        by their direct outcome track records.
        """
        if not isinstance(engine_name, str) or not engine_name:
            return {
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total_outcomes": 0,
                "total_revenue": 0.0,
                "outcome_score": None,
            }

        with _LOCK:
            rows = self._conn.execute(
                """SELECT o.polarity, o.metrics_json
                   FROM action_outcomes o
                   INNER JOIN pending_actions p ON p.id = o.action_id
                   WHERE p.engine = ?""",
                (engine_name,),
            ).fetchall()

        positive = negative = neutral = 0
        revenue = 0.0
        for r in rows:
            polarity = r["polarity"]
            if polarity == "positive":
                positive += 1
            elif polarity == "negative":
                negative += 1
            else:
                neutral += 1
            metrics = _safe_loads(r["metrics_json"])
            try:
                rev = float(metrics.get("revenue", 0) or 0)
            except (TypeError, ValueError):
                rev = 0.0
            # Refunds (negative polarity) deduct from net revenue;
            # the bridge already stores revenue as a positive number
            # regardless of polarity, so we sign it here.
            if polarity == "negative":
                revenue -= rev
            else:
                revenue += rev

        signal = positive + negative
        outcome_score: float | None = (
            (positive / signal) if signal > 0 else None
        )
        return {
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "total_outcomes": positive + negative + neutral,
            "total_revenue": round(revenue, 2),
            "outcome_score": (
                round(outcome_score, 4)
                if outcome_score is not None
                else None
            ),
        }

    def all_engine_outcome_stats(self) -> dict[str, dict[str, Any]]:
        """Per-engine outcome aggregator across every engine that
        has any matched outcomes. Engines with no outcomes are
        absent from the result (callers default to neutral).

        Single SQL pass over the join. Used by the recommender
        when it wants to score every candidate engine in one
        call rather than N round-trips through
        :meth:`engine_outcome_stats`.
        """
        with _LOCK:
            rows = self._conn.execute(
                """SELECT p.engine, o.polarity, o.metrics_json
                   FROM action_outcomes o
                   INNER JOIN pending_actions p ON p.id = o.action_id""",
            ).fetchall()

        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            engine = r["engine"]
            entry = agg.setdefault(engine, {
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total_revenue": 0.0,
            })
            polarity = r["polarity"]
            if polarity == "positive":
                entry["positive_count"] += 1
            elif polarity == "negative":
                entry["negative_count"] += 1
            else:
                entry["neutral_count"] += 1
            metrics = _safe_loads(r["metrics_json"])
            try:
                rev = float(metrics.get("revenue", 0) or 0)
            except (TypeError, ValueError):
                rev = 0.0
            if polarity == "negative":
                entry["total_revenue"] -= rev
            else:
                entry["total_revenue"] += rev

        # Finalise: compute outcome_score and total_outcomes
        for engine, entry in agg.items():
            signal = entry["positive_count"] + entry["negative_count"]
            entry["total_outcomes"] = (
                signal + entry["neutral_count"]
            )
            entry["outcome_score"] = (
                round(entry["positive_count"] / signal, 4)
                if signal > 0 else None
            )
            entry["total_revenue"] = round(entry["total_revenue"], 2)
        return agg

    def engine_confidence_calibration(
        self,
        engine_name: str,
    ) -> dict[str, Any]:
        """Per-engine confidence-bucket calibration check.

        Engines self-assign each proposed action a ``confidence``
        score in [0, 1]. Whether that confidence is actually
        meaningful — i.e. whether high-confidence actions DO
        outperform low-confidence ones — is the calibration
        question. A well-calibrated engine shows monotonically
        increasing outcome_score across confidence buckets; a
        miscalibrated one (e.g. high-confidence actions doing
        worse than mid-confidence) is a red flag.

        Operators use this surface for three things:
          1. Sanity-check trust before opting an engine into
             auto-approve (PR #161). The MIN_CONFIDENCE floor
             only works if confidence means something.
          2. Spot regressions — calibration shape suddenly
             flipping is an early warning a model degraded.
          3. Compare engines — pick whichever's better calibrated
             when two engines compete for the same goal.

        Bucketing: half-open intervals
        ``[0.0, 0.5), [0.5, 0.6), [0.6, 0.7), [0.7, 0.8),
        [0.8, 0.9), [0.9, 1.001)`` — the last bucket is inclusive
        of 1.0 so confidence=1.0 actions don't fall off the chart.

        Returns:
            {
              "engine": "<name>",
              "buckets": [
                {
                  "label": "0.0-0.5", "low": 0.0, "high": 0.5,
                  "action_count": int,
                  "positive_outcomes": int,
                  "negative_outcomes": int,
                  "outcome_score": float | None,
                },
                ...
              ],
              "monotonic_increasing": bool | None,
                # True if non-None bucket scores rise across
                # confidence (well-calibrated); False if any
                # adjacent pair inverts; None when < 2 buckets
                # have outcome data.
            }
        """
        if not isinstance(engine_name, str) or not engine_name:
            return {
                "engine": engine_name or "",
                "buckets": [],
                "monotonic_increasing": None,
            }

        # Edges define half-open ranges except the topmost which
        # nudges up to include exactly-1.0 confidences.
        edges = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.001]
        bucket_count = len(edges) - 1
        action_counts = [0] * bucket_count
        positive = [0] * bucket_count
        negative = [0] * bucket_count
        seen_actions: set[str] = set()

        with _LOCK:
            rows = self._conn.execute(
                """SELECT p.id, p.confidence,
                          o.polarity
                   FROM pending_actions p
                   LEFT JOIN action_outcomes o
                          ON o.action_id = p.id
                   WHERE p.engine = ?
                     AND p.confidence IS NOT NULL""",
                (engine_name,),
            ).fetchall()

        for r in rows:
            try:
                conf = float(r["confidence"])
            except (TypeError, ValueError):
                continue
            if conf < 0.0 or conf > 1.0:
                continue
            # Locate bucket: first edge[i] such that conf < edge[i+1]
            idx = 0
            for i in range(bucket_count):
                if conf < edges[i + 1]:
                    idx = i
                    break
            else:
                idx = bucket_count - 1

            # Count each action once toward the bucket's action
            # count (LEFT JOIN can produce duplicate rows when an
            # action has multiple outcomes).
            action_id = r["id"]
            if action_id not in seen_actions:
                action_counts[idx] += 1
                seen_actions.add(action_id)

            # Count each outcome row toward the bucket's polarity
            # counts.
            polarity = r["polarity"]
            if polarity == "positive":
                positive[idx] += 1
            elif polarity == "negative":
                negative[idx] += 1

        buckets: list[dict[str, Any]] = []
        for i in range(bucket_count):
            low = edges[i]
            # Display "1.0" rather than "1.001" for the top edge
            high_display = (
                1.0 if edges[i + 1] > 1.0 else edges[i + 1]
            )
            signal = positive[i] + negative[i]
            outcome_score: float | None = (
                round(positive[i] / signal, 4)
                if signal > 0 else None
            )
            buckets.append({
                "label": f"{low:.1f}-{high_display:.1f}",
                "low": low,
                "high": high_display,
                "action_count": action_counts[i],
                "positive_outcomes": positive[i],
                "negative_outcomes": negative[i],
                "outcome_score": outcome_score,
            })

        # Calibration quality check: outcome_score should rise
        # (or at least not fall) across consecutive buckets that
        # have signal. A single inversion flips this to False —
        # the operator sees the shape in the table and decides
        # the severity.
        scores_in_order = [
            b["outcome_score"] for b in buckets
            if b["outcome_score"] is not None
        ]
        monotonic_increasing: bool | None
        if len(scores_in_order) < 2:
            monotonic_increasing = None
        else:
            monotonic_increasing = all(
                scores_in_order[i] <= scores_in_order[i + 1]
                for i in range(len(scores_in_order) - 1)
            )

        return {
            "engine": engine_name,
            "buckets": buckets,
            "monotonic_increasing": monotonic_increasing,
        }

    def all_engines_calibration(self) -> dict[str, dict[str, Any]]:
        """Per-engine calibration sweep across every engine that
        has confidence-tagged actions.

        Returns ``{engine_name: calibration_result}``. Engines
        without any confidence-tagged actions are absent from
        the result (no signal to assess).

        Used by the ``shopai engines-calibration`` triage view
        to flag miscalibrated engines at a glance without N
        per-engine round-trips.
        """
        # Find engines that have at least one confidence-tagged
        # action — cheaper than scanning every engine in the
        # registry blindly.
        with _LOCK:
            engine_rows = self._conn.execute(
                """SELECT DISTINCT engine
                   FROM pending_actions
                   WHERE confidence IS NOT NULL""",
            ).fetchall()
        engines = [r["engine"] for r in engine_rows]
        return {
            engine: self.engine_confidence_calibration(engine)
            for engine in sorted(engines)
        }

    def pending_latency_stats(self) -> dict[str, dict[str, Any]]:
        """Per-engine PENDING-action age aggregator.

        Surfaces engines producing proposals operators consistently
        don't act on. Either the engine is spammy (too many
        proposals) or the proposals aren't useful enough to
        warrant the click — either way, a triage signal worth
        looking at.

        Returns ``{engine: stats}`` for each engine with at least
        one PENDING action. Engines with zero pending are absent.
        Each stats dict carries:
          - ``pending_count``: int
          - ``oldest_age_seconds``: float (seconds since the
            oldest PENDING was proposed)
          - ``median_age_seconds``: float (50th percentile of
            ages across this engine's PENDING bucket)
          - ``mean_age_seconds``: float (arithmetic mean, useful
            when the distribution is concentrated)
        """
        now = time.time()
        with _LOCK:
            rows = self._conn.execute(
                """SELECT engine, proposed_at
                   FROM pending_actions
                   WHERE status = ?
                   ORDER BY engine, proposed_at""",
                (ApprovalStatus.PENDING.value,),
            ).fetchall()

        by_engine: dict[str, list[float]] = {}
        for r in rows:
            age = max(0.0, now - float(r["proposed_at"]))
            by_engine.setdefault(r["engine"], []).append(age)

        result: dict[str, dict[str, Any]] = {}
        for engine, ages in by_engine.items():
            ages_sorted = sorted(ages)
            n = len(ages_sorted)
            # Median: lower middle for even-count is fine here
            # (we only need a stable indicator, not p50 to a
            # spec)
            if n == 0:
                continue
            if n % 2 == 1:
                median = ages_sorted[n // 2]
            else:
                median = (
                    ages_sorted[n // 2 - 1]
                    + ages_sorted[n // 2]
                ) / 2.0
            result[engine] = {
                "pending_count": n,
                "oldest_age_seconds": round(ages_sorted[-1], 1),
                "median_age_seconds": round(median, 1),
                "mean_age_seconds": round(sum(ages_sorted) / n, 1),
            }
        return result

    def decision_latency_stats(
        self,
        *,
        statuses: list[ApprovalStatus] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Per-engine aggregate of decision latency.

        Latency = ``decided_at - proposed_at`` — i.e. the time
        from engine proposal to operator click. This is the
        complement to :meth:`pending_latency_stats`:

          - Pending latency: "what's stale RIGHT NOW?"
          - Decision latency: "historically, how fast did
            operators DECIDE on this engine's proposals?"

        Together they distinguish four operator-engine patterns:

          - High pending + low decision latency: spammy engine,
            operators DO act quickly but lots of proposals →
            tune frequency.
          - High pending + high decision latency: engine
            producing un-actionable proposals → reconsider it.
          - Low pending + low decision latency: healthy.
          - Low pending + high decision latency: operators
            struggle when they DO act → investigate UX.

        EXPIRED is excluded from the default ``statuses`` because
        ``decided_at`` on an EXPIRED row reflects sweeper time,
        not operator-click time — including it would skew the
        signal. Operators wanting that view pass
        ``statuses=[ApprovalStatus.EXPIRED]`` explicitly.

        Returns ``{engine: stats}`` for each engine with at
        least one decided action in the requested status set.
        Each stats dict carries:
          - ``decided_count`` (int)
          - ``slowest_seconds`` (float)
          - ``median_seconds`` (float, p50)
          - ``mean_seconds`` (float, arithmetic mean)
        """
        if statuses is None:
            statuses = [
                ApprovalStatus.APPROVED,
                ApprovalStatus.REJECTED,
                ApprovalStatus.EXECUTED,
                ApprovalStatus.FAILED,
            ]
        if not statuses:
            return {}

        status_values = [s.value for s in statuses]
        placeholders = ",".join("?" for _ in status_values)
        with _LOCK:
            rows = self._conn.execute(
                f"""SELECT engine, proposed_at, decided_at
                    FROM pending_actions
                    WHERE status IN ({placeholders})
                      AND decided_at IS NOT NULL""",
                status_values,
            ).fetchall()

        by_engine: dict[str, list[float]] = {}
        for r in rows:
            latency = max(
                0.0,
                float(r["decided_at"]) - float(r["proposed_at"]),
            )
            by_engine.setdefault(r["engine"], []).append(latency)

        result: dict[str, dict[str, Any]] = {}
        for engine, latencies in by_engine.items():
            latencies_sorted = sorted(latencies)
            n = len(latencies_sorted)
            if n == 0:
                continue
            if n % 2 == 1:
                median = latencies_sorted[n // 2]
            else:
                median = (
                    latencies_sorted[n // 2 - 1]
                    + latencies_sorted[n // 2]
                ) / 2.0
            result[engine] = {
                "decided_count": n,
                "slowest_seconds": round(latencies_sorted[-1], 1),
                "median_seconds": round(median, 1),
                "mean_seconds": round(sum(latencies_sorted) / n, 1),
            }
        return result

    def rejection_rate_stats(self) -> dict[str, dict[str, Any]]:
        """Per-engine rejection rate — surfaces engines whose
        proposals operators consistently veto.

        Different signal from:
          - PR #168 pending-latency: engines whose proposals
            sit (operators IGNORE).
          - PR #169 decision-latency: engines where decisions
            are slow (operators STRUGGLE).
          - PR #162 quarantine: engines whose EXECUTED outcomes
            turn negative (downstream impact).

        Rejection is the explicit "no, this is wrong" verdict
        BEFORE execute — the operator is saying the proposal
        itself is bad. High rejection rate = the engine is
        misbehaving at the proposal stage.

        Returns ``{engine: stats}`` for each engine with at
        least one operator-decided action (APPROVED, REJECTED,
        EXECUTED, FAILED). EXPIRED is excluded because it
        wasn't an operator decision — the sweeper TTL'd it.

        Each stats dict carries:
          - ``decided_count`` (int): total operator-decided
            actions for this engine
          - ``rejected_count`` (int)
          - ``approved_count`` (int): includes APPROVED +
            EXECUTED + FAILED (all started as operator approve)
          - ``rejection_rate`` (float): rejected / decided
        """
        operator_statuses = [
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.REJECTED.value,
            ApprovalStatus.EXECUTED.value,
            ApprovalStatus.FAILED.value,
        ]
        placeholders = ",".join("?" for _ in operator_statuses)
        with _LOCK:
            rows = self._conn.execute(
                f"""SELECT engine, status, COUNT(*) AS n
                    FROM pending_actions
                    WHERE status IN ({placeholders})
                    GROUP BY engine, status""",
                operator_statuses,
            ).fetchall()

        by_engine: dict[str, dict[str, int]] = {}
        for r in rows:
            engine = r["engine"]
            entry = by_engine.setdefault(engine, {
                "approved_count": 0,
                "rejected_count": 0,
                "decided_count": 0,
            })
            count = int(r["n"])
            entry["decided_count"] += count
            if r["status"] == ApprovalStatus.REJECTED.value:
                entry["rejected_count"] += count
            else:
                # APPROVED + EXECUTED + FAILED all originate
                # from an operator approve transition.
                entry["approved_count"] += count

        result: dict[str, dict[str, Any]] = {}
        for engine, entry in by_engine.items():
            decided = entry["decided_count"]
            if decided == 0:
                continue
            result[engine] = {
                "decided_count": decided,
                "rejected_count": entry["rejected_count"],
                "approved_count": entry["approved_count"],
                "rejection_rate": round(
                    entry["rejected_count"] / decided, 4,
                ),
            }
        return result

    def revenue_attribution_stats(self) -> dict[str, dict[str, Any]]:
        """Per-engine revenue attribution from matched outcomes.

        The existing :meth:`engine_outcome_stats` returns a SIGNED
        net total that mixes positive uplift and refunded revenue
        — fine for the recommender's effectiveness score, but
        operators inspecting which engines drive revenue need the
        breakdown:

          - ``gross_revenue``: positive-polarity revenue sum
            (the engine's contribution before refunds).
          - ``refunded_revenue``: negative-polarity revenue sum,
            as a positive number (what came back). Lets operators
            see "engine X drove $10k gross but $2k came back".
          - ``net_revenue``: gross - refunded.
          - ``positive_outcomes`` / ``negative_outcomes``: outcome
            counts, helpful for sanity-checking small numbers.
          - ``revenue_per_positive_outcome``: gross / positive
            count. The "average impact when something good
            happens" — useful for cross-engine comparison
            independent of volume.

        Returns ``{engine: stats}`` for each engine with at
        least one matched outcome. Engines without outcomes are
        absent.
        """
        with _LOCK:
            rows = self._conn.execute(
                """SELECT p.engine, o.polarity, o.metrics_json
                   FROM action_outcomes o
                   INNER JOIN pending_actions p ON p.id = o.action_id""",
            ).fetchall()

        by_engine: dict[str, dict[str, Any]] = {}
        for r in rows:
            engine = r["engine"]
            entry = by_engine.setdefault(engine, {
                "gross_revenue": 0.0,
                "refunded_revenue": 0.0,
                "positive_outcomes": 0,
                "negative_outcomes": 0,
            })
            metrics = _safe_loads(r["metrics_json"])
            try:
                rev = float(metrics.get("revenue", 0) or 0)
            except (TypeError, ValueError):
                rev = 0.0
            polarity = r["polarity"]
            if polarity == "positive":
                entry["positive_outcomes"] += 1
                entry["gross_revenue"] += rev
            elif polarity == "negative":
                entry["negative_outcomes"] += 1
                entry["refunded_revenue"] += rev
            # neutral polarities don't carry revenue
            # attribution — silently skip.

        result: dict[str, dict[str, Any]] = {}
        for engine, entry in by_engine.items():
            gross = entry["gross_revenue"]
            refunded = entry["refunded_revenue"]
            pos = entry["positive_outcomes"]
            rev_per_pos: float | None = (
                round(gross / pos, 2) if pos > 0 else None
            )
            result[engine] = {
                "gross_revenue": round(gross, 2),
                "refunded_revenue": round(refunded, 2),
                "net_revenue": round(gross - refunded, 2),
                "positive_outcomes": pos,
                "negative_outcomes": entry["negative_outcomes"],
                "revenue_per_positive_outcome": rev_per_pos,
            }
        return result

    def engine_scorecard(self, engine_name: str) -> dict[str, Any]:
        """Unified scorecard combining every per-engine signal.

        The natural capstone to the per-engine intelligence stack.
        Each subsection comes from a dedicated method but reading
        them piecemeal forces operators to bounce between 5+
        commands to assemble a full picture of one engine. This
        method returns the consolidated dict in a single call.

        Sections:
          - ``engine`` (str)
          - ``volume``: counts across the action lifecycle
            (pending / approved / rejected / executed / failed /
            expired)
          - ``outcomes``: outcome counts + outcome_score from
            :meth:`engine_outcome_stats`
          - ``calibration``: monotonic_increasing flag from
            :meth:`engine_confidence_calibration`
          - ``workflow``: pending + decision latency medians
          - ``veto``: rejection_rate from
            :meth:`rejection_rate_stats`
          - ``revenue``: gross / refunded / net from
            :meth:`revenue_attribution_stats`

        Each subsection's missing-data semantics are preserved
        (e.g. ``calibration.monotonic_increasing`` is ``None`` for
        engines without enough confidence-tagged history). Empty
        subsections return their existing empty shape, not absent
        keys — callers can rely on the schema.
        """
        if not isinstance(engine_name, str) or not engine_name:
            return {"engine": engine_name or "", "error": "invalid_engine_name"}

        scorecard: dict[str, Any] = {
            "engine": engine_name,
            "volume": {
                "pending": 0,
                "approved": 0,
                "rejected": 0,
                "executed": 0,
                "failed": 0,
                "expired": 0,
            },
        }

        # ── Volume ────────────────────────────────────────────
        with _LOCK:
            volume_rows = self._conn.execute(
                """SELECT status, COUNT(*) AS n
                   FROM pending_actions
                   WHERE engine = ?
                   GROUP BY status""",
                (engine_name,),
            ).fetchall()
        for r in volume_rows:
            key = r["status"]
            if key in scorecard["volume"]:
                scorecard["volume"][key] = int(r["n"])

        # ── Outcomes ──────────────────────────────────────────
        scorecard["outcomes"] = self.engine_outcome_stats(
            engine_name,
        )

        # ── Calibration ───────────────────────────────────────
        scorecard["calibration"] = (
            self.engine_confidence_calibration(engine_name)
        )

        # ── Workflow ──────────────────────────────────────────
        pending_stats = self.pending_latency_stats()
        decision_stats = self.decision_latency_stats()
        scorecard["workflow"] = {
            "pending": pending_stats.get(engine_name, {
                "pending_count": 0,
                "oldest_age_seconds": 0.0,
                "median_age_seconds": 0.0,
                "mean_age_seconds": 0.0,
            }),
            "decision": decision_stats.get(engine_name, {
                "decided_count": 0,
                "slowest_seconds": 0.0,
                "median_seconds": 0.0,
                "mean_seconds": 0.0,
            }),
        }

        # ── Veto ──────────────────────────────────────────────
        rejection_stats = self.rejection_rate_stats()
        scorecard["veto"] = rejection_stats.get(engine_name, {
            "decided_count": 0,
            "rejected_count": 0,
            "approved_count": 0,
            "rejection_rate": 0.0,
        })

        # ── Revenue ───────────────────────────────────────────
        revenue_stats = self.revenue_attribution_stats()
        scorecard["revenue"] = revenue_stats.get(engine_name, {
            "gross_revenue": 0.0,
            "refunded_revenue": 0.0,
            "net_revenue": 0.0,
            "positive_outcomes": 0,
            "negative_outcomes": 0,
            "revenue_per_positive_outcome": None,
        })

        return scorecard

    def list_recent_outcomes(
        self,
        *,
        limit: int = 50,
        engine: str | None = None,
        polarity: str | None = None,
        since_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """Chronological view of webhook outcomes across all
        executed actions. Used by ``shopai outcomes`` + the
        ``/api/outcomes`` endpoint to answer "what's happening
        downstream right now?"

        Each row is a flat dict with action context joined in:
        ``action_id`` / ``engine`` / ``action_type`` / ``topic`` /
        ``polarity`` / ``metrics`` / ``source_event`` /
        ``recorded_at``. Newest-first.

        Filters (all optional, AND-combined):
          - ``engine``: only outcomes for one engine namespace
          - ``polarity``: positive | negative | neutral
          - ``since_seconds``: only outcomes recorded within the
            last N seconds (useful for "last hour" / "last day"
            sweeps)
        """
        clauses: list[str] = []
        params: list[Any] = []
        if engine:
            clauses.append("p.engine = ?")
            params.append(engine)
        if polarity in ("positive", "negative", "neutral"):
            clauses.append("o.polarity = ?")
            params.append(polarity)
        if since_seconds is not None and since_seconds >= 0:
            clauses.append("o.recorded_at >= ?")
            params.append(time.time() - float(since_seconds))
        where = (
            " WHERE " + " AND ".join(clauses) if clauses else ""
        )
        sql = (
            "SELECT o.action_id, p.engine, p.action_type, "
            "       o.topic, o.polarity, o.metrics_json, "
            "       o.source_event, o.recorded_at "
            "FROM action_outcomes o "
            "INNER JOIN pending_actions p ON p.id = o.action_id"
            + where
            + " ORDER BY o.recorded_at DESC LIMIT ?"
        )
        params.append(max(1, int(limit)))

        with _LOCK:
            rows = self._conn.execute(sql, params).fetchall()
        return [{
            "action_id": r["action_id"],
            "engine": r["engine"],
            "action_type": r["action_type"],
            "topic": r["topic"],
            "polarity": r["polarity"],
            "metrics": _safe_loads(r["metrics_json"]),
            "source_event": r["source_event"],
            "recorded_at": r["recorded_at"],
        } for r in rows]

    def list_decisions(
        self,
        *,
        action_id: str | None = None,
        decided_by: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Append-only decision history for an action (or, when
        ``action_id`` is omitted, the global decision ticker).

        Returns flat dicts ordered chronologically: oldest first
        when scoped to one action (reading top-to-bottom = lifecycle),
        newest first when scanning globally (latest activity first).

        Filters compose:
          - ``action_id``: only this action's transitions
          - ``decided_by``: who made the call (use ``"system"`` for
            executor / TTL-sweep transitions)
          - ``limit``: page size cap
        """
        clauses: list[str] = []
        params: list[Any] = []
        if action_id:
            clauses.append("action_id = ?")
            params.append(action_id)
        if decided_by:
            clauses.append("decided_by = ?")
            params.append(decided_by)
        where = (
            " WHERE " + " AND ".join(clauses) if clauses else ""
        )
        # Per-action: ASC (lifecycle reads top-to-bottom).
        # Global feed: DESC (newest activity first).
        order = "ASC" if action_id else "DESC"
        sql = (
            "SELECT action_id, decision, decided_by, reason, "
            "       occurred_at "
            "FROM decision_log"
            + where
            + f" ORDER BY occurred_at {order} LIMIT ?"
        )
        params.append(max(1, int(limit)))

        with _LOCK:
            rows = self._conn.execute(sql, params).fetchall()
        return [{
            "action_id": r["action_id"],
            "decision": r["decision"],
            "decided_by": r["decided_by"],
            "reason": r["reason"],
            "occurred_at": r["occurred_at"],
        } for r in rows]

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
            if cur.rowcount == 0:
                self._conn.commit()
                logger.debug(
                    "transition no-op for %s (id missing or not in %s)",
                    action_id, from_status.value,
                )
                return None
            self._conn.execute(
                """INSERT INTO decision_log
                   (action_id, decision, decided_by, reason, occurred_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    action_id, to_status.value,
                    decided_by or None, reason or None, now,
                ),
            )
            self._conn.commit()
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


def parse_age_spec(spec: str) -> float | None:
    """Parse an age spec like ``"7d"``, ``"30m"``, ``"24h"``, ``"60s"``
    into seconds. Bare integers are treated as seconds. Returns
    ``None`` on malformed input.

    Shared between CLI (``shopai approvals sweep``) and HTTP
    (``POST /api/approvals/sweep``) so both surfaces accept the
    same human-friendly age strings.
    """
    if not spec:
        return None
    spec = spec.strip().lower()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if spec[-1] in multipliers:
        try:
            return float(spec[:-1]) * multipliers[spec[-1]]
        except ValueError:
            return None
    try:
        return float(spec)
    except ValueError:
        return None


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str)
    except Exception:  # noqa: BLE001
        return "{}"


def _short_uuid() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _row_to_action(row: sqlite3.Row) -> ApprovalAction:
    # store_id is a post-launch addition (PR ~#239). Older rows
    # without the column resolve to None, which the dataclass
    # default accepts. ``KeyError`` rather than ``IndexError`` is
    # what ``sqlite3.Row`` raises on missing keys.
    try:
        store_id = row["store_id"]
    except (IndexError, KeyError):
        store_id = None
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
        store_id=store_id,
    )


def _safe_loads(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        loaded = json.loads(payload)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001
        return {}
