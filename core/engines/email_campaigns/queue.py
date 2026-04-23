"""SQLite-backed scheduling queue for email campaigns.

One row per (enrollment × step) — i.e. if a customer is enrolled
in the 3-step welcome flow, three rows land in the queue with
distinct ``send_at`` timestamps. The dispatcher drains rows
whose ``send_at`` is in the past + ``status='pending'``.

Idempotency guardrail: ``(recipient, flow, step_id)`` forms a
natural unique key. Re-enrolling the same customer into the
same flow is a no-op for each step that's already pending or
sent. This matches §4b.D — "Set X to absolute value Y" idempotency.

Schema is minimal + append-only; no in-place column edits so
hot-reload across ShopAI versions stays safe.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

_logger = logging.getLogger("shopai.email_campaigns.queue")

_DEFAULT_DB_PATH = "data/email_campaigns.db"


EnrollmentStatus = Literal[
    "pending",              # waiting for send_at
    "sent",                 # delivered via adapter
    "failed",               # adapter error, NOT retried by default
    "skipped_missing_ctx",  # required_context key absent
    "skipped_unsubscribed", # recipient opted out
    "cancelled",            # owner / engine cancelled manually
]


@dataclass
class ScheduledEmail:
    row_id: str
    recipient: str
    flow_id: str
    step_id: str
    send_at: float
    context_json: str
    status: EnrollmentStatus
    created_at: float
    sent_at: float = 0.0
    error: str = ""
    message_id: str = ""
    enrollment_id: str = ""  # groups all steps of one enrollment

    @property
    def context(self) -> dict[str, Any]:
        try:
            return json.loads(self.context_json)
        except (TypeError, ValueError):
            return {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "recipient": self.recipient,
            "flow_id": self.flow_id,
            "step_id": self.step_id,
            "send_at": round(self.send_at, 2),
            "context": self.context,
            "status": self.status,
            "created_at": round(self.created_at, 2),
            "sent_at": round(self.sent_at, 2),
            "error": self.error,
            "message_id": self.message_id,
            "enrollment_id": self.enrollment_id,
        }

    def is_terminal(self) -> bool:
        return self.status in (
            "sent", "failed", "skipped_missing_ctx",
            "skipped_unsubscribed", "cancelled",
        )


class ScheduleQueue:
    """SQLite FIFO for scheduled email sends.

    One process-wide instance per DB path. Thread-safe via a
    coarse lock — expected rate is dozens per cycle, contention
    is a non-issue.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS scheduled_emails (
        row_id         TEXT PRIMARY KEY,
        enrollment_id  TEXT NOT NULL,
        recipient      TEXT NOT NULL,
        flow_id        TEXT NOT NULL,
        step_id        TEXT NOT NULL,
        send_at        REAL NOT NULL,
        context_json   TEXT NOT NULL,
        status         TEXT NOT NULL,
        created_at     REAL NOT NULL,
        sent_at        REAL DEFAULT 0,
        error          TEXT DEFAULT '',
        message_id     TEXT DEFAULT ''
    );

    -- Dispatcher's primary lookup: pending rows due now
    CREATE INDEX IF NOT EXISTS idx_sched_pending
        ON scheduled_emails(status, send_at);

    -- Idempotency key: a recipient shouldn't receive the same
    -- flow step twice.
    CREATE UNIQUE INDEX IF NOT EXISTS idx_sched_unique
        ON scheduled_emails(recipient, flow_id, step_id);

    -- Stats lookups
    CREATE INDEX IF NOT EXISTS idx_sched_flow
        ON scheduled_emails(flow_id, status);

    -- Unsubscribe suppression list.
    CREATE TABLE IF NOT EXISTS unsubscribes (
        recipient   TEXT PRIMARY KEY,
        unsubbed_at REAL NOT NULL,
        source      TEXT DEFAULT ''
    );
    """

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        *,
        now_fn: Any = None,
    ) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._now = now_fn or time.time
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript(self._SCHEMA)

    # ── Enrollment (write) ──────────────────────────────

    def enqueue(
        self,
        *,
        recipient: str,
        flow_id: str,
        step_id: str,
        send_at: float,
        context: dict[str, Any],
        enrollment_id: str = "",
    ) -> ScheduledEmail | None:
        """Create one scheduled row.

        Returns ``None`` when idempotency blocks the insert —
        i.e. the same (recipient, flow, step) already exists.
        That's NOT a failure; it's the expected behaviour when
        a callsite re-enrolls a customer that's already in the
        flow (e.g. two successive 'abandoned_cart' webhooks).
        """
        if not recipient or not flow_id or not step_id:
            raise ValueError(
                "recipient, flow_id, step_id required",
            )
        now = float(self._now())
        row = ScheduledEmail(
            row_id=uuid.uuid4().hex[:16],
            recipient=recipient.strip().lower(),
            flow_id=flow_id,
            step_id=step_id,
            send_at=float(send_at),
            context_json=json.dumps(context, sort_keys=True),
            status="pending",
            created_at=now,
            enrollment_id=(
                enrollment_id or uuid.uuid4().hex[:16]
            ),
        )
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO scheduled_emails "
                    "(row_id, enrollment_id, recipient, flow_id, "
                    "step_id, send_at, context_json, status, "
                    "created_at) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row.row_id, row.enrollment_id,
                        row.recipient, row.flow_id, row.step_id,
                        row.send_at, row.context_json,
                        row.status, row.created_at,
                    ),
                )
                c.commit()
            except sqlite3.IntegrityError:
                # (recipient, flow_id, step_id) unique — already
                # enrolled. Treat as success-by-idempotency.
                return None
        return row

    # ── Dispatcher (read + state transitions) ──────────

    def pop_due(self, *, limit: int = 100) -> list[ScheduledEmail]:
        """Return up to ``limit`` pending rows whose ``send_at``
        is in the past, sorted oldest first.  Caller must mark
        each as ``sent`` / ``failed`` / ``skipped_*`` via
        ``mark_*`` methods after processing."""
        now = float(self._now())
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM scheduled_emails "
                "WHERE status = 'pending' AND send_at <= ? "
                "ORDER BY send_at ASC LIMIT ?",
                (now, int(limit)),
            ).fetchall()
        return [self._row(r) for r in rows]

    def mark_sent(
        self,
        row_id: str,
        *,
        message_id: str = "",
    ) -> bool:
        return self._transition(
            row_id, "sent",
            message_id=message_id,
        )

    def mark_failed(self, row_id: str, *, error: str) -> bool:
        return self._transition(
            row_id, "failed", error=error,
        )

    def mark_skipped_missing_ctx(
        self, row_id: str, *, error: str,
    ) -> bool:
        return self._transition(
            row_id, "skipped_missing_ctx", error=error,
        )

    def mark_skipped_unsubscribed(self, row_id: str) -> bool:
        return self._transition(
            row_id, "skipped_unsubscribed",
            error="recipient on unsubscribe list",
        )

    def mark_cancelled(self, row_id: str, *, error: str = "") -> bool:
        return self._transition(
            row_id, "cancelled", error=error,
        )

    def _transition(
        self,
        row_id: str,
        new_status: EnrollmentStatus,
        *,
        message_id: str = "",
        error: str = "",
    ) -> bool:
        """Move a row to a terminal status. Idempotent —
        second call on an already-terminal row is a no-op."""
        now = float(self._now())
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT status FROM scheduled_emails "
                "WHERE row_id = ?",
                (row_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] != "pending":
                return False  # already decided
            c.execute(
                "UPDATE scheduled_emails SET status = ?, "
                "sent_at = ?, error = ?, message_id = ? "
                "WHERE row_id = ?",
                (new_status, now, error, message_id, row_id),
            )
            c.commit()
        return True

    # ── Unsubscribes ────────────────────────────────────

    def unsubscribe(
        self,
        recipient: str,
        *,
        source: str = "",
    ) -> bool:
        if not recipient:
            return False
        rec = recipient.strip().lower()
        now = float(self._now())
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO unsubscribes "
                "(recipient, unsubbed_at, source) "
                "VALUES (?, ?, ?)",
                (rec, now, source),
            )
            c.commit()
        return True

    def is_unsubscribed(self, recipient: str) -> bool:
        if not recipient:
            return False
        rec = recipient.strip().lower()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT recipient FROM unsubscribes "
                "WHERE recipient = ?",
                (rec,),
            ).fetchone()
        return row is not None

    # ── Introspection ───────────────────────────────────

    def get(self, row_id: str) -> ScheduledEmail | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM scheduled_emails "
                "WHERE row_id = ?",
                (row_id,),
            ).fetchone()
        return self._row(row) if row else None

    def list_by_recipient(
        self, recipient: str,
    ) -> list[ScheduledEmail]:
        rec = recipient.strip().lower()
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM scheduled_emails "
                "WHERE recipient = ? "
                "ORDER BY send_at ASC",
                (rec,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        """Counts by flow + status — powers
        ``shopai email-stats``."""
        per_flow: dict[str, dict[str, int]] = {}
        totals = {
            "pending": 0, "sent": 0, "failed": 0,
            "skipped_missing_ctx": 0,
            "skipped_unsubscribed": 0,
            "cancelled": 0,
        }
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT flow_id, status, COUNT(*) AS n "
                "FROM scheduled_emails "
                "GROUP BY flow_id, status"
            ).fetchall()
            unsub_count = c.execute(
                "SELECT COUNT(*) AS n FROM unsubscribes"
            ).fetchone()["n"]
        for r in rows:
            fid = r["flow_id"]
            status = r["status"]
            per_flow.setdefault(fid, {})
            per_flow[fid][status] = int(r["n"])
            if status in totals:
                totals[status] += int(r["n"])
        totals["total"] = sum(
            v for k, v in totals.items() if k != "total"
        )
        return {
            "totals": totals,
            "flows": per_flow,
            "unsubscribes": int(unsub_count),
        }

    # ── Row hydration ──────────────────────────────────

    @staticmethod
    def _row(r: sqlite3.Row) -> ScheduledEmail:
        return ScheduledEmail(
            row_id=r["row_id"],
            enrollment_id=(r["enrollment_id"] or ""),
            recipient=r["recipient"],
            flow_id=r["flow_id"],
            step_id=r["step_id"],
            send_at=float(r["send_at"] or 0),
            context_json=r["context_json"] or "{}",
            status=r["status"],
            created_at=float(r["created_at"] or 0),
            sent_at=float(r["sent_at"] or 0),
            error=str(r["error"] or ""),
            message_id=str(r["message_id"] or ""),
        )
