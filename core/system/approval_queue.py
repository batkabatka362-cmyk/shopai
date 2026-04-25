"""SQLite-backed approval queue for HIGH / CRITICAL actions.

Phase 2 of the 4×4 matrix work. Owner's architectural frame:
**core logic, our brain** — the queue policy (FIFO, TTL,
idempotent decide) encodes store-specific domain knowledge.
Storage + message delivery are commodities (stdlib sqlite +
the interchangeable telegram_bot adapter).

Lifecycle of one request:

    enqueue()  →  pending         —— owner can approve / deny
              └→  expires_at (30 min default)
       │
       ├── approve() → approved  (owner confirmed)
       ├── deny()    → denied    (owner rejected, with reason)
       └── (TTL elapses) → expired (auto-cancelled)

Decide calls are idempotent — approving an already-approved
row is a no-op (returns the existing state instead of
double-writing). This matches §4b.D: external actions with
side effects must be idempotent.

Stores ``payload`` as JSON string — same shape the caller
passed to ``risk_gate.classify``. The executor pulls it back
out when the approval resolves.

Schema is minimal + stable (one version per field added, no
in-place column edits). Re-opening the DB is safe.
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

from core.contracts import RiskLevel

_logger = logging.getLogger("shopai.approval_queue")


ApprovalStatus = Literal["pending", "approved", "denied", "expired"]


_DEFAULT_DB_PATH = "data/approval_queue.db"
_DEFAULT_TTL_MINUTES = 30


@dataclass
class ApprovalRequest:
    request_id: str
    action_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    status: ApprovalStatus = "pending"
    requested_at: float = 0.0
    expires_at: float = 0.0
    decided_at: float = 0.0
    decided_by: str = ""
    decision_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action_type": self.action_type,
            "payload": dict(self.payload),
            "risk_level": self.risk_level.value,
            "status": self.status,
            "requested_at": round(self.requested_at, 2),
            "expires_at": round(self.expires_at, 2),
            "decided_at": round(self.decided_at, 2),
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
        }

    def is_terminal(self) -> bool:
        return self.status in ("approved", "denied", "expired")


class ApprovalQueue:
    """SQLite-backed FIFO queue. One instance per DB path;
    thread-safe within a process via a coarse lock — the
    approval-rate is low enough (a handful per hour) that
    contention isn't a concern."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS approvals (
        request_id      TEXT PRIMARY KEY,
        action_type     TEXT NOT NULL,
        payload_json    TEXT NOT NULL,
        risk_level      TEXT NOT NULL,
        status          TEXT NOT NULL,
        requested_at    REAL NOT NULL,
        expires_at      REAL NOT NULL,
        decided_at      REAL DEFAULT 0,
        decided_by      TEXT DEFAULT '',
        decision_reason TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_approvals_status
        ON approvals(status);
    CREATE INDEX IF NOT EXISTS idx_approvals_requested_at
        ON approvals(requested_at);
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
        #: Post-enqueue hooks — each gets ``ApprovalRequest``
        #: and runs fire-and-forget (exceptions are swallowed
        #: to the local log, never block enqueue). Commodity
        #: adapters (e.g. ``approval_notifier.ApprovalNotifier``)
        #: register here so enqueue + notify stay decoupled.
        self._on_enqueue: list[Any] = []
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

    # ── Write surface ────────────────────────────────────

    def enqueue(
        self,
        action_type: str,
        payload: dict[str, Any],
        risk_level: RiskLevel,
        *,
        ttl_minutes: int = _DEFAULT_TTL_MINUTES,
    ) -> ApprovalRequest:
        """Queue a HIGH / CRITICAL action for owner review.

        Returns the full ``ApprovalRequest`` (including
        ``request_id``) so the caller can reference it later
        via ``get()`` / ``approve()`` / ``deny()``."""
        if not action_type:
            raise ValueError("action_type is required")
        now = float(self._now())
        req = ApprovalRequest(
            request_id=uuid.uuid4().hex[:16],
            action_type=action_type,
            payload=dict(payload or {}),
            risk_level=risk_level,
            status="pending",
            requested_at=now,
            expires_at=now + ttl_minutes * 60,
        )
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO approvals "
                "(request_id, action_type, payload_json, "
                "risk_level, status, requested_at, "
                "expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    req.request_id, req.action_type,
                    json.dumps(req.payload, sort_keys=True),
                    req.risk_level.value, req.status,
                    req.requested_at, req.expires_at,
                ),
            )
            c.commit()
        _logger.info(
            "enqueued %s request_id=%s level=%s",
            action_type, req.request_id, risk_level.value,
        )
        # Fire-and-forget hooks — commodity adapters (Telegram
        # notifier, future email notifier, etc.) register here.
        # Hook exceptions are logged but never propagate; a
        # failed notification is recoverable via the CLI poll.
        for hook in list(self._on_enqueue):
            try:
                hook(req)
            except Exception as exc:  # noqa: BLE001
                _logger.debug(
                    "on_enqueue hook %s failed: %s",
                    getattr(hook, "__name__", hook), exc,
                )
        return req

    def on_enqueue(self, callback: Any) -> None:
        """Register a post-enqueue hook. Called with the
        newly-created ``ApprovalRequest`` on every successful
        enqueue. Duplicate registrations are allowed — caller
        owns idempotency if they care."""
        self._on_enqueue.append(callback)

    def approve(
        self,
        request_id: str,
        *,
        owner_id: str = "owner",
        reason: str = "",
    ) -> ApprovalRequest | None:
        return self._decide(
            request_id, "approved", owner_id, reason,
        )

    def deny(
        self,
        request_id: str,
        *,
        owner_id: str = "owner",
        reason: str = "",
    ) -> ApprovalRequest | None:
        return self._decide(
            request_id, "denied", owner_id, reason,
        )

    def _decide(
        self,
        request_id: str,
        new_status: ApprovalStatus,
        owner_id: str,
        reason: str,
    ) -> ApprovalRequest | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM approvals WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            existing = self._row_to_request(row)
            # Idempotent — if already in a terminal state,
            # return as-is instead of double-deciding. This
            # lets a flaky Telegram webhook retry without
            # corrupting state.
            if existing.is_terminal():
                return existing
            # Expire if the TTL has elapsed since enqueue
            now = float(self._now())
            if now >= existing.expires_at:
                c.execute(
                    "UPDATE approvals SET status = 'expired', "
                    "decided_at = ? WHERE request_id = ?",
                    (now, request_id),
                )
                c.commit()
                existing.status = "expired"
                existing.decided_at = now
                return existing
            c.execute(
                "UPDATE approvals SET status = ?, "
                "decided_at = ?, decided_by = ?, "
                "decision_reason = ? WHERE request_id = ?",
                (new_status, now, owner_id, reason, request_id),
            )
            c.commit()
            existing.status = new_status
            existing.decided_at = now
            existing.decided_by = owner_id
            existing.decision_reason = reason
            return existing

    def expire_old(self) -> int:
        """Sweep pending rows whose TTL has elapsed. Returns
        count expired. Safe to call from a cron / cycle hook."""
        now = float(self._now())
        with self._lock, self._conn() as c:
            result = c.execute(
                "UPDATE approvals SET status = 'expired', "
                "decided_at = ? "
                "WHERE status = 'pending' AND expires_at < ?",
                (now, now),
            )
            c.commit()
            return int(result.rowcount or 0)

    # ── Read surface ─────────────────────────────────────

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM approvals WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return self._row_to_request(row) if row else None

    def pending(self) -> list[ApprovalRequest]:
        """Oldest-first — acts as a FIFO queue for the owner."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM approvals "
                "WHERE status = 'pending' "
                "ORDER BY requested_at ASC"
            ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def recent(self, limit: int = 50) -> list[ApprovalRequest]:
        """Newest-first — for audit / dashboard views."""
        limit = max(1, min(limit, 1000))
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM approvals "
                "ORDER BY requested_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def stats(self) -> dict[str, int]:
        """Counts by status — for dashboards + health report."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) AS n FROM approvals "
                "GROUP BY status"
            ).fetchall()
        out = {"pending": 0, "approved": 0,
               "denied": 0, "expired": 0}
        for r in rows:
            out[r["status"]] = int(r["n"])
        out["total"] = sum(out.values())
        return out

    # ── Row → dataclass ──────────────────────────────────

    @staticmethod
    def _row_to_request(row: sqlite3.Row) -> ApprovalRequest:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = {}
        try:
            level = RiskLevel(row["risk_level"])
        except ValueError:
            level = RiskLevel.MEDIUM
        return ApprovalRequest(
            request_id=row["request_id"],
            action_type=row["action_type"],
            payload=payload,
            risk_level=level,
            status=row["status"],
            requested_at=float(row["requested_at"] or 0),
            expires_at=float(row["expires_at"] or 0),
            decided_at=float(row["decided_at"] or 0),
            decided_by=str(row["decided_by"] or ""),
            decision_reason=str(row["decision_reason"] or ""),
        )


# ── Module-level singleton ──────────────────────────────

_SINGLETON: ApprovalQueue | None = None
_SINGLETON_LOCK = threading.Lock()


def get_queue(db_path: str | None = None) -> ApprovalQueue:
    """Return the shared process-wide queue. Lazy-init on
    first call. Tests should instantiate ``ApprovalQueue``
    directly with a tmp path to avoid the singleton.

    On first creation, auto-registers the default Telegram
    notifier so HIGH/CRITICAL enqueues push to the owner
    without extra wiring. The notifier degrades gracefully
    when Telegram isn't configured — no error, no block."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                q = ApprovalQueue(
                    db_path=db_path or _DEFAULT_DB_PATH,
                )
                # Commodity hook — safe to call when adapter
                # missing; notifier.notify() just returns False.
                try:
                    from core.system.approval_notifier import (
                        get_notifier,
                    )
                    q.on_enqueue(get_notifier().notify)
                except Exception as exc:  # noqa: BLE001
                    _logger.debug(
                        "default notifier wire failed: %s", exc,
                    )
                _SINGLETON = q
    return _SINGLETON


def reset_singleton_for_tests() -> None:
    """Tests that need a fresh global singleton call this after
    pointing the DB at a tmp path. Never used in production."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
